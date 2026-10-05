"""UI 자동화 앱의 저장소 — SQLite (C9·C11).

레지스트리는 **문서 묶음**이라 표를 잘게 나누지 않고 화면 하나를 JSON 한 덩이로 둔다. 성적
(`LocatorStats`)만 따로 둔다 — 보고마다 갱신되기 때문이다 (C8).

- 표준 라이브러리 `sqlite3`만 쓴다. SQL은 PostgreSQL에서도 통하는 모양으로 적는다 (C7과 같은
  이유).
- **키는 해시만** 저장한다 (C11 — 원문은 발급할 때 한 번 보이고 끝이다).
- 비밀·업무 값은 들어오지 않는다. 들어오는 것은 셀렉터와 통계다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from chaeksas.contracts.service_app import ServiceAppKey
from chaeksas.ext.ui_automation.contracts.registry import LocatorStats, PageRegistration

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
  page_id    TEXT PRIMARY KEY,
  page_json  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS locator_stats (
  page_id      TEXT NOT NULL,
  semantic_key TEXT NOT NULL,
  locator_key  TEXT NOT NULL,
  stats_json   TEXT NOT NULL,
  PRIMARY KEY (page_id, semantic_key, locator_key)
);
CREATE TABLE IF NOT EXISTS app_keys (
  key_hash   TEXT PRIMARY KEY,
  key_json   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
  name  TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


@dataclass
class Database:
    """파일 하나. 없으면 만든다."""

    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        found = sqlite3.connect(self.path, isolation_level=None)
        found.row_factory = sqlite3.Row
        try:
            yield found
            found.commit()
        finally:
            found.close()


@dataclass
class SqliteKeyStore:
    """`service_kit.KeyStore` — **해시만** 들고 있는다 (C11)."""

    db: Database

    def all_keys(self) -> Iterator[ServiceAppKey]:
        with self.db.connect() as found:
            rows = found.execute("SELECT key_json FROM app_keys").fetchall()
        for row in rows:
            yield ServiceAppKey.model_validate_json(row["key_json"])

    def add(self, key: ServiceAppKey) -> None:
        self._put(key)

    def touch(self, key: ServiceAppKey, *, at: str) -> None:
        self._put(key.model_copy(update={"last_used_at": at}))

    def revoke(self, key: ServiceAppKey, *, at: str) -> None:
        """**지우지 않는다** — 사용 기록이 이름을 가리킨다 (C11)."""
        self._put(key.model_copy(update={"revoked_at": at}))

    def _put(self, key: ServiceAppKey) -> None:
        with self.db.connect() as found:
            found.execute(
                "INSERT INTO app_keys (key_hash, key_json) VALUES (?, ?) "
                "ON CONFLICT (key_hash) DO UPDATE SET key_json = excluded.key_json",
                (key.hash, key.model_dump_json()),
            )


@dataclass
class RegistryStore:
    """레지스트리를 디스크에 둔다. `Registry`는 메모리에서 돌고, 바뀐 것만 여기 쓴다."""

    db: Database

    def load(self) -> tuple[dict[str, PageRegistration], dict[tuple[str, str, str], LocatorStats], int]:
        with self.db.connect() as found:
            pages = {
                row["page_id"]: PageRegistration.model_validate_json(row["page_json"])
                for row in found.execute("SELECT page_id, page_json FROM pages").fetchall()
            }
            stats = {
                (row["page_id"], row["semantic_key"], row["locator_key"]): LocatorStats.model_validate_json(
                    row["stats_json"]
                )
                for row in found.execute(
                    "SELECT page_id, semantic_key, locator_key, stats_json FROM locator_stats"
                ).fetchall()
            }
            row = found.execute("SELECT value FROM meta WHERE name = 'revision'").fetchone()
        return pages, stats, int(row["value"]) if row else 1

    def save(
        self,
        pages: dict[str, PageRegistration],
        stats: dict[tuple[str, str, str], LocatorStats],
        revision: int,
    ) -> None:
        """통째로 다시 쓴다 — 레지스트리는 작고(화면 수십 개) 쓰기는 드물다 (등록·보고)."""
        with self.db.connect() as found:
            found.execute("DELETE FROM pages")
            found.executemany(
                "INSERT INTO pages (page_id, page_json) VALUES (?, ?)",
                [(page_id, page.model_dump_json()) for page_id, page in pages.items()],
            )
            found.execute("DELETE FROM locator_stats")
            found.executemany(
                "INSERT INTO locator_stats (page_id, semantic_key, locator_key, stats_json) "
                "VALUES (?, ?, ?, ?)",
                [(*key, value.model_dump_json()) for key, value in stats.items()],
            )
            found.execute(
                "INSERT INTO meta (name, value) VALUES ('revision', ?) "
                "ON CONFLICT (name) DO UPDATE SET value = excluded.value",
                (str(revision),),
            )


__all__ = ["SCHEMA", "Database", "RegistryStore", "SqliteKeyStore"]
