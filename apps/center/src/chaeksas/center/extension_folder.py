"""확장 폴더 — Center가 **뜰 때** 기본 확장과 승인 없는 일꾼을 들인다 (ADR-0121).

배포가 파일을 확장 폴더(`CHK_CENTER__EXTENSIONS_DIR`, 기본 `<데이터>/extensions`)에 복사해 두면 여기서 한 번
읽는다. **폴더가 원본이다** — 콘솔은 폴더가 들인 것을 등록·해제하지 않는다.

확장 정의 (`*.extension.json`, C13) — 파일에는 **정의만** 있고 서명은 Center가 한다. 관문은
`resources.register_extension` 하나다(크기·C13·E1~E4 → Center 봉투).

- 같은 `id`·`version`·같은 내용이면 아무것도 하지 않는다 (`unchanged`).
- 더 높은 판이 이미 등록돼 있으면 건너뛴다 (`skipped`·`older_than_registered`) — 옛 파일이 지금 판을 내리지 않는다.
- 같은 판에 다른 내용·철회된 판·검사 실패는 거절 (`refused`, 콘솔 등록과 같은 코드).
- **폴더에서 빠진 확장은 거둔다** (`revoked`) — 폴더가 들인 것만, 그 id의 모든 판을.

일꾼 (`*.consumer.json`, C15 `FolderConsumer`) — 이름·토픽·**토큰 해시**. Center가 처음부터 그 일꾼을 안다
(요청 코드·승인이 없다). 토픽은 파일에 적은 것으로 고정이고 키에는 만료·회전이 없다. 일꾼의 자리는 파일
이름이 정한다(`folder:<이름>`) — 파일에서 빠지면 키를 폐기하고 일꾼을 지운다.

**잘못된 파일이 Center를 막지 않는다** — 사유는 로그와 `GET /resources/extension-folder`(C7)로 간다. 읽지
못한 확장 파일이 있으면 **확장은 거두지 않는다**(그 파일이 무엇이었는지 모른다).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from chaeksas.center import keys
from chaeksas.center.api import resources
from chaeksas.center.auth import Caller
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts._semver import InvalidVersion, compare, sort_key
from chaeksas.contracts.external_task import CONSUMER, FolderConsumer
from chaeksas.contracts.resources import ExtensionFolderItem, ExtensionFolderScan

log = logging.getLogger(__name__)

#: 폴더에서 읽는 파일 — 확장 정의(C13)와 일꾼(C15).
PATTERN = "*.extension.json"
CONSUMER_SUFFIX = ".consumer.json"
#: 등록한 「누가」 — 사람이 아니라 폴더다.
ACTOR = "확장 폴더"
SOURCE = "folder"
#: 폴더가 들인 일꾼의 `machine_id` 머리 — 그 뒤는 파일 이름(확장자 앞)이다.
MACHINE_PREFIX = "folder:"


def scan(store: Store, folder: Path | None, *, required: bool = True) -> ExtensionFolderScan:
    """폴더를 한 번 읽어 들인다. **예외를 밖으로 내지 않는다** — Center 기동을 막지 않는다.

    `required=False`(기본 자리)면 폴더가 없을 때 조용히 지나간다 — 기본 확장이 없는 Center다.
    """
    if folder is None or (not required and not folder.exists()):
        return ExtensionFolderScan(configured=False)
    at = now_iso()
    where = folder.as_posix()
    if not folder.is_dir():
        # 폴더가 사라진 것(볼륨이 안 붙었다)으로 **거두지 않는다** — 아무것도 바꾸지 않는다.
        problem = "폴더가 없습니다" if not folder.exists() else "폴더가 아닙니다"
        log.warning("확장 폴더 %s: %s", where, problem)
        return ExtensionFolderScan(configured=True, dir=where, scanned_at=at, problem=problem)

    items = _extensions(store, folder) + _consumers(store, folder)
    return ExtensionFolderScan(configured=True, dir=where, scanned_at=at, items=items)


# ─────────────────────────── 확장 정의 ───────────────────────────


def _extensions(store: Store, folder: Path) -> list[ExtensionFolderItem]:
    items: list[ExtensionFolderItem] = []
    readable: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(folder.glob(PATTERN)):
        if not path.is_file():
            continue
        definition = _read(path)
        if isinstance(definition, str):
            items.append(_refused(path, None, "unreadable", definition))
        elif not isinstance(definition, dict):
            items.append(_refused(path, None, "unreadable", "확장 정의는 JSON 객체여야 합니다"))
        else:
            readable.append((path, definition))
    unreadable = bool(items)

    # 같은 id의 여러 판은 **낮은 판부터** 들인다 — 끝에 남는 지금 판이 가장 높은 판이 되게.
    readable.sort(key=lambda one: (str(one[1].get("id")), _version_key(one[1].get("version")), one[0].name))
    for path, definition in readable:
        items.append(_one(store, path, definition))

    present = {str(definition.get("id")) for _, definition in readable}
    if unreadable:
        log.warning("확장 폴더: 읽지 못한 정의 파일이 있어 빠진 확장을 거두지 않는다")
    else:
        items.extend(_revoke_missing(store, present))
    return items


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


def _revoke_missing(store: Store, present: set[str]) -> list[ExtensionFolderItem]:
    """폴더가 들였는데 이제 파일이 없는 확장 — 그 id의 폴더 판을 모두 거둔다 (Center가 철회 봉투에 서명한다)."""
    out: list[ExtensionFolderItem] = []
    for row in store.rows(
        "SELECT id, version FROM extensions WHERE source = ? AND revoked_json IS NULL ORDER BY id, version", (SOURCE,)
    ):
        ext_id, version = str(row["id"]), str(row["version"])
        if ext_id in present:
            continue
        try:
            resources.revoke_extension(
                store, ext_id, version, reason="확장 폴더에서 빠졌다", by=ACTOR, from_folder=True
            )
        except Exception as e:  # noqa: BLE001
            log.exception("확장 폴더: %s@%s를 거두다 터졌다", ext_id, version)
            out.append(ExtensionFolderItem(
                id=ext_id, version=version, outcome="refused", code="internal",
                message=f"거두다 오류가 났습니다: {type(e).__name__}",
            ))
            continue
        log.info("확장 폴더: 파일이 빠져 %s@%s를 거뒀다", ext_id, version)
        out.append(ExtensionFolderItem(
            id=ext_id, version=version, outcome="revoked", message="폴더에서 빠져 등록을 해제했습니다",
        ))
    return out


# ─────────────────────────── 일꾼 ───────────────────────────


def _consumers(store: Store, folder: Path) -> list[ExtensionFolderItem]:
    items: list[ExtensionFolderItem] = []
    present: set[str] = set()
    for path in sorted(folder.glob(f"*{CONSUMER_SUFFIX}")):
        if not path.is_file():
            continue
        stem = path.name[: -len(CONSUMER_SUFFIX)]
        # 읽지 못해도 **자리는 남긴다** — 파일이 있는 한 그 일꾼을 지우지 않는다.
        present.add(stem)
        raw = _read(path)
        if isinstance(raw, str):
            items.append(_consumer_refused(path, None, "unreadable", raw))
            continue
        try:
            spec = FolderConsumer.model_validate(raw)
        except ValidationError as e:
            first = e.errors()[0]
            where = ".".join(str(one) for one in first.get("loc", ()))
            items.append(_consumer_refused(path, None, "input_invalid", f"{where}: {first.get('msg')}"))
            continue
        try:
            items.append(_sync_consumer(store, path, stem, spec))
        except Exception as e:  # noqa: BLE001 — 한 파일이 Center를 막지 않는다
            log.exception("확장 폴더 %s를 들이다 터졌다", path.name)
            items.append(_consumer_refused(path, spec.name, "internal", f"들이다 오류가 났습니다: {type(e).__name__}"))
    items.extend(_drop_missing_consumers(store, present))
    return items


def _sync_consumer(store: Store, path: Path, stem: str, spec: FolderConsumer) -> ExtensionFolderItem:
    machine_id = f"{MACHINE_PREFIX}{stem}"
    topics = sorted(set(spec.topics))
    manifests = [one.to_json_dict() for one in spec.manifests if one.app_id in topics]
    now = now_iso()
    row = store.row("SELECT * FROM consumers WHERE machine_id = ?", (machine_id,))
    key = keys.get(store, str(row["key_id"])) if row is not None else None
    held = store.row("SELECT key_id, revoked_at FROM center_keys WHERE key_hash = ?", (spec.token_sha256,))
    if held is not None and held["revoked_at"] is not None:
        # **폐기된 토큰은 되살아나지 않는다** — 관리자가 거뒀거나 파일에서 빠졌던 토큰이다.
        return _consumer_refused(path, spec.name, "token_revoked", "이 토큰은 폐기됐습니다 — 새 토큰으로 바꾸세요")
    same_key = key is not None and key.revoked_at is None and held is not None and held["key_id"] == key.key_id
    if held is not None and not same_key:
        # 해시는 키마다 하나다 — 다른 키(다른 일꾼 파일이나 발급한 키)가 이미 쓴다.
        return _consumer_refused(path, spec.name, "token_in_use", "이 토큰은 이미 다른 키가 씁니다")
    unchanged = (
        row is not None
        and same_key
        and row["name"] == spec.name
        and (loads(row["topics_json"], []) or []) == topics
        and (loads(row["manifest_json"], None) or []) == manifests
    )
    if unchanged:
        return ExtensionFolderItem(kind="consumer", file=path.name, id=spec.name, outcome="unchanged")

    with store.tx() as cur:
        key_id = key.key_id if same_key and key is not None else keys.new_key_id()
        if not same_key:
            if key is not None:
                cur.execute("UPDATE center_keys SET revoked_at = ? WHERE key_id = ? AND revoked_at IS NULL",
                            (now, key.key_id))
            # **앞자리가 비어 있다** — 원문을 모르니 해시로만 찾는다 (`keys.find`). 만료·공개키가 없어 회전하지 않는다.
            cur.execute(
                "INSERT INTO center_keys (key_id, name, type, prefix, key_hash, created_at, expires_at)"
                " VALUES (?, ?, ?, '', ?, ?, NULL)",
                (key_id, spec.name, CONSUMER, spec.token_sha256, now),
            )
        else:
            cur.execute("UPDATE center_keys SET name = ? WHERE key_id = ?", (spec.name, key_id))
        cur.execute(
            "INSERT INTO consumers (consumer_id, key_id, machine_id, name, topics_json, manifest_json,"
            " approved_at, approved_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (consumer_id) DO UPDATE SET key_id = excluded.key_id, name = excluded.name,"
            " topics_json = excluded.topics_json, manifest_json = excluded.manifest_json",
            (
                str(row["consumer_id"]) if row is not None else f"csm_folder_{stem}",
                key_id,
                machine_id,
                spec.name,
                dumps(topics),
                dumps(manifests) if manifests else None,
                now,
                ACTOR,
            ),
        )
    log.info("확장 폴더 %s: 일꾼 %s를 들였다 (토픽 %s)", path.name, spec.name, ", ".join(topics))
    return ExtensionFolderItem(kind="consumer", file=path.name, id=spec.name, outcome="registered")


def _drop_missing_consumers(store: Store, present: set[str]) -> list[ExtensionFolderItem]:
    """파일이 빠진 일꾼 — 키를 폐기하고 행을 지운다 (그 일꾼이 쥔 일감은 잠금이 풀리면 다시 줄에 선다)."""
    out: list[ExtensionFolderItem] = []
    now = now_iso()
    for row in store.rows("SELECT * FROM consumers WHERE machine_id LIKE ?", (f"{MACHINE_PREFIX}%",)):
        stem = str(row["machine_id"])[len(MACHINE_PREFIX):]
        if stem in present:
            continue
        with store.tx() as cur:
            cur.execute("UPDATE center_keys SET revoked_at = ? WHERE key_id = ? AND revoked_at IS NULL",
                        (now, row["key_id"]))
            cur.execute("DELETE FROM consumers WHERE consumer_id = ?", (row["consumer_id"],))
        log.info("확장 폴더: 파일이 빠져 일꾼 %s를 내보냈다", row["name"])
        out.append(ExtensionFolderItem(
            kind="consumer", id=str(row["name"]), outcome="revoked", message="폴더에서 빠져 키를 폐기했습니다",
        ))
    return out


# ─────────────────────────── 공통 ───────────────────────────


def _read(path: Path) -> Any:
    """JSON을 읽는다. 못 읽으면 **사유 글**을 돌려준다."""
    try:
        # Windows에서 저장한 파일의 BOM도 받는다.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return f"파일을 JSON으로 읽지 못했습니다: {e}"


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


def _consumer_refused(path: Path, name: str | None, code: str, message: str) -> ExtensionFolderItem:
    log.warning("확장 폴더 %s를 들이지 않았다 (%s): %s", path.name, code, message)
    return ExtensionFolderItem(kind="consumer", file=path.name, id=name, outcome="refused", code=code, message=message)


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
