"""설치된 Bot — 패키지(C1 zip)를 풀어 두고 목록으로 보인다 (BUI-04 「설치된 Bot」).

- 푸는 곳은 `bots/<id>/<버전>/`이다. **같은 판을 다시 설치하면 덮어쓴다** (받은 것이 옳다).
- **푸는 것은 Center가 먼저 본 zip이라도 다시 본다** — 경로 탈출은 푸는 쪽에서 막아야 한다
  (C5가 Center에서 막는 것과 같은 검사. 수동 설치는 Center를 거치지 않는다).
- **서명은 설치할 때 본다** (`deploy.py`, C2 V1~V7). 여기 「서명」 칸은 설치된 패키지 안의
  봉투를 읽어 보일 뿐이다 — 모르는 것을 「확인됨」이라고 하지 않는다.
- **「출처」도 설치할 때 남긴다** (`write_source`) — 푸는 것만으로는 Center 배포인지 사람이 고른
  파일인지 알 수 없다. 표식이 없는 폴더는 「알 수 없음」이다 (같은 이유로 「수동 설치」라고
  단정하지 않는다 — 표식을 남기기 전에 설치된 것일 수 있다).
"""

from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path

from chaeksas.contracts.hashing import MANIFEST_NAME, content_hash_zip
from chaeksas.contracts.manifest import Manifest
from chaeksas.contracts.signing import Envelope

log = logging.getLogger(__name__)

#: 설치된 Bot이 사는 곳 (`data_dir()/bots/<id>/<버전>/`).
BOTS_DIR = "bots"
#: 패키지 안의 승인 봉투 (C2) — 설치하면 폴더에 그대로 남는다.
SIGNATURE_NAME = "SIGNATURE"
#: 「출처」 표식 — 패키지에 들어 있는 것이 아니라 **설치하는 쪽이** 봉투 옆에 쓴다.
INSTALL_SOURCE_NAME = "INSTALL_SOURCE"

#: 표식에 적는 값. 파일에는 ASCII로 적고, 화면 표기는 `SOURCE_LABELS`가 준다.
CENTER = "center"
MANUAL = "manual"

#: BUI-04 「출처」의 표기. **모르는 것은 둘 중 하나라고 하지 않는다.**
SOURCE_LABELS = {CENTER: "Center 배포", MANUAL: "수동 설치"}
SOURCE_UNKNOWN = "알 수 없음"

#: 푸는 쪽 한도 (C5의 Center 쪽 검사와 같은 뜻).
MAX_ENTRIES = 5000
MAX_UNCOMPRESSED_MB = 1024


class InstallError(RuntimeError):
    """설치하지 못했다 — 사람이 읽을 한 줄."""


@dataclass(frozen=True)
class InstalledBot:
    """설치된 Bot 하나."""

    manifest: Manifest
    folder: Path
    #: 받은 파일에서 다시 계산한 해시 (C2) — 매니페스트와 다르면 설치하지 않는다.
    content_hash: str = ""

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def name(self) -> str:
        return self.manifest.name or self.manifest.id

    @property
    def entry_path(self) -> Path:
        return self.folder / (self.manifest.entry or "")

    @property
    def signature(self) -> str:
        """서명 상태 (BUI-04 「서명」, C2).

        **설치된 것에서 읽는다** — 설치할 때 검증을 통과한 봉투가 그대로 들어 있다. 서명을
        여기서 다시 검증하지는 않는다 (그것은 설치할 때 `deploy.py`가 한다).
        """
        found = self.folder / SIGNATURE_NAME
        if not found.is_file():
            return "서명 없음"
        try:
            envelope = Envelope.model_validate_json(found.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "서명 읽지 못함"
        return f"승인됨 ({envelope.key_id[:8]}…)"

    @property
    def source(self) -> str:
        """어디서 왔나 (BUI-04 「출처」).

        **모르는 것은 「수동 설치」라고 하지 않는다** — 표식은 설치하는 쪽이 남기므로
        (`write_source`), 표식이 없으면 그 폴더가 배포로 온 것인지 사람이 고른 파일인지
        알 길이 없다 (표식을 남기기 전에 설치된 것일 수 있다). 그때는 「알 수 없음」이다.
        """
        found = self.folder / INSTALL_SOURCE_NAME
        if not found.is_file():
            return SOURCE_UNKNOWN
        try:
            raw = json.loads(found.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return SOURCE_UNKNOWN
        if not isinstance(raw, dict):
            return SOURCE_UNKNOWN
        return SOURCE_LABELS.get(str(raw.get("source") or ""), SOURCE_UNKNOWN)


def bots_dir(data_dir: Path) -> Path:
    return data_dir / BOTS_DIR


def write_source(folder: Path, source: str) -> None:
    """설치한 쪽이 「출처」를 남긴다 (BUI-04).

    **`install()`이 쓰지 않는 것은 일부러다** — 푸는 것만으로는 어느 쪽인지 알 수 없다.
    아는 쪽이 적는다: `deploy.py`는 `CENTER`, BUI-04 「패키지 파일에서 설치...」는 `MANUAL`.

    쓰지 못하면 **기록만 남긴다** — 설치는 이미 됐고, 그 폴더의 「출처」가 「알 수 없음」이
    되는 것은 거짓이 아니다 (설치 자체를 실패로 만들 일은 아니다).
    """
    try:
        (folder / INSTALL_SOURCE_NAME).write_text(
            json.dumps({"source": source}, ensure_ascii=False), encoding="utf-8", newline="\n"
        )
    except OSError as e:
        log.warning("「출처」 표식을 남기지 못했다 (%s): %s", folder, e)


def check_zip(path: Path) -> None:
    """**푸는 쪽에서** 본다 — 절대 경로·`..`·너무 많은 항목·zip 폭탄."""
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise InstallError("zip 파일이 아닙니다") from e
    try:
        entries = archive.infolist()
    finally:
        archive.close()

    if len(entries) > MAX_ENTRIES:
        raise InstallError(f"패키지 항목이 너무 많습니다 ({MAX_ENTRIES}개 초과)")
    total = 0
    for item in entries:
        name = item.filename
        if name.startswith("/") or ".." in Path(name).parts or (len(name) > 1 and name[1] == ":"):
            raise InstallError(f"패키지 안에 위험한 경로가 있습니다: {name}")
        total += item.file_size
    if total > MAX_UNCOMPRESSED_MB * 1024 * 1024:
        raise InstallError(f"풀린 크기가 {MAX_UNCOMPRESSED_MB} MB를 넘습니다")


def read_manifest(path: Path) -> Manifest:
    with zipfile.ZipFile(path) as archive:
        try:
            raw = archive.read(MANIFEST_NAME)
        except KeyError as e:
            raise InstallError("패키지에 manifest.json이 없습니다") from e
    try:
        return Manifest.model_validate_json(raw)
    except ValueError as e:
        raise InstallError(f"manifest.json이 계약과 맞지 않습니다: {e}") from e


def install(data_dir: Path, package: Path) -> InstalledBot:
    """패키지 zip 하나를 설치한다 (BUI-04 「패키지 파일에서 설치...」).

    **보낸 사람이 적은 해시를 믿지 않고 다시 계산해** 매니페스트와 대조한다 (C1 R6).
    """
    if not package.is_file():
        raise InstallError(f"파일이 없습니다: {package.name}")
    check_zip(package)
    manifest = read_manifest(package)

    found = content_hash_zip(package)
    if manifest.content_hash and found != manifest.content_hash:
        raise InstallError("패키지 내용이 매니페스트의 해시와 다릅니다 — 받다가 깨졌을 수 있습니다")

    target = bots_dir(data_dir) / manifest.id / manifest.version
    if target.exists():
        _wipe(target)
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package) as archive:
        archive.extractall(target)  # noqa: S202 — `check_zip`이 경로를 먼저 본다
    return InstalledBot(manifest=manifest, folder=target, content_hash=found)


def _wipe(folder: Path) -> None:
    for path in sorted(folder.rglob("*"), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink()
        else:
            path.rmdir()


def installed(data_dir: Path) -> list[InstalledBot]:
    """설치된 것 모두 (이름순). **읽지 못하는 것은 건너뛴다** — 목록이 통째로 막히지 않게."""
    root = bots_dir(data_dir)
    if not root.is_dir():
        return []
    out = []
    for manifest_path in sorted(root.glob("*/*/manifest.json")):
        try:
            manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append(InstalledBot(manifest=manifest, folder=manifest_path.parent))
    return sorted(out, key=lambda one: (one.name, one.version))


def find(data_dir: Path, bot_id: str, version: str | None = None) -> InstalledBot | None:
    """그 Bot. 판을 적지 않으면 **가장 최근에 설치된 것**이 아니라 **판 이름이 가장 큰 것**이다."""
    found = [one for one in installed(data_dir) if one.id == bot_id]
    if version:
        return next((one for one in found if one.version == version), None)
    return max(found, key=lambda one: _parts(one.version), default=None)


def _parts(version: str) -> tuple[int, ...]:
    out = []
    for piece in version.split("."):
        digits = "".join(c for c in piece if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def write_inputs(path: Path, inputs: dict[str, object]) -> None:
    """실행기에게 줄 입력. **인자로 넘기지 않는다** — 업무 값이 명령줄(프로세스 목록)에 뜬다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inputs, ensure_ascii=False), encoding="utf-8", newline="\n")


__all__ = [
    "BOTS_DIR",
    "CENTER",
    "INSTALL_SOURCE_NAME",
    "MANUAL",
    "MAX_ENTRIES",
    "MAX_UNCOMPRESSED_MB",
    "SOURCE_LABELS",
    "SOURCE_UNKNOWN",
    "InstallError",
    "InstalledBot",
    "bots_dir",
    "check_zip",
    "find",
    "install",
    "installed",
    "read_manifest",
    "write_inputs",
    "write_source",
]
