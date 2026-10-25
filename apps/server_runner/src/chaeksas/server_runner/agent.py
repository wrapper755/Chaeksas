"""실행기의 심장 — 등록하고 주기마다 하트비트를 보낸다 (C12).

**배포를 설치하고, 작업을 받아 돌리고, 기록을 Center로 보낸다** (M7 조각 3·4-①). 설치는
Bot UI와 **같은 코드**(`core.deploy`·`core.packages`)이고 다른 것은 `host_kind`뿐이다 —
서버는 `"*"` 대상 배포도 받는다 (ADR-0046).

실행 하나는 **스레드 하나**다 (`worker.Worker`, ADR-0054 §5). 자리 셈은 **기다리는 실행을
빼고** 센다 (C12 — PC와 거꾸로다). 기록은 **파일이 원본이고**(C3) 하트비트 뒤에 `core.run_shipping`이
묶어 보낸다 — 실행 중에 보내지 않는다 (느린 Center가 업무를 붙잡는다).

**기다리는 실행은 담아 두고 자리를 놓는다** (ADR-0054 §3, `store.py`) — 결재를 Center 결재함에
올리고(C6 — 서버의 창구는 Center만이다), 하트비트로 내려온 답으로 **되살려 이어 간다**.
**재시작도 같은 저장소가 넘긴다** — 다시 뜨면 담아 둔 것을 훑어 되살리고 `restored[]`로 알린다.

**메시지도 하트비트로 내려온다** (C12 §메시지) — 받을 곳을 **이쪽에서 다시 찾아**(Center가 고른
뒤 한 주기가 지났다) 넣고 ack한다. **넣을 자리가 없으면 ack하지 않고 둔다** — 그러면 Center가
다음 주기에 다시 싣는다 (거절로 적으면 멀쩡한 메시지가 버려진다).

**PC 위임도 하트비트로 돌아온다** (C12 §PC 위임, ADR-0062) — 맡기는 것은 엔진이 `RunEnv.delegate`
포트로 하고(`delegate.CenterDelegator`), 끝난 결과는 `delegations[]`로 내려와 기다리던 실행이
이어 간다. **ack가 올라가야 Center가 그 업무 값을 지운다** — 그래서 ack는 올릴 때까지 들고 있고,
올라가기 전에 같은 결과가 또 내려오면 **마지막 ack를 되돌려 보낸다** (작업·메시지와 같다).

한 걸음은 `tick()` 하나다 — **스레드를 만들지 않는다** (엔진과 같은 태도다). 부르는 쪽(`main`)이
돌리고, 시험은 `tick()`을 직접 민다.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chaeksas.contracts.bot_ui import (
    ApprovalAck,
    ApprovalDispatch,
    DeploymentResult,
    JobAck,
    JobDispatch,
    Readiness,
)
from chaeksas.contracts.center_api import delegated_run
from chaeksas.contracts.enrollment import SealError, open_sealed, public_of
from chaeksas.contracts.server_runner import (
    Capacity,
    DelegationAck,
    DelegationResult,
    MessageAck,
    MessageDispatch,
    RunnerVersions,
    ServerRunnerHeartbeatRequest,
    ServerRunnerHeartbeatResponse,
    ServerRunnerRegisterRequest,
    restorable,
    validate_heartbeat,
)
from chaeksas.contracts.signing import AdminKey
from chaeksas.core import build_info, machine
from chaeksas.core import requests as approval_requests
from chaeksas.core.app_directory import AppDirectory, DirectoryCache
from chaeksas.core.deploy import Deployer
from chaeksas.core.engine import WHERE_CENTER, EngineError, RunEnv
from chaeksas.core.extensions import ExtensionHost, HostTasks
from chaeksas.core.packages import InstalledBot, find, installed
from chaeksas.core.preflight import check as run_preflight
from chaeksas.core.run_env import make_env
from chaeksas.core.run_log import log_path
from chaeksas.core.run_shipping import HttpUploader, Queue, ShipError
from chaeksas.core.seen import Seen
from chaeksas.core.senders import make_sender
from chaeksas.core.service_keys import ReceivedKeys
from chaeksas.server_runner.center_client import (
    CenterClient,
    CenterProblem,
    KeyRejected,
    MachineMismatch,
    NotRegistered,
    Unreachable,
)
from chaeksas.server_runner.credentials import Credentials, SecretsUnavailable
from chaeksas.server_runner.delegate import CenterDelegator
from chaeksas.server_runner.extensions import load as load_extensions
from chaeksas.server_runner.extensions import tasks as extension_tasks
from chaeksas.server_runner.settings import Settings
from chaeksas.server_runner.store import Saved, Store
from chaeksas.server_runner.worker import ACK_STARTED, EMPTY_COUNTS, Worker, reopen_log

log = logging.getLogger(__name__)

#: 위임으로 받은 작업의 출처 (C3 `run_started.source`) — Bot UI와 같은 값이다.
SOURCE_DELEGATION = "delegation"

#: 보고하는 판 (C12 `versions`) — 설치된 dist-info다. **서버 실행기는 묶지 않는다** (ADR-0067).
CORE_VERSION = build_info.package_version("chaeksas-core")
RUNNER_VERSION = build_info.package_version("chaeksas-server-runner")

#: 지금 상태 (C12 `status` — 열린 문자열, 아는 값만 쓴다).
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_ERROR = "error"

#: 배포 대상 종류 (C2 §배포 대상 규칙) — 서버는 `"*"`도 받는다 (ADR-0046).
HOST_KIND = "server_runner"
#: 키가 없을 때 「어떻게 고치나」 한 줄 (사전 점검이 사람에게 보여 준다).
KEY_FIX_HINT = "환경변수 CHK_SERVER_RUNNER__SVC__<참조>로 키를 주세요"


@dataclass
class Agent:
    """실행기 하나. 상태를 들고 `tick()`으로 나아간다."""

    settings: Settings
    client: CenterClient
    #: 비밀 창고 — 서비스 앱 키 참조를 푼다 (사전 점검이 「값이 있나」를 묻는다).
    credentials: Credentials = field(default_factory=Credentials)
    #: Center가 준 신원 (C12). 등록 전에는 비어 있다.
    server_runner_id: str = ""
    #: 다음 하트비트까지 기다릴 초. 응답의 `next_heartbeat_s`를 따른다 (C12).
    next_in_s: int = 0
    #: 마지막으로 Center에게 들은 「일시 중지」 (CON-12).
    paused: bool = False
    #: 사람이 고쳐야 하는 문제 — 여기 담기면 **다시 걸어도 같다** (키·묶기).
    blocked_by: str = ""
    #: 지난 주기에 올리지 못해 **들고 있는** 것 (ADR-0007 — 부르는 쪽이 다시 온다).
    restored: list[str] = field(default_factory=list)
    #: 배포 서명을 검증할 Admin 공개키 (C2) — 하트비트로 온다. **없으면 아무것도 설치하지 않는다.**
    admin_keys: list[AdminKey] = field(default_factory=list)
    #: 아직 올리지 못한 배치 결정 (C4·C12 `deployment_results`). **올릴 때까지 들고 있는다** —
    #: 한 주기만 올라가는 값이라 흘려보내면 「왜 설치가 안 됐나」가 영영 남지 않는다.
    pending_results: list[DeploymentResult] = field(default_factory=list)
    #: 서명 없는 패키지를 설치하지 않는다 (C2 V7). 서버에서는 **끌 길을 두지 않는다**.
    signed_only: bool = True
    #: 마지막 하트비트에서 받은 지시 — 다음 조각이 읽는 자리다.
    last_response: ServerRunnerHeartbeatResponse | None = None
    #: 연결이 끊겼나 (로그를 주기마다 찍지 않으려고 바뀔 때만 본다 — BUI-05와 같은 결).
    online: bool = True
    #: 담아 둔 것을 이미 훑었나 — 등록한 뒤 **한 번만** 한다.
    _restored_once: bool = False
    #: 작업을 받아도 되나. **`--once`는 받지 않는다** — 그 프로세스는 곧 끝나므로 받으면
    #: 띄운 스레드를 버리게 되고, 다음 `--once`가 **같은 작업을 또** 띄운다(새 프로세스는
    #: `seen_jobs`가 비어 있다). 진짜 소켓으로 돌려 보고 발견한 자리다.
    accepts_jobs: bool = True

    #: 사전 점검 결과 캐시 — **설치가 바뀌면 비운다** (안 비우면 키를 넣어도 영원히 막힌다).
    _readiness: dict[tuple[str, str], Readiness] = field(default_factory=dict)
    _received: ReceivedKeys | None = None
    #: 지금 들고 있는 실행들 (`run_id` → 일꾼). 끝난 것은 거두고 ack를 쌓는다.
    workers: dict[str, Worker] = field(default_factory=dict)
    #: 아직 올리지 못한 작업 ack (C4). **올릴 때까지 들고 있는다** — 끝난 실행의 결과가
    #: 한 주기만 올라가는 값이라 흘려보내면 Center가 영영 모른다.
    pending_acks: list[JobAck] = field(default_factory=list)
    #: 이미 받은 작업 (`job_id` → 마지막 ack). **두 번 돌리지 않는다** (C4 멱등).
    #: **무한히 자라지 않는다** — ack가 Center에 닿고 몇 주기가 지나면 잊는다 (`core.seen`,
    #: ADR-0056). 메시지도, **Bot UI도** 같은 것을 쓴다 (ADR-0057 — 규칙이 갈라지면 한쪽만 고친다).
    seen_jobs: Seen[JobAck] = field(default_factory=Seen)
    #: 기다리는 실행을 담아 두는 곳 (ADR-0054 §3). 없으면 담지 않는다 (시험·한 번 돌리기).
    store: Store | None = None
    #: 아직 올리지 못한 결재 ack (C4·C6). 올릴 때까지 들고 있는다.
    pending_approval_acks: list[ApprovalAck] = field(default_factory=list)
    #: 이미 Center에 올린 결재 — **두 번 올리지 않는다**. 4xx로 거부된 것도 여기 넣는다
    #: (한 번 거부된 것을 주기마다 다시 올리면 Center 로그만 쌓인다).
    _posted: set[str] = field(default_factory=set)
    #: 아직 올리지 못한 메시지 ack (C12 §메시지). 올릴 때까지 들고 있는다.
    pending_message_acks: list[MessageAck] = field(default_factory=list)
    #: 이미 다룬 메시지 (`message_id` → 마지막 ack). **두 번 넣지 않는다** — ack가 올라가기
    #: 전에 같은 메시지가 또 내려오므로(C12), 들고 있지 않으면 한 메시지로 두 번 깨운다.
    #: **무한히 자라지 않는다** — `seen_jobs`와 **같은 규칙**이다 (`core.seen`, ADR-0056).
    #: 바깥 시스템이 밀어 넣는 것이라 수가 커서 여기가 더 급하다 (BX-11·BX-13).
    seen_messages: Seen[MessageAck] = field(default_factory=Seen)
    #: 아직 올리지 못한 위임 ack (C12 §PC 위임). 올릴 때까지 들고 있는다 — ack가 올라가야
    #: Center가 그 업무 값을 지운다 (원칙 6의 예외는 좁게 쓴다).
    pending_delegation_acks: list[DelegationAck] = field(default_factory=list)
    #: 이미 넣은 위임 결과 (`job_id` → 마지막 ack). ack가 올라가기 전에 같은 결과가 또
    #: 내려오므로(C12) 들고 있지 않으면 **지나간 자리에 또 넣으려 한다**.
    #: **스냅샷과 함께 담지 않는다** (ADR-0062 §5) — 메시지가 겪은 「넣은 뒤 담기 전에 죽는
    #: 틈」(ADR-0058)이 여기서는 생기지 않는다: 그 틈에서 죽으면 되살린 실행은 **다시 그
    #: 위임을 기다리는 자리**이고, Center도 ack를 못 받았으니 같은 결과를 다시 내려 준다.
    seen_delegations: Seen[DelegationAck] = field(default_factory=Seen)
    #: 거둬야 할 위임 작업 (ADR-0062 §5) — 서버 실행이 취소되면 그 PC 작업도 취소한다.
    #: **올릴 때까지 들고 있는다**(닿지 못하면 다음 주기에 다시 건다) — 거두지 못하면 PC가
    #: **받을 쪽이 없는 일**을 한다. 메모리뿐이다: 취소된 실행은 담아 둔 것도 지워져서
    #: 다시 뜬 실행기는 그 작업 id를 알 길이 없다 (그 값은 7일에 Center가 지운다).
    pending_cancels: list[str] = field(default_factory=list)
    #: `pending_cancels`를 지키는 자물쇠 — **일꾼 스레드도 넣는다** (함께 도는 반복의 한 건이
    #: 실패하면 엔진이 나머지를 거둔다, ADR-0087). 하트비트가 줄을 바꿔 끼우는 사이에 넣은
    #: 것을 잃지 않게 한다.
    _cancel_lock: threading.Lock = field(default_factory=threading.Lock)
    #: 확장 호스트 하나 (C13, ADR-0064) — **실행 위치를 쥔다**(서버에서 돌 수 있다고 적힌
    #: 태스크 종류만 낸다). 사전 점검과 실행이 **같은 것을 본다** — 점검이 다른 호스트를 보면
    #: 「점검은 통과했는데 실행이 안 된다」가 된다. **로컬 런타임은 띄우지 않는다.**
    host: ExtensionHost | None = None
    #: 그 호스트를 엔진·사전 점검에 꽂는 것 — 한 번 짓고 들고 있는다.
    _tasks: HostTasks | None = None

    @property
    def registered(self) -> bool:
        return bool(self.server_runner_id)

    def extension_host(self) -> ExtensionHost:
        """확장을 읽은 호스트 — 한 번 읽고 들고 있는다 (주기마다 엔트리 포인트를 걷지 않는다)."""
        if self.host is None:
            self.host = load_extensions()
        return self.host

    def extensions(self) -> HostTasks:
        """엔진의 `RunEnv.extensions`·사전 점검이 쓰는 **같은 하나** (ADR-0064).

        주소는 **받아 둔 바깥 앱 명부**가 답한다 (C7·C13 「전송」) — 확장 id로 묻는 것이라
        실행마다 다르지 않다. **Center를 부르지 않는다.**
        """
        if self._tasks is None:
            held = DirectoryCache(data_dir=self.settings.data_path)
            self._tasks = extension_tasks(
                host=self.extension_host(),
                service_url=lambda where: held.base_url_of(extension_id=where),
                credentials=self.credentials,
            )
        return self._tasks

    def machine_id(self) -> str:
        """C12 `machine_id` — **Bot UI와 같은 함수**다 (`core.machine`). 원값은 보내지 않는다."""
        return machine.machine_id(self.settings.data_path)

    def name(self) -> str:
        return self.settings.name or machine.pc_name()

    def versions(self) -> RunnerVersions:
        return RunnerVersions(server_runner=RUNNER_VERSION, core=CORE_VERSION)

    # ── 한 걸음 ──

    def tick(self) -> bool:
        """한 걸음 — 등록하지 않았으면 등록하고, 했으면 하트비트. 나아갔으면 참.

        **막혀 있으면(`blocked_by`) 아무것도 하지 않는다** — 거부된 키로 주기마다 두드리면
        Center 로그가 쓸모없이 쌓이고 운영자가 진짜 문제를 못 본다.
        """
        if self.blocked_by:
            return False
        if not self.registered:
            return self._register()
        return self._heartbeat()

    def once(self) -> bool:
        """**한 바퀴** — 등록하고 하트비트까지 한 번 (설치·설정 확인, `--once`).

        `tick()` 한 번으로는 모자라다: 새로 뜬 실행기의 첫 걸음은 **등록**이라 하트비트를
        한 번도 보내지 않고 끝난다. 그러면 「`--once`가 성공했는데 콘솔에는 오프라인」이
        된다 — 진짜 소켓으로 돌려 보고 발견한 자리다.

        **작업은 받지 않는다** — 이 프로세스는 곧 끝나므로 받으면 띄운 스레드를 버리게 된다.
        받지 않은 작업은 `dispatched`로 남아 **다음 하트비트에 다시 실린다** (C4 — ack가 올
        때까지 매번 싣는다). 그래서 잃는 것이 없고, 거짓 `started`도 보내지 않는다.
        """
        self.accepts_jobs = False
        self.tick()
        if self.registered and self.last_response is None and not self.blocked_by:
            self.tick()
        return self.last_response is not None

    def register_fields(self) -> dict[str, Any]:
        """등록 본문의 칸 — 등록과 등록 요청(C12 §등록 요청과 승인)이 같은 것을 싣는다."""
        return {
            "schema": 1,
            "machine_id": self.machine_id(),
            "name": self.name(),
            "os": machine.os_label(),
            "versions": self.versions(),
            "max_concurrency": self.settings.max_concurrency,
            "extensions": self.extension_host().states(),
        }

    def _public_key(self) -> str | None:
        """등록에 실을 공개키 — 실으면 Center가 키를 회전해 준다 (C4 §키 회전). 환경변수 키는 뺀다."""
        if self.credentials.center_key_from_env():
            return None
        secret = self.credentials.enroll_secret()
        return public_of(secret) if secret else None

    def _take_rotated(self, answer: Any) -> None:
        """하트비트 답의 새 키 (C4 §키 회전) — 비밀 저장소에 두고 **다음 요청부터** 쓴다."""
        rotated = getattr(answer, "rotated_key", None)
        if rotated is None or not self.server_runner_id or self.credentials.center_key_from_env():
            return
        secret = self.credentials.enroll_secret()
        if secret is None:
            return
        try:
            key = open_sealed(secret, rotated.sealed_key, salt=self.server_runner_id)
            self.credentials.set_center_api_key(key)
        except (SealError, SecretsUnavailable) as e:
            log.warning("새 Center API 키를 받지 못했다 (옛 키로 계속한다): %s", e)
            return
        self.client.api_key = key
        log.info("Center API 키를 갈았다 (새 키 만료 %s)", rotated.expires_at)

    def _register(self) -> bool:
        request = ServerRunnerRegisterRequest(
            schema=1,
            machine_id=self.machine_id(),
            name=self.name(),
            os=machine.os_label(),
            versions=self.versions(),
            max_concurrency=self.settings.max_concurrency,
            # **이 서버에 깔린 확장** (C12 — Bot UI의 C4와 같은 모양, `host.states()` 하나다).
            # 싣지 않으면 C7이 그 확장을 모르고, 그것을 요구하는 Bot의 **배포가 막힌다**
            # (「확장 누락」은 배포를 막는 셋 중 하나다). CON-12 상세도 이 목록을 그린다.
            extensions=self.extension_host().states(),
            public_key=self._public_key(),
        )
        try:
            answer = self.client.register(request)
        except (KeyRejected, MachineMismatch) as e:
            # 사람이 고쳐야 한다 — 다시 걸어도 같다 (C12 403·409).
            self.blocked_by = str(e)
            log.error("등록이 막혔다: %s", e)
            return False
        except Unreachable as e:
            self._went_offline(e)
            return False
        except CenterProblem as e:
            log.warning("등록이 실패했다: %s", e)
            return False

        self._came_online()
        self.server_runner_id = str(answer.server_runner_id)
        self.next_in_s = answer.heartbeat_interval_s
        if answer.admin_keys:
            # **등록 응답도 공개키를 싣는다** (C12) — 되살리기가 봉투를 검증하는 데 그것이
            # 필요하고(ADR-0007의 「들고 있던 정의」도 봉투로만 쓰인다) 되살리기는 첫 하트비트
            # 전에 일어난다. 빈 목록으로는 지우지 않는다 (「생략 = 그대로」와 같은 결).
            self.admin_keys = list(answer.admin_keys)
        log.info("등록했다: %s (주기 %d초)", self.server_runner_id, self.next_in_s)
        if not self._restored_once:
            # **등록한 뒤에 되살린다** — 되살리기가 `run_env`를 쓰고, 되살린 것은 첫 하트비트의
            # `restored[]`로 올라간다 (C12).
            self._restored_once = True
            self.restore_saved()
        return True

    def _heartbeat(self) -> bool:
        request = self._heartbeat_request()
        # 보내기 전에 **스스로 앞뒤를 본다** — Center가 받는 것과 같은 함수다 (C12).
        problems = validate_heartbeat(request)
        if problems:  # pragma: no cover - 지금은 늘 비어 있다 (도는 실행이 없다)
            log.error("보내려는 하트비트가 앞뒤가 맞지 않는다: %s", problems[0])
            return False

        try:
            answer = self.client.heartbeat(request)
        except NotRegistered as e:
            # Center가 우리를 모른다 (DB가 새로 섰다) — **다시 등록하면 이어진다** (멱등).
            log.warning("Center가 등록을 모른다 — 다시 등록한다 (%s)", e)
            self.server_runner_id = ""
            return False
        except (KeyRejected, MachineMismatch) as e:
            self.blocked_by = str(e)
            log.error("하트비트가 막혔다: %s", e)
            return False
        except Unreachable as e:
            self._went_offline(e)
            return False
        except CenterProblem as e:
            log.warning("하트비트가 실패했다: %s", e)
            return False

        self._came_online()
        self._apply(answer)
        self._take_rotated(answer)
        self._take_service_keys(request, answer)
        # **하트비트 뒤에** 한다 (C3 §전송·ADR-0038) — 실행 중에 보내면 느린 Center가 업무를
        # 붙잡는다. 결재를 먼저 올려야 다음 주기에 답이 내려올 수 있다.
        self.post_approvals()
        # **하트비트 뒤에** 거둔다 (결재 올리기와 같은 자리) — 업무를 붙잡지 않는다.
        self.cancel_delegations()
        self.ship_events()
        # **하트비트 뒤에 깨운다** (ADR-0061) — 깨운 실행은 그 자리에서 돌기 시작하고 **다음
        # 주기의 `running[]`**에 올라간다 (지금 보낸 보고를 뒤늦게 고치지 않는다).
        self.wake_due()
        return True

    # ── 배포 설치 (C2 V1~V7, C12) ──

    def deployer(self) -> Deployer:
        """배포를 적용하는 쪽. **Bot UI와 같은 코드**이고 다른 것은 `host_kind`뿐이다."""
        return Deployer(
            data_dir=self.settings.data_path,
            host_id=self.server_runner_id,
            host_kind=HOST_KIND,
            keys=list(self.admin_keys),
            signed_only=self.signed_only,
            fetch=self.fetch_package,
        )

    def fetch_package(self, package_id: str, version: str) -> Path:
        """패키지를 내려받아 파일로 (C5). **자기에게 배포된 것만** 받을 수 있다 (권한표)."""
        where = self.settings.data_path / "downloads"
        where.mkdir(parents=True, exist_ok=True)
        target = where / f"{package_id}-{version}.zip"
        target.write_bytes(self.client.download_package(package_id, version))
        return target

    def install_deployments(self, envelopes: list[dict[str, Any]]) -> list[DeploymentResult]:
        """내려온 배포를 적용한다. **거부도 보고하고**(사유와 함께) 기다림은 보고하지 않는다.

        설치가 바뀌면 사전 점검 캐시를 비운다 — 새로 깔린 Bot의 준비 상태를 다음 하트비트가
        올려야 한다.
        """
        if not envelopes:
            return []
        if not self.admin_keys:
            # **공개키가 없으면 서명을 볼 수 없다** — 설치하지 않고 다음 주기를 기다린다
            # (하트비트가 `admin_keys`를 준다). 거부로 보고하면 멀쩡한 배포가 영원히 닫힌다.
            log.info("Admin 공개키가 아직 없다 — 배포 %d건을 다음 주기에 본다", len(envelopes))
            return []
        found = self.deployer().apply(envelopes)
        if found:
            self._readiness.clear()
            for one in found:
                log.info("배포 %s: %s (%s)", one.deployment_id, one.result, one.reason or "-")
        return found

    # ── 준비 상태 (C12 `readiness`) ──

    def installed_bots(self) -> list[InstalledBot]:
        return installed(self.settings.data_path)

    def readiness(self) -> list[Readiness]:
        """설치된 Bot별 준비 상태 (C12 — C4와 같은 모양).

        **서버를 부르지 않는다** (ADR-0013 — 하트비트마다 돈다). 키는 「값이 있나」까지만 본다.

        **확장까지 본다** (ADR-0064) — 태스크 종류·확장 판·AI 환경 셋이다. 호스트가 **실행
        위치를 쥐므로**(`run_locations`에 `server`가 없는 종류는 기여를 내지 않는다) 그런 Bot은
        `task_types_wrong_location`으로 **시작 전에** 막힌다 — 전에는 배포·시작까지 가서 실행
        중에 `node_kind_unsupported`로 죽었다. **실행과 같은 호스트**를 쓴다.
        """
        out = []
        for bot in self.installed_bots():
            key = (bot.id, bot.version)
            found = self._readiness.get(key)
            if found is None:
                checked = run_preflight(
                    bot.manifest,
                    key_value=self.credentials.for_bot(bot.id).service_app_key,
                    fix_hint=KEY_FIX_HINT,
                    # **갖춘 설정은 이쪽만 안다** (C1 `requires.settings`, ADR-0059 §4) —
                    # 메일을 보내는 Bot인데 SMTP가 없으면 시작하기 전에 막는다.
                    settings=self.settings.ready_settings(),
                    host=self.extension_host(),
                    context=self.extensions().context,
                )
                found = Readiness(
                    bpm_process_id=bot.id,
                    version=bot.version,
                    ready=not checked.blocks,
                    missing_key_refs=list(checked.missing_key_refs),
                    blocked=list(checked.blocked),
                )
                self._readiness[key] = found
            out.append(found)
        return out

    # ── 다시 떴다 (ADR-0054 §2·§4) ──

    def restore_saved(self) -> None:
        """담아 둔 것을 훑어 **되살린다**. 되살린 것은 `restored[]`로 알린다 (C12).

        **되살리지 못하는 것이 둘**이다 (`restorable()` — 판정은 계약이 쥔다):
        판이 다르거나(`runner_version_changed`), **기다린 적이 없는 실행**
        (`runner_restarted` — 처음부터 다시 돌리면 메일·웹훅을 두 번 보낸다).
        그런 것은 **닫고 사유를 기록에 남긴다** — 다시 돌릴지는 운영자가 작업을 다시 내 정한다.
        """
        if self.store is None:
            return
        for saved in self.store.all():
            self._restore_one(saved)
        self._restore_absorbed()

    def _restore_absorbed(self) -> None:
        """되살린 실행이 **이미 빨아들인 메시지**를 멱등 기억에 되돌려 놓는다 (ADR-0058).

        이것이 없으면 ack가 올라가기 전에 죽은 실행기가 다시 떠서 **같은 메시지를 또 넣는다**
        — BX-11처럼 받고 또 기다리는 그림이면 되살린 실행이 그 메시지를 다시 기다리고 있다.

        **되살린 뒤에 읽는다** — 되살리지 못한 실행은 `_close_unrestored`가 행을 지우며 그
        기억도 함께 버렸다(받을 실행이 없으니 쓸 데가 없다).

        되돌린 ack는 **「아직 닿지 않았다」**로 들어간다 (`Seen.remember`) — 우리가 보낸 적이
        없으니 맞다. 다음 하트비트에 올라가고 그때부터 잊을 준비를 한다 (ADR-0056).
        """
        if self.store is None:  # pragma: no cover - 부르는 쪽이 먼저 본다
            return
        for message_id, run_id in self.store.absorbed().items():
            self._remember_message_ack(
                MessageAck(message_id=message_id, accepted=True, run_id=run_id)
            )

    def _restore_one(self, saved: Saved) -> None:
        bot = find(self.settings.data_path, saved.bpm_process_id, saved.version)
        ok, why = restorable(
            saved.bpm_process_id,
            saved.version,
            installed_process_id=bot.id if bot is not None else None,
            installed_version=bot.version if bot is not None else None,
            had_wait=saved.had_wait,
        )
        if not ok or bot is None or saved.snapshot is None:
            self._close_unrestored(saved, why or "snapshot_unreadable")
            return

        found = Worker(
            bot=bot,
            data_dir=self.settings.data_path,
            env=self.run_env(bot),
            run_id=saved.run_id,
            job_id=saved.job_id,
            store=self.store,
            # 맡겨진 실행이었으면 되살린 뒤에도 결과를 올린다 (ADR-0082).
            parent_run_id=self.store.parent_of(saved.run_id) if self.store is not None else None,
        )
        self.workers[saved.run_id] = found
        found.resume(saved.snapshot)
        self.restored.append(saved.run_id)
        log.info("실행 %s를 되살렸다 (%s)", saved.run_id, saved.bpm_process_id)

    def _close_unrestored(self, saved: Saved, why: str) -> None:
        """되살리지 못한 실행을 **닫는다** — 사유는 실행 기록에 남고 작업 ack로도 간다.

        기록에 남겨야 Center가 안다 (C3가 유일한 길이다). 작업이 딸려 있으면 그 작업도
        닫는다 — 안 하면 `accepted`로 영원히 남는다.
        """
        log.warning("실행 %s를 되살리지 않는다: %s", saved.run_id, why)
        found = reopen_log(saved.run_id, log_path(self.settings.data_path, saved.run_id))
        found.emit("log", level="warn", message=f"실행기가 다시 떠서 이어 가지 않는다: {why}")
        found.emit(
            "run_finished", status="failed", duration_s=0.0, error_code=why, **EMPTY_COUNTS
        )
        if saved.job_id:
            self._remember_ack(JobAck(job_id=saved.job_id, result="failed", reason=why))
        if self.store is not None:
            self.store.forget(saved.run_id)

    # ── 작업 (C12 §Center가 작업을 나누는 규칙, C4 ack) ──

    def take_jobs(self, jobs: list[JobDispatch]) -> None:
        """내려온 작업을 받는다. **이미 본 것은 마지막 ack를 되돌려 보낸다** (C4 멱등).

        Center는 **빈자리만큼만** 싣지만, 그래도 이쪽에서 다시 센다 — 하트비트를 보낸 뒤
        끝난 실행이 있을 수 있고, 상한을 넘겨 받으면 그 실행이 자리를 못 잡는다.
        """
        if not self.accepts_jobs:
            if jobs:
                # **ack를 보내지 않는다** — Center가 다음에 다시 싣는다 (C4). 거절로 적으면
                # 멀쩡한 작업이 닫히고, `started`로 적으면 Center가 도는 줄 알고 기다린다.
                log.info("작업 %d건을 받았으나 이 프로세스는 받지 않는다 (--once)", len(jobs))
            return
        for job in jobs:
            seen = self.seen_jobs.get(job.job_id)
            if seen is not None:
                self._remember_ack(seen)
                continue
            self._remember_ack(self._take_one(job))

    def _take_one(self, job: JobDispatch) -> JobAck:
        if self.paused:
            # 일시 중지 중에는 **새 작업을 받지 않는다** (C12 `paused`).
            return JobAck(job_id=job.job_id, result="rejected", reason="paused")
        if self.free_slots() <= 0:
            return JobAck(job_id=job.job_id, result="rejected", reason="queue_full")

        bot = find(self.settings.data_path, job.bpm_process_id, job.version)
        if bot is None:
            # **없는 Bot은 조용히 넘기지 않는다** (C4) — 배포가 아직 안 왔을 수 있다.
            return JobAck(job_id=job.job_id, result="rejected", reason="no_deployment")
        ready = self._ready_for(bot)
        if ready is not None and not ready.ready:
            # **준비되지 않은 Bot은 띄우지 않는다** (ADR-0013 — 키·확장이 빠졌다).
            return JobAck(job_id=job.job_id, result="rejected", reason="not_ready")

        directory = self.app_directory(bot)
        unusable = directory.unusable(bot.manifest.requires.extensions)
        if unusable:
            # **쓸 수 없는 외부 확장이 있으면 시작조차 하지 않는다** (C1·C13 — 중간에 알면 이미
            # 한 일을 되돌릴 수 없다). 사전 점검은 이것을 보지 않는다 — 봉투 검증은 여기서
            # 일어난다. 되살리는 쪽은 막지 않는다 (이미 시작된 실행이다).
            log.error("작업 %s를 시작하지 않는다 — %s", job.job_id, " / ".join(unusable))
            return JobAck(job_id=job.job_id, result="rejected", reason="not_ready")

        found = Worker(
            bot=bot,
            data_dir=self.settings.data_path,
            env=self.run_env(bot, directory=directory),
            job_id=job.job_id,
            inputs=dict(job.inputs),
            # **위임으로 받은 작업은 출처가 다르다** (C3 `source: delegation`, ADR-0082) — 그것을
            # 말해 주는 것은 작업의 `requested_by` 하나다(Bot UI와 같은 `delegated_run`).
            source=SOURCE_DELEGATION if delegated_run(job.requested_by) else "job",
            parent_run_id=delegated_run(job.requested_by),
            store=self.store,
        )
        self.workers[found.run_id] = found
        found.start()
        log.info("작업 %s를 시작했다 (%s, 실행 %s)", job.job_id, bot.id, found.run_id)
        return JobAck(job_id=job.job_id, result=ACK_STARTED, run_id=found.run_id)

    def _remember_ack(self, ack: JobAck) -> None:
        self.seen_jobs.remember(ack.job_id, ack)
        self.pending_acks = [one for one in self.pending_acks if one.job_id != ack.job_id]
        self.pending_acks.append(ack)

    def _ready_for(self, bot: Any) -> Readiness | None:
        return next(
            (r for r in self.readiness() if r.bpm_process_id == bot.id and r.version == bot.version),
            None,
        )

    def app_directory(self, bot: Any) -> AppDirectory:
        """그 Bot이 부르는 **바깥 앱 한 벌** (C13 「전송」, C7) — 주소와 검증된 외부 확장 정의.

        **Bot UI와 같은 코드가 받아 둔다** (`core.app_directory.DirectoryCache`) — 두 벌이면
        「PC는 되는데 서버는 안 된다」가 된다. 다른 것은 **파일을 거치지 않는 것**뿐이다:
        Bot UI는 자식 프로세스에 `--services`로 건네지만 여기서는 이 프로세스가 엔진을 돌린다
        (ADR-0031의 「실행기는 Center를 부르지 않는다」는 그 자식 이야기다).

        **닿지 못하면 들고 있던 것을 쓰고**(ADR-0007) **404는 버린다**(철회는 보안 동작이다).
        봉투는 **받은 쪽에서 다시 검증한다** (C13 E6 — `build`가 한다). 키 값은 명부에 없고
        **참조 이름**을 이 서버의 비밀 창고가 푼다 (ADR-0013).
        """
        found = DirectoryCache.using(self.settings.data_path, self.client)
        made = found.directory_for(
            bot.manifest,
            # Admin 공개키는 Center가 준 것이다 (C12 등록·하트비트) — 배포 검증과 같은 창고.
            keys=list(self.admin_keys),
            # **그 Bot이 받은 키로** 푼다 (ADR-0094 §8).
            secrets=self.credentials.for_bot(bot.id).service_app_key,
        )
        for why in found.problems:
            log.warning("바깥 앱 명부: %s", why)
        for app_id, why in sorted(made.problems.items()):
            # **조용히 사라지지 않는다** — 쓰지 못한 정의는 이유와 함께 로그에 남는다.
            log.warning("외부 확장 정의를 쓰지 못한다 (%s): %s", app_id, why)
        return made

    def run_env(self, bot: Any, *, directory: AppDirectory | None = None) -> RunEnv:
        """그 실행이 바깥 세계에 닿는 자리 — **Bot UI 실행기와 같은 함수**가 짓는다.

        `directory`를 주면 그것을 쓴다 — 작업을 받는 쪽이 **시작 전에** 이미 지었으므로
        (`_take_one`) 같은 것을 두 번 받지 않는다.

        모델·읽기 폴더는 **설정이 정한다** (Bot UI는 BUI-03이 정하는 자리다). 주지 않으면
        `NoLlm`·`PathDenied`로 **분명히 실패한다** — 조용히 넘어가지 않는다 (ADR-0027·0032).

        **보내기도 설정이 정한다** (ADR-0059) — SMTP 주소·보내는 주소가 없으면 `chk:email`이
        **보내지 않고 실패한다**(`SEND_FAILED`). 웹훅은 **허용 호스트에 적힌 곳만**이고 비면
        아무 데도 보내지 않는다. 비밀번호는 `credentials.smtp_password()`가 준다.

        **확장 태스크도 돈다** (ADR-0064) — 단 `run_locations`에 `server`를 적은 종류만이고,
        **로컬 런타임은 띄우지 않는다**. 적지 않은 종류는 사전 점검이 이미 막았다(`readiness`).
        """
        return make_env(
            bot,
            output_dir=self.settings.data_path / "outputs" / bot.id,
            readable=tuple(self.settings.readable_dirs),
            writable=tuple(self.settings.writable_dirs),
            llm_url=self.settings.llm_base_url,
            llm_key=self.credentials.llm_api_key() or "",
            llm_model=self.settings.llm_model,
            directory=directory if directory is not None else self.app_directory(bot),
            # 보내기 — **Bot UI와 같은 함수**가 짓는다 (ADR-0059).
            sender=make_sender(
                smtp=self.settings.smtp(),
                webhook=self.settings.webhook(),
                password=self.credentials.smtp_password() or "",
            ),
            # 누가 부르는가 (C11 `caller.type`) — 앱의 기록에 「서버 실행기」로 남는다.
            caller_type=HOST_KIND,
            # 서버 실행기의 결재 창구는 **Center만**이다 (C12).
            approval_where=WHERE_CENTER,
            # **PC 위임은 Center에 맡긴다** (ADR-0062) — 어느 PC인가도 Center가 고른다.
            # Bot UI는 이 포트를 꽂지 않는다 (PC가 PC를 기다리면 서로를 기다릴 수 있다).
            delegate=CenterDelegator(client=self.client, on_withdraw=self.withdraw_later),
            # **확장 태스크** (C13·ADR-0064) — 호스트가 실행 위치를 쥐어 서버에서 돌 수 있는
            # 종류만 수행기를 낸다. 없는 종류는 엔진이 설치 오류로 올린다.
            extensions=self.extensions_for(bot),
        )

    def extensions_for(self, bot: Any) -> HostTasks:
        """그 Bot의 실행이 쓰는 확장 — 확장이 묻는 참조 이름을 **그 Bot이 받은 키로** 푼다 (ADR-0094 §8).

        호스트는 사전 점검과 **같은 하나**다(`extensions()` — 점검과 실행이 같은 호스트를 본다).
        """
        held = DirectoryCache(data_dir=self.settings.data_path)
        return extension_tasks(
            host=self.extension_host(),
            service_url=lambda where: held.base_url_of(extension_id=where),
            credentials=self.credentials.for_bot(bot.id),
        )

    def wake_due(self) -> int:
        """**시각이 된 타이머로 기다리는 실행을 깨운다** — 깨운 수를 돌려준다 (ADR-0061).

        타이머를 보는 자리가 일꾼의 루프 안뿐이라, 기다리며 스레드를 놓은 실행은 시각이 되어도
        스스로 깨어나지 못한다 (ADR-0054 §5). 메시지·결재는 **들어오는 지시**가 깨우지만 타이머는
        깨울 사람이 없어서 이 쓸기가 그 일을 한다 — C12 §재시작과 유실의 「기한은 Center가 꺼져
        있어도 간다」를 지키는 자리다.

        **자리가 있을 때만 깨운다.** 기다리는 실행은 자리를 놓았으므로 깨우면 다시 쥔다 —
        빈자리가 없으면 **다음 주기에 다시 본다**(상한을 넘겨 돌지 않는다). 그래서 기한은
        **「그 시각 이후」**이고, 밀린 것은 `waiting[].until`이 지난 시각으로 올라가 보인다.

        **네트워크를 쓰지 않는다** — 로컬 시계와 메모리의 일꾼만 본다.
        """
        woken = 0
        # **오래 기다린 것부터** 깨운다 (C12의 작업 고르기와 같은 결) — 자리가 모자랄 때
        # 늦게 기다린 것이 먼저 깨면 먼저 기다린 쪽이 영원히 밀린다.
        for found in sorted(self.workers.values(), key=lambda one: one.run_id):
            if self.free_slots() <= 0:
                break
            if found.wake():
                woken += 1
                log.info("실행 %s를 깨웠다 (타이머)", found.run_id)
        return woken

    def collect(self) -> None:
        """끝난 실행을 거두고 ack를 쌓는다. **거둔 뒤에 자리가 빈다.**"""
        for run_id, found in list(self.workers.items()):
            shot = found.snapshot()
            if not shot.done:
                continue
            result = found.ack_result()
            log.info("실행 %s 끝남 (%s)", run_id, shot.finished)
            if found.job_id and result is not None:
                # **실행의 성패는 작업 상태가 아니다** (C5) — Center는 `run_status`에만 적는다.
                self._remember_ack(
                    JobAck(
                        job_id=found.job_id,
                        result=result,
                        run_id=run_id,
                        reason=shot.failure or None,
                        # 위임으로 받은 작업이면 **선언한 결과**가 맡긴 실행에 돌아간다 (ADR-0082).
                        outputs=found.delegated_outputs(),
                    )
                )
            del self.workers[run_id]

    def free_slots(self) -> int:
        """빈자리 — **기다리는 실행은 세지 않는다** (C12, ADR-0054 §5)."""
        return max(0, self.settings.max_concurrency - self._running_count())

    def _running_count(self) -> int:
        return sum(1 for found in self.workers.values() if found.snapshot().holds_a_slot)

    def cancel_job(self, job_id: str) -> None:
        """취소 지시 (C4 `cancel_jobs`). **시작된 실행도 중지를 부탁한다** — 유예를 기다려 준다.

        그래야 `cancelled`가 기록에 남는다. 이미 끝났으면 `cancel_refused`다 (현장이 옳다).
        """
        for run_id, found in self.workers.items():
            if found.job_id != job_id:
                continue
            if found.snapshot().done:
                self._remember_ack(
                    JobAck(job_id=job_id, result="cancel_refused", reason="already_started")
                )
                return
            # **중지를 부탁하기 전에 읽는다** — `Engine.cancel`이 기다림을 비운다 (ADR-0062 §5).
            with self._cancel_lock:
                self.pending_cancels.extend(found.delegation_jobs())
            found.stop(reason="Center에서 취소했습니다")
            log.info("작업 %s 취소를 실행 %s에 넘겼다", job_id, run_id)
            return
        # 모르는 작업이다 — 받은 적이 없으면 **취소된 것으로** 답한다 (두 번 돌지 않게).
        self._remember_ack(JobAck(job_id=job_id, result="cancelled"))

    def cancel_delegations(self) -> int:
        """맡긴 위임을 Center에서 거둔다 (ADR-0062 §5). 거둔 수를 돌려준다.

        **4xx는 다시 걸지 않는다** — 이미 시작됐거나(거절) 모르는 작업이다. 둘 다 답이고,
        다시 걸면 Center 로그만 쌓인다 (결재 올리기와 같은 결). **닿지 못한 것은 들고 있는다.**
        """
        with self._cancel_lock:
            todo, self.pending_cancels = self.pending_cancels, []
        if not todo:
            return 0
        left: list[str] = []
        done = 0
        for job_id in todo:
            try:
                self.client.cancel_delegation(job_id)
            except CenterProblem as e:
                if e.status is not None and 400 <= e.status < 500:
                    log.info("위임 %s를 거두지 못했다 (%s) — 다시 걸지 않는다", job_id, e)
                    continue
                log.info("위임 %s를 거두지 못했다 — 다음 주기에 (%s)", job_id, e)
                left.append(job_id)
                continue
            done += 1
            log.info("위임 %s를 거뒀다", job_id)
        with self._cancel_lock:
            self.pending_cancels = left + self.pending_cancels
        return done

    def withdraw_later(self, job_id: str) -> None:
        """엔진이 거둔 위임을 **다음 하트비트 뒤에** Center에서 거둔다 (ADR-0087 §4).

        일꾼 스레드에서 불린다 — 함께 도는 반복의 한 건이 실패했거나 중단 경계가 울려 그 결과를
        받을 쪽이 없어졌다. 실행 취소가 거두는 것과 **같은 줄**이다 (`cancel_delegations`).
        """
        with self._cancel_lock:
            if job_id not in self.pending_cancels:
                self.pending_cancels.append(job_id)

    # ── 결재 (C6 — 서버의 창구는 Center만이다) ──

    def post_approvals(self) -> None:
        """기다리는 결재를 Center 결재함에 올린다 (C6 `POST /approvals`).

        **두 번 올리지 않는다.** **4xx는 다시 보내지 않는다** — 한 번 거부된 것을 주기마다
        다시 올리면 Center 로그만 쌓이고 진짜 문제가 묻힌다 (ADR-0038과 같은 결).
        """
        for found in list(self.workers.values()):
            run = found.run
            if run is None:
                continue
            for pending in list(run.pendings.values()):
                if pending.request_id in self._posted:
                    continue
                body = approval_requests.create_request(run, pending).to_json_dict()
                try:
                    self.client.create_approval(body)
                except CenterProblem as e:
                    if e.status is not None and 400 <= e.status < 500:
                        self._posted.add(pending.request_id)  # 다시 보내지 않는다
                        log.error("결재 %s를 Center가 거부했다: %s", pending.request_id, e)
                    else:
                        log.info("결재 %s를 올리지 못했다 — 다음 주기에 (%s)", pending.request_id, e)
                    continue
                self._posted.add(pending.request_id)
                log.info("결재 %s를 Center 결재함에 올렸다", pending.request_id)

    def apply_approvals(self, found: list[ApprovalDispatch]) -> None:
        """답이 정해진 결재를 실행에 넣는다 (C6) — **기다리던 실행이 이어 간다**.

        **지금 기다리지 않는 답은 `not_waiting`으로 돌려보낸다** (C6 — Center가 다시 연다).
        회수·만료는 **답이 아니다** — 오류 경계로 간다 (ADR-0038).

        **빈자리가 없으면 넣지 않고 ack도 하지 않는다** (메시지·타이머와 같은 결) — 기다리던
        실행은 자리를 놓았으므로 이어 가면 **다시 쥔다**. 상한을 넘기면
        `capacity.running > max`가 되어 **하트비트가 스스로 막히고**(`validate_heartbeat`)
        실행기가 Center와 말을 못 한다. **거절로 적지 않는 것이 요점이다** — C6이 받아들이지
        못한 ack를 `open`으로 되돌리며 **답을 지우므로**(`_apply_acks`) 사람이 답한 결재가
        버려진다. ack하지 않으면 Center가 다음 주기에 **그대로 다시 내려 준다**(`delivered = 0`).
        """
        for one in found:
            worker = self._waiting_for(one.request_id)
            if worker is None:
                self.pending_approval_acks.append(
                    ApprovalAck(request_id=one.request_id, accepted=False, reason="not_waiting")
                )
                continue
            if self.free_slots() <= 0:
                log.info("결재 %s의 답을 넣을 자리가 없다 — 다음 주기에", one.request_id)
                continue
            if self._busy(worker, f"결재 {one.request_id}의 답"):
                continue
            try:
                if one.state == "answered":
                    worker.answer(
                        one.request_id,
                        dict(one.answer or {}),
                        answered_by=one.answered_by or "Center",
                        answered_via=one.answered_via,
                    )
                else:
                    # `expired`·`withdrawn` — 답이 아니다 (C6·ADR-0038).
                    worker.withdraw(one.request_id, reason=one.state)
            except EngineError as e:
                # 폼에 맞지 않는 답이거나 이미 지나간 자리다 — **받아들이지 못했다고 말한다**.
                self.pending_approval_acks.append(
                    ApprovalAck(request_id=one.request_id, accepted=False, reason=str(e)[:200])
                )
                continue
            self.pending_approval_acks.append(
                ApprovalAck(request_id=one.request_id, accepted=True)
            )
            self._posted.discard(one.request_id)

    # ── 메시지 (C12 §메시지 — 외부 시스템이 Center를 거쳐 온다) ──

    def apply_messages(self, found: list[MessageDispatch]) -> None:
        """내려온 메시지를 기다리는 실행에 넣는다 — **기다리던 실행이 이어 간다**.

        **받을 곳을 이쪽에서 다시 찾는다** (`message_matches`와 같은 규칙) — Center가 고른 뒤
        하트비트 한 주기가 지났으니 그 실행이 타이머로 지나갔을 수 있다. 그때는 `no_receiver`로
        돌려보낸다 (Center는 다시 싣지 않는다).

        **ack하지 않고 두는 자리가 있다** — 빈자리가 없으면 넣지 않고 ack도 하지 않는다. 그러면
        Center가 다음 주기에 다시 싣는다 (C12 — 작업과 같다). 거절로 적으면 멀쩡한 메시지가
        버려진다.

        **이미 다룬 메시지는 마지막 ack를 되돌려 보낸다** — ack가 올라가기 전에 같은 메시지가
        또 내려오므로, 들고 있지 않으면 한 메시지로 **두 번 깨운다**.
        """
        for one in found:
            seen = self.seen_messages.get(one.message_id)
            if seen is not None:
                self._remember_message_ack(seen)
                continue
            worker = self._waiting_message(one)
            if worker is None:
                self._remember_message_ack(
                    MessageAck(message_id=one.message_id, accepted=False, reason="no_receiver")
                )
                continue
            if self.free_slots() <= 0:
                # **ack를 보내지 않는다** — 자리가 비면 다음 주기에 넣는다 (C12).
                log.info("메시지 %s를 넣을 자리가 없다 — 다음 주기에", one.message_id)
                continue
            if self._busy(worker, f"메시지 {one.message_id}"):
                continue
            try:
                put = worker.deliver(
                    one.name,
                    correlation=one.correlation,
                    payload=one.payload,
                    # **담을 때 스냅샷과 함께 적힌다** (ADR-0058) — 그래야 ack가 올라가기 전에
                    # 실행기가 죽어도 되살린 실행에 같은 메시지가 두 번 들어가지 않는다.
                    message_id=one.message_id,
                )
            except EngineError as e:
                # 넣다 업무가 실패했다 — **받아들이지 못했다고 말한다** (실행은 실패로 닫힌다).
                self._remember_message_ack(
                    MessageAck(message_id=one.message_id, accepted=False, reason=str(e)[:200])
                )
                continue
            if not put:  # pragma: no cover - 바로 위에서 찾았다
                self._remember_message_ack(
                    MessageAck(message_id=one.message_id, accepted=False, reason="no_receiver")
                )
                continue
            self._remember_message_ack(
                MessageAck(message_id=one.message_id, accepted=True, run_id=worker.run_id)
            )
            log.info("메시지 %s를 실행 %s에 넣었다 (%s)", one.message_id, worker.run_id, one.name)

    @staticmethod
    def _busy(worker: Worker, what: str) -> bool:
        """**그 실행을 미는 스레드가 아직 돌고 있으면** 넣지 않는다 — ack도 하지 않고 다음 주기에.

        기다리는 줄(`waits_for_*`)은 `Run`이 기다리는 자리를 보지만, 되살리기(`_resumed_body`)나
        이어 가기 스레드는 `Run`을 걸어 둔 채 **다시 담을 때까지** 돈다. 그 틈에 넣으면 `_continue`가
        스레드를 하나 더 띄워 **같은 `Run`을 둘이 민다** — 메시지 하나로 견적이 둘 붙었다
        (`test_a_restarted_runner_still_takes_the_message`가 가끔 깨진 까닭). 빈자리 관문과 같은
        결이라 Center가 그대로 다시 내려 준다.
        """
        if not worker.alive:
            return False
        log.info("%s — 실행 %s가 아직 돌고 있다, 다음 주기에 넣는다", what, worker.run_id)
        return True

    def _remember_message_ack(self, ack: MessageAck) -> None:
        self.seen_messages.remember(ack.message_id, ack)
        self.pending_message_acks = [
            one for one in self.pending_message_acks if one.message_id != ack.message_id
        ]
        self.pending_message_acks.append(ack)

    def _waiting_message(self, found: MessageDispatch) -> Worker | None:
        """그 메시지를 기다리는 일꾼. 여럿이면 **먼저 시작한 것** (C12 — 오래 기다린 쪽부터)."""
        picked = [
            one
            for one in self.workers.values()
            if one.waits_for_message(found.name, correlation=found.correlation)
        ]
        if not picked:
            return None
        return sorted(picked, key=lambda one: (one.snapshot().started_at, one.run_id))[0]

    # ── PC 위임 (C12 §PC 위임 — 맡긴 PC 실행이 끝났다) ──

    def apply_delegations(self, found: list[DelegationResult]) -> None:
        """내려온 위임 결과를 기다리는 실행에 넣는다 (ADR-0062) — **그 실행이 이어 간다**.

        **맡기는 쪽은 엔진이다** (`RunEnv.delegate` → `delegate.CenterDelegator`) — 여기는
        **돌아오는 길**뿐이다. `finished`가 아닌 것도 그대로 넘긴다: 엔진이 업무 실패로 올려
        오류 경계가 받는다 (가르는 자리를 둘로 두지 않는다).

        **ack하지 않고 두는 자리가 있다** — 빈자리가 없으면 넣지 않는다 (메시지와 같은 결).
        위임으로 멈춘 실행은 자리를 놓았으므로 이어 가면 **다시 쥔다**: 상한을 넘기면
        `capacity.running > max`가 되어 **하트비트가 스스로 막는다**(`validate_heartbeat`).
        그러면 실행기가 Center와 말을 못 한다 — 다음 주기에 넣는 편이 싸다.

        **지나간 자리는 받았다고 말한다** — 넣을 실행이 없으면 다시 내려와도 같으므로, ack해
        Center가 그 업무 값을 지우게 한다 (들고 있을 까닭이 없다).
        """
        for one in found:
            seen = self.seen_delegations.get(one.job_id)
            if seen is not None:
                self._remember_delegation_ack(seen)
                continue
            worker = self._waiting_delegation(one.job_id)
            if worker is None:
                log.info("위임 %s의 결과를 넣을 실행이 없다 — 받은 것으로 둔다", one.job_id)
                self._remember_delegation_ack(DelegationAck(job_id=one.job_id, accepted=True))
                continue
            if self.free_slots() <= 0:
                log.info("위임 %s의 결과를 넣을 자리가 없다 — 다음 주기에", one.job_id)
                continue
            if self._busy(worker, f"위임 {one.job_id}의 결과"):
                continue
            try:
                worker.delegation_done(
                    one.job_id, state=one.state, outputs=one.outputs, reason=one.reason
                )
            except EngineError as e:  # pragma: no cover - 바로 위에서 기다림을 찾았다
                # 기다림은 이미 걷혔다 — **받은 것으로 둔다** (다시 내려와도 같다).
                log.error("위임 %s의 결과를 넣다 실패했다: %s", one.job_id, e)
                self._remember_delegation_ack(DelegationAck(job_id=one.job_id, accepted=True))
                continue
            self._remember_delegation_ack(DelegationAck(job_id=one.job_id, accepted=True))
            log.info(
                "위임 %s의 결과를 실행 %s에 넣었다 (%s)", one.job_id, worker.run_id, one.state
            )

    def _remember_delegation_ack(self, ack: DelegationAck) -> None:
        self.seen_delegations.remember(ack.job_id, ack)
        self.pending_delegation_acks = [
            one for one in self.pending_delegation_acks if one.job_id != ack.job_id
        ]
        self.pending_delegation_acks.append(ack)

    def _waiting_delegation(self, job_id: str) -> Worker | None:
        """그 위임을 기다리는 일꾼. 없으면 `None` (지나갔거나 끝난 실행이다).

        **`run_id`로 찾지 않는다** — 작업 id가 그 자리의 열쇠이고(멱등 키가 그것으로 지어졌다)
        그 실행이 정말 **지금 그것을** 기다리는지는 작업 id로만 알 수 있다.
        """
        for found in self.workers.values():
            if found.waits_for_delegation(job_id):
                return found
        return None

    def _waiting_for(self, request_id: str) -> Worker | None:
        """그 결재를 기다리는 일꾼. 없으면 `None` (지나갔거나 남의 것이다)."""
        for found in self.workers.values():
            run = found.run
            if run is not None and request_id in run.pendings:
                return found
        return None

    # ── 실행 기록 보내기 (C3 §전송) ──

    def ship_events(self) -> None:
        """하트비트 **뒤에** 묶어 보낸다 — 실행 중에 보내지 않는다 (느린 Center가 붙잡는다).

        멱등이라 실패하면 같은 배치를 그대로 다시 보낸다. **401·403은 멈춘다** (키 문제다).
        """
        queue = Queue(data_dir=self.settings.data_path)
        try:
            # **Center와 말하는 클라이언트를 함께 쓴다** — 주소·키가 한 자리에서 오고, 시험은
            # ASGI를 꽂은 그 클라이언트로 진짜 Center에 닿는다.
            queue.ship(
                HttpUploader(
                    base_url=self.settings.center_url,
                    api_key=self.client.api_key,
                    client=self.client.client,
                )
            )
        except ShipError as e:
            if e.fatal:
                self.blocked_by = f"실행 기록을 보낼 수 없습니다: {e}"
                log.error("%s", self.blocked_by)
                return
            log.info("실행 기록을 보내지 못했다 — 다음 주기에 다시 보낸다 (%s)", e)

    def unsent_events(self) -> int:
        """C12 `unsent_events` — **파일을 읽어 센다** (원본이 파일이다)."""
        return Queue(data_dir=self.settings.data_path).unsent_count()

    def _heartbeat_request(self) -> ServerRunnerHeartbeatRequest:
        """지금 상태 (C12 `HeartbeatRequest`).

        **`restored[]`는 첫 하트비트에만** 올린다 (C12) — 올린 뒤에는 비운다. 올리지 못했으면
        그대로 들고 있다가 다음에 올린다 (ADR-0007).

        **`running[]`·`waiting[]`을 정말 싣는다.** 비워 올리면 셋이 함께 깨진다 — CON-12가
        아무것도 못 보이고, `capacity.running`이 늘 0이라 Center가 **상한을 넘겨 보내고**,
        맞추기 규칙이 멀쩡한 실행을 두 주기 뒤 `runner_lost`로 닫는다. 조각 4-①에서 이 자리가
        빈 채로 나갔고(#109) 시험이 `running[]`의 **내용**을 보지 않아 드러나지 않았다.
        """
        shots = [found.snapshot() for found in self.workers.values()]
        alive = [one for one in shots if not one.done]
        running = [one.running_row() for one in alive if one.holds_a_slot]
        waiting = [one.waiting for one in alive if one.waiting is not None]
        return ServerRunnerHeartbeatRequest(
            schema=1,
            status=STATUS_PAUSED if self.paused else STATUS_RUNNING,
            # **`running`은 기다리는 실행을 뺀 수**다 (C12) — `running[]` 길이와 같아야 한다
            # (어긋나면 Center가 422로 거부한다, `validate_heartbeat`).
            capacity=Capacity(max=self.settings.max_concurrency, running=len(running)),
            running=running,
            waiting=waiting,
            versions=self.versions(),
            # **설치된 Bot별 준비 상태** (C12) — 캐시하고 설치·키가 바뀌면 비운다.
            readiness=self.readiness(),
            deployment_results=list(self.pending_results),
            job_acks=list(self.pending_acks),
            approval_acks=list(self.pending_approval_acks),
            message_acks=list(self.pending_message_acks),
            delegation_acks=list(self.pending_delegation_acks),
            restored=list(self.restored),
            unsent_events=self.unsent_events(),
            service_key_acks=list(self.received_keys().pending),
        )

    def received_keys(self) -> ReceivedKeys:
        """Center가 내려 준 서비스 앱 키의 자리와 보낼 ack (ADR-0094 — Bot UI와 같은 코드)."""
        if self._received is None:
            self._received = ReceivedKeys.at(self.settings.data_path)
        return self._received

    def _take_service_keys(self, request: Any, answer: Any) -> None:
        """하트비트 답의 서비스 앱 키를 받아 둔다. 바뀌었으면 사전 점검을 다시 잰다."""
        held = self.received_keys()
        held.sent(request.service_key_acks)
        if self.credentials.center_key_from_env():
            return  # 공개키를 보내지 않았다 — Center가 싣지 않는다 (환경변수 키를 쓴다)
        changed = held.take(
            list(getattr(answer, "service_keys", []) or []),
            list(getattr(answer, "drop_service_keys", []) or []),
            secret=self.credentials.enroll_secret(),
            put=self.credentials.set,
            delete=self.credentials.delete,
        )
        if changed:
            self._readiness.clear()

    def _acks_delivered(self) -> None:
        """실어 올린 ack가 Center에 닿았다 — 멱등 기억이 **그때부터** 잊을 준비를 한다.

        **멱등 기억을 늘리면 여기 한 줄을 더한다** (ADR-0056) — 부르는 자리를 갈라 두면
        한쪽만 고치는 일이 생긴다(작업과 메시지는 같은 까닭으로 있다).

        **한 번 부르는 것이 한 주기다** — 그래서 이 함수는 하트비트가 성공했을 때만 불린다.
        """
        self.seen_jobs.delivered(one.job_id for one in self.pending_acks)
        self.seen_messages.delivered(one.message_id for one in self.pending_message_acks)
        self.seen_delegations.delivered(one.job_id for one in self.pending_delegation_acks)

    def _apply(self, answer: ServerRunnerHeartbeatResponse) -> None:
        """응답을 반영한다 — 배포는 설치하고 작업은 돌린다.

        **순서가 중요하다.** 「일시 중지」를 **작업을 받기 전에** 반영한다 — 거꾸로 두면 다시
        시작한 바로 그 주기에 들고 있던 옛 값으로 작업을 거절하고, 그 거절이 `seen_jobs`에
        남아 **그 작업은 영원히 돌지 않는다** (C4 멱등 — 이미 본 작업은 마지막 ack를 되돌려
        보낸다). 시험이 그것을 잡았다.

        **여기가 「ack가 닿았다」를 아는 유일한 자리다** (ADR-0056) — 이 함수는 하트비트가
        성공해 응답이 돌아왔을 때만 불리고, Center는 **그 요청에서** ack를 반영한다
        (`center/api/jobs.py` `_apply_acks`). 그래서 비우기 **전에** 멱등 기억에게 알린다.
        """
        self._acks_delivered()  # **비우기 전에** — 무엇이 실려 올라갔는지는 여기서만 안다
        self.restored.clear()  # 올렸다
        self.pending_results.clear()  # 올렸다
        self.pending_acks.clear()  # 올렸다
        self.pending_approval_acks.clear()  # 올렸다
        self.pending_message_acks.clear()  # 올렸다
        self.pending_delegation_acks.clear()  # 올렸다
        self.next_in_s = answer.next_heartbeat_s
        self.last_response = answer
        if answer.paused != self.paused:
            log.info("Center가 %s라고 한다", "일시 중지" if answer.paused else "다시 시작")
        self.paused = answer.paused
        if answer.admin_keys is not None:
            # **생략 = 그대로**다 (C4·C12) — `None`이면 들고 있던 것을 지우지 않는다.
            self.admin_keys = list(answer.admin_keys)
        self.pending_results.extend(self.install_deployments(answer.deployments))
        # **끝난 것을 먼저 거둔다** — 그래야 자리가 비고 이번에 온 작업이 들어간다.
        self.collect()
        self.take_jobs(answer.jobs)
        for job_id in answer.cancel_jobs:
            self.cancel_job(job_id)
        self.apply_approvals(list(answer.approvals))
        self.apply_messages(list(answer.messages))
        # **작업보다 뒤다** — 둘 다 자리를 쓰는데, 자리가 없을 때 작업은 `rejected`로 닫히고
        # (거절은 다시 싣지 않는다, C4) 위임 결과는 **ack하지 않으면 다시 내려온다**. 거꾸로
        # 두면 멀쩡한 작업이 큐에서 사라진다.
        self.apply_delegations(list(answer.delegations))

    # ── 연결 (로그는 바뀔 때만) ──

    def _went_offline(self, problem: CenterProblem) -> None:
        if self.online:
            log.warning("Center에 닿지 못한다 — 계속 다시 걸어 본다 (%s)", problem)
        self.online = False

    def _came_online(self) -> None:
        if not self.online:
            log.info("Center에 다시 닿았다")
        self.online = True

    # ── 사람이 보는 한 줄 ──

    def status_line(self) -> str:
        """로그·`--once`가 찍는 한 줄. **키 값은 넣지 않는다.**"""
        if self.blocked_by:
            return f"막혔다: {self.blocked_by}"
        if not self.registered:
            return "등록 전" if self.online else "등록 전 (Center에 닿지 못한다)"
        where = "일시 중지" if self.paused else "동작"
        link = "" if self.online else " (Center에 닿지 못한다)"
        return f"{self.server_runner_id} — {where}, 상한 {self.settings.max_concurrency}{link}"


def build(
    settings: Settings, api_key: str, *, client: Any | None = None, store: Store | None = None
) -> Agent:
    """설정과 키로 실행기 하나를 만든다 (시험은 `client`에 ASGI를 꽂는다).

    `store`를 주지 않으면 **설정이 가리키는 파일**에 담는다 (ADR-0054 — SQLite 한 파일).
    담지 않게 하려면 부르는 쪽이 `Agent`를 직접 만든다 (`--once`가 그렇지 않다 — 담아 둔 것을
    되살리는 것은 `--once`에서도 해야 **다시 뜬 뒤 상태**를 볼 수 있다).
    """
    return Agent(
        settings=settings,
        client=CenterClient(
            base_url=settings.center_url, api_key=api_key, client=client, timeout_s=5.0
        ),
        store=store if store is not None else Store(path=settings.state_db),
    )


__all__ = [
    "CORE_VERSION",
    "HOST_KIND",
    "KEY_FIX_HINT",
    "RUNNER_VERSION",
    "STATUS_ERROR",
    "STATUS_PAUSED",
    "STATUS_RUNNING",
    "Agent",
    "build",
]
