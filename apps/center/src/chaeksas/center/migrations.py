"""Center 저장소를 옮기는 단계 ([ADR-0065](../../../../../docs/decisions/0065-center-schema-migrations.md)).

`CREATE TABLE IF NOT EXISTS`는 **없는 표를 만들 뿐 있는 표를 고치지 않는다** — 그래서 돌던
Center에 열을 더하거나 이름을 바꿀 길이 없었다. 여기서 판 번호를 쥐고 모자란 단계만 돌린다.

규칙 넷:

1. **기준선(`storage.SCHEMA`)은 1판이고 얼었다.** 표를 더하는 것도 여기 단계로 한다 —
   기준선을 고치면 「새로 만든 DB」와 「옮겨 온 DB」가 다른 모양이 된다 (시험이 지킨다).
2. **앞으로만 간다.** 되돌리는 단계는 없고, DB 판이 코드보다 높으면 **뜨지 않는다**.
3. **단계 하나 = 트랜잭션 하나** (그 판의 기록과 함께). `BEGIN IMMEDIATE`로 잠금을 잡고 판을
   **다시 읽는다** — Center 둘이 동시에 떠도 한 쪽만 옮긴다.
4. 단계는 **SQL 문 목록**이다. `executescript`를 쓰지 않는다 — 파이썬 `sqlite3`의
   `executescript`는 먼저 커밋해 버려 트랜잭션이 깨진다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

log = logging.getLogger(__name__)

#: 판 기록 표. **이 표만은 단계가 아니다** — 판을 읽으려면 먼저 있어야 한다.
VERSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     INTEGER PRIMARY KEY,
  about       TEXT NOT NULL,
  applied_at  TEXT NOT NULL
)
"""

#: 기준선의 판 (`storage.SCHEMA`).
BASELINE = 1


@dataclass(frozen=True)
class Step:
    """옮기는 걸음 하나. `statements`는 **한 트랜잭션**에서 차례로 돈다."""

    version: int
    about: str
    statements: tuple[str, ...]


#: **더하기만 한다.** 지우거나 고치지 않는다 — 이미 이 단계를 지난 DB가 있다. 잘못 간 단계는
#: 새 단계로 바로잡는다. 판은 2부터 빈틈 없이 오른다 (시험이 본다).
MIGRATIONS: tuple[Step, ...] = (
    Step(
        2,
        "deployment_results.bot_ui_id → host_id (PC와 서버 실행기를 함께 담는다, C4·C12)",
        ("ALTER TABLE deployment_results RENAME COLUMN bot_ui_id TO host_id",),
    ),
)


class MigrationError(RuntimeError):
    """저장소를 옮길 수 없다 — Center를 띄우지 않는다."""


def latest(steps: Sequence[Step] = MIGRATIONS) -> int:
    """이 코드가 아는 가장 높은 판."""
    return max((one.version for one in steps), default=BASELINE)


def current(conn: sqlite3.Connection) -> int:
    """DB의 판. **판 표가 없으면 0**이다 (새 DB이거나 이 결정 전에 만들어진 DB)."""
    found = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if found is None:
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def statements_of(script: str) -> list[str]:
    """여러 문이 든 글을 문 하나씩으로 — **`executescript` 없이** 트랜잭션 안에서 돌리려고.

    `;`로 자르지 않고 `sqlite3.complete_statement`로 판단한다 (주석·문자열 안의 `;`에 속지 않는다).
    """
    out: list[str] = []
    pending: list[str] = []
    for line in script.splitlines():
        pending.append(line)
        text = "\n".join(pending).strip()
        if text and sqlite3.complete_statement(text):
            out.append(text)
            pending = []
    rest = "\n".join(pending).strip()
    if rest and any(line.strip() and not line.strip().startswith("--") for line in pending):
        raise MigrationError(f"끝나지 않은 SQL 문이 있다: {rest[:80]}")
    return out


def migrate(
    conn: sqlite3.Connection,
    *,
    baseline: str,
    steps: Sequence[Step] = MIGRATIONS,
    now: str | None = None,
) -> int:
    """모자란 단계를 차례로 돌린다. 끝난 판을 돌려준다.

    **연결의 자동 트랜잭션을 잠시 끈다** — 파이썬 `sqlite3`는 DDL 앞에서 트랜잭션을 열지 않아
    `ALTER`가 혼자 커밋된다. `BEGIN IMMEDIATE`·`COMMIT`을 우리가 적는다.
    """
    _check_steps(steps)
    known = latest(steps)
    saved = conn.isolation_level
    conn.isolation_level = None
    try:
        found = current(conn)
        if found > known:
            # **옛 Center가 새 DB를 열었다.** 모르는 열·표를 조용히 깨뜨리기 전에 멈춘다.
            raise MigrationError(
                f"저장소 판이 {found}인데 이 Center는 {known}판까지만 안다 — "
                "새 판의 Center로 띄우세요 (되돌리는 단계는 없다, ADR-0065)"
            )
        _apply(conn, BASELINE, "기준선 (storage.SCHEMA)", statements_of(baseline), now)
        for one in steps:
            _apply(conn, one.version, one.about, list(one.statements), now)
        return current(conn)
    finally:
        conn.isolation_level = saved


def _apply(
    conn: sqlite3.Connection,
    version: int,
    about: str,
    statements: Sequence[str],
    now: str | None,
) -> None:
    """한 판을 **한 트랜잭션**에 — 그 판의 기록과 함께. 이미 있으면 지나간다."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(VERSIONS_TABLE)
        # **잠금을 잡은 뒤에 다시 읽는다** — 그 사이 다른 Center가 옮겼을 수 있다.
        at = current(conn)
        if at >= version:
            conn.execute("ROLLBACK")
            return
        if at != version - 1:  # pragma: no cover — `_check_steps`가 먼저 막는다
            raise MigrationError(f"{version}판 앞에 {at + 1}판이 없다")
        for sql in statements:
            conn.execute(sql)
        conn.execute(
            "INSERT INTO schema_migrations (version, about, applied_at) VALUES (?, ?, ?)",
            (version, about, now or datetime.now(UTC).isoformat()),
        )
        conn.execute("COMMIT")
        # **운영자가 「어느 판으로 갔나」를 본다** — 올린 뒤 처음 뜰 때만 찍힌다.
        log.info("저장소를 %d판으로 옮겼다: %s", version, about)
    except BaseException:
        # **기록과 문이 함께 되돌아간다** — 다음에 뜰 때 이 판부터 다시 돈다.
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def _check_steps(steps: Sequence[Step]) -> None:
    """판이 2부터 빈틈 없이 오르는가 — 틀리면 **어떤 DB도 건드리기 전에** 멈춘다."""
    wanted = list(range(BASELINE + 1, BASELINE + 1 + len(steps)))
    got = [one.version for one in steps]
    if got != wanted:
        raise MigrationError(f"단계의 판이 {wanted}이어야 하는데 {got}이다")
    for one in steps:
        if not one.statements:
            raise MigrationError(f"{one.version}판에 문이 없다")


__all__ = [
    "BASELINE",
    "MIGRATIONS",
    "VERSIONS_TABLE",
    "MigrationError",
    "Step",
    "current",
    "latest",
    "migrate",
    "statements_of",
]
