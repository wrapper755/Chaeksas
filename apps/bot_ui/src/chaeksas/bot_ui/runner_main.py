"""실행기 — **Bot 하나를 돌리는 자식 프로세스** (ADR-0023, 진입점 `chk-bot-runner`).

Bot UI는 이것을 띄우기만 하고 기다리지 않는다. 주고받는 길은 파일 한 벌이다 (ADR-0031).

- 올라오는 것: **실행 기록** `runs/<run_id>.jsonl` (C3) — 노드 상태·결재 요청·끝남.
- 내려가는 것: **제어 파일** `runs/<run_id>.control.jsonl` — 중지와 결재 답.

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
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chaeksas.bot_ui.credentials import Credentials
from chaeksas.bot_ui.runtimes import HostSettings
from chaeksas.contracts.bpmn_ext import BpmnProcess, read_process
from chaeksas.contracts.dmn import Decision, DmnReadError, read_decisions
from chaeksas.contracts.manifest import Manifest
from chaeksas.core import control, requests
from chaeksas.core.app_directory import AppDirectory, read_directory
from chaeksas.core.engine import WHERE_CENTER, WHERE_FIELD, Engine, EngineError, Run, RunEnv, State
from chaeksas.core.extensions import ExtensionHost, HostTasks, load_host
from chaeksas.core.files import Workspace
from chaeksas.core.llm import NoLlm, OpenAiCompatibleLlm
from chaeksas.core.replay import read_memory
from chaeksas.core.run_log import RunLog, log_path
from chaeksas.core.senders import NoSender
from chaeksas.core.tools import builtin_tools
from chaeksas.extension_api import HOST_BOT_UI

log = logging.getLogger(__name__)

#: 제어 파일·타이머를 보는 간격 (초). ADR-0031 §4.
TICK_S = 0.2

#: 한 번 깨어날 때 밟는 노드 수 — 멈춤 신호를 자주 본다.
STEPS_PER_TICK = 50

MANIFEST_NAME = "manifest.json"


@dataclass
class Package:
    """풀어 놓은 패키지 하나 (C1)."""

    folder: Path
    manifest: Manifest

    @classmethod
    def read(cls, folder: Path) -> Package:
        raw = (folder / MANIFEST_NAME).read_text(encoding="utf-8")
        return cls(folder=folder, manifest=Manifest.model_validate_json(raw))

    def entry(self) -> BpmnProcess:
        if not self.manifest.entry:
            raise EngineError("매니페스트에 진입 정의가 없다", code="package_no_entry")
        return read_process((self.folder / self.manifest.entry).read_text(encoding="utf-8"))

    def processes(self) -> dict[str, BpmnProcess]:
        """호출(`callActivity`)이 찾을 다른 정의 — `process/`와 `libs/`."""
        out: dict[str, BpmnProcess] = {}
        for path in sorted([*self.folder.glob("process/*.bpmn"), *self.folder.glob("libs/*.bpmn")]):
            try:
                found = read_process(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — 깨진 정의 하나가 실행을 막지 않게
                log.warning("정의를 읽지 못했다: %s", path.name)
                continue
            out[found.id] = found
        return out

    def decisions(self) -> dict[str, Decision]:
        found: dict[str, Decision] = {}
        for path in sorted(self.folder.glob("process/*.dmn")):
            try:
                found.update(read_decisions(path.read_text(encoding="utf-8")))
            except DmnReadError:
                log.warning("DMN을 읽지 못했다: %s", path.name)
        return found


@dataclass(frozen=True)
class RunnerSecrets:
    """`extension_api.Secrets` — 실행기에서 확장이 묻는 이름을 푼다 (ADR-0013).

    태스크의 **서비스 앱 키 참조**(BUI-10)가 먼저, 아니면 그 확장의 비밀 칸이다.
    """

    credentials: Credentials
    extension_id: str

    def resolve(self, ref: str) -> str | None:
        return self.credentials.service_app_key(ref) or self.credentials.extension_secret(self.extension_id, ref)


def extension_tasks(values: dict[str, dict[str, Any]], *, host: ExtensionHost | None = None) -> HostTasks:
    """이 실행의 확장 — 설치된 것을 읽고, Bot UI가 넘긴 확장별 설정(Worker 자리 등)을 붙인다."""
    loaded = host if host is not None else load_host()
    credentials = Credentials()

    def make_context(extension_id: str) -> Any:
        return loaded.context(
            extension_id,
            host=HOST_BOT_UI,
            settings=HostSettings(values=dict(values.get(extension_id) or {})),
            secrets=RunnerSecrets(credentials=credentials, extension_id=extension_id),
        )

    return HostTasks(host=loaded, make_context=make_context)


def app_directory(path: Path | None) -> AppDirectory:
    """부를 수 있는 바깥 앱들 (C13 「전송」) — Bot UI가 Center에서 받아 파일로 건넨 것.

    **봉투를 다시 검증한다** — `read_directory`가 통과한 것만 싣고 나머지는 사유를 남긴다.
    키 값은 파일에 없다. **참조 이름**을 BUI-10의 서비스 앱 키로 푼다 (ADR-0013).
    """
    return read_directory(path, secrets=Credentials().service_app_key)


def refuse_unusable(package: Package, directory: AppDirectory) -> None:
    """매니페스트가 요구하는 외부 확장을 쓸 수 없으면 **시작하지 않는다** (C1·C13).

    중간에 알면 이미 한 일을 되돌릴 수 없다. 정의가 바뀌었으면 그 Bot은 승인·배포를 다시
    받아야 한다 — 몰래 새 정의로 돌리지 않는다.
    """
    unusable = directory.unusable(package.manifest.requires.extensions)
    if unusable:
        raise EngineError(
            "쓸 수 없는 외부 확장이 있다: " + " / ".join(unusable),
            code="extension_definition_unusable",
        )


def make_env(package: Package, *, output_dir: Path, readable: tuple[Path, ...],
             writable: tuple[Path, ...] = (), llm_url: str = "", llm_key: str = "",
             llm_model: str, extensions: HostTasks | None = None,
             approval_where: str = WHERE_FIELD, directory: AppDirectory | None = None) -> RunEnv:
    """바깥 세계 한 벌 — **주소·키는 실행하는 쪽만 안다** (ADR-0013)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    space = Workspace(output_dir=output_dir, readable=readable, writable=writable)
    model = (
        OpenAiCompatibleLlm(base_url=llm_url, api_key=llm_key, model=llm_model) if llm_url else NoLlm()
    )
    made = RunEnv(
        workspace=space,
        # 보내기 어댑터는 조각 4b다 — **없으면 보내지 않고 실패한다** (조용히 넘어가지 않는다).
        sender=NoSender(),
        processes=package.processes(),
        decisions=package.decisions(),
        llm=model,
        tools=builtin_tools(space),
        memory=read_memory(package.folder),
        # `location: follow` 결재를 어디서 답하나 — BUI-03 「원격 결재」 (ADR-0038).
        approval_where=approval_where,
    )
    if extensions is not None:
        # 확장 태스크·`web`·`desktop` AI 태스크 (ADR-0018·ADR-0037) — 없으면 그림·설치 오류가 된다.
        made = replace(made, extensions=extensions)
    if directory is not None:
        # `chk:serviceCall` — 서비스 앱(C11)과 외부 앱(C13 어댑터)이 **같은 자리**로 간다.
        made = replace(made, services=directory.caller())
    return made


@dataclass
class Runner:
    """실행 하나를 끝까지 민다. **부르는 쪽이 `drive()`를 부른다** (스레드 없음)."""

    run_id: str
    package: Package
    data_dir: Path
    inputs: dict[str, Any]
    mode: str = "deterministic"
    source: str = "manual"
    job_id: str | None = None
    #: 대기열에서 기다린 초 (C3 `run_started.queued_s`). 모르면 `None` — 0과 다르다.
    queued_s: float | None = None
    tick_s: float = TICK_S
    env: RunEnv | None = None

    engine: Engine = None  # type: ignore[assignment]
    run: Run | None = None
    stopping: bool = False
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

    def _post_requests(self, run: Run) -> None:
        """`where=center`인 새 결재를 요청 파일에 쓴다 (ADR-0038) — Bot UI가 나른다."""
        for pending in list(run.pendings.values()):
            if pending.where != WHERE_CENTER or pending.request_id in self._posted:
                continue
            requests.append(self.requests, requests.create_request(run, pending).to_json_dict())
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
            job_id=self.job_id,
            queued_s=self.queued_s,
        )
        return self.run

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
                    )
                except EngineError as e:
                    # 답이 폼에 안 맞는다 — **실행을 죽이지 않는다**. 화면이 다시 묻는다.
                    run.log.emit("log", level="warn", message=f"답을 받지 못했다: {e}")
                acted = True
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

    parser = argparse.ArgumentParser(prog="chk-bot-runner", description="Bot 하나를 돌린다")
    parser.add_argument("--package", required=True, type=Path, help="풀어 놓은 패키지 폴더")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-dir", required=True, type=Path)
    # 입력은 **파일로** 받는다 — 명령줄에 실으면 업무 값이 프로세스 목록에 뜬다 (원칙 6).
    parser.add_argument("--inputs", type=Path, default=None, help="입력 변수 JSON 파일")
    parser.add_argument("--mode", default="deterministic", choices=("deterministic", "autonomous"))
    parser.add_argument("--source", default="manual")
    parser.add_argument("--job-id", default=None)
    # C3 `run_started.queued_s` — Bot UI가 대기열에서 기다린 초를 알려 준다 (모르면 안 준다).
    parser.add_argument("--queued-s", type=float, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--readable", type=Path, action="append", default=[])
    parser.add_argument("--writable", type=Path, action="append", default=[])
    parser.add_argument("--llm-url", default="")
    parser.add_argument("--llm-model", default="")
    # `location: follow` 결재를 어디서 답하나 (BUI-03 「원격 결재」, ADR-0038).
    parser.add_argument("--approval-where", default=WHERE_FIELD, choices=(WHERE_FIELD, WHERE_CENTER))
    # 확장별 설정 (그 칸 + 예약 키 — Worker 자리). **비밀은 없다** (키는 참조 이름으로 푼다).
    parser.add_argument("--extensions", type=Path, default=None, help="확장별 설정 JSON 파일")
    # 부를 수 있는 바깥 앱 — 주소·Admin 공개키·외부 확장 정의와 봉투 (C13 「전송」).
    parser.add_argument("--services", type=Path, default=None, help="바깥 앱 명부 JSON 파일")
    found = parser.parse_args(argv)

    package = Package.read(found.package)
    inputs = json.loads(found.inputs.read_text(encoding="utf-8")) if found.inputs else {}
    output_dir = found.output_dir or (found.data_dir / "outputs" / package.manifest.id)
    # 모델 키는 **환경변수로** 받는다 (설정 파일·명령줄에 두지 않는다, CLAUDE.md §5).
    import os  # noqa: PLC0415

    directory = app_directory(found.services)
    for app_id, why in sorted(directory.problems.items()):
        # **조용히 사라지지 않는다** — 쓰지 못한 정의는 이유와 함께 기록에 남는다.
        log.warning("외부 확장 정의를 쓰지 못한다 (%s): %s", app_id, why)
    refuse_unusable(package, directory)

    runner = Runner(
        run_id=found.run_id,
        package=package,
        data_dir=found.data_dir,
        inputs=inputs,
        mode=found.mode,
        source=found.source,
        job_id=found.job_id,
        queued_s=found.queued_s,
        env=make_env(
            package,
            output_dir=output_dir,
            readable=tuple(found.readable),
            writable=tuple(found.writable),
            llm_url=found.llm_url,
            llm_key=os.environ.get("CHK_BOT_UI__LLM__API_KEY", ""),
            llm_model=found.llm_model,
            extensions=extension_tasks(
                json.loads(found.extensions.read_text(encoding="utf-8")) if found.extensions else {}
            ),
            approval_where=found.approval_where,
            directory=directory,
        ),
    )
    state = runner.drive()
    control.clear(runner.control)
    requests.clear(runner.requests)
    # 끝난 방식을 종료 코드로도 알린다 (ADR-0023 — 실행 기록과 함께 본다).
    return 0 if state is State.DONE else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
