"""실행 프로세스 — **BPM 프로세스 하나를 돌리는 자식 프로세스** (ADR-0023, 진입점 `chk-bot-runner`).

PC 실행기는 이것을 띄우기만 하고 기다리지 않는다. 주고받는 길은 파일 한 벌이다 (ADR-0031).

- 올라오는 것: **실행 기록** `runs/<run_id>.jsonl` (C3) — 노드 상태·결재 요청·끝남.
- 내려가는 것: **제어 파일** `runs/<run_id>.control.jsonl` — 중지와 결재 답.
- **PC 위임으로 받은 작업이면** 끝날 때 `runs/<run_id>.outputs.json`에 결과를 쓴다
  (C4 `JobAck.outputs`, ADR-0062 §4) — 실행 변수를 아는 것은 이 프로세스뿐이고 실행 기록에는
  업무 값이 없다 (원칙 6). PC 실행기가 ack에 실어 올리고 그 자리에서 지운다.

**스레드를 만들지 않는다.** 엔진은 한 걸음씩 돌고(`step()`), 멈추면(`blocked()`) 제어 파일을
보고 타이머를 본다. 사람을 기다리는 동안에도 같은 자리를 돈다 (ADR-0014 — 자리를 쥔다).

**운영 실행은 결정 수행이다** (ADR-0010) — 기본 `--mode deterministic`.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chaeksas.bot_ui.credentials import ENV_CALL_TOKEN, Credentials
from chaeksas.bot_ui.host_settings import HostSettings
from chaeksas.contracts.extension import CALL_TOKEN_SECRET
from chaeksas.core import control, outputs, requests
from chaeksas.core.app_directory import AppDirectory, read_directory
from chaeksas.core.engine import WHERE_CENTER, WHERE_FIELD, Engine, EngineError, Run, RunEnv, State
from chaeksas.core.extensions import ExtensionHost, HostTasks, load_host
from chaeksas.core.packages import InstalledBot
from chaeksas.core.run_env import make_env
from chaeksas.core.run_log import RunLog, log_path
from chaeksas.core.senders import (
    DEFAULT_ATTACHMENT_MB,
    SECURITY_STARTTLS,
    SmtpConfig,
    WebhookConfig,
    make_sender,
)
from chaeksas.core.services import CenterServiceCaller
from chaeksas.extension_api import HOST_BOT_UI

log = logging.getLogger(__name__)

#: 제어 파일·타이머를 보는 간격 (초). ADR-0031 §4.
TICK_S = 0.2

#: 한 번 깨어날 때 밟는 노드 수 — 멈춤 신호를 자주 본다.
STEPS_PER_TICK = 50

#: C3 `run_started.source` — **PC 위임으로 받은 작업**이다 (ADR-0062). 이 출처만 출력 파일을 쓴다.
SOURCE_DELEGATION = "delegation"


@dataclass
class CallTokenHolder:
    """이 실행의 호출 토큰 (C15) — 처음 것은 환경변수로, 새것은 제어 파일로 온다 (PC 실행기가 갈아 넣는다)."""

    value: str | None = None

    def __call__(self) -> str | None:
        return self.value


@dataclass(frozen=True)
class RunnerSecrets:
    """`extension_api.Secrets` — 실행 프로세스에서 확장이 묻는 이름을 푼다 (ADR-0013).

    `call_token`은 이 실행의 호출 토큰(C15), 나머지는 그 확장의 비밀 칸이다.
    """

    credentials: Any  # `Credentials`
    extension_id: str
    call_token: CallTokenHolder | None = None

    def resolve(self, ref: str) -> str | None:
        if ref == CALL_TOKEN_SECRET:
            return self.call_token() if self.call_token is not None else None
        found: str | None = self.credentials.extension_secret(self.extension_id, ref)
        return found


def extension_tasks(
    values: dict[str, dict[str, Any]],
    *,
    host: ExtensionHost | None = None,
    off: Sequence[str] = (),
    call_token: CallTokenHolder | None = None,
) -> HostTasks:
    """이 실행의 확장 — 설치된 것을 읽고, PC 실행기가 넘긴 확장별 설정을 붙인다.

    **사람이 BUI-11에서 끈 확장은 여기서도 기여를 내지 않는다** (ADR-0043) — 끌 id는 PC 실행기가
    넘긴다(`--off`). 그런 BPM 프로세스는 사전 점검이 이미 막지만, 「꺼짐」의 뜻이 앱마다 달라지면 안 된다.
    """
    loaded = host if host is not None else load_host(off=off)
    credentials: Any = Credentials()

    def make_context(extension_id: str) -> Any:
        return loaded.context(
            extension_id,
            host=HOST_BOT_UI,
            settings=HostSettings(values=dict(values.get(extension_id) or {})),
            secrets=RunnerSecrets(credentials=credentials, extension_id=extension_id, call_token=call_token),
        )

    return HostTasks(host=loaded, make_context=make_context)


def app_directory(path: Path | None) -> AppDirectory:
    """검증된 외부 확장 정의 (C13 「전송」) — PC 실행기가 Center에서 받아 파일로 건넨 것.

    **봉투를 다시 검증한다** — `read_directory`가 통과한 것만 싣고 나머지는 사유를 남긴다.
    """
    return read_directory(path)


def refuse_unusable(package: InstalledBot, directory: AppDirectory) -> None:
    """매니페스트가 요구하는 외부 확장을 쓸 수 없으면 **시작하지 않는다** (C1·C13).

    중간에 알면 이미 한 일을 되돌릴 수 없다. 정의가 바뀌었으면 그 BPM 프로세스는 승인·배포를 다시
    받아야 한다 — 몰래 새 정의로 돌리지 않는다.
    """
    unusable = directory.unusable(package.manifest.requires.extensions)
    if unusable:
        raise EngineError(
            "쓸 수 없는 외부 확장이 있다: " + " / ".join(unusable),
            code="extension_definition_unusable",
        )


def _succeeded(run: Run) -> bool:
    """**성공으로 끝났나** — 기록에서 읽는다 (C3 `run_finished.status`).

    `State.DONE`으로는 가를 수 없다 — **취소도 `DONE`으로 앉는다** (서버 일꾼의 `_finished`와
    같은 까닭이다).
    """
    for event in reversed(run.log.events):
        if event.kind == "run_finished":
            return str(event.data.get("status")) == "success"
    return False


@dataclass
class Runner:
    """실행 하나를 끝까지 민다. **부르는 쪽이 `drive()`를 부른다** (스레드 없음)."""

    run_id: str
    package: InstalledBot
    data_dir: Path
    inputs: dict[str, Any]
    mode: str = "deterministic"
    source: str = "manual"
    job_id: str | None = None
    #: 대기열에서 기다린 초 (C3 `run_started.queued_s`). 모르면 `None` — 0과 다르다.
    queued_s: float | None = None
    #: **맡긴 서버 실행** (C3 `run_started.parent_run_id`, ADR-0062 §6). 위임이 아니면 `None`.
    parent_run_id: str | None = None
    tick_s: float = TICK_S
    env: RunEnv | None = None

    engine: Engine = None  # type: ignore[assignment]
    run: Run | None = None
    stopping: bool = False
    #: 이 실행의 호출 토큰 (C15) — 제어 파일로 새것이 오면 바꾼다.
    call_token: CallTokenHolder = field(default_factory=CallTokenHolder)
    #: 요청 파일에 이미 쓴 결재 — 두 번 올리지 않는다.
    _posted: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.engine = Engine()

    @property
    def control(self) -> Path:
        return control.control_path(self.data_dir, self.run_id)

    @property
    def requests(self) -> Path:
        return requests.requests_path(self.data_dir, self.run_id)

    @property
    def outputs(self) -> Path:
        return outputs.outputs_path(self.data_dir, self.run_id)

    @property
    def field_requests(self) -> Path:
        return requests.field_requests_path(self.data_dir, self.run_id)

    def _post_requests(self, run: Run) -> None:
        """새 결재·확인의 본문을 요청 파일에 쓴다.

        `where=center`는 올릴 파일로(ADR-0038 — PC 실행기가 나른다), 현장 것은 **결재 창이 읽을
        파일로** 간다(ADR-0078 — 제목·검토 자료를 아는 것은 여기뿐이다).
        """
        for pending in list(run.pendings.values()):
            if pending.request_id in self._posted:
                continue
            path = self.requests if pending.where == WHERE_CENTER else self.field_requests
            requests.append(path, requests.create_request(run, pending).to_json_dict())
            self._posted.add(pending.request_id)

    def start(self) -> Run:
        log_file = log_path(self.data_dir, self.run_id)
        found = RunLog(run_id=self.run_id, path=log_file)
        self.run = self.engine.start(
            self.package.entry(),
            run_id=self.run_id,
            log=found,
            env=self.env,
            inputs=self.inputs,
            mode=self.mode,
            executor="bot_ui",
            source=self.source,
            version=self.package.manifest.version,
            # 실행 기록이 말하는 이름은 **패키지 id**다 (ADR-0086 — 그림 id가 아니다).
            bpm_process_id=self.package.manifest.id,
            job_id=self.job_id,
            queued_s=self.queued_s,
            parent_run_id=self.parent_run_id,
        )
        return self.run

    def post_outputs(self) -> dict[str, Any] | None:
        """끝난 뒤 **위임의 결과**를 출력 파일에 쓴다 (C4 `JobAck.outputs`, ADR-0062 §4).

        **위임으로 받은 작업만** 쓴다 — 평범한 실행의 업무 값을 디스크에 남기지 않는다.
        그리고 **성공했을 때만**이다: 실패·취소는 돌려줄 값이 없고(서버 쪽은 그것을 업무
        실패로 다룬다) 쓰면 값만 더 오래 남는다.

        **거르는 자리는 그 BPM 프로세스가 선언한 `outputs`다** (C1) — 그것이 곧 「부르는 쪽이 받을
        것」이다. 선언이 없으면 빈 벌을 쓴다(「끝났는데 돌려줄 것이 없다」도 사실이다 — 그러면
        서버 그림이 읽는 값이 없어 그쪽에서 업무 실패가 된다).
        """
        run = self.run
        if self.source != SOURCE_DELEGATION or run is None or not _succeeded(run):
            return None
        found = outputs.pick(self.package.manifest.outputs, run.variables)
        outputs.write(self.outputs, found)
        log.info("위임 결과 %d개를 올릴 파일에 썼다", len(found))
        return found

    def drive(self, *, deadline_s: float | None = None) -> State:
        """끝날 때까지 (또는 중지될 때까지) 민다."""
        run = self.run or self.start()
        started = time.monotonic()
        while not run.finished:
            if deadline_s is not None and time.monotonic() - started > deadline_s:
                return run.state
            if self._obey(run):
                continue
            if self.engine.blocked(run):
                if not self._unblock(run):
                    time.sleep(self.tick_s)
                continue
            for _ in range(STEPS_PER_TICK):
                if run.finished or self.engine.blocked(run):
                    break
                self.engine.step(run)
            self._post_requests(run)
        return run.state

    def _obey(self, run: Run) -> bool:
        """내려온 지시를 따른다 (ADR-0031). 따른 것이 있으면 참."""
        acted = False
        for command in control.take(self.control):
            if command.is_stop:
                self.stopping = True
                self.engine.cancel(run, reason="사용자가 중지했습니다")
                return True
            if command.kind == control.ANSWER:
                try:
                    self.engine.answer(
                        run,
                        command.request_id,
                        command.answer,
                        answered_by=command.answered_by or "사람",
                        answered_via=command.answered_via or None,
                    )
                except EngineError as e:
                    # 답이 폼에 안 맞는다 — **실행을 죽이지 않는다**. 화면이 다시 묻는다.
                    run.log.emit("log", level="warn", message=f"답을 받지 못했다: {e}")
                acted = True
            if command.kind == control.CALL_TOKEN and command.token:
                # 새 호출 토큰 (C15) — 다음 외부 작업부터 이것으로 올린다.
                self.call_token.value = command.token
            if command.kind == control.WITHDRAW:
                try:
                    # 답 없이 끝남 — 오류 경계가 있으면 그리로, 없으면 실패 (C6, ADR-0038).
                    self.engine.withdraw(run, command.request_id, reason=command.reason or "admin_withdraw")
                except EngineError as e:
                    # 이미 현장에서 답했다 — 그 결재는 끝났다. 할 일이 없다.
                    run.log.emit("log", level="info", message=f"회수할 결재가 없다: {e}")
                acted = True
        return acted

    def _unblock(self, run: Run) -> bool:
        """사람·메시지를 기다리는 중이면 타이머만 본다. 민 것이 있으면 참."""
        due = run.next_due()
        now = datetime.now(UTC)
        if due is not None and due <= now:
            self.engine.tick(run, now)
            return True
        return False


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(prog="chk-bot-runner", description="BPM 프로세스 하나를 돌린다")
    parser.add_argument("--package", required=True, type=Path, help="풀어 놓은 패키지 폴더")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-dir", required=True, type=Path)
    # 입력은 **파일로** 받는다 — 명령줄에 실으면 업무 값이 프로세스 목록에 뜬다 (원칙 6).
    parser.add_argument("--inputs", type=Path, default=None, help="입력 변수 JSON 파일")
    parser.add_argument("--mode", default="deterministic", choices=("deterministic", "autonomous"))
    parser.add_argument("--source", default="manual")
    parser.add_argument("--job-id", default=None)
    # C3 `run_started.parent_run_id` — 맡긴 서버 실행 (ADR-0062 §6). 위임이 아니면 주지 않는다.
    parser.add_argument("--parent-run-id", default=None)
    # C3 `run_started.queued_s` — PC 실행기가 대기열에서 기다린 초를 알려 준다 (모르면 안 준다).
    parser.add_argument("--queued-s", type=float, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--readable", type=Path, action="append", default=[])
    parser.add_argument("--writable", type=Path, action="append", default=[])
    parser.add_argument("--llm-url", default="")
    parser.add_argument("--llm-model", default="")
    # `location: follow` 결재를 어디서 답하나 (BUI-03 「원격 결재」, ADR-0038).
    parser.add_argument("--approval-where", default=WHERE_FIELD, choices=(WHERE_FIELD, WHERE_CENTER))
    # 확장별 설정 (그 칸 + 예약 키). **비밀은 없다** (키는 참조 이름으로 푼다).
    parser.add_argument("--extensions", type=Path, default=None, help="확장별 설정 JSON 파일")
    # 사람이 BUI-11에서 끈 확장 (ADR-0043) — 끌 id는 PC 실행기가 준다.
    parser.add_argument("--off", action="append", default=[], help="끈 확장 id (여러 번)")
    # 외부 확장 정의와 봉투·Admin 공개키 (C13 「전송」) — 고정한 해시와 대조한다.
    parser.add_argument("--services", type=Path, default=None, help="외부 확장 명부 JSON 파일")
    # 서비스 태스크를 올릴 Center (C15). 호출 토큰은 환경변수·제어 파일로 온다.
    parser.add_argument("--center-url", default="")
    # 보내기 (BUI-03 「보내기」, ADR-0059). **비밀번호는 명령줄에 없다** — 이 프로세스가
    # 비밀 저장소에서 읽는다 (모델 키와 같은 길).
    parser.add_argument("--smtp-host", default="")
    parser.add_argument("--smtp-port", type=int, default=0)
    parser.add_argument("--smtp-security", default=SECURITY_STARTTLS)
    parser.add_argument("--smtp-user", default="")
    parser.add_argument("--smtp-from", default="")
    parser.add_argument("--smtp-attachment-mb", type=float, default=DEFAULT_ATTACHMENT_MB)
    parser.add_argument("--webhook-host", action="append", default=[], help="웹훅 허용 호스트 (여러 번)")
    found = parser.parse_args(argv)

    package = InstalledBot.read(found.package)
    inputs = json.loads(found.inputs.read_text(encoding="utf-8")) if found.inputs else {}
    output_dir = found.output_dir or (found.data_dir / "outputs" / package.manifest.id)
    # 모델 키는 **환경변수로** 받는다 (설정 파일·명령줄에 두지 않는다, CLAUDE.md §5).
    import os  # noqa: PLC0415

    directory = app_directory(found.services)
    for app_id, why in sorted(directory.problems.items()):
        # **조용히 사라지지 않는다** — 쓰지 못한 정의는 이유와 함께 기록에 남는다.
        log.warning("외부 확장 정의를 쓰지 못한다 (%s): %s", app_id, why)
    refuse_unusable(package, directory)

    token = CallTokenHolder(value=os.environ.get(ENV_CALL_TOKEN) or None)
    runner = Runner(
        run_id=found.run_id,
        package=package,
        data_dir=found.data_dir,
        inputs=inputs,
        mode=found.mode,
        source=found.source,
        job_id=found.job_id,
        queued_s=found.queued_s,
        parent_run_id=found.parent_run_id,
        call_token=token,
        env=make_env(
            package,
            output_dir=output_dir,
            readable=tuple(found.readable),
            writable=tuple(found.writable),
            llm_url=found.llm_url,
            llm_key=os.environ.get("CHK_BOT_UI__LLM__API_KEY", ""),
            llm_model=found.llm_model,
            extensions=extension_tasks(
                json.loads(found.extensions.read_text(encoding="utf-8")) if found.extensions else {},
                off=list(found.off),
                call_token=token,
            ),
            approval_where=found.approval_where,
            # 서비스 태스크는 Center에 외부 작업으로 올린다 (C15) — 바깥 앱의 주소·키는 모른다.
            services=CenterServiceCaller(base_url=found.center_url, token=token, caller_type="bot_ui")
            if found.center_url
            else None,
            # 보내기 — **서버 실행기와 같은 함수**가 짓는다 (ADR-0059). 설정이 비면
            # `chk:email`·`chk:webhook`이 **보내지 않고 실패한다**.
            sender=make_sender(
                smtp=SmtpConfig(
                    host=found.smtp_host,
                    port=found.smtp_port,
                    security=found.smtp_security,
                    username=found.smtp_user,
                    sender=found.smtp_from,
                    max_attachment_mb=found.smtp_attachment_mb,
                ),
                webhook=WebhookConfig(allowed_hosts=tuple(found.webhook_host)),
                password=Credentials().smtp_password() or "",
            ),
        ),
    )
    state = runner.drive()
    # **쓰는 것이 먼저다** — 제어·요청 파일을 치우는 것과 달리 이것은 **올릴 것을 남기는**
    # 일이다 (PC 실행기가 읽어 ack에 싣고 그 자리에서 지운다, ADR-0062 §4).
    runner.post_outputs()
    control.clear(runner.control)
    requests.clear(runner.requests)
    requests.clear(runner.field_requests)
    # 끝난 방식을 종료 코드로도 알린다 (ADR-0023 — 실행 기록과 함께 본다).
    return 0 if state is State.DONE else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
