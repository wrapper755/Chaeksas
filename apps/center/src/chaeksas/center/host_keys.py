"""키 묶기 — Center API 키 ↔ 기계 ↔ 행, **양방향으로 하나씩** (C4·C12 「키 묶기」).

Bot UI(C4)와 서버 실행기(C12)가 **같은 규칙**을 쓴다. C12가 「키 묶기는 C4와 같다」고 적어
두었으므로 규칙이 두 군데 있으면 한쪽만 고쳐져 갈라진다 — 그래서 표 이름만 다르게 받고
판정은 여기 하나다.

지키는 것 둘:

| 방향 | 어긋나면 |
| --- | --- |
| 키 → 기계 | 409 `machine_mismatch` — 이 키는 다른 기계에 묶여 있다 |
| 기계 → 키 | 409 `machine_already_registered` — 이 기계는 이미 다른 키로 등록돼 있다 |

**행이 둘 생기면** 화면에 두 줄로 보이고, 리소스 집계가 부풀고, 작업이 하트비트를 보내지 않는
쪽으로 간다. 그래서 거꾸로도 막는다.

표에 `UNIQUE`는 **아직 걸지 않았다** — 옮기기 단계로 걸 수 있게 됐지만(ADR-0065) **이미 겹친
행이 있으면 그 단계가 실패해 Center가 뜨지 않는다**. 겹친 것을 어떻게 다룰지 먼저 정한다.
그때까지 지키는 것은 이 모듈이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from chaeksas.center import keys
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.center_keys import BoundTo


@dataclass(frozen=True)
class HostTable:
    """묶기를 지킬 표 하나.

    `id_column`은 그 표의 기본키 이름이고 `label`은 사람에게 보일 말이다 (「PC」·「서버」) —
    메시지에 「PC」라고 적어 두면 서버 실행기 운영자가 PC를 찾아 헤맨다.
    """

    name: str
    id_column: str
    label: str
    #: 운영자가 묶음을 푸는 단추의 이름 (화면 글과 같아야 한다 — CON-11).
    unbind_label: str = "묶음 풀기"


#: C4 Bot UI (`bot_uis`) — 키 종류 `bot_ui`.
BOT_UI = HostTable(name="bot_uis", id_column="bot_ui_id", label="PC", unbind_label="PC 묶음 풀기")
#: C12 서버 실행기 (`server_runners`) — 키 종류 `server_runner`.
SERVER_RUNNER = HostTable(
    name="server_runners", id_column="server_runner_id", label="서버", unbind_label="묶음 풀기"
)


def row_for_key(store: Store, table: HostTable, key_id: str) -> Any | None:
    """그 키로 등록된 행. 등록 전이면 `None` — **키가 신원이다** (C4·C12)."""
    return store.row(f"SELECT * FROM {table.name} WHERE key_id = ?", (key_id,))  # noqa: S608 — 표 이름은 이 모듈의 상수다


def id_for_key(store: Store, table: HostTable, key_id: str) -> str | None:
    """그 키로 등록된 행의 id. 표를 아는 자리를 하나로 두려고 여기 둔다."""
    found = row_for_key(store, table, key_id)
    return str(found[table.id_column]) if found is not None else None


def exists(store: Store, table: HostTable, host_id: str) -> bool:
    """등록된 기계인가 (C5 배포·작업 지시의 대상 검사, [ADR-0049]).

    **id는 등록에서 Center가 만든다** — 등록 전에는 아무도 그 id를 모르므로, 명부에 없는 id는
    **미리 배포해 둔 것이 아니라 오타이거나 낡은 id**다. 행은 지우지 않으니(묶음 풀기는 키만
    푼다) 한번 참이면 영원히 참이다.
    """
    return (
        store.row(f"SELECT 1 FROM {table.name} WHERE {table.id_column} = ?", (host_id,))  # noqa: S608 — 위와 같다
        is not None
    )


def _refuse_if_bound_elsewhere(table: HostTable, key: keys.KeyRecord, machine_id: str) -> None:
    """키 → 기계: 키는 처음 등록한 기계에 묶인다."""
    if key.bound_to is not None and key.bound_to.id != machine_id:
        raise ApiError(
            409,
            "machine_mismatch",
            f"이 키는 다른 {table.label}에 묶여 있다 (「{key.bound_to.name}」). "
            f"{table.label}를 다시 설치했다면 콘솔에서 「{table.unbind_label}」을 하세요",
            {"bound_to": key.bound_to.to_json_dict()},
        )


def _adopt_or_refuse(
    store: Store, table: HostTable, key: keys.KeyRecord, *, machine_id: str, own: Any | None
) -> Any | None:
    """기계 → 키: `machine_id` 하나에 행도 하나다.

    돌려주는 것은 **이어받을 자리**다 (그 기계가 비어 있으면 `None`). 묶음이 풀린 키의 자리는
    놓인 자리라 새 키가 이어받는다 — 새 행을 만들면 배포·작업·결재가 가리키는 id를 버리게
    되고 화면에 유령 한 줄이 남는다.
    """
    other = store.row(
        f"SELECT * FROM {table.name} WHERE machine_id = ? AND key_id <> ?",  # noqa: S608 — 위와 같다
        (machine_id, key.key_id),
    )
    if other is None:
        return None
    detail = {table.id_column: str(other[table.id_column]), "name": str(other["name"])}
    owner = keys.get(store, str(other["key_id"]))
    if owner is not None and owner.bound_to is not None:
        # 키 하나가 혼자서 남의 자리를 가져가지 못한다 — 관문은 운영자다.
        raise ApiError(
            409,
            "machine_already_registered",
            f"이 {table.label}는 이미 다른 키로 등록되어 있다 (「{other['name']}」). "
            f"키를 바꾸려면 콘솔에서 옛 키의 「{table.unbind_label}」을 먼저 하세요",
            {**detail, "reason": "bound_elsewhere"},
        )
    if own is not None:
        # 이어받기는 행이 없는 키만 한다 — 어느 쪽 이력을 버릴지 짐작하지 않는다.
        raise ApiError(
            409,
            "machine_already_registered",
            f"이 키는 이미 다른 {table.label}로 등록되어 있어 이 {table.label}"
            f"(「{other['name']}」)의 자리를 이어받을 수 없다. 이 {table.label}에는 새 키를 발급하세요",
            {**detail, "reason": "key_has_another_pc"},
        )
    return other


def claim(
    store: Store,
    table: HostTable,
    key: keys.KeyRecord,
    *,
    machine_id: str,
    name: str,
    key_type: str,
) -> tuple[Any | None, Any | None]:
    """등록할 자리를 정한다 — `(이 키의 행, 이어받을 행)`.

    **묶기 전에 두 방향을 다 본다** — 막힌 등록이 키를 묶으면 운영자가 그 묶음까지 풀어야
    한다. 돌려준 것이 둘 다 `None`이면 새 행을 만들 자리다.
    """
    existing = row_for_key(store, table, key.key_id)
    _refuse_if_bound_elsewhere(table, key, machine_id)
    adopted = _adopt_or_refuse(store, table, key, machine_id=machine_id, own=existing)
    if key.bound_to is None:
        keys.bind(
            store,
            key.key_id,
            BoundTo(type=key_type, id=machine_id, name=name, first_seen=now_iso()),
        )
    return existing, adopted


__all__ = [
    "BOT_UI",
    "SERVER_RUNNER",
    "HostTable",
    "claim",
    "exists",
    "id_for_key",
    "row_for_key",
]
