"""일꾼 폴더 — Center가 **뜰 때** 일꾼을 들인다. 일꾼이 들어오는 길은 이것 하나다 (ADR-0122, C15).

배포가 `<이름>.consumer.json`(C15 `FolderConsumer` — 이름·토픽·**토큰 해시**)을 일꾼 폴더
(`CHK_CENTER__CONSUMERS_DIR`, 기본 `<데이터>/consumers`)에 복사해 두면 여기서 한 번 읽는다. 요청 코드·승인이 없다 —
폴더에 쓸 수 있는 사람을 관리자로 본다.

- 토픽은 파일에 적은 것으로 고정이고 키에는 만료·회전이 없다(공개키가 없다). 일꾼의 자리는 파일 이름이 정한다.
- 해시가 바뀌면 옛 키를 폐기한다. 폐기된 토큰은 되살아나지 않고, 다른 키가 쓰는 해시는 거절한다.
- **폴더가 원본이다** — 파일이 빠지면 키를 폐기하고 일꾼을 지운다. 일꾼이 올린 외부 확장 가운데 어느 일꾼의
  토픽에도 없게 된 것은 철회한다. 읽지 못한 파일이 있거나 폴더가 없으면 **아무것도 거두지 않는다**.
- **잘못된 파일이 Center를 막지 않는다** — 사유는 로그와 `GET /resources/consumer-folder`(C7)로 간다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from chaeksas.center import keys
from chaeksas.center.api import external_tasks, resources
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.center_keys import KEY_PREFIX, KEY_RANDOM_LEN
from chaeksas.contracts.external_task import CONSUMER, FolderConsumer
from chaeksas.contracts.resources import ConsumerFolderItem, ConsumerFolderScan

log = logging.getLogger(__name__)

SUFFIX = ".consumer.json"
#: 일꾼이 한 일(확장 올리기·거두기)의 「누가」 머리, 폴더가 거둘 때의 「누가」.
ACTOR = "일꾼 폴더"
#: 일꾼이 올린 외부 확장의 출처 (`extensions.source`).
SOURCE = external_tasks.EXTENSION_SOURCE
#: 폴더가 들인 일꾼의 `machine_id` 머리 — 그 뒤는 파일 이름(확장자 앞)이다.
MACHINE_PREFIX = "folder:"


def scan(store: Store, folder: Path | None, *, required: bool = True) -> ConsumerFolderScan:
    """폴더를 한 번 읽어 들인다. **예외를 밖으로 내지 않는다** — Center 기동을 막지 않는다.

    `required=False`(기본 자리)면 폴더가 없을 때 조용히 지나간다.
    """
    if folder is None or (not required and not folder.exists()):
        return ConsumerFolderScan(configured=False)
    at = now_iso()
    where = folder.as_posix()
    if not folder.is_dir():
        # 볼륨이 붙지 않은 것을 「다 뺐다」로 읽지 않는다 — 아무것도 바꾸지 않는다.
        problem = "폴더가 없습니다" if not folder.exists() else "폴더가 아닙니다"
        log.warning("일꾼 폴더 %s: %s", where, problem)
        return ConsumerFolderScan(configured=True, dir=where, scanned_at=at, problem=problem)

    items: list[ConsumerFolderItem] = []
    present: set[str] = set()
    topics: set[str] = set()
    unreadable = False
    for path in sorted(folder.glob(f"*{SUFFIX}")):
        if not path.is_file():
            continue
        stem = path.name[: -len(SUFFIX)]
        # 읽지 못해도 **자리는 남긴다** — 파일이 있는 한 그 일꾼을 지우지 않는다.
        present.add(stem)
        spec, why = _read(path)
        if spec is None:
            unreadable = True
            items.append(_refused(path, None, *why))
            continue
        topics |= set(spec.topics)
        try:
            items.append(admit(store, stem, spec, file=path.name))
        except Exception as e:  # noqa: BLE001 — 한 파일이 Center를 막지 않는다
            log.exception("일꾼 폴더 %s를 들이다 터졌다", path.name)
            items.append(_refused(path, spec.name, "internal", f"들이다 오류가 났습니다: {type(e).__name__}"))
    items.extend(_drop_missing(store, present))
    if unreadable:
        log.warning("일꾼 폴더: 읽지 못한 파일이 있어 일꾼이 올린 확장을 거두지 않는다")
    else:
        items.extend(_revoke_orphans(store, topics))
    return ConsumerFolderScan(configured=True, dir=where, scanned_at=at, items=items)


def admit(store: Store, stem: str, spec: FolderConsumer, *, file: str | None = None) -> ConsumerFolderItem:
    """일꾼 하나를 들인다(또는 맞춘다). 폴더를 읽을 때 부르고, 시험도 같은 길로 들인다."""
    machine_id = f"{MACHINE_PREFIX}{stem}"
    topics = sorted(set(spec.topics))
    manifests = [one.to_json_dict() for one in spec.manifests if one.app_id in topics]
    now = now_iso()
    row = store.row("SELECT * FROM consumers WHERE machine_id = ?", (machine_id,))
    key = keys.get(store, str(row["key_id"])) if row is not None else None
    held = store.row("SELECT key_id, revoked_at FROM center_keys WHERE key_hash = ?", (spec.token_sha256,))
    if held is not None and held["revoked_at"] is not None:
        # **폐기된 토큰은 되살아나지 않는다** — 바꾼 토큰이거나 파일에서 빠졌던 토큰이다.
        return _refused_at(file, spec.name, "token_revoked", "이 토큰은 폐기됐습니다 — 새 토큰으로 바꾸세요")
    same_key = key is not None and key.revoked_at is None and held is not None and held["key_id"] == key.key_id
    if held is not None and not same_key:
        return _refused_at(file, spec.name, "token_in_use", "이 토큰은 이미 다른 키가 씁니다")
    if (
        row is not None
        and same_key
        and row["name"] == spec.name
        and (loads(row["topics_json"], []) or []) == topics
        and (loads(row["manifest_json"], None) or []) == manifests
    ):
        return ConsumerFolderItem(file=file, id=spec.name, outcome="unchanged")

    with store.tx() as cur:
        key_id = key.key_id if same_key and key is not None else keys.new_key_id()
        if not same_key:
            if key is not None:
                cur.execute(
                    "UPDATE center_keys SET revoked_at = ? WHERE key_id = ? AND revoked_at IS NULL", (now, key.key_id)
                )
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
    log.info("일꾼 폴더 %s: 일꾼 %s를 들였다 (토픽 %s)", file or stem, spec.name, ", ".join(topics))
    return ConsumerFolderItem(file=file, id=spec.name, outcome="registered")


def _drop_missing(store: Store, present: set[str]) -> list[ConsumerFolderItem]:
    """파일이 빠진 일꾼 — 키를 폐기하고 행을 지운다 (쥔 일감은 잠금이 풀리면 다시 줄에 선다)."""
    out: list[ConsumerFolderItem] = []
    now = now_iso()
    for row in store.rows("SELECT * FROM consumers WHERE machine_id LIKE ?", (f"{MACHINE_PREFIX}%",)):
        if str(row["machine_id"])[len(MACHINE_PREFIX) :] in present:
            continue
        with store.tx() as cur:
            cur.execute(
                "UPDATE center_keys SET revoked_at = ? WHERE key_id = ? AND revoked_at IS NULL", (now, row["key_id"])
            )
            cur.execute("DELETE FROM consumers WHERE consumer_id = ?", (row["consumer_id"],))
        log.info("일꾼 폴더: 파일이 빠져 일꾼 %s를 내보냈다", row["name"])
        out.append(
            ConsumerFolderItem(id=str(row["name"]), outcome="revoked", message="폴더에서 빠져 키를 폐기했습니다")
        )
    return out


def _revoke_orphans(store: Store, topics: set[str]) -> list[ConsumerFolderItem]:
    """일꾼이 올렸는데 이제 어느 일꾼의 토픽에도 없는 확장 — 그 판들을 거둔다 (Center가 철회 봉투에 서명한다)."""
    out: list[ConsumerFolderItem] = []
    for row in store.rows(
        "SELECT id, version FROM extensions WHERE source = ? AND revoked_json IS NULL ORDER BY id, version", (SOURCE,)
    ):
        ext_id, version = str(row["id"]), str(row["version"])
        if ext_id in topics:
            continue
        try:
            resources.revoke_extension(store, ext_id, version, reason="맡은 일꾼이 일꾼 폴더에서 빠졌다", by=ACTOR)
        except Exception as e:  # noqa: BLE001
            log.exception("일꾼 폴더: %s@%s를 거두다 터졌다", ext_id, version)
            out.append(ConsumerFolderItem(
                kind="extension", id=ext_id, version=version, outcome="refused", code="internal",
                message=f"거두다 오류가 났습니다: {type(e).__name__}",
            ))
            continue
        log.info("일꾼 폴더: 맡은 일꾼이 없어 %s@%s를 거뒀다", ext_id, version)
        out.append(ConsumerFolderItem(
            kind="extension", id=ext_id, version=version, outcome="revoked",
            message="맡은 일꾼이 없어 등록을 해제했습니다",
        ))
    return out


def _read(path: Path) -> tuple[FolderConsumer | None, tuple[str, str]]:
    try:
        # Windows에서 저장한 파일의 BOM도 받는다.
        raw: Any = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return None, ("unreadable", f"파일을 JSON으로 읽지 못했습니다: {e}")
    try:
        return FolderConsumer.model_validate(raw), ("", "")
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(one) for one in first.get("loc", ())) or "(전체)"
        return None, ("input_invalid", f"{where}: {first.get('msg')}")


def _refused(path: Path, name: str | None, code: str, message: str) -> ConsumerFolderItem:
    return _refused_at(path.name, name, code, message)


def _refused_at(file: str | None, name: str | None, code: str, message: str) -> ConsumerFolderItem:
    log.warning("일꾼 폴더 %s를 들이지 않았다 (%s): %s", file, code, message)
    return ConsumerFolderItem(file=file, id=name, outcome="refused", code=code, message=message)


# ─────────────────────────── 파일 짓기 (`chk-center consumer-file`) ───────────────────────────


def new_token() -> str:
    """일꾼 토큰 원문 — C7 키 모양(`chk_ctr_` + 40자)이다. Center는 모양을 보지 않고 해시만 맞춘다."""
    return f"{KEY_PREFIX}{secrets.token_urlsafe(48)[:KEY_RANDOM_LEN]}"


def token_sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_file(folder: Path, name: str, topics: list[str]) -> tuple[Path, str]:
    """`<이름>.consumer.json`을 쓰고 `(파일, 토큰 원문)`을 돌려준다. 원문은 파일에 넣지 않는다."""
    raw = new_token()
    spec = FolderConsumer(name=name, topics=topics, token_sha256=token_sha256(raw))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}{SUFFIX}"
    body = {"name": spec.name, "topics": spec.topics, "token_sha256": spec.token_sha256}
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, raw
