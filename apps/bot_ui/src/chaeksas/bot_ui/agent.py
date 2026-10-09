"""Bot UI의 머리 — 등록·하트비트·대기열 (C4, ADR-0014).

화면이 없는 순수 로직이다. **Qt를 import하지 않는다** — 그래서 화면 없이 시험할 수 있고,
트레이가 없는 환경에서도 같은 코드가 돈다.

실행 자리는 **하나**다 (ADR-0014). 자리가 비어 있으면 Center 작업을 바로 시작한 것으로 ack하고,
차 있으면 대기열에 넣는다. 대기열이 가득 차면 거절한다 (`queue_full`).

Bot을 실제로 돌리는 것은 자식 프로세스(`chk-bot-runner`, ADR-0023)다. 이 모듈은 **자리와
대기열만** 관리하고 `claim_slot()`·`release_slot()`으로 자리를 쥐고 놓는다.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chaeksas.bot_ui import machine
from chaeksas.bot_ui.bots import InstalledBot, find, installed
from chaeksas.bot_ui.center_client import CenterClient, CenterProblem, KeyRejected, MachineMismatch, Unreachable
from chaeksas.bot_ui.credentials import Credentials
from chaeksas.bot_ui.deploy import Deployer
from chaeksas.bot_ui.runner import Launcher, Running
from chaeksas.bot_ui.runtimes import BUSY, RESERVED, HostSettings, RuntimeUnavailable, runtime_ids_of
from chaeksas.bot_ui.runtimes import Runtimes as LocalRuntimes
from chaeksas.bot_ui.services import Services
from chaeksas.bot_ui.settings import Settings
from chaeksas.bot_ui.store import Store
from chaeksas.contracts import SERVICE_URL_ENV, SERVICE_URL_SETTING, STORAGE_DIR_SETTING
from chaeksas.contracts.bot_ui import (
    DEFAULT_HEARTBEAT_S,
    ApprovalAck,
    ApprovalDispatch,
    CurrentRun,
    ExtensionState,
    HeartbeatRequest,
    HeartbeatResponse,
    JobAck,
    JobDispatch,
    Queue,
    QueueItem,
    Readiness,
    RegisterRequest,
    RegisterResponse,
    Runtimes,
    Versions,
    WorkerState,
)
from chaeksas.core import requests
from chaeksas.core.extensions import ExtensionHost
from chaeksas.core.preflight import Preflight
from chaeksas.core.preflight import check as run_preflight
from chaeksas.core.processes import Supervisor
from chaeksas.core.run_log import run_dir
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
#: Bot 차례인데 Worker를 다른 쪽(셀렉터 등록·Studio 시험)이 쓰는 중 (ADR-0014 §4).
TRAY_WORKER_BUSY = "Worker를 다른 쪽이 쓰는 중 — 끝나면 실행합니다"

#: 사전 점검이 키가 없다고 할 때 「어떻게 고치나」 (BUI-10). 화면 이름은 **부르는 쪽이** 적는다.
KEY_FIX_HINT = "「도구」 → 「서비스 앱 키...」에서 등록하세요 (BUI-10)"


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
    #: 런타임이 마지막으로 말한 상태 (C13 `status`). BUI-09가 **이것을 읽는다** — 화면이 제
    #: 손으로 묻지 않는다(GUI 스레드에서 2초씩 멈춘다). `None`은 아직 묻지 않은 것,
    #: 빈 사전은 **물었는데 못 받은 것**이다 (둘은 화면에서 다르게 말한다).
    worker_status: dict[str, Any] | None = None
    #: 실행 기록 큐 (C3). 처음 쓸 때 만든다 — 설정이 가리키는 폴더를 그때 읽는다.
    _runs: RunQueue | None = None
    #: 실행기를 띄우는 쪽 (ADR-0023). 마찬가지로 처음 쓸 때 만든다.
    _launcher: Launcher | None = None
    #: 종료 중이다 — **새 Bot을 띄우지 않는다** (BUI-01 종료 순서 「1. 새 요청 막기」).
    stopping: bool = False
    #: 로컬 런타임 (C13·BUI-09). 처음 쓸 때 만든다 — 확장 호스트가 있어야 한다.
    _runtimes: LocalRuntimes | None = None
    #: 차례가 왔는데 Worker 예약이 409였다 — 대기열 맨 앞에서 기다린다 (ADR-0014 §4).
    worker_busy: bool = False
    #: 사전 점검 결과 (BUI-04 「준비」·C4 `readiness`). **설치·키·확장이 바뀌면 비운다** —
    #: 하트비트마다 OS 비밀 저장소를 두드리면 주기가 느려진다 (C4 「바뀌었을 때만 보내도 됨」).
    _preflights: dict[tuple[str, str], Preflight] = field(default_factory=dict)
    #: 이 실행에 묶은 로컬 런타임 — 끝나면 푼다.
    _reserved: list[str] = field(default_factory=list)

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
        return self.host.context(
            extension_id,
            host=HOST_BOT_UI,
            settings=HostSettings(values=self.extension_values(extension_id, runtime_ids=runtime_ids)),
            secrets=ExtensionSecrets(credentials=self.credentials, extension_id=extension_id),
        )

    def extension_values(self, extension_id: str, *, runtime_ids: tuple[str, ...] = ()) -> dict[str, object]:
        """확장에게 줄 설정 — **그 확장의 칸 + 호스트가 채우는 예약 키** (C13). 비밀은 없다."""
        values: dict[str, object] = dict(self.settings.extension(extension_id))
        values.update(self.runtimes().host_settings(runtime_ids))
        values[SERVICE_URL_SETTING] = self.service_url(extension_id)
        values[STORAGE_DIR_SETTING] = str(self.storage_dir(extension_id))
        return values

    def needed_extensions(self, bot: InstalledBot) -> set[str]:
        """그 Bot이 쓰는 확장 — `requires.extensions` + `requires.domains`의 환경을 기여한 확장 (ADR-0037)."""
        if self.host is None:
            return set()
        requires = bot.manifest.requires
        needed = {need.id for need in requires.extensions}
        needed |= {owner for owner in map(self.host.environment_owner, requires.domains) if owner}
        return needed

    # ── 사전 점검 (ADR-0013 §사전 점검, C4 `readiness`) ──

    def preflight(self, bot: InstalledBot) -> Preflight:
        """그 Bot을 **지금 이 PC에서** 돌릴 수 있나. 결과는 캐시한다.

        확장이 기여한 점검도 함께 돈다 (C13) — 호스트가 없으면 플랫폼 점검만 한다.
        """
        key = (bot.id, bot.version)
        found = self._preflights.get(key)
        if found is None:
            found = run_preflight(
                bot.manifest,
                key_value=self.credentials.service_app_key,
                host=self.host,
                context=self.extension_context if self.host is not None else None,
                fix_hint=KEY_FIX_HINT,
            )
            for why in found.skipped:
                log.warning("Bot %s의 사전 점검 하나를 돌리지 못했다: %s", bot.id, why)
            self._preflights[key] = found
        return found

    def invalidate_preflight(self) -> None:
        """키·설치·확장이 바뀌었다 — 다음에 묻는 쪽이 다시 점검한다.

        BUI-10에서 키를 넣거나 지웠을 때, 배포를 적용했을 때 부른다. **빠진 키를 등록하면 다음
        하트비트에 「준비됨」이 올라가야 한다** — 캐시가 그것을 막으면 안 된다.
        """
        self._preflights.clear()

    def readiness(self) -> list[Readiness]:
        """설치된 Bot별 준비 상태 (C4). 사전 점검 결과를 그대로 옮긴다.

        `blocked`에는 **막은 점검의 코드**가 간다 (C4 — 열린 문자열이다). 사람이 읽을 문구는
        BUI-04가 `Finding`에서 만든다 — Center로는 코드만 보낸다 (원칙 6: 업무 값을 올리지 않는다).
        """
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        out = []
        for bot in installed(data_dir()):
            found = self.preflight(bot)
            out.append(
                Readiness(
                    bpm_process_id=bot.id,
                    version=bot.version,
                    ready=not found.blocks,
                    missing_key_refs=list(found.missing_key_refs),
                    blocked=list(found.blocked),
                )
            )
        return out

    def reserve_runtimes(self, bot: InstalledBot, run_id: str) -> list[str] | None:
        """그 Bot이 쓰는 런타임을 이 실행에 묶는다 (ADR-0014 §4). **하나라도 바쁘면 `None`** —
        이미 묶은 것은 풀고, Bot은 대기열 맨 앞에서 기다린다."""
        if self.host is None:
            return []
        held: list[str] = []
        for extension_id in sorted(self.needed_extensions(bot)):
            for runtime_id in runtime_ids_of(self.host, extension_id):
                found = self.runtimes().reserve(runtime_id, run_id)
                if found == BUSY:
                    for one in held:
                        self.runtimes().release(one)
                    return None
                if found == RESERVED:
                    held.append(runtime_id)
        return held

    def release_runtimes(self) -> None:
        for runtime_id in self._reserved:
            self.runtimes().release(runtime_id)
        self._reserved = []

    def run_extensions(self, bot: InstalledBot) -> dict[str, dict[str, object]]:
        """실행기에게 넘길 확장별 설정. **그 Bot이 쓰는 확장의 로컬 런타임은 먼저 띄운다**.

        쓰는 확장은 매니페스트에서 온다 (C1): `requires.extensions`, 그리고 `requires.domains`의
        `web`·`desktop` AI 태스크 — 그 환경을 기여한 확장이다 (ADR-0037, 그림에 확장을 적지 않아도 된다).

        UI 태스크·데스크톱 AI 태스크는 Worker가 떠 있어야 돈다 — 실행기가 띄우지 않는다 (Bot은
        Worker를 띄우거나 끄지 않는다, CLAUDE.md §5). 못 띄우면 기록만 하고 실행은 보낸다 —
        그 태스크가 「Worker에 닿지 못했다」로 분명히 실패한다 (조용히 넘어가지 않는다).
        """
        if self.host is None:
            return {}
        needed = self.needed_extensions(bot)
        table: dict[str, dict[str, object]] = {}
        for found in self.host.enabled():
            runtime_ids = runtime_ids_of(self.host, found.id)
            if found.id in needed:
                for runtime_id in runtime_ids:
                    try:
                        self.runtimes().ensure(runtime_id)
                    except RuntimeUnavailable as e:
                        log.warning("Bot %s이 쓰는 %s을 띄우지 못했다: %s", bot.id, runtime_id, e)
            table[found.id] = self.extension_values(found.id, runtime_ids=runtime_ids)
        return table

    def run_services(self, bot: InstalledBot, run_id: str) -> Path | None:
        """실행기에게 줄 **바깥 앱 명부** (C7 주소 + 외부 확장 정의·봉투, C13 「전송」).

        Bot을 띄우기 **전에** 받는다 — 실행기는 Center를 부르지 않는다 (ADR-0031). 닿지 못하면
        들고 있던 것을 쓰고(ADR-0007), 받지 못한 사유는 기록에 남는다. **봉투 검증은 실행기가**
        한다 (C13 — 파일이 손을 타도 검증되지 않은 정의는 쓰이지 않는다).
        """
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        try:
            client = self.client()
        except KeyRejected:
            # 키가 없다 — **들고 있던 것으로 간다.** 키 문제는 트레이·BUI-03이 이미 말한다.
            client = None
        found = Services(data_dir=data_dir(), client=client)
        made = found.write_for(
            bot.manifest,
            path=run_dir(data_dir()) / f"{run_id}.services.json",
            # Admin 공개키는 하트비트로 온 것이다 (C4 `admin_keys`) — 배포 검증과 같은 창고.
            keys=list(self.store.state.admin_keys),
        )
        for why in found.problems:
            log.warning("바깥 앱 명부: %s", why)
        return made

    def service_url(self, extension_id: str) -> str | None:
        """확장의 서버 부분 주소. **출처는 하나다** (C13) — Center 리소스 등록이 있으면 그것,
        없으면 정의의 `service.base_url`.
        """
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        found = self.host.get(extension_id) if self.host is not None else None
        service = found.manifest.service if found is not None else None
        # 들고 있는 명부를 먼저 본다 — **Center를 여기서 부르지 않는다** (화면마다 묻지 않게).
        registered = Services(data_dir=data_dir()).base_url_of(extension_id=extension_id)
        if registered:
            return registered
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
        """C4 `worker`. 감시자가 없으면 「꺼 둠」(`off`)이다 — 확장이 아직 없는 PC.

        **예약은 런타임이 말하는 것을 싣는다** (C13 `status` → C10 `reserved_for`) — 우리가 예약을
        걸어 두었더라도 런타임이 다시 떴으면 예약은 사라진다. 상태를 못 받으면 **비운다**
        (모르는 것을 적지 않는다, CON-03 「예약」).
        """
        worker = self.supervisors.get("worker")
        if worker is None:
            return WorkerState(state="off", restarts=0, session="idle")
        # 「지금 무엇을 하나」는 런타임이 `health`로 말해 준다 (C13). 없으면 모른 채 둔다.
        running = worker.state == "running"
        health = self.runtimes().health_of("worker") if running else None
        status = self.runtimes().status_of("worker") if running else None
        # 화면이 같은 것을 또 묻지 않게 들고 있는다 (BUI-09는 Agent에서만 읽는다).
        self.worker_status = (status or {}) if running else None
        return WorkerState(
            state=worker.state,
            version=str((health or {}).get("version") or "") or None,
            restarts=worker.restarts,
            session=str((health or {}).get("session") or "idle"),
            reserved_for=str((status or {}).get("reserved_for") or "") or None,
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
            readiness=self.readiness(),
            job_acks=list(self.store.state.pending_acks),
            deployment_results=list(self.store.state.pending_deployments),
            approval_acks=list(self.store.state.pending_approval_acks),
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
        self.store.approval_acks_sent(request.approval_acks)
        self.apply(response)
        self.store.save()
        # 기록 보내기는 **하트비트가 끝난 뒤**다 — 늦어도 다음 주기에 또 보낸다.
        self.ship_runs()
        self.ship_approvals()
        return response

    # ── 지시 처리 (C4 HeartbeatResponse) ──

    def apply(self, response: HeartbeatResponse) -> None:
        """내려온 지시를 반영한다. 순서가 중요하다 — **취소를 먼저** 본다."""
        self.cancel_jobs(response.cancel_jobs)
        self.apply_deployments(response)
        self.jobs_waiting = list(response.jobs)
        for job in response.jobs:
            self.take_job(job)
        self.apply_approvals(response.approvals)

    # ── 결재 (C6, ADR-0038) ──

    def apply_approvals(self, found: list[ApprovalDispatch]) -> list[ApprovalAck]:
        """Center에서 정해진 결재를 실행기로 내려보낸다 — **제어 파일로** (ADR-0031).

        - 답: 지금 기다리는 것이면 넘기고 받았다고 한다. 아니면 `accepted: false`(`not_waiting`)
          — Center가 다시 열어 결재자가 안다 (조용히 버리지 않는다).
        - 회수·만료: 기다리는 것이면 「답 없이 끝남」으로 넘긴다. 아니면(현장에서 먼저 답해
          거둔 것 등) 할 일이 없으니 받았다고만 한다.
        """
        running = self.runner().running
        waiting = {one.request_id: one for one in running.pendings} if running is not None else {}
        made: list[ApprovalAck] = []
        for one in found:
            here = running is not None and one.request_id in waiting
            if one.state == "answered":
                if here and running is not None:
                    running.answer(one.request_id, dict(one.answer or {}), answered_by=one.answered_by or "")
                    ack = ApprovalAck(request_id=one.request_id, accepted=True)
                else:
                    ack = ApprovalAck(request_id=one.request_id, accepted=False, reason="not_waiting")
            else:
                if here and running is not None:
                    running.withdraw(
                        one.request_id, reason="expired" if one.state == "expired" else "admin_withdraw"
                    )
                ack = ApprovalAck(request_id=one.request_id, accepted=True)
            self.store.remember_approval_ack(ack)
            made.append(ack)
        return made

    def ship_approvals(self) -> None:
        """올릴 결재와 거둘 결재를 Center로 (ADR-0038). **하트비트 뒤에** 돈다 — 실행 기록처럼.

        닿지 못하면 멈추고 다음 주기에 그 자리부터. **4xx는 다시 보내지 않는다** — 한 줄이
        큐를 영원히 막는다 (거부된 결재는 현장에서 답할 수 있다 — CMN-01이 그대로 있다).
        """
        running = self.runner().running
        if running is None or not self.api_key():
            return
        path = running.requests_path
        for number, body in requests.unsent(path):
            try:
                self.client().create_approval(body)
            except (Unreachable, KeyRejected) as e:
                log.warning("결재를 올리지 못했다 — 다음 주기에 다시: %s", e)
                return
            except CenterProblem as e:
                log.warning("Center가 결재 %s를 받지 않았다 — 현장에서 답해야 한다: %s", body.get("request_id"), e)
            requests.mark_sent(path, number)
        while running.field_answered:
            request_id = running.field_answered[0]
            try:
                self.client().withdraw_approval(request_id, reason="answered_in_field")
            except (Unreachable, KeyRejected) as e:
                log.warning("현장에서 답한 결재를 거두지 못했다 — 다음 주기에 다시: %s", e)
                return
            except CenterProblem as e:
                # 409 — 이미 답했거나 닫혔다. 거둘 것이 없다.
                log.info("결재 %s는 거둘 수 없다: %s", request_id, e)
            running.field_answered.pop(0)

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
            # 설치된 것이 바뀌었다 — 새 Bot의 준비 상태를 다음 하트비트가 알려야 한다.
            self.invalidate_preflight()

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

    def claim_slot(self, item: QueueItem, *, run_id: str | None = None) -> CurrentRun:
        """대기열에서 하나를 꺼내 실행 자리에 올린다. `run_id`는 예약에 쓴 것을 그대로 받는다."""
        if self.current_run is not None:
            raise RuntimeError("실행 자리가 이미 차 있다 (PC 한 대에 실행 중 Bot은 하나다)")
        if item in self.store.state.queue:
            self.store.state.queue.remove(item)
        run = CurrentRun(
            run_id=run_id or new_run_id(),
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
        self.release_runtimes()
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

        ready = self.preflight(bot)
        if ready.blocks:
            # 키·확장이 빠졌다 — 띄우면 그 태스크에서 죽는다. **띄우기 전에** 거절한다
            # (ADR-0013 §사전 점검, C4 `not_ready`). 자리를 쥐지 않았으니 대기열은 계속 돈다.
            self.store.state.queue.remove(item)
            self.store.state.inputs.pop(item.queue_id, None)
            if item.job_id:
                self._ack_id(item.job_id, "rejected", reason="not_ready")
            self.store.save()
            log.warning("Bot %s은 준비되지 않았다: %s", bot.id, ", ".join(ready.blocked))
            return

        inputs = dict(self.store.state.inputs.get(item.queue_id) or {})
        extensions = self.run_extensions(bot)
        run_id = new_run_id()
        services_path = self.run_services(bot, run_id)
        held = self.reserve_runtimes(bot, run_id)
        if held is None:
            # 다른 쪽(셀렉터 등록·Studio 시험)이 Worker를 쓰는 중 — **강제로 닫지 않고 기다린다**
            # (ADR-0014 §4). 항목은 대기열 맨 앞에 그대로 있고 다음 주기에 다시 묻는다.
            self.worker_busy = True
            return
        self.worker_busy = False
        self._reserved = held
        run = self.claim_slot(item, run_id=run_id)
        try:
            running = self.runner().start(
                bot,
                inputs=inputs,
                source=item.source,
                job_id=item.job_id,
                run_id=run.run_id,
                extensions=extensions,
                services_path=services_path,
                # `location: follow` 결재를 어디서 답하나 — BUI-03 「원격 결재」 (ADR-0038).
                approval_where="center" if self.settings.remote_approval else "field",
            )
        except Exception as e:  # noqa: BLE001 — 띄우지 못한 것은 실행 실패다
            log.exception("실행기를 띄우지 못했다")
            if item.job_id:
                self._ack_id(item.job_id, "failed", reason=str(e)[:200])
            self.release_runtimes()
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
        if run is None and waiting and self.worker_busy:
            return TRAY_WORKER_BUSY
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
