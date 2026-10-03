"""C5. 패키지 업로드·목록·정보·내려받기 (C1 검사 포함).

업로드가 믿는 것은 **파일 자체**다. 보낸 사람이 적은 해시를 믿지 않고 다시 계산해 매니페스트와
대조한다 (C1 R6). zip 안전 검사(경로 탈출·크기)도 여기서 한다 — 패키지를 푸는 곳은 현장 PC다.
"""

from __future__ import annotations

import shutil
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from chaeksas.center.errors import ApiError
from chaeksas.center.settings import MAX_PACKAGE_MB
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.center_api import PackageInfo
from chaeksas.contracts.hashing import MANIFEST_NAME, content_hash_zip
from chaeksas.contracts.manifest import Manifest
from chaeksas.contracts.manifest import validate as validate_manifest

#: 업로드된 패키지의 처음 상태 (C5 — 승인은 Admin 서명으로, M5).
STATUS_CANDIDATE = "candidate"

#: zip 안전 검사 한도. 푸는 쪽(현장 PC)을 지키려고 Center가 먼저 본다.
MAX_ENTRIES = 5000
MAX_UNCOMPRESSED_MB = 1024


@contextmanager
def _open_zip(path: Path) -> Iterator[zipfile.ZipFile]:
    """zip을 열고 **반드시 닫는다.**

    닫지 않으면 Windows가 그 파일을 지우지 못한다 (`WinError 32` — 다른 프로세스가 쓰는 중).
    검사가 실패하는 길에서도 닫혀야 해서 컨텍스트 관리자로 둔다. CI의 Windows가 잡아 줬다.
    """
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise ApiError(422, "not_a_zip", "zip 파일이 아니다") from e
    try:
        yield archive
    finally:
        archive.close()


def check_zip_safety(path: Path) -> None:
    """**위험한 항목**을 거부한다. 푸는 곳은 현장 PC이므로 Center가 먼저 본다.

    - 절대 경로·`..`·드라이브 문자: 푸는 쪽에서 폴더 밖에 쓰게 된다 (경로 탈출).
    - 항목 수·풀린 크기 한도: 작은 파일로 디스크를 채우는 공격 (zip bomb).
    """
    with _open_zip(path) as archive:
        entries = archive.infolist()
    if len(entries) > MAX_ENTRIES:
        raise ApiError(422, "zip_too_many_entries", f"zip 항목이 {MAX_ENTRIES}개를 넘는다")
    total = 0
    for item in entries:
        name = item.filename
        if name.startswith("/") or ".." in Path(name).parts or (len(name) > 1 and name[1] == ":"):
            raise ApiError(422, "zip_unsafe_path", f"zip에 위험한 경로가 있다: {name}")
        total += item.file_size
    if total > MAX_UNCOMPRESSED_MB * 1024 * 1024:
        raise ApiError(422, "zip_too_large", f"풀린 크기가 {MAX_UNCOMPRESSED_MB} MB를 넘는다")


def read_manifest(path: Path) -> Manifest:
    """zip 루트의 `manifest.json`을 읽는다 (C1). 먼저 안전 검사를 한다."""
    check_zip_safety(path)
    with _open_zip(path) as archive:
        try:
            raw = archive.read(MANIFEST_NAME)
        except KeyError as e:
            raise ApiError(422, "manifest_missing", f"zip 루트에 {MANIFEST_NAME}이 없다") from e
    try:
        return Manifest.model_validate_json(raw)
    except ValueError as e:
        raise ApiError(
            422, "manifest_invalid", "매니페스트가 C1과 맞지 않는다", {"error": str(e).splitlines()[0]}
        ) from e


def upload(store: Store, *, package_dir: Path, raw: bytes, actor: str) -> tuple[PackageInfo, bool]:
    """패키지 하나를 받는다. `(정보, 새로 만들었나)`.

    같은 id·버전·해시로 다시 보내면 **200으로 그대로 돌려준다** (재시도가 안전해야 한다).
    해시가 다르면 409 — 올린 것을 몰래 바꾸지 못한다.
    """
    if len(raw) > MAX_PACKAGE_MB * 1024 * 1024:
        raise ApiError(413, "too_large", f"패키지가 {MAX_PACKAGE_MB} MB를 넘는다")

    package_dir.mkdir(parents=True, exist_ok=True)
    staged = package_dir / f".upload-{now_iso().replace(':', '')}.zip"
    staged.write_bytes(raw)
    try:
        manifest = read_manifest(staged)
        # **보낸 해시를 믿지 않는다** — 파일에서 다시 계산한다 (C1 R6).
        computed = content_hash_zip(staged)
        problems = validate_manifest(manifest, computed_hash=computed)
        blocking = [str(v) for v in problems]
        if blocking:
            raise ApiError(422, "manifest_invalid", "C1 검사에 걸렸다", {"violations": blocking})

        existing = store.row(
            "SELECT * FROM packages WHERE id = ? AND version = ?", (manifest.id, manifest.version)
        )
        if existing is not None:
            if existing["content_hash"] != computed:
                raise ApiError(
                    409,
                    "version_conflict",
                    f"{manifest.id}@{manifest.version}이 이미 있고 내용이 다르다 — 버전을 올리세요",
                    {"stored": existing["content_hash"], "uploaded": computed},
                )
            return info_of(store, manifest.id, manifest.version), False

        final = package_dir / f"{manifest.id}-{manifest.version}.zip"
        shutil.move(str(staged), final)
        with store.tx() as cur:
            cur.execute(
                "INSERT INTO packages (id, version, kind, name, status, run_location, content_hash,"
                " manifest_json, file_name, size_bytes, uploaded_at, uploaded_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    manifest.id,
                    manifest.version,
                    manifest.kind,
                    manifest.name,
                    STATUS_CANDIDATE,
                    manifest.run_location,
                    computed,
                    dumps(manifest.to_json_dict()),
                    final.name,
                    len(raw),
                    now_iso(),
                    actor,
                ),
            )
        return info_of(store, manifest.id, manifest.version), True
    finally:
        staged.unlink(missing_ok=True)


def _info(row: Any) -> PackageInfo:
    # `size_bytes`는 C5 `PackageInfo`에 없다 — DB에만 둔다 (운영용). 화면이 필요하면 계약 먼저 고친다.
    return PackageInfo(
        id=row["id"],
        version=row["version"],
        kind=row["kind"],
        name=row["name"],
        status=row["status"],
        run_location=row["run_location"],
        content_hash=row["content_hash"],
        manifest=Manifest.model_validate(loads(row["manifest_json"], {})),
        uploaded_at=row["uploaded_at"],
        uploaded_by=row["uploaded_by"],
    )


def info_of(store: Store, package_id: str, version: str) -> PackageInfo:
    row = store.row("SELECT * FROM packages WHERE id = ? AND version = ?", (package_id, version))
    if row is None:
        raise ApiError(404, "not_found", f"{package_id}@{version}이 없다")
    return _info(row)


def listing(
    store: Store, *, kind: str | None = None, status: str | None = None, package_id: str | None = None
) -> list[PackageInfo]:
    rows = store.rows("SELECT * FROM packages ORDER BY id, version")
    found = [_info(r) for r in rows]
    if kind:
        found = [p for p in found if p.kind == kind]
    if status:
        found = [p for p in found if p.status == status]
    if package_id:
        found = [p for p in found if p.id == package_id]
    return found


def file_path(store: Store, *, package_dir: Path, package_id: str, version: str) -> tuple[Path, str]:
    """내려받을 파일과 그 해시. 응답 헤더 `X-Content-Hash`에 해시를 싣는다 (C5)."""
    row = store.row("SELECT * FROM packages WHERE id = ? AND version = ?", (package_id, version))
    if row is None:
        raise ApiError(404, "not_found", f"{package_id}@{version}이 없다")
    if row["status"] == "revoked":
        raise ApiError(410, "revoked", "철회된 패키지다")
    path = package_dir / row["file_name"]
    if not path.exists():
        raise ApiError(500, "file_missing", "메타데이터는 있는데 파일이 없다 (저장소를 확인하세요)")
    return path, row["content_hash"]
