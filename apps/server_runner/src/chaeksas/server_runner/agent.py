"""실행기의 심장 — 등록하고 주기마다 하트비트를 보낸다 (C12).

**배포를 설치하고 준비 상태를 보고한다** (M7 조각 3). 설치는 Bot UI와 **같은 코드**
(`core.deploy`·`core.packages`)이고 다른 것은 `host_kind`뿐이다 — 서버는 `"*"` 대상 배포도
받는다 (ADR-0046).

**아직 Bot을 돌리지 않는다** — 내려온 작업은 **받아서 기록만 한다**. 그래서 `capacity.running`은
늘 0이고 `running[]`·`waiting[]`은 비어 있다. **없는 것을 있는 척하지 않는다**: 작업을 받고도
`started` ack를 보내면 Center는 도는 줄 알고 기다린다.

한 걸음은 `tick()` 하나다 — **스레드를 만들지 않는다** (엔진과 같은 태도다). 부르는 쪽(`main`)이
돌리고, 시험은 `tick()`을 직접 민다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chaeksas.contracts.bot_ui import DeploymentResult, Readiness
from chaeksas.contracts.server_runner import (
    Capacity,
    RunnerVersions,
    ServerRunnerHeartbeatRequest,
    ServerRunnerHeartbeatResponse,
    ServerRunnerRegisterRequest,
    validate_heartbeat,
)
from chaeksas.contracts.signing import AdminKey
from chaeksas.core import machine
from chaeksas.core.deploy import Deployer
from chaeksas.core.packages import InstalledBot, installed
from chaeksas.core.preflight import check as run_preflight
from chaeksas.server_runner.center_client import (
    CenterClient,
    CenterProblem,
    KeyRejected,
    MachineMismatch,
    NotRegistered,
    Unreachable,
)
from chaeksas.server_runner.credentials import Credentials
from chaeksas.server_runner.settings import Settings

log = logging.getLogger(__name__)

#: 보고하는 버전 (C12 `versions`). `core`의 판은 함께 올린다.
CORE_VERSION = "0.1.0"
RUNNER_VERSION = "0.1.0"

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

    #: 사전 점검 결과 캐시 — **설치가 바뀌면 비운다** (안 비우면 키를 넣어도 영원히 막힌다).
    _readiness: dict[tuple[str, str], Readiness] = field(default_factory=dict)

    @property
    def registered(self) -> bool:
        return bool(self.server_runner_id)

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
        """
        self.tick()
        if self.registered and self.last_response is None and not self.blocked_by:
            self.tick()
        return self.last_response is not None

    def _register(self) -> bool:
        request = ServerRunnerRegisterRequest(
            schema=1,
            machine_id=self.machine_id(),
            name=self.name(),
            os=machine.os_label(),
            versions=self.versions(),
            max_concurrency=self.settings.max_concurrency,
            # 확장은 아직 싣지 않는다 (다음 조각) — **빈 목록이 거짓이 아니다**: 지금 이
            # 실행기는 정말 확장을 하나도 들고 있지 않다.
            extensions=[],
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
        log.info("등록했다: %s (주기 %d초)", self.server_runner_id, self.next_in_s)
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
        확장 점검은 아직 없다 — 실행기가 확장을 싣는 것은 다음 조각이다 (`host=None`이면
        플랫폼 점검만 돈다).
        """
        out = []
        for bot in self.installed_bots():
            key = (bot.id, bot.version)
            found = self._readiness.get(key)
            if found is None:
                checked = run_preflight(
                    bot.manifest,
                    key_value=self.credentials.service_app_key,
                    fix_hint=KEY_FIX_HINT,
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

    def _heartbeat_request(self) -> ServerRunnerHeartbeatRequest:
        """지금 상태 (C12 `HeartbeatRequest`).

        **`restored[]`는 첫 하트비트에만** 올린다 (C12) — 올린 뒤에는 비운다. 올리지 못했으면
        그대로 들고 있다가 다음에 올린다 (ADR-0007).
        """
        return ServerRunnerHeartbeatRequest(
            schema=1,
            status=STATUS_PAUSED if self.paused else STATUS_RUNNING,
            # 아직 돌리지 않으므로 **자리를 쥔 것이 없다** (M7 조각 2).
            capacity=Capacity(max=self.settings.max_concurrency, running=0),
            running=[],
            waiting=[],
            versions=self.versions(),
            # **설치된 Bot별 준비 상태** (C12) — 캐시하고 설치·키가 바뀌면 비운다.
            readiness=self.readiness(),
            deployment_results=list(self.pending_results),
            restored=list(self.restored),
        )

    def _apply(self, answer: ServerRunnerHeartbeatResponse) -> None:
        """응답을 반영한다 — **배포는 설치하고**, 작업은 받아 두고 적는다 (돌리지 않는다)."""
        self.restored.clear()  # 올렸다
        self.pending_results.clear()  # 올렸다
        self.next_in_s = answer.next_heartbeat_s
        if answer.admin_keys is not None:
            # **생략 = 그대로**다 (C4·C12) — `None`이면 들고 있던 것을 지우지 않는다.
            self.admin_keys = list(answer.admin_keys)
        self.pending_results.extend(self.install_deployments(answer.deployments))
        if answer.paused != self.paused:
            log.info("Center가 %s라고 한다", "일시 중지" if answer.paused else "다시 시작")
        self.paused = answer.paused
        self.last_response = answer
        if answer.jobs:
            # **받고도 돌리지 않는다**는 것을 분명히 남긴다 (조용히 버리면 「왜 안 도나」가 된다).
            log.info("작업 %d건을 받았으나 아직 돌리지 않는다 — M7 다음 조각이다", len(answer.jobs))

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


def build(settings: Settings, api_key: str, *, client: Any | None = None) -> Agent:
    """설정과 키로 실행기 하나를 만든다 (시험은 `client`에 ASGI를 꽂는다)."""
    return Agent(
        settings=settings,
        client=CenterClient(
            base_url=settings.center_url, api_key=api_key, client=client, timeout_s=5.0
        ),
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
