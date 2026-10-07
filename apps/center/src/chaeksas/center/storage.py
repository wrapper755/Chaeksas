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
  -- `key_id`·`machine_id`는 둘 다 한 행에만 있다 (C4 「키 묶기」). UNIQUE를 걸지 않은 것은
  -- `CREATE TABLE IF NOT EXISTS`가 이미 만들어진 DB를 고치지 않아서다 (옮기기 수단이 없다) —
  -- 지키는 것은 `api/bot_ui.py`의 `register`다.
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
CREATE TABLE IF NOT EXISTS jobs (
  job_id           TEXT PRIMARY KEY,
  bpm_process_id   TEXT NOT NULL,
  version          TEXT,
  target_type      TEXT NOT NULL,
  target_id        TEXT,
  inputs_json      TEXT NOT NULL,
  expires_at       TEXT,
  note             TEXT,
  -- 멱등 키의 범위이자 「자기 것」 판정 기준 (C5 — 부른 쪽 키 또는 행위자마다 따로).
  owner            TEXT NOT NULL,
  idempotency_key  TEXT,
  body_hash        TEXT NOT NULL,
  requested_by     TEXT NOT NULL,
  requested_at     TEXT NOT NULL,
  state            TEXT NOT NULL,
  state_reason     TEXT,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  cancel_result    TEXT,
  queue_position   INTEGER,
  dispatched_at    TEXT,
  run_id           TEXT,
  run_status       TEXT,
  -- 실행하는 쪽이 마지막 말을 했다 — 더 내려보내지도, 맞추기(C4)로 건드리지도 않는다.
  settled          INTEGER NOT NULL DEFAULT 0,
  -- 맞추기 규칙: 하트비트에 연속으로 보이지 않은 횟수 (C4 `bot_ui_lost`).
  misses           INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS approvals (
  request_id       TEXT PRIMARY KEY,
  -- 올린 키. **답은 이 키에게만** 내려간다 (C6 §소유).
  owner_key_id     TEXT NOT NULL,
  host_type        TEXT NOT NULL,
  host_id          TEXT NOT NULL,
  run_id           TEXT NOT NULL,
  node_id          TEXT NOT NULL,
  node_instance    INTEGER NOT NULL,
  bpm_process_id   TEXT NOT NULL,
  version          TEXT NOT NULL,
  title            TEXT,
  description      TEXT,
  form_json        TEXT,
  -- 업무 값이다 (원칙 6의 예외) — 끝난 뒤 VALUE_RETENTION_DAYS가 지나면 지운다.
  review_json      TEXT,
  answer_json      TEXT,
  expires_at       TEXT,
  body_hash        TEXT NOT NULL,
  created_at       TEXT NOT NULL,
  state            TEXT NOT NULL,
  answered_by      TEXT,
  answered_at      TEXT,
  withdraw_reason  TEXT,
  delivered        INTEGER NOT NULL DEFAULT 0,
  delivery_accepted INTEGER,
  delivery_reason  TEXT,
  -- 값을 지운 시각. 지운 뒤에도 누가·언제·결과는 남는다 (C6).
  values_purged_at TEXT
);
CREATE TABLE IF NOT EXISTS deployment_results (
  -- 배치 결정은 하트비트 한 주기만 올라온다 (C4). 흘려보내면 「왜 설치가 안 됐나」가
  -- 영영 남지 않아서 쌓아 둔다 (CON-03 「최근 배치 결정」).
  bot_ui_id      TEXT NOT NULL,
  deployment_id  TEXT NOT NULL,
  bpm_process_id TEXT NOT NULL,
  version        TEXT NOT NULL,
  result         TEXT NOT NULL,
  reason         TEXT,
  at             TEXT NOT NULL,
  PRIMARY KEY (bot_ui_id, deployment_id, at)
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
