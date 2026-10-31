"""PC 실행기의 머리 — 등록·하트비트·대기열 (C4, ADR-0014).

화면이 없는 순수 로직이다. **Qt를 import하지 않는다** — 그래서 화면 없이 시험할 수 있고,
트레이가 없는 환경에서도 같은 코드가 돈다.

실행 자리는 **하나**다 (ADR-0014). 자리가 비어 있으면 Center 작업을 바로 시작한 것으로 ack하고,
차 있으면 대기열에 넣는다. 대기열이 가득 차면 거절한다 (`queue_full`).

BPM 프로세스를 실제로 돌리는 것은 자식 프로세스(`chk-bot-runner`, ADR-0023)다. 이 모듈은 **자리와
대기열만** 관리하고 `claim_slot()`·`release_slot()`으로 자리를 쥐고 놓는다.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from chaeksas.bot_ui.center_client import CenterClient, CenterProblem, KeyRejected, MachineMismatch, Unreachable
from chaeksas.bot_ui.credentials import Credentials, SecretsUnavailable
from chaeksas.bot_ui.host_settings import HostSettings
from chaeksas.bot_ui.notices import Notices
from chaeksas.bot_ui.runner import Launcher, Running
from chaeksas.bot_ui.settings import Settings
from chaeksas.bot_ui.store import Store
from chaeksas.contracts import CALL_TOKEN_SECRET, CENTER_URL_SETTING, STORAGE_DIR_SETTING
from chaeksas.contracts.bot_ui import (
    DEFAULT_HEARTBEAT_S,
    ApprovalAck,
    ApprovalDispatch,
    BuildStamp,
    CurrentRun,
    DeploymentResult,
    EnrollRequest,
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
)
from chaeksas.contracts.center_api import delegated_run, job_source
from chaeksas.contracts.center_keys import EXPIRY_WARNING_DAYS
from chaeksas.contracts.enrollment import (
    ROTATE_NOTICE_DAYS,
    EnrollStatus,
    SealError,
    new_keypair,
    open_sealed,
    public_of,
    request_code,
)
from chaeksas.core import build_info, machine, requests
from chaeksas.core.app_directory import DirectoryCache
from chaeksas.core.deploy import APPLIED, Deployer, deployment_finding
from chaeksas.core.extensions import ExtensionHost
from chaeksas.core.packages import InstalledBot, find, installed
from chaeksas.core.preflight import Preflight
from chaeksas.core.preflight import check as run_preflight
from chaeksas.core.run_log import run_dir
from chaeksas.core.run_shipping import HttpUploader, Shipment
from chaeksas.core.run_shipping import Queue as RunQueue
from chaeksas.extension_api import HOST_BOT_UI, ExtensionContext

log = logging.getLogger(__name__)

#: 이 PC 실행기의 판 (C4 `versions`, ADR-0067) — **묶은 앱이면 빌드가 찍은 판**, 아니면 dist-info.
BOT_UI_VERSION = build_info.product_version("chaeksas-bot-ui")
CORE_VERSION = build_info.package_version("chaeksas-core")

#: 트레이 상태 글 (BUI-01). 색은 `status_map`의 「PC 실행기」·「BPM 프로세스」에서 온다.
TRAY_UNREGISTERED = "등록 전"
#: 등록 요청을 보내고 승인을 기다린다 (C4 §등록 요청과 승인) — 뒤에 요청 코드가 붙는다.
TRAY_AWAITING_APPROVAL = "승인 대기"
TRAY_DISCONNECTED = "연결 끊김"
TRAY_KEY_REVOKED = "키 폐기됨"
TRAY_KEY_EXPIRED = "키 만료"
TRAY_DISABLED = "비활성"
TRAY_ERROR = "오류"
TRAY_IDLE = "대기"

#: 호출 토큰을 새로 청하는 때 — 만료까지 이만큼 남으면 (C15 「정한 것」 — 2시간 전).
CALL_TOKEN_RENEW_S = 2 * 3600

@dataclass(frozen=True)
class ExtensionSecrets:
    """`extension_api.Secrets` — 확장 하나의 비밀을 푼다 (ADR-0013).

    **값을 가진 쪽은 호스트다.** 확장은 이름으로 묻고, 받은 값을 기록·템플릿에 넣지 않는다.
    """

    credentials: Credentials
    extension_id: str
    #: 호출 토큰을 주는 쪽 (C15) — `call_token`을 물으면 이것이 답한다 (C13 예약 비밀).
    call_token: Any = None

    def resolve(self, ref: str) -> str | None:
        if ref == CALL_TOKEN_SECRET:
            return self.call_token() if self.call_token is not None else None
        return self.credentials.extension_secret(self.extension_id, ref)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def waited(item: QueueItem, *, now: datetime | None = None) -> float | None:
    """대기열에서 기다린 초 (C3 `run_started.queued_s`).

    **모르면 `None`**이다 — 요청 시각이 깨져 있으면 0을 넣지 않는다 (0은 「기다리지 않고 바로
    돌았다」는 뜻이고, 둘을 같은 값으로 적으면 CON-01이 거짓말을 한다). 시계가 거꾸로 간
    경우(음수)도 0으로 깎는다.
    """
    try:
        asked = datetime.fromisoformat(item.requested_at)
    except ValueError:  # pragma: no cover - 깨진 기록
        return None
    return max((now or datetime.now(UTC)) - asked, timedelta(0)).total_seconds()


def _past(when: str | None, now: datetime) -> bool:
    """그 시각이 지났나. **읽을 수 없으면 지나지 않은 것으로 본다** (모르는 것으로 버리지 않는다)."""
    if not when:
        return False
    try:
        found = datetime.fromisoformat(when)
    except (TypeError, ValueError):  # pragma: no cover - C4 모델이 ISO가 아닌 값을 받지 않는다
        return False
    if found.tzinfo is None:
        # C4는 시간대가 붙은 시각을 보낸다 — 없으면 이 PC의 시간대로 읽는다 (버리지 않으려고).
        found = found.astimezone()
    return found <= now


def new_queue_id() -> str:
    return f"q_{secrets.token_hex(3)}"


def new_run_id() -> str:
    at = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"run_{at}_{secrets.token_hex(3)}"


@dataclass
class Agent:
    """PC 실행기 한 벌의 상태와 Center와의 주기.

    `register()` → `beat()`를 주기마다. 화면은 `tray_status()`·`state`만 읽는다.
    """

    settings: Settings
    store: Store
    credentials: Credentials = field(default_factory=Credentials)
    #: 확장 호스트 (ADR-0018). 없으면 확장이 없는 PC 실행기다 — 그래도 BPM 프로세스는 돈다.
    host: ExtensionHost | None = None
    #: 설치된 확장 (C13). 확장 호스트가 채운다.
    extensions: list[ExtensionState] = field(default_factory=list)
    #: 시험에서 Center를 바꿔 끼우려고 둔 자리.
    client_factory: Callable[[str, str], CenterClient] | None = None
    #: 확장을 다시 읽는 길 (BUI-11이 끄고 켠 뒤). 시험이 바꿔 끼운다 — 기본은 엔트리 포인트다.
    extension_loader: Callable[[Iterable[str]], ExtensionHost] | None = None
    #: 띄울 알림 (BUI-05). **여기는 넣기만 하고** 화면이 `take()`로 거둬 간다 — Agent는 Qt를 모른다.
    notices: Notices = field(default_factory=Notices)

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
    #: 실행 프로세스를 띄우는 쪽 (ADR-0023). 마찬가지로 처음 쓸 때 만든다.
    _launcher: Launcher | None = None
    #: 종료 중이다 — **새 BPM 프로세스를 띄우지 않는다** (BUI-01 종료 순서 「1. 새 요청 막기」).
    stopping: bool = False
    #: 사전 점검 결과 (BUI-04 「준비」·C4 `readiness`). **설치·키·확장이 바뀌면 비운다** —
    #: 하트비트마다 OS 비밀 저장소를 두드리면 주기가 느려진다 (C4 「바뀌었을 때만 보내도 됨」).
    _preflights: dict[tuple[str, str], Preflight] = field(default_factory=dict)
    #: 서비스 앱 주소를 마지막으로 받아 둔 때 (`time.monotonic`). 처음 붙은 주기는 바로 받는다.
    #: 호출 토큰 (C15) — `(원문, 만료)`. 메모리에만 든다.
    _call_token: tuple[str, str] | None = None

    def extension_context(self, extension_id: str) -> ExtensionContext:
        """확장 코드에 넘길 바깥 세상 (C13).

        설정은 **그 확장의 칸 + 호스트가 채우는 예약 키**(`center.url`·`storage.dir`)다. 비밀은 OS
        비밀 저장소에서 확장 이름 공간으로 푼다 — 확장은 값을 묻기만 한다 (ADR-0013).
        """
        if self.host is None:
            raise LookupError("확장 호스트가 없습니다")
        return self.host.context(
            extension_id,
            host=HOST_BOT_UI,
            settings=HostSettings(values=self.extension_values(extension_id)),
            secrets=ExtensionSecrets(
                credentials=self.credentials, extension_id=extension_id, call_token=self.call_token
            ),
        )

    def extension_values(self, extension_id: str) -> dict[str, object]:
        """확장에게 줄 설정 — **그 확장의 칸 + 호스트가 채우는 예약 키** (C13). 비밀은 없다."""
        values: dict[str, object] = dict(self.settings.extension(extension_id))
        values[CENTER_URL_SETTING] = self.settings.center_url
        values[STORAGE_DIR_SETTING] = str(self.storage_dir(extension_id))
        return values

    def reload_extensions(self) -> ExtensionHost:
        """확장을 **다시 읽는다** — BUI-11이 끄고 켠 뒤에 부른다 (ADR-0043).

        꺼진 확장은 기여를 하나도 내지 않으므로 태스크 종류·칸·점검이 한꺼번에 빠진다.

        사전 점검 캐시도 비운다 — 안 비우면 꺼도 「준비됨」이 하트비트로 계속 올라간다.
        """
        load = self.extension_loader or load_extensions
        host = load(self.settings.disabled_extensions)
        self.host = host
        self.extensions = host.states()
        self.invalidate_preflight()
        return host

    def needed_extensions(self, bot: InstalledBot) -> set[str]:
        """그 BPM 프로세스가 쓰는 확장 — `requires.extensions` (C1)."""
        if self.host is None:
            return set()
        return {need.id for need in bot.manifest.requires.extensions}

    # ── 사전 점검 (ADR-0013 §사전 점검, C4 `readiness`) ──

    def preflight(self, bot: InstalledBot) -> Preflight:
        """그 BPM 프로세스를 **지금 이 PC에서** 돌릴 수 있나. 결과는 캐시한다.

        확장이 기여한 점검도 함께 돈다 (C13) — 호스트가 없으면 플랫폼 점검만 한다.
        """
        key = (bot.id, bot.version)
        found = self._preflights.get(key)
        if found is None:
            found = run_preflight(
                bot.manifest,
                host=self.host,
                context=self.extension_context if self.host is not None else None,
                # **갖춘 설정은 이쪽만 안다** (C1 `requires.settings`, ADR-0059 §4) — 메일을
                # 보내는 BPM 프로세스인데 SMTP가 없으면 **띄우기 전에** 막는다.
                settings=self.settings.ready_settings(),
            )
            for why in found.skipped:
                log.warning("BPM 프로세스 %s의 사전 점검 하나를 돌리지 못했다: %s", bot.id, why)
            self._preflights[key] = found
        # **배포가 정하는 점검은 캐시하지 않는다** — 기한은 시각이 정한다 (ADR-0113 §4). 맨 앞에
        # 두어 BUI-04 「준비」가 이것을 먼저 말한다 — 다시 배포받기 전에는 다른 것을 고쳐도 돌지 않는다.
        standing = deployment_finding(bot)
        if standing is not None:
            found = Preflight(findings=(standing, *found.findings), skipped=found.skipped)
        return found

    def invalidate_preflight(self) -> None:
        """설치·확장·설정이 바뀌었다 — 다음에 묻는 쪽이 다시 점검한다."""
        self._preflights.clear()

    def readiness(self) -> list[Readiness]:
        """설치된 BPM 프로세스별 준비 상태 (C4). 사전 점검 결과를 그대로 옮긴다.

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
                    blocked=list(found.blocked),
                )
            )
        return out

    def run_extensions(self, bot: InstalledBot) -> dict[str, dict[str, object]]:
        """실행 프로세스에게 넘길 확장별 설정 (켜진 확장 모두 — 비밀은 없다)."""
        del bot
        if self.host is None:
            return {}
        return {found.id: self.extension_values(found.id) for found in self.host.enabled()}

    def run_services(self, bot: InstalledBot, run_id: str) -> Path | None:
        """실행 프로세스에게 줄 **외부 확장 정의·봉투** (C13 「전송」) — 고정한 해시와 대조하려고.

        BPM 프로세스를 띄우기 **전에** 받는다. 닿지 못하면 들고 있던 것을 쓰고(ADR-0007), **봉투 검증은
        실행 프로세스가** 한다 (C13). 주소·키는 없다 — 바깥 앱은 Center에 외부 작업으로 올린다 (ADR-0102).
        """
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        try:
            client = self.client()
        except KeyRejected:
            # 키가 없다 — **들고 있던 것으로 간다.** 키 문제는 트레이·BUI-03이 이미 말한다.
            client = None
        found = DirectoryCache.using(data_dir(), client)
        made = found.write_for(
            bot.manifest,
            path=run_dir(data_dir()) / f"{run_id}.services.json",
            # Admin 공개키는 하트비트로 온 것이다 (C4 `admin_keys`) — 배포 검증과 같은 창고.
            keys=list(self.store.state.admin_keys),
        )
        for why in found.problems:
            log.warning("외부 확장 명부: %s", why)
        return made

    def call_token(self, *, fresh_for_s: float = CALL_TOKEN_RENEW_S) -> str | None:
        """호출 토큰 (C15 「정한 것」) — 실행 프로세스가 외부 작업을 올릴 때 쓴다.

        PC 실행기가 **제 Center API 키로** 청한다(24시간). 만료가 `fresh_for_s` 안으로 들어오면 새로
        청한다. 닿지 못하면 들고 있던 것을 준다(아직 살아 있으면). **메모리에만 든다.**
        """
        held = self._call_token
        now = datetime.now(UTC)
        if held is not None and datetime.fromisoformat(held[1]) - now > timedelta(seconds=fresh_for_s):
            return held[0]
        try:
            got = self.client().call_token()
        except Exception as e:  # noqa: BLE001 — 닿지 못해도 들고 있던 것이 있으면 그것을 쓴다
            log.warning("호출 토큰을 받지 못했다: %s", e)
            if held is not None and datetime.fromisoformat(held[1]) > now:
                return held[0]
            return None
        self._call_token = (got.token, got.expires_at)
        return got.token

    def service_url(self, extension_id: str) -> str | None:
        """확장 정의에 적힌 서버 부분 주소 — **보여 주기만 한다** (BUI-11). 아무도 이 주소로 부르지
        않는다 (ADR-0102 — 바깥 기능은 Center에 외부 작업으로 올린다)."""
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
            raise KeyRejected("Center API 키가 아직 없습니다 — 등록 요청이 승인되면 받습니다", code="no_key")
        return self._client_with(key)

    def _client_with(self, key: str) -> CenterClient:
        if self.client_factory is not None:
            return self.client_factory(self.settings.center_url, key)
        return CenterClient(base_url=self.settings.center_url, api_key=key)

    # ── 등록 요청과 승인 (C4 §등록 요청과 승인, ADR-0092) ──

    @property
    def enrollment(self) -> EnrollStatus | None:
        return self.store.state.enrollment

    def _secret(self, *, make: bool) -> str | None:
        """등록 요청에 쓰는 키 쌍의 비밀 반쪽. `make`면 없을 때 만들어 **비밀 저장소에** 둔다."""
        found = self.credentials.enroll_secret()
        if found or not make:
            return found
        private, _ = new_keypair()
        self.credentials.set_enroll_secret(private)  # 저장소가 없으면 SecretsUnavailable
        return private

    def request_enrollment(self) -> EnrollStatus:
        """등록 요청을 보낸다 (BUI-03 「다시 요청」도 이것이다). 키 쌍은 있으면 그대로 쓴다.

        **요청 코드를 스스로 다시 계산해** 맞을 때만 받아들인다 — 가운데서 응답을 바꿔치면
        사람이 엉뚱한 코드를 승인하게 된다.
        """
        try:
            secret = self._secret(make=True)
        except SecretsUnavailable as e:
            problem = CenterProblem(f"키를 둘 비밀 저장소가 없어 등록 요청을 보내지 않습니다 — {e}", code="no_secrets")
            self.last_problem = problem
            raise problem from e
        assert secret is not None
        public = public_of(secret)
        request = EnrollRequest(
            schema=1,
            machine_id=self.machine_id(),
            name=self.display_name(),
            os=machine.os_label(),
            versions=self.versions(),
            runtimes=Runtimes(extensions=list(self.extensions)) if self.extensions else None,
            public_key=public,
        )
        try:
            found = self._client_with("").enroll(request)
        except CenterProblem as e:
            self.last_problem = e
            raise
        if found.code != request_code(public, found.enrollment_id):
            problem = CenterProblem(
                "Center가 준 요청 코드가 이 PC가 계산한 것과 다릅니다 — Center 주소가 맞는지 확인하세요",
                code="code_mismatch",
            )
            self.last_problem = problem
            raise problem
        self.last_problem = None
        self.store.state.enrollment = found
        self.store.save()
        log.info("등록 요청을 보냈다 — 요청 코드 %s (%s까지)", found.code, found.expires_at)
        return found

    def enroll_step(self) -> bool:
        """키가 없을 때 한 걸음. 키를 받았으면 `True` — 그다음은 평소의 `register`다.

        - 요청이 없거나 만료됐으면 새로 보낸다.
        - 기다리는 중이면 묻고, 승인됐으면 봉함을 열어 **비밀 저장소에** 넣는다.
        - 거절됐으면 사람이 「다시 요청」을 누를 때까지 기다린다 (같은 요청을 거듭 보내지 않는다).
        """
        current = self.store.state.enrollment
        if current is None or current.state == "expired":
            self.request_enrollment()
            return False
        if current.state == "rejected":
            return False
        try:
            found = self._client_with("").enroll_status(current.enrollment_id)
        except CenterProblem as e:
            if e.status == 404:
                # Center가 모르는 요청이다 (DB를 갈았거나 오래돼 지워졌다) — 새로 보낸다.
                self.store.state.enrollment = None
                self.store.save()
                return False
            self.last_problem = e
            raise
        if found.state == "approved" and found.sealed_key is not None:
            secret = self._secret(make=False)
            if secret is None:
                # 비밀 반쪽을 잃었다 — 이 봉함은 열 수 없다. 새로 요청한다.
                self.store.state.enrollment = None
                self.store.save()
                return False
            try:
                key = open_sealed(secret, found.sealed_key, salt=found.enrollment_id)
            except SealError as e:
                problem = CenterProblem(f"받은 키를 열지 못했습니다 — {e}", code="seal_error")
                self.last_problem = problem
                raise problem from e
            self.credentials.set_center_api_key(key)
            self.store.state.enrollment = found.model_copy(update={"sealed_key": None})
            self.store.save()
            self.last_problem = None
            log.info("등록 요청이 승인되어 Center API 키를 받았다")
            return True
        self.store.state.enrollment = found.model_copy(update={"sealed_key": None})
        self.store.save()
        self.last_problem = None
        return False

    def _key_notice_days(self) -> int:
        """Center가 회전해 주는 키면 7일, 아니면 14일 (C4 §키 회전, BUI-05)."""
        if self.credentials.center_key_from_env() or self.credentials.enroll_secret() is None:
            return EXPIRY_WARNING_DAYS
        return ROTATE_NOTICE_DAYS

    def _take_rotated(self, response: HeartbeatResponse) -> None:
        """하트비트 답의 새 키를 받는다 (C4 §키 회전). 다음 요청부터 새 키를 쓴다."""
        rotated = response.rotated_key
        if rotated is None or not self.bot_ui_id or self.credentials.center_key_from_env():
            return
        secret = self.credentials.enroll_secret()
        if secret is None:
            return
        try:
            key = open_sealed(secret, rotated.sealed_key, salt=self.bot_ui_id)
            self.credentials.set_center_api_key(key)
        except (SealError, SecretsUnavailable) as e:
            # 옛 키는 아직 산다 — 다음 주기에 같은 것이 또 온다.
            log.warning("새 Center API 키를 받지 못했다: %s", e)
            return
        log.info("Center API 키를 갈았다 (새 키 만료 %s)", rotated.expires_at)

    # ── 등록·하트비트 ──

    def versions(self) -> Versions:
        # **묶은 것에서 도는지**는 찍힌 파일이 말한다 — 없으면 `build`를 비운다(체크아웃이다).
        found = build_info.stamp()
        return Versions(
            bot_ui=BOT_UI_VERSION,
            core=CORE_VERSION,
            build=None if found is None else BuildStamp(commit=found.commit, built_at=found.built_at),
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
            # 공개키를 싣으면 Center가 키를 회전해 준다 (C4 §키 회전). 환경변수 키는 회전하지 않는다.
            public_key=self._register_public_key(),
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
        # 키 만료일은 **Center만 안다** (C4 `key_expires_at`) — 받은 자리에서 바로 재 둔다.
        self.notices.center_key_expiring(
            expires_at=found.key_expires_at, now=now_iso(), within_days=self._key_notice_days()
        )
        log.info("등록됨: %s (하트비트 %d초)", found.bot_ui_id, found.heartbeat_interval_s)
        return found

    def _register_public_key(self) -> str | None:
        if self.credentials.center_key_from_env():
            return None
        secret = self.credentials.enroll_secret()
        return public_of(secret) if secret else None

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
        # 돌고 있는 BPM 프로세스를 들여다보고, 자리가 비면 대기열에서 다음을 올린다 (조각 4a).
        self.pump()

        if not self.credentials.center_api_key():
            # **키가 없다 — 등록 요청을 보내고 승인을 기다린다** (C4 §등록 요청과 승인).
            try:
                got = self.enroll_step()
            except Unreachable as e:
                self.last_problem = e
                log.warning("%s", e)
                self.notices.connection(online=False)
                return None
            except CenterProblem as e:
                log.warning("등록 요청: %s", e)
                return None
            if not got:
                return None
            # 새 키다 — 들고 있던 자리 이름은 옛 키의 것이다. 등록이 다시 정한다.
            self.store.state.bot_ui_id = None

        if not self.registered:
            try:
                self.register()
            except Unreachable as e:
                # 등록도 못 한 채 Center가 꺼져 있을 수 있다 — 조용히 다음 주기를 기다린다.
                # (사람이 고칠 것이 없으므로 알림을 띄우지 않는다.)
                self.last_problem = e
                log.warning("%s", e)
                self.notices.connection(online=False)
                return None

        request = self.heartbeat_request()
        try:
            response = self.client().heartbeat(request)
        except Unreachable as e:
            # 닿지 못한 것은 **오류 상태가 아니다** — 대기열·실행은 그대로 간다.
            self.last_problem = e
            log.warning("%s", e)
            self.notices.connection(online=False)
            return None
        except CenterProblem as e:
            self.last_problem = e
            if isinstance(e, KeyRejected):
                # 키를 고치는 것은 **사람의 일**이다 (C4 403) — 지나가게 두지 않는다.
                self.notices.key_rejected()
            raise

        self.last_problem = None
        self.last_beat_at = now_iso()
        self.heartbeat_interval_s = response.next_heartbeat_s
        self.disabled = response.disabled
        # **주기마다 재지만 알림은 하루 한 번**이다 (BUI-05) — 그 판단은 `notices`가 쥔다.
        self.notices.center_key_expiring(
            expires_at=response.key_expires_at, now=self.last_beat_at, within_days=self._key_notice_days()
        )
        self._take_rotated(response)
        # 보낸 ack는 Center가 받았다 (같은 요청에 실어 보냈으므로).
        self.store.ack_sent(request.job_acks)
        self.store.deployments_sent(request.deployment_results)
        self.store.approval_acks_sent(request.approval_acks)
        self.apply(response)
        self.store.save()
        # 기록 보내기는 **하트비트가 끝난 뒤**다 — 늦어도 다음 주기에 또 보낸다.
        shipped = self.ship_runs()
        # 「복구」는 **보낸 것까지** 말한다 — 끊겨 있던 동안 쌓인 기록이 나갔다는 뜻이다 (BUI-05).
        self.notices.connection(online=True, shipped=shipped.sent)
        self.ship_approvals()
        self._renew_call_token()
        return response

    def _renew_call_token(self) -> None:
        """돌고 있는 실행의 호출 토큰이 곧 끝나면 새것을 제어 파일로 넣는다 (C15 「정한 것」 — 2시간 전)."""
        running = self.runner().running
        if running is None:
            return
        token = self.call_token()
        if token and token != running.call_token:
            running.give_call_token(token)

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
        """Center에서 정해진 결재를 실행 프로세스로 내려보낸다 — **제어 파일로** (ADR-0031).

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
                    running.answer(
                        one.request_id,
                        dict(one.answer or {}),
                        answered_by=one.answered_by or "",
                        answered_via=one.answered_via or "",
                    )
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
            else:
                # 올라갔다 — **현장에서도 답할 수 있다**고 알린다 (BUI-05·ADR-0038). 올리기
                # 전에 알리면 못 올렸는데 「올라갔습니다」가 뜬다.
                self.notices.sent_to_center(bot=running.bot.name)
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
        deployer = self.deployer()
        found = deployer.apply(response.deployments) if response.deployments else []
        if found:
            self.store.remember_deployments(found)
            # 설치된 것이 바뀌었다 — 새 BPM 프로세스의 준비 상태를 다음 하트비트가 알려야 한다.
            self.invalidate_preflight()
            self._tell_deployments(found)
        # **답한 목록과 설치를 맞춘다** (C2 §검증 규칙·C4, ADR-0113) — 여기는 Center가 **답했을
        # 때만** 온다(닿지 못하면 들고 있던 판단으로 돈다, ADR-0007). 빈 목록도 목록이다.
        for bot in deployer.reconcile(response.deployments):
            self.notices.deployment_withdrawn(bot=bot.name, version=bot.version)

    def _tell_deployments(self, found: list[DeploymentResult]) -> None:
        """배치 결정을 사람에게 알린다 (BUI-05). **거부는 지나가게 두지 않는다** (sticky).

        설치된 것은 이름·판을 말한다. 키는 보지 않는다 — 현장에 서비스 앱 키가 없다 (ADR-0102).
        설치는 됐는데 돌 수 없는 까닭(꺼 둔 확장·없는 태스크 종류)은 사전 점검이 BUI-04 「준비」로 말한다.
        """
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        for one in found:
            if one.result != APPLIED:
                # 기다리는 것(`not_before`·내려받기 실패)은 **보고조차 오지 않는다** (C2 — 거부가
                # 아니라 기다림이다). 여기 오는 나머지는 거부뿐이다.
                self.notices.deploy_refused(why=one.reason or "사유를 모릅니다")
                continue
            bot = find(data_dir(), one.bpm_process_id, one.version)
            name = bot.name if bot is not None else one.bpm_process_id
            self.notices.deployed(bot=name, version=one.version)

    def deployer(self) -> Deployer:
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        return Deployer(
            data_dir=data_dir(),
            host_id=self.bot_ui_id or "",
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
            # 받지 않은 요청은 **현장 사람도 알아야 한다** (BUI-05) — Center만 알면 PC 앞에서는
            # 「왜 안 도나」가 된다.
            self.notices.queue_full(bot=job.bpm_process_id, limit=self.settings.queue_max)
            return self._ack(job, "rejected", reason="queue_full")

        parent = delegated_run(job.requested_by)
        item = QueueItem(
            queue_id=new_queue_id(),
            # **PC 위임으로 받은 작업은 출처가 다르다** (C3·C4 `source: delegation`,
            # ADR-0062 §6) — 그 출처만 끝날 때 결과를 올린다. 일정이 만든 작업은 `schedule`이다
            # (ADR-0110) — 가르는 것은 서버 실행기와 같은 `job_source`다.
            source=job_source(job.requested_by),
            bpm_process_id=job.bpm_process_id,
            version=job.version,
            job_id=job.job_id,
            requested_at=job.requested_at,
            expires_at=job.expires_at,
        )
        self.store.state.queue.append(item)
        if job.inputs:
            self.store.state.inputs[item.queue_id] = dict(job.inputs)
        if parent:
            # 맡긴 서버 실행 — 실행을 띄울 때 C3 `run_started.parent_run_id`로 넘긴다.
            self.store.state.parents[item.queue_id] = parent
        log.info("작업 %s을 대기열 %d번째에 넣었다", job.job_id, len(self.queue))
        return self._ack(job, "queued", position=len(self.queue))

    def cancel_jobs(self, job_ids: list[str]) -> list[JobAck]:
        """콘솔에서 취소된 작업 (C4 `cancel_jobs`).

        대기열에 있으면 빼고 `cancelled`. **이미 시작했으면 멈추지 않고** `cancel_refused`다 —
        실행 중 BPM 프로세스를 멈추는 것은 schema 1 범위 밖이다 (C4).
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
                self.store.state.parents.pop(found.queue_id, None)
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
            raise RuntimeError("실행 자리가 이미 차 있다 (PC 한 대에 실행 중 BPM 프로세스는 하나다)")
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
        self.store.state.parents.pop(item.queue_id, None)
        self.store.save()
        return run

    def release_slot(self) -> None:
        """실행이 끝났다 (결과는 C3 `run_finished`로 따로 보낸다)."""
        self.current_run = None
        self.store.save()

    # ── BPM 프로세스 실행 (조각 4a — ADR-0023·0031) ──

    def runner(self) -> Launcher:
        """실행 프로세스를 띄우는 쪽. **한 번에 하나** (ADR-0014)."""
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
                # 보내기도 BUI-03이 정한다 (ADR-0059) — 비어 있으면 `chk:email`이 **보내지
                # 않고 실패한다**. 웹훅은 적어 둔 호스트만이고 비면 아무 데도 보내지 않는다.
                smtp=self.settings.smtp(),
                webhook_hosts=tuple(self.settings.webhook_allowed_hosts),
            )
        return self._launcher

    def pump(self) -> None:
        """한 주기 — 돌고 있는 것을 들여다보고, 자리가 비면 대기열에서 다음을 올린다.

        **화면도 하트비트도 이것을 부른다.** 실행 프로세스를 기다리지 않으므로 어느 쪽에서 불러도
        멈추지 않는다 (ADR-0031 — 상태는 기록 파일에서 읽는다).
        """
        launcher = self.runner()
        done = launcher.tick()
        if done is not None:
            self._finished(done)
        if launcher.running is not None:
            # 기다리는 결재·확인마다 알림 하나 (BUI-05) — **현장에서 답할 것만** 여기서 알린다.
            self.notices.requests(launcher.running.pendings, bot=launcher.running.bot.name)
            self.current_run = launcher.running.current()
            return
        self._start_next()

    def _finished(self, done: Running) -> None:
        """끝난 실행 하나를 거둔다 — Center 작업이면 결과를 ack한다 (C4)."""
        log.info("BPM 프로세스 %s 끝남 (%s)", done.bot.id, done.finished or "unknown")
        if done.finished == "failed":
            # 실패는 사람이 알아야 한다 (BUI-05). 사유는 **기록에 적힌 한 줄**이다 (C3).
            self.notices.run_failed(bot=done.bot.name, why=done.failure)
        if done.job_id:
            result = "finished" if done.finished == "success" else (
                "cancelled" if done.finished == "cancelled" else "failed"
            )
            # **PC 위임의 결과를 나르기만 한다** (C4 `JobAck.outputs`, ADR-0062 §4) — 내용을
            # 짓는 것은 실행 프로세스다(선언한 `outputs`만 골라 썼다). 위임이 아니거나 실패했으면
            # 비어 있고, 파일은 `cleanup()`이 읽으며 **그 자리에서 지웠다**.
            self._ack_id(done.job_id, result, run_id=done.run_id, outputs=done.outputs)
        self.release_slot()

    def _start_next(self) -> None:
        """대기열에서 다음을 올린다. **없는 BPM 프로세스는 건너뛰지 않고 거절한다** (C4).

        종료 중에는 아무것도 띄우지 않는다 — 종료 순서의 첫 걸음이 「새 요청 막기」다.
        """
        if self.stopping or self.disabled or self.current_run is not None:
            return
        self.drop_expired()
        item = self.next_in_queue()
        if item is None:
            return

        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        bot = find(data_dir(), item.bpm_process_id, item.version)
        if bot is None:
            # 설치되지 않은 BPM 프로세스이다 — 조용히 두면 대기열이 영원히 막힌다 (C4 `rejected`).
            self.store.state.queue.remove(item)
            self.store.state.inputs.pop(item.queue_id, None)
            self.store.state.parents.pop(item.queue_id, None)
            if item.job_id:
                self._ack_id(item.job_id, "rejected", reason="bot_not_installed")
            self.store.save()
            log.warning("설치되지 않은 BPM 프로세스이다: %s", item.bpm_process_id)
            return

        ready = self.preflight(bot)
        if ready.blocks:
            # 키·확장이 빠졌다 — 띄우면 그 태스크에서 죽는다. **띄우기 전에** 거절한다
            # (ADR-0013 §사전 점검, C4 `not_ready`). 자리를 쥐지 않았으니 대기열은 계속 돈다.
            self.store.state.queue.remove(item)
            self.store.state.inputs.pop(item.queue_id, None)
            self.store.state.parents.pop(item.queue_id, None)
            if item.job_id:
                self._ack_id(item.job_id, "rejected", reason="not_ready")
            self.store.save()
            log.warning("BPM 프로세스 %s은 준비되지 않았다: %s", bot.id, ", ".join(ready.blocked))
            return

        inputs = dict(self.store.state.inputs.get(item.queue_id) or {})
        # **읽기만 한다** — 지우는 것은 `claim_slot`이다.
        parent = self.store.state.parents.get(item.queue_id)
        extensions = self.run_extensions(bot)
        run_id = new_run_id()
        services_path = self.run_services(bot, run_id)
        run = self.claim_slot(item, run_id=run_id)
        try:
            running = self.runner().start(
                bot,
                inputs=inputs,
                source=item.source,
                job_id=item.job_id,
                # C3 `run_started.queued_s` — **여기만 안다** (요청 시각과 지금 사이).
                queued_s=waited(item),
                # C3 `run_started.parent_run_id` — **두 실행이 서로를 안다** (ADR-0062 §6).
                parent_run_id=parent,
                run_id=run.run_id,
                extensions=extensions,
                services_path=services_path,
                # 서비스 태스크는 Center에 외부 작업으로 올린다 (C15) — 주소와 호출 토큰.
                center_url=self.settings.center_url,
                call_token=self.call_token(),
                # `location: follow` 결재를 어디서 답하나 — BUI-03 「원격 결재」 (ADR-0038).
                approval_where="center" if self.settings.remote_approval else "field",
                # 사람이 BUI-11에서 끈 확장 — 자식도 같은 것을 끈다 (ADR-0043).
                off_extensions=tuple(self.settings.disabled_extensions),
            )
        except Exception as e:  # noqa: BLE001 — 띄우지 못한 것은 실행 실패다
            log.exception("실행 프로세스를 띄우지 못했다")
            if item.job_id:
                self._ack_id(item.job_id, "failed", reason=str(e)[:200])
            self.release_slot()
            return
        self.current_run = running.current()

    def next_in_queue(self) -> QueueItem | None:
        return self.queue[0] if self.queue else None

    def drop_expired(self, *, now: datetime | None = None) -> list[JobAck]:
        """기다리는 동안 유효 시간이 지난 작업을 버린다 (C4 `expired`).

        **지난 것을 돌리지 않는다** — 작업에 `expires_at`을 적는 뜻이 그것이다(「이 시간 뒤에는
        하지 마라」). 버린 것은 Center에 `expired`로 알리고 현장에도 알린다 (BUI-05).

        **모르면 버리지 않는다** — 시각을 읽을 수 없으면 그대로 둔다 (`expires_at`이 없는 수동
        실행은 여기 걸리지 않는다).
        """
        at = now or datetime.now(UTC)
        made: list[JobAck] = []
        dropped = False
        for item in list(self.queue):
            if not _past(item.expires_at, at):
                continue
            dropped = True
            self.store.state.queue.remove(item)
            self.store.state.inputs.pop(item.queue_id, None)
            self.store.state.parents.pop(item.queue_id, None)
            if item.job_id:
                made.append(self._ack_id(item.job_id, "expired"))
            self.notices.queue_expired(bot=item.bpm_process_id)
            log.warning("작업 %s이 기다리는 동안 만료됐다", item.job_id or item.queue_id)
        if dropped:
            self.store.save()
        return made

    def enqueue_manual(self, bpm_process_id: str, *, version: str | None = None, front: bool = False) -> QueueItem:
        """수동 실행 (BUI-04 「지금 실행...」). 맨 앞에 넣을 수 있다.

        **배포가 끝난 것은 넣지 않는다** (ADR-0113) — 철회·만료는 사람이 PC에서 고칠 수 없으니 넣는
        자리에서 까닭을 말한다. 다른 사전 점검은 띄울 때(`_start_next`) 본다 — 그 사이에 켜거나
        채울 수 있다.
        """
        if len(self.queue) >= self.settings.queue_max:
            raise RuntimeError(f"대기열이 가득 찼습니다 ({self.settings.queue_max}건)")
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        bot = find(data_dir(), bpm_process_id, version)
        ended = deployment_finding(bot) if bot is not None else None
        if ended is not None:
            raise RuntimeError(" ".join([ended.message, *([ended.fix_hint] if ended.fix_hint else [])]))
        item = QueueItem(
            queue_id=new_queue_id(),
            source="manual",
            bpm_process_id=bpm_process_id,
            version=version,
            requested_at=now_iso(),
        )
        self.store.state.queue.insert(0 if front else len(self.queue), item)
        self.store.save()
        if self.current_run is not None:
            # 바로 돌지 않는다 — **무엇 때문에 기다리나**까지 말한다 (BUI-05).
            self.notices.queued(
                bot=bpm_process_id,
                position=self.queue.index(item) + 1,
                running=self.current_run.bpm_process_id,
            )
        return item

    def cancel_queued(self, queue_id: str) -> JobAck | None:
        """현장에서 대기열 항목을 취소한다 (BUI-04). Center 작업이면 그렇게 알린다."""
        found = next((item for item in self.queue if item.queue_id == queue_id), None)
        if found is None:
            return None
        self.store.state.queue.remove(found)
        self.store.state.inputs.pop(queue_id, None)
        self.store.state.parents.pop(queue_id, None)
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
            pending = self.store.state.enrollment
            if pending is not None and pending.state == "pending":
                return f"{TRAY_AWAITING_APPROVAL} — 코드 {pending.code}"
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
        if self.last_problem is not None:
            parts.append(f"오류: {self.last_problem}")
        return " · ".join(parts)


def load_extensions(off: Iterable[str] = ()) -> ExtensionHost:
    """설치된 확장을 읽는다 (엔트리 포인트 `chaeksas.extensions`, ADR-0018).

    **읽다 실패해도 PC 실행기는 뜬다** — 확장 하나가 없다고 BPM 프로세스를 못 돌리면 더 나쁘다. 못 읽은
    것은 호스트가 `failures()`로 들고 있고 BUI-11이 보여 준다.

    끌 id는 **부르는 쪽이 준다** (ADR-0043 — 여기서는 PC 실행기 설정의 `disabled_extensions`).
    꺼진 확장은 기여를 하나도 내지 않는다.
    """
    host = ExtensionHost(off=off)
    try:
        host.load_entry_points()
    except Exception as e:  # noqa: BLE001 — 확장 때문에 PC 실행기가 안 뜨면 안 된다
        log.warning("확장을 읽지 못했다: %s", e)
    for failure in host.failures:
        log.warning("확장을 켜지 못했다: %s", failure)
    return host


def make_agent(settings: Settings | None = None, *, state_path: Path | None = None) -> Agent:
    """평소 쓰는 조합 — 설정 파일 + 상태 파일 + OS 비밀 저장소 + 설치된 확장."""
    from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415

    found = settings or Settings.load()
    path = state_path or (data_dir() / "state.json")
    host = load_extensions(found.disabled_extensions)
    return Agent(settings=found, store=Store.load(path), host=host, extensions=host.states())


__all__ = [
    "BOT_UI_VERSION",
    "CORE_VERSION",
    "TRAY_AWAITING_APPROVAL",
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
