"""확장 폴더 — Center가 **뜰 때** 외부 확장 정의를 콘솔 등록과 같은 관문으로 들인다 (ADR-0121).

배포가 `*.extension.json`을 `CHK_CENTER__EXTENSIONS_DIR`에 복사해 두면 여기서 한 번 읽는다. 파일에는 **정의만**
있고 서명은 Center가 한다 — 관문은 `resources.register_extension` 하나다(크기·C13·E1~E4 → Center 봉투).

- 같은 `id`·`version`·같은 내용이면 아무것도 하지 않는다 (`unchanged`).
- 더 높은 판이 이미 등록돼 있으면 건너뛴다 (`skipped`·`older_than_registered`) — 옛 파일이 지금 판을 내리지 않는다.
- 같은 판에 다른 내용·철회된 판·검사 실패는 거절 (`refused`, 콘솔 등록과 같은 코드).
- 폴더에서 사라진 것은 지우지 않는다. **잘못된 파일이 Center를 막지 않는다** — 사유는 로그와
  `GET /resources/extension-folder`(C7)로 간다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from chaeksas.center.api import resources
from chaeksas.center.auth import Caller
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts._semver import InvalidVersion, compare, sort_key
from chaeksas.contracts.resources import ExtensionFolderItem, ExtensionFolderScan

log = logging.getLogger(__name__)

#: 폴더에서 읽는 파일 (C13 확장 정의).
PATTERN = "*.extension.json"
#: 등록한 「누가」 — 사람이 아니라 폴더다.
ACTOR = "확장 폴더"
SOURCE = "folder"


def scan(store: Store, folder: Path | None) -> ExtensionFolderScan:
    """폴더를 한 번 읽어 들인다. **예외를 밖으로 내지 않는다** — Center 기동을 막지 않는다."""
    if folder is None:
        return ExtensionFolderScan(configured=False)
    at = now_iso()
    where = folder.as_posix()
    if not folder.is_dir():
        problem = "폴더가 없습니다" if not folder.exists() else "폴더가 아닙니다"
        log.warning("확장 폴더 %s: %s", where, problem)
        return ExtensionFolderScan(configured=True, dir=where, scanned_at=at, problem=problem)

    items: list[ExtensionFolderItem] = []
    readable: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(folder.glob(PATTERN)):
        if not path.is_file():
            continue
        try:
            # Windows에서 저장한 파일의 BOM도 받는다.
            definition = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, ValueError) as e:
            items.append(_refused(path, None, "unreadable", f"파일을 JSON으로 읽지 못했습니다: {e}"))
            continue
        if not isinstance(definition, dict):
            items.append(_refused(path, None, "unreadable", "확장 정의는 JSON 객체여야 합니다"))
            continue
        readable.append((path, definition))

    # 같은 id의 여러 판은 **낮은 판부터** 들인다 — 끝에 남는 지금 판이 가장 높은 판이 되게.
    readable.sort(key=lambda one: (str(one[1].get("id")), _version_key(one[1].get("version")), one[0].name))
    for path, definition in readable:
        items.append(_one(store, path, definition))
    return ExtensionFolderScan(configured=True, dir=where, scanned_at=at, items=items)


def _one(store: Store, path: Path, definition: dict[str, Any]) -> ExtensionFolderItem:
    ext_id = definition.get("id") if isinstance(definition.get("id"), str) else None
    version = definition.get("version") if isinstance(definition.get("version"), str) else None
    if ext_id and version:
        newer = _newer_registered(store, ext_id, version)
        if newer is not None:
            message = f"{ext_id}@{newer}이 이미 등록돼 있어 {version}은 들이지 않습니다"
            log.warning("확장 폴더 %s: %s", path.name, message)
            return ExtensionFolderItem(
                file=path.name, id=ext_id, version=version, outcome="skipped",
                code="older_than_registered", message=message,
            )
    try:
        info, created = resources.register_extension(
            store, Caller(kind="admin", actor=ACTOR), {"definition": definition}, source=SOURCE
        )
    except ApiError as e:
        return _refused(path, definition, e.code, e.message)
    except Exception as e:  # noqa: BLE001 — 한 파일이 Center를 막지 않는다
        log.exception("확장 폴더 %s를 들이다 터졌다", path.name)
        return _refused(path, definition, "internal", f"들이다 오류가 났습니다: {type(e).__name__}")
    outcome = "registered" if created else "unchanged"
    if created:
        log.info("확장 폴더 %s: %s@%s를 등록했다", path.name, info.id, info.version)
    return ExtensionFolderItem(file=path.name, id=ext_id, version=version, outcome=outcome)


def _refused(path: Path, definition: dict[str, Any] | None, code: str, message: str) -> ExtensionFolderItem:
    log.warning("확장 폴더 %s를 들이지 않았다 (%s): %s", path.name, code, message)
    got = definition or {}
    return ExtensionFolderItem(
        file=path.name,
        id=got.get("id") if isinstance(got.get("id"), str) else None,
        version=got.get("version") if isinstance(got.get("version"), str) else None,
        outcome="refused",
        code=code,
        message=message,
    )


def _newer_registered(store: Store, ext_id: str, version: str) -> str | None:
    """철회되지 않은 판 가운데 `version`보다 높은 것 (가장 높은 것). 판을 읽을 수 없으면 비교하지 않는다."""
    best: str | None = None
    for row in store.rows("SELECT version FROM extensions WHERE id = ? AND revoked_json IS NULL", (ext_id,)):
        other = str(row["version"])
        try:
            if compare(other, version) > 0 and (best is None or compare(other, best) > 0):
                best = other
        except InvalidVersion:
            continue
    return best


def _version_key(version: Any) -> tuple[int, Any]:
    """판 순서 — 읽을 수 없는 판은 뒤로 (등록이 거절하며 사유를 남긴다)."""
    try:
        return (0, sort_key(str(version)))
    except InvalidVersion:
        return (1, str(version))
