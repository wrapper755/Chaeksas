"""STU-10 「Center」 — Studio도 요청 코드를 관리자가 승인해 들인다 (C5 §Studio 등록 요청과 승인, ADR-0093).

Bot UI와 **같은 길**이다 (C4 §등록 요청과 승인): 키 쌍을 만들어 비밀 반쪽을 OS 비밀 저장소에 두고,
등록 요청을 보내 요청 코드를 띄운다. 관리자가 콘솔 「Center API 키」(CON-11)의 「승인 대기」에서 같은
코드를 승인하면 봉한 Studio 키를 받아 열어 비밀 저장소에 둔다. **아이디·비밀번호는 없다.**

다른 것은 둘이다: Studio에는 하트비트가 없어 **키를 회전하지 않고**(1년, 만료되면 다시 요청),
`register`가 없어 **그 키로 처음 부르는 것**이 받았다는 표시다(Center가 봉함을 지운다).

화면을 모르는 자리라 Qt 없이 시험한다. 사람에게 보일 글은 **키 값을 담지 않는다**.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from chaeksas.contracts.center_keys import EXPIRY_WARNING_DAYS
from chaeksas.contracts.enrollment import (
    EnrollStatus,
    SealError,
    StudioEnrollRequest,
    StudioVersions,
    new_keypair,
    open_sealed,
    public_of,
    request_code,
)
from chaeksas.core import build_info, machine
from chaeksas.studio.credentials import CENTER_KEY_NAME, SecretsUnavailable, StudioCredentials

log = logging.getLogger(__name__)

TIMEOUT_S = 10.0
ENROLL_PATH = "/api/v1/studio/enroll"
#: 보낸 요청을 담는 파일 (데이터 폴더). **키도 봉함도 담지 않는다** — 요청 id·코드·상태뿐이다.
STATE_FILE = "enrollment.json"
#: 등록 요청에 쓴 키 쌍의 비밀 반쪽 — OS 비밀 저장소에만 (환경변수 길이 없다).
ENROLL_SECRET = "enroll_secret"

STUDIO_VERSION = build_info.product_version("chaeksas-studio")
CORE_VERSION = build_info.package_version("chaeksas-core")

#: Center의 오류 코드 → 사람에게 할 말 (STU-10 · C4 오류 표).
BUSY = "Center가 지금 등록 요청을 받지 않습니다 — 잠시 뒤 「다시 요청」하세요"


@dataclass(frozen=True)
class Outcome:
    """한 걸음의 결과. `key_name`·`expires_at`은 키를 받았을 때만 있다."""

    text: str
    got_key: bool = False
    key_name: str = ""
    expires_at: str = ""


def _when(text: str | None) -> str:
    return (text or "")[:16].replace("T", " ")


def waiting_text(found: EnrollStatus) -> str:
    """상태 줄 (STU-10 — Bot UI의 BUI-03과 같은 말)."""
    if found.state == "pending":
        return f"승인을 기다립니다 — 관리자에게 요청 코드 {found.code}를 알려 주세요 ({_when(found.expires_at)}까지)"
    if found.state == "rejected":
        return f"거절되었습니다{': ' + found.reason if found.reason else ''}"
    if found.state == "expired":
        return "요청이 만료되었습니다"
    return "승인되었습니다 — 키를 받는 중입니다."


def connected_text(key_name: str, expires_at: str) -> str:
    """키가 있을 때의 상태 줄. 만료 14일 전부터는 미리 다시 요청하라고 한다."""
    until = expires_at[:10]
    if expires_soon(expires_at):
        return f"{until}에 키가 만료됩니다 — 「다시 요청」으로 미리 승인받으세요"
    name = f"「{key_name}」으로 " if key_name else ""
    return f"연결됨 — {name}들어와 있습니다" + (f" ({until}까지)" if until else "")


def expires_soon(expires_at: str) -> bool:
    if not expires_at:
        return False
    try:
        until = datetime.fromisoformat(expires_at)
    except ValueError:
        return False
    return until - datetime.now(UTC) <= timedelta(days=EXPIRY_WARNING_DAYS)


@dataclass
class StudioEnrollment:
    """Studio 등록 요청 한 벌. `client`를 넣으면 그것으로 부른다 (시험은 Center TestClient)."""

    base_url: str
    data_dir: Path
    credentials: StudioCredentials
    client: Any = None

    # ── 보낸 요청 (파일) ──

    @property
    def state_path(self) -> Path:
        return self.data_dir / STATE_FILE

    def current(self) -> EnrollStatus | None:
        if not self.state_path.is_file():
            return None
        try:
            return EnrollStatus.model_validate(json.loads(self.state_path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            log.warning("등록 요청 기록을 읽지 못해 새로 요청한다 (%s): %s", self.state_path, e)
            return None

    def _save(self, found: EnrollStatus | None) -> None:
        if found is None:
            self.state_path.unlink(missing_ok=True)
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        kept = found.model_copy(update={"sealed_key": None}).to_json_dict()
        self.state_path.write_text(
            json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    # ── Center ──

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        import httpx  # noqa: PLC0415 — 누를 때만 든다

        url = f"{self.base_url.rstrip('/')}{path}"
        if self.client is not None:
            return self.client.request(method, url, json=body)
        with httpx.Client(timeout=TIMEOUT_S) as made:
            return made.request(method, url, json=body)

    def _secret(self) -> str:
        found = self.credentials.stored(ENROLL_SECRET)
        if found:
            return found
        private, _ = new_keypair()
        self.credentials.set(ENROLL_SECRET, private)  # 저장소가 없으면 SecretsUnavailable
        return private

    def request(self) -> Outcome:
        """새 등록 요청 (「다시 요청」도 이것이다). 요청 코드를 **스스로 다시 계산해** 맞을 때만 받는다."""
        import httpx  # noqa: PLC0415

        if not self.base_url.strip():
            return Outcome("Center 주소가 비었습니다.")
        try:
            secret = self._secret()
        except SecretsUnavailable as e:
            return Outcome(f"키를 둘 비밀 저장소가 없어 등록 요청을 보내지 않습니다 — {e}")
        public = public_of(secret)
        body = StudioEnrollRequest(
            schema=1,
            machine_id=machine.machine_id(self.data_dir),
            name=machine.pc_name(),
            os=machine.os_label(),
            versions=StudioVersions(studio=STUDIO_VERSION, core=CORE_VERSION),
            public_key=public,
        )
        try:
            answer = self._call("POST", ENROLL_PATH, body.to_json_dict())
        except httpx.HTTPError as e:
            return Outcome(f"닿지 못함 — {type(e).__name__}")
        if answer.status_code == 429:
            return Outcome(BUSY)
        if answer.status_code >= 400:
            return Outcome(f"등록 요청을 보내지 못했습니다 — Center가 {answer.status_code}로 답했습니다")
        found = EnrollStatus.model_validate(answer.json())
        if found.code != request_code(public, found.enrollment_id):
            return Outcome("Center가 준 요청 코드가 이 PC가 계산한 것과 다릅니다 — Center 주소가 맞는지 확인하세요")
        self._save(found)
        log.info("Center에 등록 요청을 보냈다 — 요청 코드 %s", found.code)
        return Outcome(waiting_text(found))

    def step(self) -> Outcome:
        """한 걸음 — 요청이 없거나 만료됐으면 보내고, 기다리는 중이면 묻고, 승인됐으면 키를 받는다.

        거절된 요청은 다시 보내지 않는다 — 사람이 「다시 요청」을 누를 때까지.
        """
        import httpx  # noqa: PLC0415

        current = self.current()
        if current is None or current.state == "expired":
            return self.request()
        if current.state == "rejected":
            return Outcome(waiting_text(current))
        try:
            answer = self._call("GET", f"{ENROLL_PATH}/{current.enrollment_id}")
        except httpx.HTTPError as e:
            return Outcome(f"닿지 못함 — {type(e).__name__}")
        if answer.status_code == 404:
            self._save(None)  # Center가 모르는 요청 — 새로 보낸다
            return self.request()
        if answer.status_code >= 400:
            return Outcome(f"Center가 {answer.status_code}로 답했습니다")
        found = EnrollStatus.model_validate(answer.json())
        if found.state == "approved" and found.sealed_key is not None:
            secret = self.credentials.stored(ENROLL_SECRET)
            if not secret:
                self._save(None)
                return self.request()
            try:
                key = open_sealed(secret, found.sealed_key, salt=found.enrollment_id)
                self.credentials.set_center_api_key(key)
            except SealError as e:
                return Outcome(f"받은 키를 열지 못했습니다 — {e}")
            except SecretsUnavailable as e:
                return Outcome(f"받은 키를 둘 곳이 없습니다 — {e}")
            self._save(None)
            log.info("등록 요청이 승인되어 Center API 키를 받았다")
            return Outcome(
                connected_text(found.key_name or "", found.key_expires_at or ""),
                got_key=True,
                key_name=found.key_name or "",
                expires_at=found.key_expires_at or "",
            )
        self._save(found)
        return Outcome(waiting_text(found))

    def forget(self) -> None:
        """보낸 요청 기록을 지운다 (「다시 요청」 — 다음 걸음이 새로 보낸다)."""
        self._save(None)

    def again(self) -> Outcome:
        """「다시 요청」 — 들고 있던 키(거부·만료)와 요청을 버리고 새로 요청한다."""
        self.credentials.delete(CENTER_KEY_NAME)
        self._save(None)
        return self.request()


# ─────────────────────────── 켤 때 (STU-16 「언제 뜨나」) ───────────────────────────

#: 켤 때 무엇을 할까 — `connect`·`refused`면 STU-16을 띄우고, `soon`·`unreachable`이면 상태 표시줄 한 줄.
NEED_NONE, NEED_CONNECT, NEED_REFUSED, NEED_SOON, NEED_UNREACHABLE = (
    "none", "connect", "refused", "soon", "unreachable",
)


@dataclass(frozen=True)
class Need:
    kind: str
    text: str = ""


def need_at_start(
    *, base_url: str, key: str | None, from_env: bool, key_expires: str, client: Any = None
) -> Need:
    """STU-16 표 — Studio를 켤 때 「Center에 연결」을 띄울지.

    키가 있을 때만 **한 번** 묻는다(그 키가 살아 있나). 닿지 못한 것은 키 문제가 아니다 — 띄우지
    않는다. 환경변수 키(자동화·CI)는 묻지도 않는다.
    """
    from chaeksas.studio.checks import center_status  # noqa: PLC0415

    if from_env:
        return Need(NEED_NONE)
    if not key:
        return Need(NEED_CONNECT)
    said = center_status(base_url, key, client=client)
    if said.startswith("키가 거부되었습니다"):
        return Need(NEED_REFUSED, "키가 거부되었습니다 — 「다시 요청」으로 새로 승인받으세요")
    if said.startswith("닿지 못함"):
        return Need(NEED_UNREACHABLE, f"Center에 닿지 못했습니다 ({base_url})")
    if expires_soon(key_expires):
        return Need(NEED_SOON, f"{key_expires[:10]}에 Center 키가 만료됩니다 — 설정 → Center에서 「다시 요청」하세요")
    return Need(NEED_NONE)


__all__ = [
    "NEED_CONNECT",
    "NEED_NONE",
    "NEED_REFUSED",
    "NEED_SOON",
    "NEED_UNREACHABLE",
    "ENROLL_SECRET",
    "Need",
    "need_at_start",
    "STATE_FILE",
    "Outcome",
    "StudioEnrollment",
    "connected_text",
    "expires_soon",
    "waiting_text",
]
