"""옮기기 지킴에 걸린 DB를 **사람이** 고치는 도구 (`bpm-center hosts`, ADR-0066).

3판(키 묶기 UNIQUE)은 같은 키·같은 기계가 여러 행에 있으면 멈춘다 — **어느 행을 남길지
짐작하지 않는다** (#57). 그래서 고르는 것은 사람이고, 이 도구는 보이고 은퇴시키기만 한다.

**`Store`를 열지 않는다** — 열면 옮기기가 돌고 바로 그 지킴에 걸려 고칠 수가 없다. 그래서
DB를 그냥 연다 (두 표의 모양은 1판부터 그대로라 판과 무관하게 읽힌다).

**은퇴는 지우지 않는다** — 배포·작업·실행 기록·배치 결정이 그 id를 가리킨다. 그 행의
`key_id`·`machine_id`를 `retired:<id>`로 바꿔 **자리를 놓게** 하고 다시 쓰이지 않게 한다
(PC는 `disabled = 1`, 서버 실행기는 `paused = 1`).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from chaeksas.center.migrations import DUPLICATE_HOSTS

#: 은퇴한 행이 쥐는 값의 머리 — 실제 키 id(`ck_…`)·기계 지문(64자 16진)과 겹칠 수 없다.
RETIRED = "retired:"

#: 표마다 id 칸과 「다시 쓰지 않게」 하는 칸.
_TABLES = {
    "bot_uis": ("bot_ui_id", "disabled"),
    "server_runners": ("server_runner_id", "paused"),
}


@dataclass(frozen=True)
class Duplicate:
    """겹친 무리의 행 하나 — 사람이 고를 거리를 함께 든다."""

    table: str
    column: str
    shared: str
    host_id: str
    name: str
    last_seen_at: str | None


class RepairError(RuntimeError):
    """고칠 수 없다 — 사람이 읽을 사유."""


def duplicates(conn: sqlite3.Connection) -> list[Duplicate]:
    """겹친 무리의 모든 행 (`migrations.DUPLICATE_HOSTS` — 3판의 지킴과 **같은 질의**다)."""
    out = []
    for table, column, shared, host_id in conn.execute(DUPLICATE_HOSTS).fetchall():
        id_column, _ = _TABLES[str(table)]
        row = conn.execute(
            f"SELECT name, last_seen_at FROM {table} WHERE {id_column} = ?",  # noqa: S608 — 표·칸은 위의 상수다
            (host_id,),
        ).fetchone()
        out.append(
            Duplicate(
                table=str(table),
                column=str(column),
                shared=str(shared),
                host_id=str(host_id),
                name=str(row[0]) if row else "",
                last_seen_at=str(row[1]) if row and row[1] else None,
            )
        )
    return out


def retire(conn: sqlite3.Connection, host_id: str) -> str:
    """그 행 하나를 은퇴시킨다. 어느 표였는지 돌려준다.

    **겹친 무리에 든 행만** 은퇴시킬 수 있다 — 멀쩡한 기계를 은퇴시키면 그 기계가 다시 등록할 때
    **새 id**를 받아 이력이 갈라진다.
    """
    found = next((one for one in duplicates(conn) if one.host_id == host_id), None)
    if found is None:
        raise RepairError(
            f"{host_id}는 겹친 무리에 없다 — 겹친 행만 은퇴시킬 수 있다 (`bpm-center hosts duplicates`)"
        )
    id_column, stop_column = _TABLES[found.table]
    tomb = f"{RETIRED}{host_id}"
    with conn:
        conn.execute(
            f"UPDATE {found.table} SET key_id = ?, machine_id = ?, {stop_column} = 1"  # noqa: S608 — 위와 같다
            f" WHERE {id_column} = ?",
            (tomb, tomb, host_id),
        )
    return found.table


def describe(found: list[Duplicate]) -> str:
    """사람이 읽을 목록 — 무리마다 묶어 이름·마지막으로 본 때를 보인다 (고를 거리)."""
    if not found:
        return "겹친 행이 없다 — Center를 띄우면 된다."
    lines = []
    last = None
    for one in found:
        group = (one.table, one.column, one.shared)
        if group != last:
            lines.append(f"\n{one.table}.{one.column} = {one.shared}")
            last = group
        lines.append(f"  {one.host_id}  「{one.name}」  마지막으로 본 때 {one.last_seen_at or '없음'}")
    lines.append("\n남길 행을 고르고 나머지를 `bpm-center hosts retire <id>`로 은퇴시키세요 (지우지 않는다).")
    return "\n".join(lines).lstrip("\n")


__all__ = ["RETIRED", "Duplicate", "RepairError", "describe", "duplicates", "retire"]
