"""Bot UI의 머리 — 등록·하트비트·대기열 (C4, ADR-0014).

화면이 없는 순수 로직이다. **Qt를 import하지 않는다** — 그래서 화면 없이 시험할 수 있고,
트레이가 없는 환경에서도 같은 코드가 돈다.

실행 자리는 **하나**다 (ADR-0014). 자리가 비어 있으면 Center 작업을 바로 시작한 것으로 ack하고,
차 있으면 대기열에 넣는다. 대기열이 가득 차면 거절한다 (`queue_full`).

실제로 Bot을 실행하는 일(BPMN 엔진)은 M3이다. 지금은 **자리와 대기열만** 관리한다 — 그래서
`claim_slot()`·`release_slot()`을 엔진이 나중에 부르게 두었다.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from chaeksas.bot_ui import machine
from chaeksas.bot_ui.bots import find
from chaeksas.bot_ui.center_client import CenterClient, CenterProblem, KeyRejected, MachineMismatch, Unreachable
from chaeksas.bot_ui.credentials import Credentials
from chaeksas.bot_ui.deploy import Deployer
from chaeksas.bot_ui.runner import Launcher, Running
from chaeksas.bot_ui.runtimes import HostSettings
from chaeksas.bot_ui.runtimes import Runtimes as LocalRuntimes
from chaeksas.bot_ui.settings import Settings
from chaeksas.bot_ui.store import Store
from chaeksas.contracts import SERVICE_URL_ENV, SERVICE_URL_SETTING, STORAGE_DIR_SETTING
from chaeksas.contracts.bot_ui import (
    DEFAULT_HEARTBEAT_S,
    CurrentRun,
    ExtensionState,
    HeartbeatRequest,
    HeartbeatResponse,
    JobAck,
    JobDispatch,
    Queue,
    QueueItem,
    RegisterRequest,
    RegisterResponse,
    Runtimes,
    Versions,
    WorkerState,
)
from chaeksas.core.extensions import ExtensionHost
from chaeksas.core.processes import Supervisor
from chaeksas.core.run_shipping import HttpUploader, Shipment
from chaeksas.core.run_shipping import Queue as RunQueue
from chaeksas.extension_api import HOST_BOT_UI, ExtensionContext

log = logging.getLogger(__name__)

#: 이 Bot UI의 버전 (C4 `versions`). 패키지 버전을 그대로 쓴다.
try:  # pragma: no cover - 설치되지 않은 경우
    from importlib.metadata import version as _dist_version

    BOT_UI_VERSION = _dist_version("chaeksas-bot-ui")
    CORE_VERSION = _dist_version("chaeksas-core")
except Exception:  # noqa: BLE001 - 소스에서 바로 돌릴 때
    BOT_UI_VERSION = CORE_VERSION = "0.0.0"

#: 트레이 상태 글 (BUI-01). 색은 `status_map`의 「Bot UI」·「Bot」에서 온다.
TRAY_UNREGISTERED = "등록 전"
TRAY_DISCONNECTED = "연결 끊김"
TRAY_KEY_REVOKED = "키 폐기됨"
TRAY_KEY_EXPIRED = "키 만료"
TRAY_DISABLED = "비활성"
TRAY_ERROR = "오류"
TRAY_IDLE = "대기"


@dataclass(frozen=True)
class ExtensionSecrets:
    """`extension_api.Secrets` — 확장 하나의 비밀을 푼다 (ADR-0013).

    **값을 가진 쪽은 호스트다.** 확장은 이름으로 묻고, 받은 값을 기록·템플릿에 넣지 않는다.
    """

    credentials: Credentials
    extension_id: str

    def resolve(self, ref: str) -> str | None:
        return self.credentials.extension_secret(self.extension_id, ref)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_queue_id() -> str:
    return f"q_{secrets.token_hex(3)}"


def new_run_id() -> str:
    at = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"run_{at}_{secrets.token_hex(3)}"


@dataclass
class Agent:
    """Bot UI 한 벌의 상태와 Center와의 주기.

    `register()` → `beat()`를 주기마다. 화면은 `tray_status()`·`state`만 읽는다.
    """

    settings: Settings
    store: Store
    credentials: Credentials = field(default_factory=Credentials)
    #: 확장 호스트 (ADR-0018). 없으면 확장이 없는 Bot UI다 — 그래도 Bot은 돈다.
    host: ExtensionHost | None = None
    #: 설치된 확장 (C13). 확장 호스트가 채운다.
    extensions: list[ExtensionState] = field(default_factory=list)
    #: 시험에서 Center를 바꿔 끼우려고 둔 자리.
    client_factory: Callable[[str, str], CenterClient] | None = None

    # ── 지금 상태 (디스크에 남기지 않는 것) ──
    current_run: CurrentRun | None = None
    heartbeat_interval_s: int = DEFAULT_HEARTBEAT_S
    disabled: bool = False
    last_beat_at: str | None = None
    last_problem: CenterProblem | None = None
    #: 마지막 하트비트 응답으로 내려온 지시 (화면이 보여 준다).
    jobs_waiting: list[JobDispatch] = field(default_factory=list)
    #: 실행 기록 큐 (C3). 처음 쓸 때 만든다 — 설정이 가리키는 폴더를 그때 읽는다.
    _runs: RunQueue | None = None
    #: 실행기를 띄우는 쪽 (ADR-0023). 마찬가지로 처음 쓸 때 만든다.
    _launcher: Launcher | None = None
    #: 종료 중이다 — **새 Bot을 띄우지 않는다** (BUI-01 종료 순서 「1. 새 요청 막기」).
    stopping: bool = False
    #: 로컬 런타임 (C13·BUI-09). 처음 쓸 때 만든다 — 확장 호스트가 있어야 한다.
    _runtimes: LocalRuntimes | None = None

    def runtimes(self) -> LocalRuntimes:
        """확장이 기여한 로컬 런타임들. **띄우지는 않는다** — 필요할 때 `ensure()`가 띄운다."""
        if self._runtimes is None:
            self._runtimes = LocalRuntimes(
                host=self.host or ExtensionHost(),
                settings=self.settings,
                environment=self._runtime_env,
            )
        return self._runtimes

    def _runtime_env(self, extension_id: str) -> dict[str, str]:
        """로컬 런타임 자식에게 물려줄 것 — **주소뿐이다** (키는 세션이 준다, ADR-0013)."""
        found = self.service_url(extension_id)
        return {SERVICE_URL_ENV: found} if found else {}

    @property
    def supervisors(self) -> dict[str, Supervisor]:
        return self.runtimes().supervisors

    def extension_context(self, extension_id: str, *, runtime_ids: tuple[str, ...] = ()) -> ExtensionContext:
        """확장 코드에 넘길 바깥 세상 (C13).

        설정은 **그 확장의 칸 + 호스트가 채우는 예약 키**(`runtime.<id>.*`)다. 비밀은 OS
        비밀 저장소에서 확장 이름 공간으로 푼다 — 확장은 값을 묻기만 한다 (ADR-0013).
        """
        if self.host is None:
            raise LookupError("확장 호스트가 없습니다")
        values: dict[str, object] = dict(self.settings.extension(extension_id))
        values.update(self.runtimes().host_settings(runtime_ids))
        values[SERVICE_URL_SETTING] = self.service_url(extension_id)
        values[STORAGE_DIR_SETTING] = str(self.storage_dir(extension_id))
        return self.host.context(
            extension_id,
            host=HOST_BOT_UI,
            settings=HostSettings(values=values),
            secrets=ExtensionSecrets(credentials=self.credentials, extension_id=extension_id),
        )

    def service_url(self, extension_id: str) -> str | None:
        """확장의 서버 부분 주소. **출처는 하나다** (C13) — Center 리소스 등록이 있으면 그것,
        없으면 정의의 `service.base_url`.

        > 상태: Center 리소스 목록(C7)은 M5다. 그때까지는 정의의 값을 쓴다.
        """
        found = self.host.get(extension_id) if self.host is not None else None
        service = found.manifest.service if found is not None else None
        return service.base_url if service is not None else None

    def storage_dir(self, extension_id: str) -> Path:
        """확장이 자기 파일을 둘 폴더 (C13 `storage.dir`). **비밀은 여기 두지 않는다.**"""
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        found = data_dir() / "extensions" / extension_id
        found.mkdir(parents=True, exist_ok=True)
        return found

    @property
    def bot_ui_id(self) -> str | None:
        return self.store.state.bot_ui_id

    @property
    def registered(self) -> bool:
        return bool(self.bot_ui_id)

    @property
    def queue(self) -> list[QueueItem]:
        return self.store.state.queue

    def machine_id(self) -> str:
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        return machine.machine_id(data_dir())

    def display_name(self) -> str:
        return self.settings.name or machine.pc_name()

    def client(self) -> CenterClient:
        """Center 클라이언트. 키가 없으면 `KeyRejected`로 막는다 (BUI-03으로 보낸다)."""
        key = self.credentials.center_api_key()
        if not key:
            raise KeyRejected("Center API 키가 없습니다 — 설정에서 콘솔에서 발급한 키를 넣으세요", code="no_key")
        if self.client_factory is not None:
            return self.client_factory(self.settings.center_url, key)
        return CenterClient(base_url=self.settings.center_url, api_key=key)

    # ── 등록·하트비트 ──

    def versions(self) -> Versions:
        worker = self.supervisors.get("worker")
        return Versions(
            bot_ui=BOT_UI_VERSION,
            core=CORE_VERSION,
            worker=None if worker is None else BOT_UI_VERSION,
        )

    def register(self) -> RegisterResponse:
        """C4 등록. 멱등이라 켤 때마다 불러도 된다 (이름·버전이 바뀌면 Center가 갱신한다)."""
        request = RegisterRequest(
            schema=1,
            machine_id=self.machine_id(),
            name=self.display_name(),
            os=machine.os_label(),
            versions=self.versions(),
            runtimes=Runtimes(extensions=list(self.extensions)) if self.extensions else None,
        )
        try:
            found = self.client().register(request)
        except CenterProblem as e:
            self.last_problem = e
            raise
        self.last_problem = None
        self.store.state.bot_ui_id = str(found.bot_ui_id)
        self.store.save()
        self.heartbeat_interval_s = found.heartbeat_interval_s
        log.info("등록됨: %s (하트비트 %d초)", found.bot_ui_id, found.heartbeat_interval_s)
        return found

    def worker_state(self) -> WorkerState:
        """C4 `worker`. 감시자가 없으면 「꺼 둠」(`off`)이다 — 확장이 아직 없는 PC."""
        worker = self.supervisors.get("worker")
        if worker is None:
            return WorkerState(state="off", restarts=0, session="idle")
        # 「지금 무엇을 하나」는 런타임이 `health`로 말해 준다 (C13). 없으면 모른 채 둔다.
        health = self.runtimes().health_of("worker") if worker.state == "running" else None
        return WorkerState(
            state=worker.state,
            version=str((health or {}).get("version") or "") or None,
            restarts=worker.restarts,
            session=str((health or {}).get("session") or "idle"),
        )

    def wire_status(self) -> str:
        """하트비트에 싣는 `status` (C4의 알려진 값)."""
        if self.current_run is not None:
            return self.current_run.state if self.current_run.state != "running" else "running"
        if self.last_problem is not None and not isinstance(self.last_problem, Unreachable):
            return "error"
        return "idle"

    def runs(self) -> RunQueue:
        """실행 기록 큐 (C3) — `runs/`에 쌓인 것을 하트비트마다 비운다."""
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        if self._runs is None:
            self._runs = RunQueue(data_dir=data_dir())
        return self._runs

    def heartbeat_request(self) -> HeartbeatRequest:
        return HeartbeatRequest(
            schema=1,
            status=self.wire_status(),
            current_run=self.current_run,
            queue=Queue(max=self.settings.queue_max, items=list(self.queue)),
            worker=self.worker_state(),
            versions=self.versions(),
            job_acks=list(self.store.state.pending_acks),
            deployment_results=list(self.store.state.pending_deployments),
            extensions=list(self.extensions),
            unsent_events=self.runs().unsent_count(),
        )

    def api_key(self) -> str:
        return self.credentials.center_api_key() or ""

    def ship_runs(self) -> Shipment:
        """쌓인 실행 기록을 Center로 보낸다 (C3 §전송).

        **하트비트 뒤에 따로 돈다** — 실행 중에 보내면 느린 Center가 업무를 붙잡는다. 닿지
        못하면 다음 주기에 **같은 배치를 그대로** 다시 보낸다 (멱등).
        """
        key = self.api_key()
        if not key:
            return Shipment()
        found = self.runs().ship(
            HttpUploader(base_url=self.settings.center_url, api_key=key)
        )
        if found.error:
            log.warning("실행 기록을 보내지 못했다: %s", found.error)
        return found

    def beat(self) -> HeartbeatResponse | None:
        """한 주기. 닿지 못하면 `None`을 돌려주고 **실행은 계속한다** (ADR-0007).

        키가 거부되면 예외를 올린다 — 트레이가 「키 폐기됨」을 보여야 하고, 사람이 고쳐야 한다.
        """
        self.runtimes().tick()
        # 돌고 있는 Bot을 들여다보고, 자리가 비면 대기열에서 다음을 올린다 (조각 4a).
        self.pump()

        if not self.registered:
            try:
                self.register()
            except Unreachable as e:
                # 등록도 못 한 채 Center가 꺼져 있을 수 있다 — 조용히 다음 주기를 기다린다.
                # (사람이 고칠 것이 없으므로 알림을 띄우지 않는다.)
                self.last_problem = e
                log.warning("%s", e)
                return None

        request = self.heartbeat_request()
        try:
            response = self.client().heartbeat(request)
        except Unreachable as e:
            # 닿지 못한 것은 **오류 상태가 아니다** — 대기열·실행은 그대로 간다.
            self.last_problem = e
            log.warning("%s", e)
            return None
        except CenterProblem as e:
            self.last_problem = e
            raise

        self.last_problem = None
        self.last_beat_at = now_iso()
        self.heartbeat_interval_s = response.next_heartbeat_s
        self.disabled = response.disabled
        # 보낸 ack는 Center가 받았다 (같은 요청에 실어 보냈으므로).
        self.store.ack_sent(request.job_acks)
        self.store.deployments_sent(request.deployment_results)
        self.apply(response)
        self.store.save()
        # 기록 보내기는 **하트비트가 끝난 뒤**다 — 늦어도 다음 주기에 또 보낸다.
        self.ship_runs()
        return response

    # ── 지시 처리 (C4 HeartbeatResponse) ──

    def apply(self, response: HeartbeatResponse) -> None:
        """내려온 지시를 반영한다. 순서가 중요하다 — **취소를 먼저** 본다."""
        self.cancel_jobs(response.cancel_jobs)
        self.apply_deployments(response)
        self.jobs_waiting = list(response.jobs)
        for job in response.jobs:
            self.take_job(job)

    def apply_deployments(self, response: HeartbeatResponse) -> None:
        """배포를 적용한다 (C2 V1~V7). **서명이 유일한 관문**이다.

        Admin 키는 바뀌었을 때만 내려온다 (C4) — 없으면 들고 있던 것을 쓴다.
        """
        if response.admin_keys is not None:
            self.store.state.admin_keys = list(response.admin_keys)
        if not response.deployments:
            return
        found = self.deployer().apply(response.deployments)
        if found:
            self.store.remember_deployments(found)

    def deployer(self) -> Deployer:
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        return Deployer(
            data_dir=data_dir(),
            bot_ui_id=self.bot_ui_id or "",
            keys=list(self.store.state.admin_keys),
            signed_only=self.settings.signed_only,
            fetch=self.fetch_package,
        )

    def fetch_package(self, package_id: str, version: str) -> Path:
        """패키지를 내려받아 임시 파일로 (C5). **키가 없으면 받지 못한다.**"""
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        where = data_dir() / "downloads"
        where.mkdir(parents=True, exist_ok=True)
        target = where / f"{package_id}-{version}.zip"
        target.write_bytes(self.client().download_package(package_id, version))
        return target

    def take_job(self, job: JobDispatch) -> JobAck:
        """작업 하나를 받는다 (C4 작업 상태 흐름).

        **이미 본 작업이면 마지막 ack를 그대로 되돌려 보낸다** — 두 번 실행하지 않는다 (C4).
        """
        seen = self.store.state.seen_jobs.get(job.job_id)
        if seen is not None:
            self.store.remember_ack(seen)
            return seen

        if self.disabled:
            # 비활성이면 새 작업을 받지 않는다 (C4 `disabled`).
            return self._ack(job, "rejected", reason="bot_ui_shutdown")
        if len(self.queue) >= self.settings.queue_max:
            return self._ack(job, "rejected", reason="queue_full")

        item = QueueItem(
            queue_id=new_queue_id(),
            source="job",
            bpm_process_id=job.bpm_process_id,
            version=job.version,
            job_id=job.job_id,
            requested_at=job.requested_at,
            expires_at=job.expires_at,
        )
        self.store.state.queue.append(item)
        if job.inputs:
            self.store.state.inputs[item.queue_id] = dict(job.inputs)
        log.info("작업 %s을 대기열 %d번째에 넣었다", job.job_id, len(self.queue))
        return self._ack(job, "queued", position=len(self.queue))

    def cancel_jobs(self, job_ids: list[str]) -> list[JobAck]:
        """콘솔에서 취소된 작업 (C4 `cancel_jobs`).

        대기열에 있으면 빼고 `cancelled`. **이미 시작했으면 멈추지 않고** `cancel_refused`다 —
        실행 중 Bot을 멈추는 것은 schema 1 범위 밖이다 (C4).
        """
        made: list[JobAck] = []
        for job_id in job_ids:
            if self.current_run is not None and self.current_run.job_id == job_id:
                made.append(self._ack_id(job_id, "cancel_refused", reason="already_started"))
                continue
            found = next((item for item in self.queue if item.job_id == job_id), None)
            if found is not None:
                self.store.state.queue.remove(found)
                self.store.state.inputs.pop(found.queue_id, None)
                made.append(self._ack_id(job_id, "cancelled"))
                continue
            # 모르는 작업이다 — 이미 끝났거나 못 받았다. 취소된 것으로 ack해 Center에서 지운다.
            made.append(self._ack_id(job_id, "cancelled"))
        return made

    def _ack(self, job: JobDispatch, result: str, **extra: object) -> JobAck:
        return self._ack_id(job.job_id, result, **extra)

    def _ack_id(self, job_id: str, result: str, **extra: object) -> JobAck:
        ack = JobAck(job_id=job_id, result=result, **extra)  # type: ignore[arg-type]
        self.store.remember_ack(ack)
        return ack

    # ── 실행 자리 (ADR-0014 — 하나다) ──

    def claim_slot(self, item: QueueItem) -> CurrentRun:
        """대기열에서 하나를 꺼내 실행 자리에 올린다. 엔진(M3)이 부른다."""
        if self.current_run is not None:
            raise RuntimeError("실행 자리가 이미 차 있다 (PC 한 대에 실행 중 Bot은 하나다)")
        if item in self.store.state.queue:
            self.store.state.queue.remove(item)
        run = CurrentRun(
            run_id=new_run_id(),
            bpm_process_id=item.bpm_process_id,
            version=item.version or "0.0.0",
            state="running",
            started_at=now_iso(),
            source=item.source,
            job_id=item.job_id,
        )
        self.current_run = run
        if item.job_id:
            self._ack_id(item.job_id, "started", run_id=run.run_id)
        self.store.state.inputs.pop(item.queue_id, None)
        self.store.save()
        return run

    def release_slot(self) -> None:
        """실행이 끝났다 (결과는 C3 `run_finished`로 따로 보낸다)."""
        self.current_run = None
        self.store.save()

    # ── Bot 실행 (조각 4a — ADR-0023·0031) ──

    def runner(self) -> Launcher:
        """실행기를 띄우는 쪽. **한 번에 하나** (ADR-0014)."""
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        if self._launcher is None:
            # 읽기 허용 폴더·모델은 BUI-03이 정한다. **비어 있으면 그 태스크는 실패한다** —
            # 조용히 넘어가지 않는다 (ADR-0026·ADR-0027).
            self._launcher = Launcher(
                data_dir=data_dir(),
                readable=tuple(self.settings.readable_dirs),
                writable=tuple(self.settings.writable_dirs),
                llm_url=self.settings.llm_base_url,
                llm_model=self.settings.llm_model,
                llm_key=self.credentials.llm_api_key() or "",
            )
        return self._launcher

    def pump(self) -> None:
        """한 주기 — 돌고 있는 것을 들여다보고, 자리가 비면 대기열에서 다음을 올린다.

        **화면도 하트비트도 이것을 부른다.** 실행기를 기다리지 않으므로 어느 쪽에서 불러도
        멈추지 않는다 (ADR-0031 — 상태는 기록 파일에서 읽는다).
        """
        launcher = self.runner()
        done = launcher.tick()
        if done is not None:
            self._finished(done)
        if launcher.running is not None:
            self.current_run = launcher.running.current()
            return
        self._start_next()

    def _finished(self, done: Running) -> None:
        """끝난 실행 하나를 거둔다 — Center 작업이면 결과를 ack한다 (C4)."""
        log.info("Bot %s 끝남 (%s)", done.bot.id, done.finished or "unknown")
        if done.job_id:
            result = "finished" if done.finished == "success" else (
                "cancelled" if done.finished == "cancelled" else "failed"
            )
            self._ack_id(done.job_id, result, run_id=done.run_id)
        self.release_slot()

    def _start_next(self) -> None:
        """대기열에서 다음을 올린다. **없는 Bot은 건너뛰지 않고 거절한다** (C4).

        종료 중에는 아무것도 띄우지 않는다 — 종료 순서의 첫 걸음이 「새 요청 막기」다.
        """
        if self.stopping or self.disabled or self.current_run is not None:
            return
        item = self.next_in_queue()
        if item is None:
            return

        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        bot = find(data_dir(), item.bpm_process_id, item.version)
        if bot is None:
            # 설치되지 않은 Bot이다 — 조용히 두면 대기열이 영원히 막힌다 (C4 `rejected`).
            self.store.state.queue.remove(item)
            self.store.state.inputs.pop(item.queue_id, None)
            if item.job_id:
                self._ack_id(item.job_id, "rejected", reason="bot_not_installed")
            self.store.save()
            log.warning("설치되지 않은 Bot이다: %s", item.bpm_process_id)
            return

        inputs = dict(self.store.state.inputs.get(item.queue_id) or {})
        run = self.claim_slot(item)
        try:
            running = self.runner().start(
                bot, inputs=inputs, source=item.source, job_id=item.job_id, run_id=run.run_id
            )
        except Exception as e:  # noqa: BLE001 — 띄우지 못한 것은 실행 실패다
            log.exception("실행기를 띄우지 못했다")
            if item.job_id:
                self._ack_id(item.job_id, "failed", reason=str(e)[:200])
            self.release_slot()
            return
        self.current_run = running.current()

    def next_in_queue(self) -> QueueItem | None:
        return self.queue[0] if self.queue else None

    def enqueue_manual(self, bpm_process_id: str, *, version: str | None = None, front: bool = False) -> QueueItem:
        """수동 실행 (BUI-04 「지금 실행...」). 맨 앞에 넣을 수 있다."""
        if len(self.queue) >= self.settings.queue_max:
            raise RuntimeError(f"대기열이 가득 찼습니다 ({self.settings.queue_max}건)")
        item = QueueItem(
            queue_id=new_queue_id(),
            source="manual",
            bpm_process_id=bpm_process_id,
            version=version,
            requested_at=now_iso(),
        )
        self.store.state.queue.insert(0 if front else len(self.queue), item)
        self.store.save()
        return item

    def cancel_queued(self, queue_id: str) -> JobAck | None:
        """현장에서 대기열 항목을 취소한다 (BUI-04). Center 작업이면 그렇게 알린다."""
        found = next((item for item in self.queue if item.queue_id == queue_id), None)
        if found is None:
            return None
        self.store.state.queue.remove(found)
        self.store.state.inputs.pop(queue_id, None)
        ack = None
        if found.job_id:
            # C4: 현장에서 취소한 것은 `rejected` + `cancelled_on_pc`다.
            ack = self._ack_id(found.job_id, "rejected", reason="cancelled_on_pc")
        self.store.save()
        return ack

    # ── 화면이 읽는 것 ──

    def tray_status(self) -> str:
        """BUI-01 트레이 상태 글. 하나만 고른다 — 급한 것이 먼저다."""
        if not self.credentials.center_api_key():
            return TRAY_UNREGISTERED
        # 키는 있다 — 그럼 왜 못 하고 있는지가 더 쓸모 있는 말이다 (닿지 못함 / 키 거부).
        problem = self.last_problem
        if isinstance(problem, KeyRejected):
            if problem.code == "key_revoked":
                return TRAY_KEY_REVOKED
            if problem.code == "key_expired":
                return TRAY_KEY_EXPIRED
            return TRAY_UNREGISTERED
        if isinstance(problem, MachineMismatch):
            return TRAY_UNREGISTERED
        if isinstance(problem, Unreachable):
            return TRAY_DISCONNECTED
        if problem is not None:
            return TRAY_ERROR
        if not self.registered:
            return TRAY_UNREGISTERED
        if self.disabled:
            return TRAY_DISABLED

        run = self.current_run
        waiting = len(self.queue)
        if run is None:
            return f"{TRAY_IDLE} · 대기 {waiting}건" if waiting else TRAY_IDLE
        if run.state == "waiting_approval":
            return "결재 대기"
        if run.state == "waiting_confirmation":
            return "확인 대기"
        return f"실행 중 · 대기 {waiting}건" if waiting else "실행 중"

    def status_line(self) -> str:
        """BUI-02 상태 줄. 해당할 때만 뒤를 붙인다."""
        parts = [self.tray_status(), f"Center {self.settings.center_url}"]
        worker = self.settings.runtime("worker")
        if worker is not None and self.worker_state().state == "running":
            parts.append(f"Worker 127.0.0.1:{worker.port}")
        if self.last_problem is not None:
            parts.append(f"오류: {self.last_problem}")
        return " · ".join(parts)


def load_extensions() -> ExtensionHost:
    """설치된 확장을 읽는다 (엔트리 포인트 `chaeksas.extensions`, ADR-0018).

    **읽다 실패해도 Bot UI는 뜬다** — 확장 하나가 없다고 Bot을 못 돌리면 더 나쁘다. 못 읽은
    것은 호스트가 `failures()`로 들고 있고 BUI-11이 보여 준다.
    """
    host = ExtensionHost()
    try:
        host.load_entry_points()
    except Exception as e:  # noqa: BLE001 — 확장 때문에 Bot UI가 안 뜨면 안 된다
        log.warning("확장을 읽지 못했다: %s", e)
    for failure in host.failures:
        log.warning("확장을 켜지 못했다: %s", failure)
    return host


def make_agent(settings: Settings | None = None, *, state_path: Path | None = None) -> Agent:
    """평소 쓰는 조합 — 설정 파일 + 상태 파일 + OS 비밀 저장소 + 설치된 확장."""
    from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415

    found = settings or Settings.load()
    path = state_path or (data_dir() / "state.json")
    host = load_extensions()
    return Agent(settings=found, store=Store.load(path), host=host, extensions=host.states())


__all__ = [
    "BOT_UI_VERSION",
    "CORE_VERSION",
    "TRAY_DISABLED",
    "TRAY_DISCONNECTED",
    "TRAY_ERROR",
    "TRAY_IDLE",
    "TRAY_KEY_EXPIRED",
    "TRAY_KEY_REVOKED",
    "TRAY_UNREGISTERED",
    "Agent",
    "ExtensionSecrets",
    "load_extensions",
    "make_agent",
    "new_run_id",
]
