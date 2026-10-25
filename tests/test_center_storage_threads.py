"""Center 저장소 하나를 여러 스레드가 함께 쓴다 — FastAPI 스레드 풀이 그렇게 부른다.

락이 없던 때 콘솔이 한 화면에서 여럿을 함께 읽으면 세션 찾기가 sqlite3
`InterfaceError: bad parameter or other API misuse`로 깨져 401·500이 났다.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from chaeksas.center.storage import Store


def test_many_threads_can_read_and_write_one_store(tmp_path: Path) -> None:
    store = Store(tmp_path / "center.db")
    with store.tx() as cur:
        cur.execute("CREATE TABLE t (n INTEGER)")

    def work(n: int) -> int:
        for _ in range(200):
            with store.tx() as cur:
                cur.execute("INSERT INTO t (n) VALUES (?)", (n,))
            found = store.row("SELECT count(*) AS c FROM t WHERE n = ?", (n,))
            assert found is not None
        return n

    with ThreadPoolExecutor(max_workers=16) as pool:
        assert sorted(pool.map(work, range(16))) == list(range(16))
    total = store.row("SELECT count(*) AS c FROM t")
    assert total is not None and total["c"] == 16 * 200
    store.close()
