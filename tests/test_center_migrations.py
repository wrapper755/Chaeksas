"""Center 저장소 옮기기 (`center.migrations`, ADR-0065).

`CREATE TABLE IF NOT EXISTS`는 있는 표를 고치지 않는다 — 그래서 판 번호와 단계로 옮긴다. 여기서
보는 것은 **수단이 약속한 넷**이다:

1. **옛 DB가 데이터째 옮겨진다** (이 결정 전에 만들어진 DB — 판 표가 없다).
2. **두 번 열어도, 둘이 동시에 열어도** 한 번만 옮긴다.
3. **중간에 실패하면 그 단계는 없던 일이 된다** (문과 판 기록이 한 트랜잭션이다).
4. **새 DB를 옛 코드가 열면 뜨지 않는다** (되돌리는 단계는 없다).

그리고 **기준선은 얼었다** — 바뀌면 「새로 만든 DB」와 「옮겨 온 DB」가 갈라진다.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path

import pytest

from chaeksas.center.migrations import (
    BASELINE,
    MIGRATIONS,
    MigrationError,
    Step,
    current,
    latest,
    migrate,
    statements_of,
)
from chaeksas.center.storage import SCHEMA, Store

#: 끝 판까지의 모든 판.
ALL = list(range(BASELINE, latest() + 1))

#: 얼린 기준선의 지문 — **SQL만** 본다(주석·공백은 빼고). 주석은 고쳐도 된다.
FROZEN_BASELINE = "d043c4e83144224b43c3a8a389fa98dea08cf9a4804c2dbbe14a70908d82d3f6"


def _normalized(script: str) -> str:
    sql = "\n".join(line.split("--", 1)[0] for line in script.splitlines())
    return " ".join(sql.split())


def _columns(db: Path, table: str) -> list[str]:
    with sqlite3.connect(db) as conn:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _versions(db: Path) -> list[int]:
    with sqlite3.connect(db) as conn:
        return [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]


def _old_center_db(db: Path) -> None:
    """**이 결정 전의 Center가 만든 DB** — 판 표가 없고 기준선 그대로이며 데이터가 있다."""
    with sqlite3.connect(db) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO deployment_results (bot_ui_id, deployment_id, bpm_process_id, version, result,"
            " reason, at) VALUES ('srv_0001', 'dep_00000001', 'fx.amount', '1.0.0', 'applied', NULL,"
            " '2026-10-16T00:00:00+00:00')"
        )


# ─────────────────────────── 얼린 기준선 ───────────────────────────


def test_the_baseline_is_frozen() -> None:
    """**기준선을 고치지 않는다** — 열·표·제약을 바꾸려면 `migrations.MIGRATIONS`에 단계를 더한다.

    기준선을 고치면 **새로 만든 DB는 새 모양, 옮겨 온 DB는 옛 모양**이 되어 갈라진다(옛 DB는
    기준선을 다시 돌지 않는다). 주석은 고쳐도 된다 — SQL만 본다.
    """
    digest = hashlib.sha256(_normalized(SCHEMA).encode("utf-8")).hexdigest()
    assert digest == FROZEN_BASELINE, (
        "storage.SCHEMA의 SQL이 바뀌었다 — 기준선은 얼었다(ADR-0065). "
        "바꿀 것은 migrations.MIGRATIONS에 새 단계로 더한다"
    )


def test_steps_count_up_from_two_without_gaps() -> None:
    assert [one.version for one in MIGRATIONS] == list(range(BASELINE + 1, BASELINE + 1 + len(MIGRATIONS)))
    assert latest() == MIGRATIONS[-1].version
    assert all(one.statements and one.about for one in MIGRATIONS)


# ─────────────────────────── 1. 옛 DB가 옮겨진다 ───────────────────────────


def test_a_new_database_ends_at_the_latest_version(tmp_path: Path) -> None:
    db = tmp_path / "center.sqlite3"
    Store(db).close()

    assert _versions(db) == list(range(BASELINE, latest() + 1))
    assert "host_id" in _columns(db, "deployment_results")
    assert "bot_ui_id" not in _columns(db, "deployment_results")


def test_an_old_database_is_moved_with_its_data(tmp_path: Path) -> None:
    """**이 결정 전에 만들어진 DB** — 판 표가 없다. 기준선을 다시 돌려 1판으로 적고 2판으로 간다.

    2판은 열 이름만 바꾸므로 **데이터가 그대로 새 이름 밑에** 있어야 한다.
    """
    db = tmp_path / "center.sqlite3"
    _old_center_db(db)
    assert "bot_ui_id" in _columns(db, "deployment_results")

    store = Store(db)
    try:
        row = store.row("SELECT host_id, deployment_id FROM deployment_results")
    finally:
        store.close()

    assert row is not None and row["host_id"] == "srv_0001" and row["deployment_id"] == "dep_00000001"
    assert _versions(db) == ALL


def test_a_new_and_a_moved_database_have_the_same_shape(tmp_path: Path) -> None:
    """**두 길이 갈라지지 않는다** — 새로 만든 것과 옛것을 옮긴 것의 표·열이 같다."""
    fresh, moved = tmp_path / "fresh.sqlite3", tmp_path / "moved.sqlite3"
    Store(fresh).close()
    _old_center_db(moved)
    Store(moved).close()

    def shape(db: Path) -> dict[str, list[str]]:
        with sqlite3.connect(db) as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: _columns(db, name) for name in tables}

    assert shape(fresh) == shape(moved)


# ─────────────────────────── 2. 한 번만 옮긴다 ───────────────────────────


def test_opening_twice_moves_once(tmp_path: Path) -> None:
    db = tmp_path / "center.sqlite3"
    Store(db).close()
    Store(db).close()
    assert _versions(db) == ALL


def test_two_centers_starting_together_move_once(tmp_path: Path) -> None:
    """**둘이 동시에 떠도** 한 쪽만 옮긴다 — 잠금을 잡은 뒤 판을 다시 읽기 때문이다.

    다시 읽지 않으면 둘째가 같은 판을 또 적으려다 기본키에 걸려 **Center가 뜨지 않는다**.
    """
    db = tmp_path / "center.sqlite3"
    start = threading.Barrier(4)
    errors: list[BaseException] = []

    def open_one() -> None:
        try:
            start.wait()
            Store(db).close()
        except BaseException as e:  # noqa: BLE001 — 시험이 모아서 본다
            errors.append(e)

    threads = [threading.Thread(target=open_one) for _ in range(4)]
    for one in threads:
        one.start()
    for one in threads:
        one.join(timeout=30)

    assert not errors, errors
    assert _versions(db) == ALL


# ─────────────────────────── 3. 중간 실패는 없던 일 ───────────────────────────


def test_a_failing_step_leaves_nothing_behind(tmp_path: Path) -> None:
    """**문과 판 기록이 한 트랜잭션**이다 — 둘째 문에서 터지면 첫째 문도 되돌아간다.

    그래서 다음에 뜰 때 **그 단계부터 다시** 돈다. 파이썬 `sqlite3`는 DDL 앞에서 트랜잭션을 열지
    않으므로 우리가 `BEGIN`을 적지 않으면 첫째 `CREATE`가 혼자 커밋돼 남는다.
    """
    db = tmp_path / "center.sqlite3"
    broken = (Step(2, "둘째 문이 틀렸다", ("CREATE TABLE half_done (x TEXT)", "THIS IS NOT SQL")),)
    conn = sqlite3.connect(db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            migrate(conn, baseline=SCHEMA, steps=broken)
        assert current(conn) == 1
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "half_done" not in tables, "첫째 문이 혼자 커밋됐다 — 트랜잭션이 깨졌다"

        fixed = (Step(2, "고쳤다", ("CREATE TABLE half_done (x TEXT)",)),)
        assert migrate(conn, baseline=SCHEMA, steps=fixed) == 2
    finally:
        conn.close()


def test_steps_with_a_gap_touch_nothing(tmp_path: Path) -> None:
    """판이 비면 **어떤 DB도 건드리기 전에** 멈춘다."""
    db = tmp_path / "center.sqlite3"
    conn = sqlite3.connect(db)
    try:
        with pytest.raises(MigrationError, match="판"):
            migrate(conn, baseline=SCHEMA, steps=(Step(3, "건너뛰었다", ("SELECT 1",)),))
        assert current(conn) == 0
    finally:
        conn.close()


# ─────────────────────────── 4. 앞으로만 간다 ───────────────────────────


def test_an_old_center_refuses_a_newer_database(tmp_path: Path) -> None:
    """**옛 Center가 새 DB를 열면 뜨지 않는다** — 모르는 열·표를 조용히 깨뜨리기 전에 멈춘다."""
    db = tmp_path / "center.sqlite3"
    Store(db).close()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO schema_migrations (version, about, applied_at) VALUES (?, '앞선 판', '2027-01-01')",
            (latest() + 1,),
        )

    with pytest.raises(MigrationError, match="새 판의 Center"):
        Store(db)


# ─────────────────────────── 문 나누기 ───────────────────────────


def test_statements_are_split_without_executescript() -> None:
    """`;`로 자르지 않는다 — 주석·문자열 안의 `;`에 속지 않는다."""
    found = statements_of(
        "-- 머리 주석; 여기서 자르면 안 된다\n"
        "CREATE TABLE a (x TEXT DEFAULT 'a;b');\n"
        "CREATE TABLE b (\n  y TEXT -- 꼬리; 주석\n);\n"
    )
    assert len(found) == 2
    assert found[0].endswith("DEFAULT 'a;b');")
    assert "CREATE TABLE b" in found[1]


def test_the_baseline_splits_into_its_tables() -> None:
    found = statements_of(SCHEMA)
    assert found and all(one.lstrip("-").strip() for one in found)
    assert sum("CREATE TABLE" in one for one in found) == len(found)


# ─────────────────────────── 3판 — 키 묶기를 DB도 지킨다 (ADR-0066) ───────────────────────────


def _host(conn: sqlite3.Connection, table: str, host_id: str, *, key: str, machine: str, name: str) -> None:
    """등록된 기계 행 하나 — **`host_keys`를 비켜 가서** 넣는다(겹친 옛 DB를 흉내 낸다)."""
    if table == "bot_uis":
        conn.execute(
            "INSERT INTO bot_uis (bot_ui_id, key_id, machine_id, name, os, versions_json, registered_at,"
            " last_seen_at) VALUES (?, ?, ?, ?, 'Windows 11', '{}', '2026-10-05T00:00:00+00:00', ?)",
            (host_id, key, machine, name, f"2026-10-0{len(name) % 9 + 1}T00:00:00+00:00"),
        )
    else:
        conn.execute(
            "INSERT INTO server_runners (server_runner_id, key_id, machine_id, name, os, versions_json,"
            " max_concurrency, registered_at) VALUES (?, ?, ?, ?, 'Linux', '{}', 10, '2026-10-05T00:00:00+00:00')",
            (host_id, key, machine, name),
        )


def _database_at_two_with(db: Path, *rows: tuple[str, str, str, str, str]) -> None:
    """**2판에 멈춘 DB**에 행을 넣는다 — 2026-10-08 전에 같은 PC가 두 줄로 남은 꼴."""
    conn = sqlite3.connect(db)
    try:
        migrate(conn, baseline=SCHEMA, steps=MIGRATIONS[:1])
        for table, host_id, key, machine, name in rows:
            _host(conn, table, host_id, key=key, machine=machine, name=name)
        conn.commit()
    finally:
        conn.close()


def test_a_key_or_a_machine_cannot_be_on_two_rows_any_more(tmp_path: Path) -> None:
    """**판정을 비켜 가는 새 코드**를 막는 마지막 울타리다 — 사람에게 할 말은 `host_keys`가 안다."""
    db = tmp_path / "center.sqlite3"
    Store(db).close()
    with sqlite3.connect(db) as conn:
        _host(conn, "bot_uis", "bui_00000001", key="ck_a", machine="m" * 64, name="구매 PC")
        with pytest.raises(sqlite3.IntegrityError):
            _host(conn, "bot_uis", "bui_00000002", key="ck_b", machine="m" * 64, name="다른 PC")
        with pytest.raises(sqlite3.IntegrityError):
            _host(conn, "bot_uis", "bui_00000003", key="ck_a", machine="n" * 64, name="다른 PC")


def test_duplicate_hosts_stop_the_step_and_say_what_to_do(tmp_path: Path) -> None:
    """**짐작해 고치지 않는다** (#57) — 겹친 행을 보이고 고치는 길을 말하고 멈춘다.

    문은 하나도 돌지 않는다 — DB는 2판에 그대로 남는다.
    """
    db = tmp_path / "center.sqlite3"
    _database_at_two_with(
        db,
        ("bot_uis", "bui_00000001", "ck_a", "m" * 64, "구매 PC"),
        ("bot_uis", "bui_00000002", "ck_b", "m" * 64, "구매 PC (옛 키)"),
    )

    with pytest.raises(MigrationError) as caught:
        Store(db)
    said = str(caught.value)
    assert "bui_00000001" in said and "bui_00000002" in said
    assert "bpm-center hosts" in said
    assert _versions(db) == [1, 2]


def test_the_person_picks_the_row_and_the_step_goes_through(tmp_path: Path) -> None:
    """**고르는 것은 사람**이고 도구는 은퇴시키기만 한다 — 지우지 않는다(이력이 그 id를 가리킨다)."""
    from chaeksas.center.repair import RETIRED, RepairError, duplicates, retire  # noqa: PLC0415

    db = tmp_path / "center.sqlite3"
    _database_at_two_with(
        db,
        ("bot_uis", "bui_00000001", "ck_a", "m" * 64, "구매 PC"),
        ("bot_uis", "bui_00000002", "ck_b", "m" * 64, "구매 PC (옛 키)"),
        ("bot_uis", "bui_00000003", "ck_c", "z" * 64, "멀쩡한 PC"),
    )
    conn = sqlite3.connect(db)
    try:
        found = duplicates(conn)
        assert {one.host_id for one in found} == {"bui_00000001", "bui_00000002"}
        assert all(one.name for one in found), "고를 거리(이름)가 없다"

        # **겹친 무리에 없는 행은 은퇴시키지 못한다** — 멀쩡한 PC의 이력이 갈라진다.
        with pytest.raises(RepairError):
            retire(conn, "bui_00000003")

        assert retire(conn, "bui_00000002") == "bot_uis"
        row = conn.execute(
            "SELECT key_id, machine_id, disabled FROM bot_uis WHERE bot_ui_id = 'bui_00000002'"
        ).fetchone()
        assert row == (f"{RETIRED}bui_00000002", f"{RETIRED}bui_00000002", 1)
        assert duplicates(conn) == []
    finally:
        conn.close()

    Store(db).close()
    assert _versions(db) == ALL


def test_a_server_runner_is_retired_by_pausing(tmp_path: Path) -> None:
    """서버 실행기에는 `disabled`가 없다 — **일시 중지**로 다시 쓰이지 않게 한다."""
    from chaeksas.center.repair import retire  # noqa: PLC0415

    db = tmp_path / "center.sqlite3"
    _database_at_two_with(
        db,
        ("server_runners", "srv_00000001", "ck_s", "s" * 64, "서버 1"),
        ("server_runners", "srv_00000002", "ck_s", "t" * 64, "서버 1 (다시 설치)"),
    )
    conn = sqlite3.connect(db)
    try:
        assert retire(conn, "srv_00000001") == "server_runners"
        paused = conn.execute("SELECT paused FROM server_runners WHERE server_runner_id = 'srv_00000001'")
        assert paused.fetchone() == (1,)
    finally:
        conn.close()
    Store(db).close()
    assert _versions(db) == ALL


def test_the_cli_does_not_open_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """**지킴에 걸린 DB에서도 돈다** — `Store`를 열면 옮기기가 돌아 그 지킴에 다시 걸린다."""
    from chaeksas.center.__main__ import hosts  # noqa: PLC0415

    db = tmp_path / "center.sqlite3"
    _database_at_two_with(
        db,
        ("bot_uis", "bui_00000001", "ck_a", "m" * 64, "구매 PC"),
        ("bot_uis", "bui_00000002", "ck_b", "m" * 64, "구매 PC (옛 키)"),
    )
    monkeypatch.setenv("BPM_CENTER__DB_PATH", str(db))

    assert hosts(["duplicates"]) == 0
    listed = capsys.readouterr().out
    assert "bui_00000001" in listed and "「구매 PC (옛 키)」" in listed

    assert hosts(["retire", "bui_00000002"]) == 0
    assert "겹친 행이 없다" in capsys.readouterr().out
    assert hosts(["retire", "bui_00000001"]) == 2  # 이제 겹치지 않는다 — 은퇴시킬 수 없다
