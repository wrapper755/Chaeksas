"""Admin 서명 키 — 만들고, **암호문으로 보호해** 사용자 폴더에 둔다 (C2, ADM-01).

개인키는 **이 PC에만** 있다. Center도 콘솔도 모른다 — 토큰이 새도 배포를 만들 수 없게 하는
마지막 관문이 이것이다.

- 암호는 **묻는다.** 환경변수(`CHK_ADMIN__PASSPHRASE`)는 CI·시험용이다.
- 파일은 현재 사용자만 읽게 둔다 (Windows는 ACL이라 `chmod`가 소용없지만, 사용자 데이터
  폴더 자체가 그 사용자 것이다).
- **공개키는 따로 적어 둔다** (`.pub`) — 부트스트랩에 쓰고, 개인키를 열지 않고도 보인다.
"""

from __future__ import annotations

import base64
import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import platformdirs
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from chaeksas.contracts.signing import key_id_for

#: 암호를 환경에서 받는 자리 (CI·시험). 사람이 쓸 때는 묻는다.
PASSPHRASE_ENV = "CHK_ADMIN__PASSPHRASE"
ENV_PREFIX = "CHK_ADMIN__"


def data_dir() -> Path:
    """키가 사는 곳. Windows `%LOCALAPPDATA%`, Linux `~/.local/share` (CLAUDE.md §5)."""
    override = os.environ.get(f"{ENV_PREFIX}DATA_DIR")
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir("chaeksas", appauthor=False)) / "admin"


class KeyError_(RuntimeError):
    """키를 만들거나 열지 못했다. 사람이 읽을 한 줄."""


@dataclass(frozen=True)
class StoredKey:
    """이 PC에 있는 서명 키 하나."""

    key_id: str
    path: Path
    label: str | None = None
    created_at: str = ""

    @property
    def public_path(self) -> Path:
        return self.path.with_suffix(".pub")

    def public_bytes(self) -> bytes:
        """raw 32바이트 공개키 (base64로 적어 둔 것을 푼다)."""
        return base64.b64decode(self.public_path.read_text(encoding="utf-8").strip(), validate=True)

    def to_json_dict(self) -> dict[str, object]:
        return {"key_id": self.key_id, "label": self.label, "created_at": self.created_at}


def _passphrase(given: str | None, *, confirm: bool = False) -> bytes:
    """암호를 받는다. **빈 암호는 받지 않는다** — 개인키를 평문으로 두지 않는다."""
    found = given if given is not None else os.environ.get(PASSPHRASE_ENV)
    if found is None:  # pragma: no cover — 사람이 칠 때만
        import getpass

        found = getpass.getpass("서명 키 암호: ")
        if confirm and found != getpass.getpass("한 번 더: "):
            raise KeyError_("암호가 서로 다릅니다")
    if not found:
        raise KeyError_("암호가 비어 있습니다 — 개인키를 평문으로 두지 않습니다")
    return found.encode("utf-8")


def _index(root: Path) -> Path:
    return root / "keys.json"


def _read_index(root: Path) -> dict[str, dict[str, object]]:
    found = _index(root)
    if not found.is_file():
        return {}
    try:
        raw = json.loads(found.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def create(*, label: str | None = None, root: Path | None = None, passphrase: str | None = None) -> StoredKey:
    """새 서명 키 (ADM-01 「새 키」). 개인키는 **암호문으로** 저장한다."""
    where = root or data_dir()
    where.mkdir(parents=True, exist_ok=True)
    secret = _passphrase(passphrase, confirm=True)

    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    key_id = key_id_for(public)
    target = where / f"{key_id}.pem"
    if target.exists():  # pragma: no cover — 128비트 충돌
        raise KeyError_(f"같은 key_id의 키가 이미 있습니다: {key_id}")

    target.write_bytes(
        private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.BestAvailableEncryption(secret),
        )
    )
    _only_me(target)
    target.with_suffix(".pub").write_text(
        base64.b64encode(public).decode("ascii") + "\n", encoding="utf-8", newline="\n"
    )

    made = StoredKey(
        key_id=key_id, path=target, label=label, created_at=datetime.now(UTC).isoformat()
    )
    index = _read_index(where)
    index[key_id] = made.to_json_dict()
    _index(where).write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return made


def _only_me(path: Path) -> None:
    """현재 사용자만 읽게. Windows에서는 효과가 없어 조용히 지나간다 (ACL이 다르다)."""
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:  # pragma: no cover — Windows·특수 파일 시스템
        pass


def listing(root: Path | None = None) -> list[StoredKey]:
    """이 PC의 키들 (ADM-01). **개인키를 열지 않는다** — 암호를 묻지 않고 보인다."""
    where = root or data_dir()
    index = _read_index(where)
    out = []
    for one in sorted(where.glob("*.pem")):
        key_id = one.stem
        meta = index.get(key_id, {})
        out.append(
            StoredKey(
                key_id=key_id,
                path=one,
                label=str(meta.get("label")) if meta.get("label") else None,
                created_at=str(meta.get("created_at") or ""),
            )
        )
    return out


def find(key_id: str | None, root: Path | None = None) -> StoredKey:
    """쓸 키 하나. 적지 않았는데 키가 여럿이면 **고르라고 한다** (아무거나 쓰지 않는다)."""
    found = listing(root)
    if not found:
        raise KeyError_("이 PC에 서명 키가 없습니다 — `chk-admin keys new`로 만드세요")
    if key_id:
        picked = next((one for one in found if one.key_id == key_id), None)
        if picked is None:
            raise KeyError_(f"그 키가 없습니다: {key_id}")
        return picked
    if len(found) > 1:
        names = ", ".join(one.key_id for one in found)
        raise KeyError_(f"키가 여럿입니다 — `--key`로 고르세요 ({names})")
    return found[0]


def load(key: StoredKey, *, passphrase: str | None = None) -> Ed25519PrivateKey:
    """개인키를 연다. **암호가 틀리면 분명히 말한다** (조용히 실패하지 않는다)."""
    secret = _passphrase(passphrase)
    try:
        found = serialization.load_pem_private_key(key.path.read_bytes(), password=secret)
    except (ValueError, TypeError) as e:
        raise KeyError_(f"키를 열지 못했습니다 (암호가 다를 수 있습니다): {key.key_id}") from e
    if not isinstance(found, Ed25519PrivateKey):
        raise KeyError_(f"Ed25519 키가 아닙니다: {key.key_id}")
    return found


__all__ = [
    "ENV_PREFIX",
    "PASSPHRASE_ENV",
    "KeyError_",
    "StoredKey",
    "create",
    "data_dir",
    "find",
    "listing",
    "load",
]
