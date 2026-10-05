"""배포를 받아 Bot을 설치한다 (C2 V1~V7, C4·C5).

하트비트로 내려온 **배포 봉투**를 보고, 이 PC 것이면 패키지를 내려받아 설치한다.

지키는 것 다섯.

- **서명이 유일한 관문**이다. 모르는 키·철회된 키·손댄 봉투·해시가 다른 패키지·승인 서명
  없는 패키지는 **설치하지 않는다** (V1~V7).
- **거부도 보고한다** — 사유 코드와 함께 (C4 `deployment_results`, CON-03 「⛔ 거부」).
- **예약 배포는 때가 될 때까지 두고 본다** (V5b `not_before`) — 거부가 아니다.
- **남의 배포는 받지 않는다** (V6) — `target`이 나여야 한다.
- 설치는 **한 번만** 한다. 이미 그 해시로 설치돼 있으면 조용히 지나간다.
"""

from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chaeksas.bot_ui.bots import InstallError, install, installed
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

log = logging.getLogger(__name__)

#: 패키지 안의 승인 봉투 (C2).
SIGNATURE_NAME = "SIGNATURE"

#: C4 `deployment_results.result` (열린 문자열).
APPLIED = "applied"
REJECTED = "rejected"
PENDING = "pending"

#: 아직 때가 아니다 — **거부가 아니라 기다림**이다 (C2 V5b).
NOT_YET = "not_yet"


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
    """배포를 적용하는 쪽. **설치만 한다** — 실행은 대기열이 정한다 (ADR-0014)."""

    data_dir: Path
    bot_ui_id: str
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
        problems = verify_target(envelope, runner_kind="bot_ui", runner_id=self.bot_ui_id)
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
            install(self.data_dir, package)
        except InstallError as e:
            made.reason = str(e)
            return made
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
    "NOT_YET",
    "PENDING",
    "REJECTED",
    "SIGNATURE_NAME",
    "Deployer",
    "Outcome",
    "read_signature",
]
