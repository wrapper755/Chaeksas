"""배포를 받아 BPM 프로세스를 설치한다 (C2 V1~V7, C4·C5·C12).

하트비트로 내려온 **배포 봉투**를 보고, 이 기계 것이면 패키지를 내려받아 설치한다.

**PC 실행기와 서버 실행기가 같은 코드를 쓴다** — 다른 것은 `host_kind`·`host_id`뿐이다 (C2 V6의
대상 검사에 들어간다). 규칙이 두 군데 있으면 「PC는 거부하는데 서버는 설치한다」가 된다.

지키는 것 다섯.

- **서명이 유일한 관문**이다. 모르는 키·철회된 키·손댄 봉투·해시가 다른 패키지·승인 서명
  없는 패키지는 **설치하지 않는다** (V1~V7).
- **거부도 보고한다** — 사유 코드와 함께 (C4 `deployment_results`, CON-03 「⛔ 거부」).
- **예약 배포는 때가 될 때까지 두고 본다** (V5b `not_before`) — 거부가 아니다.
- **남의 배포는 받지 않는다** (V6) — `target`이 나여야 한다.
- 설치는 **한 번만** 한다. 이미 그 해시로 설치돼 있으면 조용히 지나간다.

그리고 **목록과 설치를 맞춘다** (C2 §검증 규칙·C4 `deployments`, ADR-0113) — Center가 **답한** 목록에
덮는 봉투가 없는 「Center 배포」 설치는 폴더의 `DEPLOYMENT` 표식에 적어 「실행 불가」로 돌린다
(`reconcile`). 파일은 지우지 않는다. 기한은 그 표식으로 현장이 혼자 본다 (`deployment_finding`).
"""

from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chaeksas.contracts.bot_ui import DeploymentResult
from chaeksas.contracts.hashing import content_hash_zip
from chaeksas.contracts.signing import (
    AdminKey,
    Envelope,
    verify,
    verify_package,
    verify_target,
    verify_time,
)
from chaeksas.core.packages import (
    CENTER,
    SOURCE_LABELS,
    InstalledBot,
    InstallError,
    install,
    installed,
    write_source,
)
from chaeksas.extension_api import SEVERITY_BLOCK, Finding

log = logging.getLogger(__name__)

#: 패키지 안의 승인 봉투 (C2).
SIGNATURE_NAME = "SIGNATURE"

#: C4 `deployment_results.result` (열린 문자열).
APPLIED = "applied"
REJECTED = "rejected"
PENDING = "pending"

#: 아직 때가 아니다 — **거부가 아니라 기다림**이다 (C2 V5b).
NOT_YET = "not_yet"

#: 「Center 배포」 설치를 **지금 덮는 배포**를 적는 표식 (ADR-0113). 「출처」(`INSTALL_SOURCE`)와 같은 자리다.
STANDING_NAME = "DEPLOYMENT"

#: 사전 점검 코드 (C4 `Readiness.blocked`, BUI-04 「준비」) — 덮는 배포가 없다 / 덮는 배포의 기한이 지났다.
DEPLOYMENT_WITHDRAWN = "deployment_withdrawn"
DEPLOYMENT_EXPIRED = "deployment_expired"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def read_signature(package: Path) -> Envelope | None:
    """패키지 안 `SIGNATURE` (C2). 없거나 읽지 못하면 `None` — **없는 것은 없는 것이다**."""
    try:
        with zipfile.ZipFile(package) as archive:
            raw = archive.read(SIGNATURE_NAME)
    except (KeyError, OSError, zipfile.BadZipFile):
        return None
    try:
        return Envelope.model_validate_json(raw)
    except ValueError:
        return None


def _when(text: str) -> datetime:
    found = datetime.fromisoformat(text)
    return found if found.tzinfo else found.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Standing:
    """`DEPLOYMENT` 표식 — 그 설치를 덮는 배포와 그 기한, 빠졌으면 언제 빠졌나 (ADR-0113)."""

    deployment_ids: tuple[str, ...] = ()
    #: 덮는 배포의 기한 중 **가장 늦은 것**. 하나라도 기한이 없으면 `None`(기한 없음)이다.
    expires_at: str | None = None
    #: Center가 답한 목록에서 빠진 때. 빠지지 않았으면 `None`.
    withdrawn_at: str | None = None

    def problem(self, *, now: str) -> str | None:
        """막는 까닭 — `DEPLOYMENT_WITHDRAWN`·`DEPLOYMENT_EXPIRED`, 아니면 `None`."""
        if self.withdrawn_at:
            return DEPLOYMENT_WITHDRAWN
        if self.expires_at and _when(self.expires_at) <= _when(now):
            return DEPLOYMENT_EXPIRED
        return None


def read_standing(folder: Path) -> Standing | None:
    """표식이 없거나 읽지 못하면 `None` — **모르는 것으로 막지 않는다** (표식 전에 설치된 폴더일 수 있다)."""
    try:
        raw = json.loads((folder / STANDING_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return Standing(
        deployment_ids=tuple(str(one) for one in raw.get("deployment_ids") or ()),
        expires_at=str(raw["expires_at"]) if raw.get("expires_at") else None,
        withdrawn_at=str(raw["withdrawn_at"]) if raw.get("withdrawn_at") else None,
    )


def write_standing(folder: Path, standing: Standing) -> None:
    """쓰지 못하면 기록만 남긴다 — 다음 하트비트가 다시 쓴다 (`write_source`와 같은 결)."""
    body = {
        "deployment_ids": list(standing.deployment_ids),
        "expires_at": standing.expires_at,
        "withdrawn_at": standing.withdrawn_at,
    }
    try:
        (folder / STANDING_NAME).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8", newline="\n")
    except OSError as e:
        log.warning("배포 표식을 남기지 못했다 (%s): %s", folder, e)


def _from_center(bot: InstalledBot) -> bool:
    """**「Center 배포」로 설치된 것만** 목록이 정한다 — 수동 설치·출처 모름은 다루지 않는다 (ADR-0113 §3)."""
    return bot.source == SOURCE_LABELS[CENTER]


def deployment_finding(bot: InstalledBot, *, now: str | None = None) -> Finding | None:
    """그 설치를 **지금** 띄워도 되나 — 배포가 정하는 사전 점검 하나 (ADR-0113 §4).

    **시각이 정하므로 캐시하지 않는다** — 부르는 쪽이 다른 사전 점검과 따로 붙인다.
    """
    if not _from_center(bot):
        return None
    standing = read_standing(bot.folder)
    if standing is None:
        return None
    code = standing.problem(now=now or now_iso())
    if code == DEPLOYMENT_WITHDRAWN:
        return Finding(
            id=DEPLOYMENT_WITHDRAWN,
            severity=SEVERITY_BLOCK,
            message=f"Center의 배포 목록에 {bot.id} {bot.version}이 없습니다 — 배포나 승인이 철회되었습니다",
            fix_hint="Center 운영자에게 다시 배포해 달라고 요청하세요",
        )
    if code == DEPLOYMENT_EXPIRED:
        return Finding(
            id=DEPLOYMENT_EXPIRED,
            severity=SEVERITY_BLOCK,
            message=f"{bot.id} {bot.version} 배포의 유효 기간이 지났습니다 ({standing.expires_at})",
            fix_hint="Center 운영자에게 새로 배포해 달라고 요청하세요",
        )
    return None


@dataclass
class Outcome:
    """배포 하나를 어떻게 했나."""

    deployment_id: str
    bpm_process_id: str
    version: str
    result: str
    reason: str | None = None

    def to_result(self) -> DeploymentResult:
        return DeploymentResult(
            deployment_id=self.deployment_id,
            bpm_process_id=self.bpm_process_id,
            version=self.version,
            result=self.result,
            at=now_iso(),
            reason=self.reason,
        )


@dataclass
class Deployer:
    """배포를 적용하는 쪽. **설치만 한다** — 돌리는 것은 부르는 쪽이 정한다.

    PC는 대기열이(ADR-0014), 서버는 Center가 빈자리만큼 보낸 작업이 정한다 (C12).
    """

    data_dir: Path
    #: 이 기계가 누구인가 — C2 V6이 봉투의 `target`과 맞춰 본다.
    host_id: str
    #: `bot_ui` 또는 `server_runner` (C2 §배포 대상 규칙). 서버는 `"*"` 대상도 받는다.
    host_kind: str = "bot_ui"
    keys: list[AdminKey] = field(default_factory=list)
    #: 서명 없는 패키지를 설치하지 않는다 (BUI-03 「서명된 패키지만」, 기본 켬).
    signed_only: bool = True
    #: 패키지를 내려받는 쪽 — `(id, version) -> 파일 경로`. 없으면 내려받지 못한다.
    fetch: Any = None
    clock: Any = now_iso

    def apply(self, envelopes: list[dict[str, Any]]) -> list[DeploymentResult]:
        """내려온 배포들을 적용한다 → 보고할 결정들 (**기다림은 보고하지 않는다**)."""
        out = []
        for raw in envelopes:
            found = self._one(raw)
            if found is None or found.result == PENDING:
                continue  # 아직 때가 아니다 — 다음 하트비트에 다시 본다
            out.append(found.to_result())
        return out

    def _one(self, raw: dict[str, Any]) -> Outcome | None:
        try:
            envelope = Envelope.model_validate(raw)
        except ValueError as e:
            log.warning("배포 봉투를 읽지 못했다: %s", e)
            return None  # 보고할 `deployment_id`조차 모른다
        claim = envelope.payload
        made = Outcome(
            deployment_id=str(claim.get("deployment_id") or ""),
            bpm_process_id=str(claim.get("bpm_process_id") or ""),
            version=str(claim.get("version") or ""),
            result=REJECTED,
        )

        # V1~V4 — 서명과 종류.
        problems = verify(envelope, keys=self.keys, expect_kind="deployment")
        if problems:
            return self._refused(made, problems[0])
        # V6 — 남의 배포는 받지 않는다.
        problems = verify_target(envelope, runner_kind=self.host_kind, runner_id=self.host_id)
        if problems:
            return self._refused(made, problems[0])
        # V5 — 만료는 거부, `not_before`는 **기다림**이다.
        problems = verify_time(envelope, now=self.clock(), check_not_before=True)
        if problems:
            first = problems[0]
            if first.code == NOT_YET:
                made.result = PENDING
                return made
            return self._refused(made, first)

        if self._already(made):
            return None  # 같은 해시로 이미 설치돼 있다 — 조용히 지나간다
        return self._install(made, envelope)

    def reconcile(self, envelopes: list[dict[str, Any]]) -> list[InstalledBot]:
        """**Center가 답한** 목록과 설치를 맞춘다 → 이번에 새로 빠진 설치들 (C2 §검증 규칙, ADR-0113).

        부르는 쪽은 하트비트가 **답했을 때만** 부른다 — 닿지 못한 주기에는 아무것도 바꾸지 않는다
        (ADR-0007). 빈 목록도 목록이다(C4 — 활성 배포 **전체**다). 덮는 봉투는 **지금 설치를 허락할
        것**(V1~V6)뿐이라 버린 서명 키(V2)·지난 기한도 여기서 빠진다.

        **믿는 키가 없으면 맞추지 않는다** — 서명을 볼 수 없는데 맞추면 모든 설치가 빠진다.
        """
        if not self.keys:
            return []
        covering: dict[tuple[str, str], list[tuple[str, str | None]]] = {}
        for raw in envelopes:
            try:
                envelope = Envelope.model_validate(raw)
            except ValueError:
                continue
            if (
                verify(envelope, keys=self.keys, expect_kind="deployment")
                or verify_target(envelope, runner_kind=self.host_kind, runner_id=self.host_id)
                or verify_time(envelope, now=self.clock(), check_not_before=True)
            ):
                continue
            claim = envelope.payload
            ends = claim.get("expires_at")
            covering.setdefault((str(claim.get("bpm_process_id") or ""), str(claim.get("version") or "")), []).append(
                (str(claim.get("deployment_id") or ""), str(ends) if ends else None)
            )

        withdrawn: list[InstalledBot] = []
        for bot in installed(self.data_dir):
            if not _from_center(bot):
                continue
            old = read_standing(bot.folder)
            found = covering.get((bot.id, bot.version))
            if found:
                ends = [end for _, end in found]
                new = Standing(
                    deployment_ids=tuple(sorted({one for one, _ in found})),
                    expires_at=None if any(end is None for end in ends) else max(ends, key=lambda e: _when(e or "")),
                )
            elif old is not None and old.withdrawn_at:
                continue  # 이미 빠졌다고 적었다 — 빠진 때를 다시 쓰지 않는다
            else:
                new = Standing(
                    deployment_ids=old.deployment_ids if old else (),
                    expires_at=old.expires_at if old else None,
                    withdrawn_at=self.clock(),
                )
                withdrawn.append(bot)
                log.warning("배포 목록에서 %s %s이 빠졌다 — 실행 불가로 돌린다", bot.id, bot.version)
            if new != old:
                write_standing(bot.folder, new)
        return withdrawn

    def _already(self, made: Outcome) -> bool:
        wanted = str(made.version)
        for one in installed(self.data_dir):
            if one.id == made.bpm_process_id and one.version == wanted:
                return True
        return False

    def _install(self, made: Outcome, envelope: Envelope) -> Outcome:
        if self.fetch is None:
            made.reason = "패키지를 내려받을 길이 없습니다 (Center 설정을 보세요)"
            return made
        try:
            package = self.fetch(made.bpm_process_id, made.version)
        except Exception as e:  # noqa: BLE001 — 닿지 못할 수 있다
            # **닿지 못한 것은 거부가 아니다** — 다음 하트비트에 다시 받는다.
            log.info("패키지를 내려받지 못했다 (%s): %s", made.bpm_process_id, e)
            made.result = PENDING
            return made

        signature = read_signature(package)
        problems = verify_package(
            envelope, package_hash=content_hash_zip(package), package_signature=signature, keys=self.keys
        )
        if problems and (self.signed_only or problems[0].code != "unsigned_package"):
            # **서명 없는 패키지는 거부한다** (BUI-03 「서명된 패키지만」).
            return self._refused(made, problems[0])

        try:
            bot = install(self.data_dir, package)
        except InstallError as e:
            made.reason = str(e)
            return made
        # **배포로 온 것은 배포가 적는다** (BUI-04 「출처」) — 푸는 쪽은 알 수 없다.
        write_source(bot.folder, CENTER)
        made.result = APPLIED
        made.reason = None
        return made

    def _refused(self, made: Outcome, problem: Any) -> Outcome:
        """**거부도 보고한다** — 왜 거부했는지가 콘솔에 보여야 한다 (CON-03)."""
        made.result = REJECTED
        made.reason = problem.code or "bad_signature"
        log.warning("배포 %s 거부: %s (%s)", made.deployment_id, problem.message, problem.code)
        return made


__all__ = [
    "APPLIED",
    "DEPLOYMENT_EXPIRED",
    "DEPLOYMENT_WITHDRAWN",
    "NOT_YET",
    "PENDING",
    "REJECTED",
    "SIGNATURE_NAME",
    "STANDING_NAME",
    "Deployer",
    "Outcome",
    "Standing",
    "deployment_finding",
    "read_signature",
    "read_standing",
    "write_standing",
]
