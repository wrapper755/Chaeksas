"""실행기를 띄우고 들여다본다 (Bot UI 쪽, ADR-0023·ADR-0031).

**Bot UI는 실행기를 기다리지 않는다.** 띄워 놓고, 지금 상태는 **실행 기록 파일**을 읽어 안다
(C3) — 실행기가 멈춰도 화면은 멈추지 않는다.

- 띄우기·끝내기·Job Object는 `core.processes.ChildProcess`가 한다 (ADR-0023).
- 내려보내는 것(중지·결재 답)은 제어 파일 (`core.control`).
- 올라오는 것(노드 상태·결재 요청·끝남)은 실행 기록 (`core.run_log`).

**PC 한 대에 실행 중인 Bot은 하나**다 (ADR-0014) — 이 모듈도 하나만 들고 있는다.
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chaeksas.bot_ui.bots import InstalledBot, write_inputs
from chaeksas.bot_ui.credentials import ENV_LLM_API_KEY
from chaeksas.contracts.bot_ui import CurrentRun
from chaeksas.core import control
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
    readable: tuple[Path, ...] = (),
    llm_url: str = "",
    llm_model: str = "",
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
    for one in readable:
        args += ["--readable", str(one)]
    if llm_url:
        args += ["--llm-url", llm_url, "--llm-model", llm_model]
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

    @property
    def control_path(self) -> Path:
        return control.control_path(self.data_dir, self.run_id)

    @property
    def log_path(self) -> Path:
        return log_path(self.data_dir, self.run_id)

    @property
    def alive(self) -> bool:
        return self.child.alive

    @property
    def finished(self) -> str:
        """끝났으면 `success`·`failed`·`cancelled`, 아직이면 빈 글."""
        return self._finished

    @property
    def pendings(self) -> list[Request]:
        """답을 기다리는 결재·확인 (BUI-04 「결재 창 열기」·CMN-01)."""
        return list(self._pendings.values())

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
        elif kind in ("human_answered", "human_timeout"):
            self._pendings.pop(str(data.get("request_id") or ""), None)
        elif kind == "run_finished":
            self._finished = str(data.get("status") or "success")
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

    def answer(self, request_id: str, body: dict[str, Any], *, answered_by: str) -> None:
        """결재·확인 답 (CMN-01). **값은 제어 파일에만** 있다 (원칙 6, ADR-0031)."""
        control.answer(self.control_path, request_id, body, answered_by=answered_by)

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
        """끝난 뒤 치운다. **실행 기록은 남긴다** (Center로 가야 한다)."""
        control.clear(self.control_path)


@dataclass
class Launcher:
    """실행기를 띄우는 쪽. **한 번에 하나** (ADR-0014)."""

    data_dir: Path
    readable: tuple[Path, ...] = ()
    llm_url: str = ""
    llm_model: str = ""
    #: 모델 키 — 실행기에게 **환경변수로** 건넨다 (명령줄·설정 파일에 두지 않는다).
    llm_key: str = ""
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
        run_id: str | None = None,
    ) -> Running:
        """Bot 하나를 띄운다. 이미 돌고 있으면 거절한다 — 대기열은 부르는 쪽이 본다."""
        if self.busy:
            raise RuntimeError("이미 실행 중입니다 (PC 한 대에 Bot 하나, ADR-0014)")

        made = run_id or new_run_id()
        inputs_path: Path | None = None
        if inputs:
            inputs_path = run_dir(self.data_dir) / f"{made}.inputs.json"
            write_inputs(inputs_path, inputs)

        args = runner_args(
            package=bot.folder,
            run_id=made,
            data_dir=self.data_dir,
            inputs_path=inputs_path,
            mode=mode,
            source=source,
            job_id=job_id,
            readable=self.readable,
            llm_url=self.llm_url,
            llm_model=self.llm_model,
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
