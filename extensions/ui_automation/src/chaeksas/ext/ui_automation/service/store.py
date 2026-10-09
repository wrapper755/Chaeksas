"""UI 자동화 앱의 저장소 — SQLite (C9·C11).

레지스트리는 **문서 묶음**이라 표를 잘게 나누지 않고 화면 하나를 JSON 한 덩이로 둔다. 성적
(`LocatorStats`)만 따로 둔다 — 보고마다 갱신되기 때문이다 (C8).

- 표준 라이브러리 `sqlite3`만 쓴다. SQL은 PostgreSQL에서도 통하는 모양으로 적는다 (C7과 같은
  이유).
- **키는 해시만** 저장한다 (C11 — 원문은 발급할 때 한 번 보이고 끝이다).
- 비밀·업무 값은 들어오지 않는다. 들어오는 것은 셀렉터와 통계다.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from chaeksas.contracts.service_app import ServiceAppKey
from chaeksas.ext.ui_automation.contracts.console import FallbackSpread, SessionCounts, SessionRow
from chaeksas.ext.ui_automation.contracts.plan import (
    ORIGIN_TEST,
    STATUS_ESCALATED,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    SessionReport,
)
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
CREATE TABLE IF NOT EXISTS sessions (
  business_key   TEXT PRIMARY KEY,
  at             TEXT NOT NULL,
  page_id        TEXT NOT NULL,
  origin         TEXT NOT NULL,
  status         TEXT NOT NULL,
  healed         INTEGER NOT NULL DEFAULT 0,
  caller         TEXT NOT NULL DEFAULT '',
  mode           TEXT NOT NULL DEFAULT '',
  bpm_process_id TEXT,
  host           TEXT,
  report_json    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_at ON sessions (at DESC);
CREATE TABLE IF NOT EXISTS meta (
  name  TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

#: 세션 기록을 몇 줄까지 들고 있을까 (UIA-01·03). 넘으면 **오래된 것부터 버린다** —
#: 모니터링 자료라 영원히 쌓을 이유가 없고, 지우는 쪽이 커지는 쪽보다 안전하다 (C9).
MAX_SESSIONS = 5000

#: 뒤에 더한 열 — 이미 있는 파일에는 `ALTER TABLE`로 넣는다 (`(표, 열, 타입)`).
LATER_COLUMNS = (
    ("sessions", "caller", "TEXT NOT NULL DEFAULT ''"),
    ("sessions", "mode", "TEXT NOT NULL DEFAULT ''"),
    ("sessions", "bpm_process_id", "TEXT"),
    ("sessions", "host", "TEXT"),
)


@dataclass
class Database:
    """파일 하나. 없으면 만든다."""

    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
            self._add_missing_columns(db)

    @staticmethod
    def _add_missing_columns(db: sqlite3.Connection) -> None:
        """이미 있는 파일에 **열만 더한다** (`CREATE TABLE IF NOT EXISTS`는 못 하는 일).

        앱은 같은 파일을 계속 쓰므로, 열을 더할 때 기존 기록을 버리지 않는다. 더한 열은
        비어 있고(기본값), 화면은 그것을 「—」로 보인다.
        """
        for table, column, kind in LATER_COLUMNS:
            known = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in known:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")

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


@dataclass
class SessionStore:
    """UI 세션 기록 (C8 보고 → UIA-01 「최근 UI 세션」·UIA-03).

    **보고가 도착한 것만** 들어온다 — 세션이 끝날 때 한 번이다 (도는 세션은 모른다).
    집계에 쓰는 칸은 열로 빼 두고(세는 데 JSON을 다 풀지 않게) 본문은 그대로 둔다.

    **업무 값은 없다** — C8 `SessionReport`가 읽은 값·입력한 글자를 담지 않는다 (원칙 6).
    같은 `business_key`가 다시 오면 **나중 것이 이긴다** (재시도는 `attempt`가 달라 다른 키다).
    """

    db: Database

    def record(
        self,
        report: SessionReport,
        *,
        at: str,
        caller: str = "",
        mode: str = "",
        bpm_process_id: str | None = None,
        host: str | None = None,
    ) -> None:
        """보고 한 줄. `caller`·`mode`·`bpm_process_id`·`host`는 **봉투가 말해 준 것**이다
        (C11 `OpRequest.caller`·`mode`) — C8 보고 자체에는 없다."""
        with self.db.connect() as found:
            found.execute(
                "INSERT INTO sessions (business_key, at, page_id, origin, status, healed, "
                "caller, mode, bpm_process_id, host, report_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (business_key) DO UPDATE SET at = excluded.at, page_id = excluded.page_id, "
                "origin = excluded.origin, status = excluded.status, healed = excluded.healed, "
                "caller = excluded.caller, mode = excluded.mode, "
                "bpm_process_id = excluded.bpm_process_id, host = excluded.host, "
                "report_json = excluded.report_json",
                (
                    report.business_key,
                    at,
                    report.page_id,
                    report.origin,
                    report.status,
                    1 if report.healed else 0,
                    caller,
                    mode,
                    bpm_process_id,
                    host,
                    report.model_dump_json(),
                ),
            )
            # 오래된 것부터 버린다 (`MAX_SESSIONS`).
            found.execute(
                "DELETE FROM sessions WHERE business_key IN ("
                "  SELECT business_key FROM sessions ORDER BY at DESC LIMIT -1 OFFSET ?"
                ")",
                (MAX_SESSIONS,),
            )

    def counts(self, *, today: str) -> SessionCounts:
        """UIA-01 「최근 UI 세션」·UIA-03 요약. `today`는 `YYYY-MM-DD`(앱 서버 기준)다.

        **시험 보고는 따로 센다** — 운영 통계를 흔들지 않는다 (C8 `origin: test`).
        """
        with self.db.connect() as found:
            rows = found.execute(
                "SELECT origin, status, healed, substr(at, 1, 10) AS day FROM sessions"
            ).fetchall()
        made = SessionCounts()
        for row in rows:
            if row["origin"] == ORIGIN_TEST:
                made.test += 1
                continue
            made.total += 1
            if row["status"] == STATUS_SUCCEEDED:
                made.succeeded += 1
            elif row["status"] == STATUS_ESCALATED:
                made.escalated += 1
            elif row["status"] == STATUS_FAILED:
                made.failed += 1
            if row["healed"]:
                made.healed += 1
            if row["day"] == today:
                made.today += 1
        return made

    def recent(self, *, limit: int = 100) -> list[SessionReport]:
        """최근 보고부터 (UIA-03 「UI 세션 이력」). **시험도 들어간다** — 거르는 것은 화면이다."""
        with self.db.connect() as found:
            rows = found.execute(
                "SELECT report_json FROM sessions ORDER BY at DESC LIMIT ?", (max(limit, 0),)
            ).fetchall()
        return [SessionReport.model_validate_json(row["report_json"]) for row in rows]

    def rows(self, *, limit: int = 100) -> list[SessionRow]:
        """최근 보고부터, **봉투가 말해 준 것까지** (UIA-03 표의 열이 다 여기 있다)."""
        with self.db.connect() as found:
            rows = found.execute(
                "SELECT at, caller, mode, bpm_process_id, host, report_json FROM sessions "
                "ORDER BY at DESC LIMIT ?",
                (max(limit, 0),),
            ).fetchall()
        return [
            SessionRow(
                schema=1,
                at=row["at"],
                caller=row["caller"] or "",
                mode=row["mode"] or "",
                bpm_process_id=row["bpm_process_id"],
                host=row["host"],
                report=json.loads(row["report_json"]),
            )
            for row in rows
        ]

    def healed_marks(self, page_id: str) -> dict[str, list[str]]:
        """그 화면에서 **치유가 더한 로케이터**와 그것이 밀어낸 것들 (UIA-02).

        레지스트리에는 「치유로 들어왔다」는 표시가 없어서 **보고에서** 모은다 (C8
        `healed[].locator`·`supersedes`). 나중 보고가 적은 것이 이긴다.
        """
        out: dict[str, list[str]] = {}
        with self.db.connect() as found:
            rows = found.execute(
                "SELECT report_json FROM sessions WHERE page_id = ? ORDER BY at ASC", (page_id,)
            ).fetchall()
        for row in rows:
            for one in SessionReport.model_validate_json(row["report_json"]).healed:
                out[one.locator.key] = list(one.supersedes)
        return out

    def fallback(self, *, limit: int = MAX_SESSIONS) -> FallbackSpread:
        """「폴백 깊이 분포」 (UIA-03) — 요소 하나를 찾기까지 사다리를 몇 칸 내려갔나.

        `attempts`를 **요소별로 차례대로** 세어, 성공한 시도까지 실패한 횟수를 깊이로 본다.
        **성공한 요소만** 센다 (끝까지 실패한 것은 깊이가 아니라 전환·실패다). 시험 보고는
        빼지 않는다 — 분포를 보는 화면이고 승격 통계가 아니다.
        """
        made = FallbackSpread()
        for report in self.recent(limit=limit):
            depth: dict[str, int] = {}
            for attempt in report.attempts:
                key = attempt.semantic_key
                if attempt.succeeded:
                    made.depths[str(depth.get(key, 0))] = made.depths.get(str(depth.get(key, 0)), 0) + 1
                    made.counted += 1
                    if depth.get(key, 0) == 0:
                        made.first_hit += 1
                    depth[key] = 0
                    continue
                depth[key] = depth.get(key, 0) + 1
        return made


__all__ = [
    "LATER_COLUMNS",
    "MAX_SESSIONS",
    "SCHEMA",
    "Database",
    "RegistryStore",
    "SessionStore",
    "SqliteKeyStore",
]
