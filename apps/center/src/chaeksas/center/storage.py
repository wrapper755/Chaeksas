"""Center 저장소 — SQLite (01-architecture §7).

**DB에는 메타데이터만** 둔다. 패키지 zip은 파일 저장소에, 비밀(서비스 앱 키)은 아예 두지 않는다
(ADR-0013). Center API 키도 **해시만** 저장한다 (C7).

표준 라이브러리 `sqlite3`만 쓴다. SQL을 PostgreSQL에서도 통하는 모양으로 적어 둔다 (C7이
「SQLite로 시작, PostgreSQL 호환」이라고 적었다) — 그래서 SQLite 전용 문법은 피한다.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS center_keys (
  key_id      TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  type        TEXT NOT NULL,
  prefix      TEXT NOT NULL,
  key_hash    TEXT NOT NULL UNIQUE,
  created_at  TEXT NOT NULL,
  expires_at  TEXT,
  last_used_at TEXT,
  revoked_at  TEXT,
  bound_json  TEXT
);
CREATE TABLE IF NOT EXISTS bot_uis (
  bot_ui_id   TEXT PRIMARY KEY,
  key_id      TEXT NOT NULL,
  machine_id  TEXT NOT NULL,
  name        TEXT NOT NULL,
  os          TEXT NOT NULL,
  versions_json TEXT NOT NULL,
  runtimes_json TEXT,
  registered_at TEXT NOT NULL,
  last_seen_at  TEXT,
  disabled    INTEGER NOT NULL DEFAULT 0,
  state_json  TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  run_id        TEXT PRIMARY KEY,
  owner_key_id  TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL,
  summary_json  TEXT
);
CREATE TABLE IF NOT EXISTS run_events (
  run_id    TEXT NOT NULL,
  seq       INTEGER NOT NULL,
  ts        TEXT NOT NULL,
  kind      TEXT NOT NULL,
  node_id   TEXT,
  data_json TEXT,
  PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS deployments (
  deployment_id  TEXT PRIMARY KEY,
  target_type    TEXT NOT NULL,
  target_id      TEXT NOT NULL,
  bpm_process_id TEXT NOT NULL,
  version        TEXT NOT NULL,
  content_hash   TEXT NOT NULL,
  -- 봉투는 **저장된 JSON 그대로** 내려 준다 (재직렬화하면 서명이 깨진다, C4).
  envelope_json  TEXT NOT NULL,
  revoked_json   TEXT,
  at             TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_keys (
  key_id        TEXT PRIMARY KEY,
  key_json      TEXT NOT NULL,
  -- 받은 봉투를 **그대로** 둔다 (감사 추적). 부트스트랩 키는 봉투가 없다.
  envelope_json TEXT,
  at            TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS packages (
  id          TEXT NOT NULL,
  version     TEXT NOT NULL,
  kind        TEXT NOT NULL,
  name        TEXT,
  status      TEXT NOT NULL,
  run_location TEXT,
  content_hash TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  file_name   TEXT NOT NULL,
  size_bytes  INTEGER NOT NULL,
  uploaded_at TEXT NOT NULL,
  uploaded_by TEXT NOT NULL,
  -- 승인·철회 봉투 (C2). 내려줄 때 zip의 `SIGNATURE`로 넣는다.
  signature_json TEXT,
  revoke_json TEXT,
  PRIMARY KEY (id, version)
);
"""


def now_iso() -> str:
    """지금 (ISO 8601 + 시간대). 계약의 `Timestamp`는 시간대를 요구한다."""
    return datetime.now(UTC).isoformat()


class Store:
    """Center의 저장소 하나. 스레드마다 연결을 따로 쓴다 (FastAPI는 스레드 풀에서 돈다)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        if str(db_path) != ":memory:":
            db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False + 연결마다 락: 작은 규모에서 가장 단순하다.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self.tx() as cur:
            cur.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Cursor]:
        """트랜잭션 하나. 예외가 나면 되돌린다."""
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cur.close()

    def rows(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        cur = self._conn.execute(sql, params)
        try:
            return cur.fetchall()
        finally:
            cur.close()

    def row(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        found = self.rows(sql, params)
        return found[0] if found else None


def loads(raw: str | None, default: Any = None) -> Any:
    """저장된 JSON 칸을 읽는다 (비어 있으면 기본값)."""
    if not raw:
        return default
    return json.loads(raw)


def dumps(value: Any) -> str:
    """JSON 칸에 넣을 모양. 한글을 그대로 둔다 (읽을 수 있게)."""
    return json.dumps(value, ensure_ascii=False)
