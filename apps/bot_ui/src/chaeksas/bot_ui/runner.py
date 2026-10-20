"""실행기를 띄우고 들여다본다 (Bot UI 쪽, ADR-0023·ADR-0031).

**Bot UI는 실행기를 기다리지 않는다.** 띄워 놓고, 지금 상태는 **실행 기록 파일**을 읽어 안다
(C3) — 실행기가 멈춰도 화면은 멈추지 않는다.

- 띄우기·끝내기·Job Object는 `core.processes.ChildProcess`가 한다 (ADR-0023).
- 내려보내는 것(중지·결재 답)은 제어 파일 (`core.control`).
- 올라오는 것(노드 상태·결재 요청·끝남)은 실행 기록 (`core.run_log`).

**PC 한 대에 실행 중인 Bot은 하나**다 (ADR-0014) — 이 모듈도 하나만 들고 있는다.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chaeksas.bot_ui.credentials import ENV_LLM_API_KEY
from chaeksas.contracts.bot_ui import CurrentRun
from chaeksas.core import control, outputs, requests
from chaeksas.core.packages import InstalledBot, write_inputs
from chaeksas.core.processes import ChildProcess
from chaeksas.core.run_log import RunLog, log_path, run_dir

log = logging.getLogger(__name__)

#: 협조 중지에 주는 유예 (초). 지나면 Job 나무째 끝낸다 (ADR-0023).
STOP_GRACE_S = 5.0

#: 실행기 진입점 (ADR-0024 — **같은 실행 파일**을 쓴다. 개발에서는 모듈로 부른다).
RUNNER_MODULE = "chaeksas.bot_ui.runner_main"

#: C3 `run_started.run_id` 모양 — 운영 실행은 `run_`으로 시작한다.
RUN_PREFIX = "run"


def new_run_id(now: datetime | None = None) -> str:
    at = now or datetime.now(UTC)
    return f"{RUN_PREFIX}_{at:%Y%m%d_%H%M%S}_{secrets.token_hex(3)}"


def runner_args(
    *,
    package: Path,
    run_id: str,
    data_dir: Path,
    inputs_path: Path | None,
    mode: str,
    source: str,
    job_id: str | None,
    queued_s: float | None = None,
    parent_run_id: str | None = None,
    readable: tuple[Path, ...] = (),
    writable: tuple[Path, ...] = (),
    llm_url: str = "",
    llm_model: str = "",
    extensions_path: Path | None = None,
    services_path: Path | None = None,
    approval_where: str = "field",
    off_extensions: tuple[str, ...] = (),
    smtp: Any = None,
    webhook_hosts: tuple[str, ...] = (),
) -> list[str]:
    """실행기 명령줄. **업무 값은 싣지 않는다** — 입력은 파일로 준다 (원칙 6)."""
    args = [
        sys.executable,
        "-m",
        RUNNER_MODULE,
        "--package",
        str(package),
        "--run-id",
        run_id,
        "--data-dir",
        str(data_dir),
        "--mode",
        mode,
        "--source",
        source,
    ]
    if inputs_path is not None:
        args += ["--inputs", str(inputs_path)]
    if job_id:
        args += ["--job-id", job_id]
    if parent_run_id:
        # C3 `run_started.parent_run_id` — 맡긴 서버 실행 (ADR-0062 §6). **업무 값이 아니다**
        # (실행 이름이라 명령줄에 실어도 된다 — 입력과 다르다).
        args += ["--parent-run-id", parent_run_id]
    if queued_s is not None:
        # C3 `run_started.queued_s` — **모르면 넣지 않는다** (0은 「기다리지 않았다」는 뜻이다).
        args += ["--queued-s", f"{queued_s:.3f}"]
    for one in readable:
        args += ["--readable", str(one)]
    for one in writable:
        args += ["--writable", str(one)]
    if llm_url:
        args += ["--llm-url", llm_url, "--llm-model", llm_model]
    if smtp is not None and smtp.host:
        # 보내기 설정 (ADR-0059) — **비밀번호는 넘기지 않는다**. 자식이 이 PC의 비밀
        # 저장소에서 제 손으로 읽는다 (서비스 앱 키와 같은 길).
        args += ["--smtp-host", smtp.host, "--smtp-security", smtp.security]
        if smtp.port:
            args += ["--smtp-port", str(smtp.port)]
        if smtp.username:
            args += ["--smtp-user", smtp.username]
        if smtp.sender:
            args += ["--smtp-from", smtp.sender]
        args += ["--smtp-attachment-mb", f"{smtp.max_attachment_mb:g}"]
    for host in webhook_hosts:
        args += ["--webhook-host", host]
    if extensions_path is not None:
        args += ["--extensions", str(extensions_path)]
    if services_path is not None:
        args += ["--services", str(services_path)]
    for extension_id in off_extensions:
        # 사람이 BUI-11에서 끈 확장 (ADR-0043) — 자식도 기여를 내지 않게 **id만** 넘긴다.
        args += ["--off", extension_id]
    if approval_where != "field":
        args += ["--approval-where", approval_where]
    return args


@dataclass
class Request:
    """사람을 기다리는 요청 하나 — 실행 기록에서 읽은 것 (C3 `human_requested`)."""

    request_id: str
    node_id: str
    layer: str = "approval"
    where: str = "field"
    at: str = ""

    @property
    def is_confirmation(self) -> bool:
        return self.layer == "confirmation"


#: 앱이 **키를 거부한** 상태 코드 (C11 오류표 — 401 `key_invalid`, 403 `key_revoked`·`key_expired`).
#: **값이 이 PC에 없는 것(`key_missing`)은 여기 없다** — 그것은 사전 점검이 할 말이다 (ADR-0052).
KEY_REFUSED_STATUS = (401, 403)


@dataclass(frozen=True)
class KeyRefusal:
    """서비스 앱이 키를 거부한 호출 하나 — 실행 기록에서 읽은 것 (C3 `service_call`)."""

    app_id: str
    key_ref: str
    status: int


@dataclass
class Running:
    """지금 돌고 있는 Bot 하나 (실행 자리, ADR-0014)."""

    bot: InstalledBot
    run_id: str
    source: str
    started_at: str
    child: ChildProcess
    job_id: str | None = None
    data_dir: Path = field(default_factory=Path)
    #: 마지막으로 읽은 기록 줄 수 — 늘어난 것만 다시 읽는다.
    _seen: int = 0
    _state: str = "실행 중"
    _node_id: str | None = None
    _pendings: dict[str, Request] = field(default_factory=dict)
    _finished: str = ""
    #: 실패로 끝났을 때 기록에 적힌 한 줄 (C3 `run_finished`의 `message`·`code`).
    _failure: str = ""
    #: 현장에서 먼저 답한 Center 결재 — Bot UI가 Center에서 거둔다 (`answered_in_field`, ADR-0038).
    field_answered: list[str] = field(default_factory=list)
    #: 앱이 키를 거부한 호출 — `(앱, 참조)`마다 하나다 (재시도가 여러 줄을 남긴다).
    _refusals: dict[tuple[str, str], KeyRefusal] = field(default_factory=dict)
    #: **PC 위임의 결과** — 실행기가 출력 파일에 쓴 것을 `cleanup()`이 들고 온다 (ADR-0062 §4).
    #: 위임이 아니거나 실패했으면 비어 있다. 올리는 것은 `agent._finished`다.
    outputs: dict[str, Any] = field(default_factory=dict)

    @property
    def control_path(self) -> Path:
        return control.control_path(self.data_dir, self.run_id)

    @property
    def log_path(self) -> Path:
        return log_path(self.data_dir, self.run_id)

    @property
    def requests_path(self) -> Path:
        """올라갈 결재 요청 (ADR-0038) — 실행기가 쓰고 Bot UI가 나른다."""
        return requests.requests_path(self.data_dir, self.run_id)

    @property
    def field_requests_path(self) -> Path:
        """현장 결재·확인의 본문 (ADR-0078) — 실행기가 쓰고 결재 창이 **읽기만** 한다."""
        return requests.field_requests_path(self.data_dir, self.run_id)

    def body_of(self, request_id: str) -> dict[str, Any] | None:
        """그 요청의 C6 본문 — 제목·설명·폼·검토 자료 (CMN-01, ADR-0078).

        현장 것과 **Center로 올라간 것 둘 다** 본다 — 올라간 결재도 여기서 답할 수 있다
        (ADR-0038). 실행기가 아직 쓰지 않았으면(기록 줄이 먼저 쓰인다) `None`이다.
        """
        for path in (self.field_requests_path, self.requests_path):
            found = requests.find(path, request_id)
            if found is not None:
                return found
        return None

    @property
    def outputs_path(self) -> Path:
        """올라갈 위임 결과 (ADR-0062 §4) — 실행기가 쓰고 Bot UI가 나른다."""
        return outputs.outputs_path(self.data_dir, self.run_id)

    @property
    def alive(self) -> bool:
        return self.child.alive

    @property
    def finished(self) -> str:
        """끝났으면 `success`·`failed`·`cancelled`, 아직이면 빈 글."""
        return self._finished

    @property
    def failure(self) -> str:
        """실패 사유 한 줄 (BUI-05 알림·U13). **기록에 적힌 것만** 쓴다 — 없으면 빈 글이다."""
        return self._failure

    @property
    def pendings(self) -> list[Request]:
        """답을 기다리는 결재·확인 (BUI-04 「결재 창 열기」·CMN-01)."""
        return list(self._pendings.values())

    @property
    def key_refusals(self) -> list[KeyRefusal]:
        """앱이 키를 거부한 호출들 (BUI-05, ADR-0052). **끝난 뒤에도 남는다** — 실패한 실행을
        거둘 때 알리는 자리가 여기를 읽는다."""
        return list(self._refusals.values())

    def read(self) -> None:
        """기록 파일에서 **늘어난 줄만** 읽어 지금 상태를 고친다."""
        if not self.log_path.is_file():
            return
        events = list(RunLog.read(self.log_path))
        for event in events[self._seen :]:
            self._apply(event.kind, event.node_id, event.data, event.ts)
        self._seen = len(events)

    def _apply(self, kind: str, node_id: str | None, data: dict[str, Any], ts: str) -> None:
        if kind == "node_state":
            state = str(data.get("state") or "")
            if state in ("started", "waiting"):
                self._node_id = node_id
            self._state = "기다리는 중" if state == "waiting" else "실행 중"
        elif kind == "human_requested":
            request_id = str(data.get("request_id") or "")
            self._pendings[request_id] = Request(
                request_id=request_id,
                node_id=node_id or "",
                layer=str(data.get("layer") or "approval"),
                where=str(data.get("where") or "field"),
                at=ts,
            )
        elif kind in ("human_answered", "human_timeout", "human_withdrawn"):
            self._pendings.pop(str(data.get("request_id") or ""), None)
        elif kind == "service_call":
            # **묻지 않고 안다** (ADR-0052) — 앱이 키를 거부한 것은 실행이 이미 겪었다.
            # 거부만 본다: 값이 이 PC에 없는 것은 `status`가 없어 0으로 남고, 그것은
            # 「앱이 거부했다」가 아니라 사전 점검의 「서비스 앱 키 없음」이다.
            status = int(data.get("status") or 0)
            key_ref = str(data.get("key_ref") or "")
            app_id = str(data.get("app_id") or "")
            if status in KEY_REFUSED_STATUS and key_ref:
                self._refusals[(app_id, key_ref)] = KeyRefusal(app_id=app_id, key_ref=key_ref, status=status)
        elif kind == "run_finished":
            self._finished = str(data.get("status") or "success")
            # **업무 값은 없다** — `sanitize()`를 지난 `message`·`code`뿐이다 (C3, 원칙 6).
            self._failure = str(data.get("message") or data.get("code") or "")
            self._state = "완료"
            self._pendings.clear()

    def current(self) -> CurrentRun:
        """C4 하트비트의 실행 자리 (`current_run`)."""
        return CurrentRun(
            run_id=self.run_id,
            bpm_process_id=self.bot.id,
            version=self.bot.version,
            node_id=self._node_id,
            state=self._state,
            started_at=self.started_at,
            source=self.source,
            job_id=self.job_id,
        )

    # ── 내려보내기 ──

    def answer(self, request_id: str, body: dict[str, Any], *, answered_by: str, answered_via: str = "") -> None:
        """결재·확인 답 (CMN-01). **값은 제어 파일에만** 있다 (원칙 6, ADR-0031)."""
        control.answer(self.control_path, request_id, body, answered_by=answered_by, answered_via=answered_via)
        asked = self._pendings.get(request_id)
        if asked is not None and asked.where == "center" and request_id not in self.field_answered:
            # Center 결재함에도 올라가 있다 — 거두지 않으면 결재자가 끝난 것에 또 답한다.
            self.field_answered.append(request_id)

    def withdraw(self, request_id: str, *, reason: str) -> None:
        """Center 결재가 답 없이 끝났다 — 회수·만료 (ADR-0038). **답이 아니다.**"""
        control.withdraw(self.control_path, request_id, reason=reason)

    def stop(self, *, grace_s: float = STOP_GRACE_S) -> int | None:
        """협조 중지 → 유예 → Job 나무째 (ADR-0023).

        **유예를 기다려 준다.** 바로 끝내 버리면 실행기가 `run_finished(cancelled)`를 남길
        틈이 없어, 「무엇을 하다 멈췄는지」가 기록에서 사라진다. 기다려도 안 끝나면 그때
        나무째 끝낸다 (멈춰 버린 실행기도 있다).
        """
        control.stop(self.control_path)
        until = time.monotonic() + grace_s
        while self.child.alive and time.monotonic() < until:
            time.sleep(0.05)
        if not self.child.alive:
            return self.child.poll()
        log.warning("실행기가 %.1f초 안에 멈추지 않았다 — 나무째 끝낸다", grace_s)
        return self.child.stop(timeout_s=1.0)

    def cleanup(self) -> None:
        """끝난 뒤 치운다. **실행 기록은 남긴다** (Center로 가야 한다).

        요청 파일도 지운다 — 실행기가 죽으면 스스로 못 지우고, **검토 자료에는 업무 값이 있다**.

        **위임 결과는 치우기 전에 들고 온다** (ADR-0062 §4) — 읽기와 지우기를 한 걸음으로
        묶어야(`outputs.take`) 값이 디스크에 남는 길이 생기지 않는다. 올리지 못한 ack는
        메모리에 들고 있으면 되고(`pending_acks`), 파일은 들고 있을 까닭이 없다.
        """
        self.outputs = outputs.take(self.outputs_path)
        control.clear(self.control_path)
        requests.clear(self.requests_path)
        requests.clear(self.field_requests_path)


@dataclass
class Launcher:
    """실행기를 띄우는 쪽. **한 번에 하나** (ADR-0014)."""

    data_dir: Path
    readable: tuple[Path, ...] = ()
    #: 출력 폴더 밖에 쓸 수 있는 폴더 (BUI-03 「파일」, ADR-0032).
    writable: tuple[Path, ...] = ()
    llm_url: str = ""
    llm_model: str = ""
    #: 모델 키 — 실행기에게 **환경변수로** 건넨다 (명령줄·설정 파일에 두지 않는다).
    llm_key: str = ""
    #: 보내기 (BUI-03 「보내기」, ADR-0059). `SmtpConfig` 또는 `None`. **비밀번호는 없다** —
    #: 자식이 이 PC의 비밀 저장소에서 제 손으로 읽는다.
    smtp: Any = None
    #: 웹훅을 보낼 수 있는 호스트. 비면 자식이 아무 데도 보내지 않는다.
    webhook_hosts: tuple[str, ...] = ()
    #: 시험이 바꿔 끼운다 (진짜 프로세스를 띄우지 않고).
    make_child: Any = None

    running: Running | None = None

    @property
    def busy(self) -> bool:
        return self.running is not None and self.running.alive

    def start(
        self,
        bot: InstalledBot,
        *,
        inputs: dict[str, Any] | None = None,
        mode: str = "deterministic",
        source: str = "manual",
        job_id: str | None = None,
        queued_s: float | None = None,
        parent_run_id: str | None = None,
        run_id: str | None = None,
        extensions: dict[str, dict[str, Any]] | None = None,
        services_path: Path | None = None,
        approval_where: str = "field",
        off_extensions: tuple[str, ...] = (),
    ) -> Running:
        """Bot 하나를 띄운다. 이미 돌고 있으면 거절한다 — 대기열은 부르는 쪽이 본다.

        `extensions`는 확장별 설정(그 칸 + 예약 키 — Worker 자리)이다. **비밀은 없다** — 키는
        실행기가 OS 비밀 저장소에서 참조 이름으로 푼다 (ADR-0013).

        `off_extensions`는 사람이 BUI-11에서 끈 확장 id다 (ADR-0043) — **실행마다 지금 설정을
        받는다**(실행기를 띄우는 이 객체는 한 번 만들어 두고 쓴다).

        `services_path`는 바깥 앱 명부다 (C7 주소 + 외부 확장 정의·봉투, C13 「전송」) — 부르는
        쪽이 Center에서 받아 써 둔다. **봉투는 실행기가 다시 검증한다.**
        """
        if self.busy:
            raise RuntimeError("이미 실행 중입니다 (PC 한 대에 Bot 하나, ADR-0014)")

        made = run_id or new_run_id()
        inputs_path: Path | None = None
        if inputs:
            inputs_path = run_dir(self.data_dir) / f"{made}.inputs.json"
            write_inputs(inputs_path, inputs)
        extensions_path: Path | None = None
        if extensions:
            extensions_path = run_dir(self.data_dir) / f"{made}.extensions.json"
            extensions_path.parent.mkdir(parents=True, exist_ok=True)
            extensions_path.write_text(json.dumps(extensions, ensure_ascii=False, default=str), encoding="utf-8")

        args = runner_args(
            package=bot.folder,
            run_id=made,
            data_dir=self.data_dir,
            inputs_path=inputs_path,
            mode=mode,
            source=source,
            job_id=job_id,
            queued_s=queued_s,
            parent_run_id=parent_run_id,
            readable=self.readable,
            writable=self.writable,
            llm_url=self.llm_url,
            llm_model=self.llm_model,
            smtp=self.smtp,
            webhook_hosts=self.webhook_hosts,
            extensions_path=extensions_path,
            services_path=services_path,
            approval_where=approval_where,
            off_extensions=off_extensions,
        )
        factory = self.make_child or ChildProcess
        child = factory(
            args=args,
            name=f"실행기 {bot.id}",
            log_path=run_dir(self.data_dir) / f"{made}.runner.log",
            # **환경을 통째로 물려준다** — 키만 주면 PATH도 없는 자식이 된다.
            env={**os.environ, ENV_LLM_API_KEY: self.llm_key} if self.llm_key else None,
        )
        child.start()
        self.running = Running(
            bot=bot,
            run_id=made,
            source=source,
            started_at=datetime.now(UTC).isoformat(),
            child=child,
            job_id=job_id,
            data_dir=self.data_dir,
        )
        log.info("Bot %s@%s 실행 (run_id %s)", bot.id, bot.version, made)
        return self.running

    def tick(self) -> Running | None:
        """한 주기 — 기록을 읽고, 끝났으면 자리를 비운다. 끝난 실행을 돌려준다."""
        found = self.running
        if found is None:
            return None
        found.read()
        if found.alive:
            return None
        # 프로세스가 사라졌는데 기록에 끝이 없다 — 죽은 것이다 (화면이 그렇게 말해야 한다).
        if not found.finished:
            found._finished = "failed"  # noqa: SLF001 — 같은 모듈의 상태다
        found.cleanup()
        self.running = None
        return found

    def stop(self, *, grace_s: float = STOP_GRACE_S) -> Running | None:
        found = self.running
        if found is None:
            return None
        found.stop(grace_s=grace_s)
        found.read()
        found.cleanup()
        self.running = None
        return found


__all__ = [
    "RUNNER_MODULE",
    "RUN_PREFIX",
    "STOP_GRACE_S",
    "Launcher",
    "Request",
    "Running",
    "new_run_id",
    "runner_args",
]
