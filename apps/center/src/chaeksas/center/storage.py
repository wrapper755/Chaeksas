"""Center 저장소 — SQLite (01-architecture §7).

**DB에는 메타데이터만** 둔다. 패키지 zip은 파일 저장소에, 비밀(서비스 앱 키)은 아예 두지 않는다
(ADR-0013). Center API 키도 **해시만** 저장한다 (C7).

표준 라이브러리 `sqlite3`만 쓴다. SQL을 PostgreSQL에서도 통하는 모양으로 적어 둔다 (C7이
「SQLite로 시작, PostgreSQL 호환」이라고 적었다) — 그래서 SQLite 전용 문법은 피한다.

**표를 고치는 길은 `migrations.py`다** ([ADR-0065](../../../../../docs/decisions/0065-center-schema-migrations.md)).
아래 `SCHEMA`는 **1판 기준선이고 얼었다** — 열·표·제약을 더하거나 이름을 바꾸는 것은 거기
단계로 더한다. 여기를 고치면 「새로 만든 DB」와 「옮겨 온 DB」가 다른 모양이 된다(시험이 막는다).
**주석은 고쳐도 된다** — 시험은 SQL만 본다.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chaeksas.center.migrations import migrate

#: **1판 기준선 — 얼었다** (ADR-0065). 바꿀 것은 `migrations.MIGRATIONS`에 단계로 더한다.
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
  -- `key_id`·`machine_id`는 둘 다 한 행에만 있다 (C4 「키 묶기」). 판정은 `host_keys.py`가 하고
  -- **3판 단계가 UNIQUE 색인을 건다**(ADR-0066 — 겹친 옛 행은 사람이 고른다).
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
CREATE TABLE IF NOT EXISTS server_runners (
  server_runner_id TEXT PRIMARY KEY,
  -- `bot_uis`와 **같은 묶기 규칙**이다 (C12 「키 묶기는 C4와 같다」) — 판정은
  -- `center/host_keys.py` 하나이고 UNIQUE 색인도 같은 3판 단계가 건다 (ADR-0066).
  key_id        TEXT NOT NULL,
  machine_id    TEXT NOT NULL,
  name          TEXT NOT NULL,
  os            TEXT NOT NULL,
  versions_json TEXT NOT NULL,
  -- 실행기가 설정값으로 정한 동시 실행 상한 (C12 `max_concurrency`, 기본 10).
  max_concurrency INTEGER NOT NULL,
  extensions_json TEXT,
  registered_at TEXT NOT NULL,
  last_seen_at  TEXT,
  -- CON-12 「일시 중지」. 켜 두면 **새 작업을 받지 않고** 도는 것은 끝까지 간다 (C12).
  paused        INTEGER NOT NULL DEFAULT 0,
  -- 운영자가 「유실 처리」한 시각 (C12 — 오프라인인 실행기만). 비어 있으면 멀쩡하다.
  lost_at       TEXT,
  state_json    TEXT
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
CREATE TABLE IF NOT EXISTS messages (
  -- 외부 시스템이 넣은 메시지 (C12 §메시지). **작업 표와 따로 둔다** — 메시지 시작으로 온
  -- 것은 작업이 되지만(`job_id`), 기다리는 실행으로 가는 것은 작업이 아니다.
  message_id       TEXT PRIMARY KEY,
  name             TEXT NOT NULL,
  -- 상관 키는 **아무 JSON 값**이다 (주문 번호 글자일 수도, 수일 수도 있다) — 그래서 JSON으로
  -- 담고 비교도 JSON 글로 한다. 없으면 NULL이고 그때는 메시지 시작만이다.
  correlation_json TEXT,
  -- 업무 값이다 (원칙 6의 예외 — 받는 실행에 넣어야 한다). 작업의 `inputs`와 같은 결이다.
  payload_json     TEXT NOT NULL,
  -- 멱등 키의 범위이자 「자기 것」 판정 기준 (C5와 같다).
  owner            TEXT NOT NULL,
  idempotency_key  TEXT,
  body_hash        TEXT NOT NULL,
  received_at      TEXT NOT NULL,
  received_by      TEXT NOT NULL,
  delivered_to     TEXT NOT NULL,
  -- 「실행으로」 갈 때만 채운다. `runner_id`는 **그 실행을 보고한 실행기**다 (한 실행은 시작한
  -- 실행기에 끝까지 머문다 — C12 §Center가 작업을 나누는 규칙 4).
  run_id           TEXT,
  runner_id        TEXT,
  job_id           TEXT,
  -- pending(내려줄 차례) | done(ack 받았다) | refused(받아들이지 못했다)
  state            TEXT NOT NULL,
  reason           TEXT,
  acked_at         TEXT
);
CREATE TABLE IF NOT EXISTS delegations (
  -- PC 위임 하나 (C12 §PC 위임, ADR-0062). **작업 표와 따로 둔다** — 만들 때는 옮기기 수단이
  -- 없어 열을 더할 수 없었다(ADR-0065 전). 지금은 단계로 더할 수 있지만 **값을 ack와 함께
  -- 지우는 표**라 작업 행과 수명이 달라 그대로 둔다.
  --
  -- `outputs_json`은 **업무 값**이다 (원칙 6의 명시한 예외) — 실행기가 받았다고 ack하면
  -- **바로 지운다**. 못 받은 것은 작업 멱등 기간(7일)에 지운다.
  job_id        TEXT PRIMARY KEY,
  runner_id     TEXT NOT NULL,
  run_id        TEXT NOT NULL,
  node_id       TEXT NOT NULL,
  node_instance INTEGER NOT NULL,
  bot_ui_id     TEXT NOT NULL,
  state         TEXT,
  outputs_json  TEXT,
  reason        TEXT,
  pc_run_id     TEXT,
  acked         INTEGER NOT NULL DEFAULT 0,
  at            TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contributed_resources (
  -- 확장이 기여한 자원 (C7·C13 §5). Center는 `data`를 **해석하지 않고** 그대로 넘긴다.
  resource_type  TEXT NOT NULL,
  id             TEXT NOT NULL,
  extension_id   TEXT,
  name           TEXT,
  summary        TEXT,
  updated_at     TEXT,
  revision       INTEGER,
  data_json      TEXT,
  at             TEXT NOT NULL,
  PRIMARY KEY (resource_type, id)
);
CREATE TABLE IF NOT EXISTS catalog_reads (
  -- 카탈로그를 어디서 언제 읽었나. `revision`이 같으면 **항목을 다시 쓰지 않는다** (C7).
  source         TEXT PRIMARY KEY,
  resource_type  TEXT NOT NULL,
  extension_id   TEXT,
  revision       INTEGER,
  read_at        TEXT,
  error          TEXT
);
CREATE TABLE IF NOT EXISTS extensions (
  -- Center에 **외부로 등록된** 확장 정의 (C13, tier=external만). 내장·사내는 설치 파일에
  -- 든 것만 쓴다 (E2) — 여기 들어오지 않는다.
  id              TEXT NOT NULL,
  version         TEXT NOT NULL,
  -- 정의와 봉투를 **그대로** 둔다 — 실행하는 쪽이 받아 다시 검증한다 (C13 전송, E6).
  -- 모델로 바꿔 다시 쓰면 `definition_hash`가 달라져 서명이 깨진다.
  definition_json TEXT NOT NULL,
  envelope_json   TEXT NOT NULL,
  definition_hash TEXT NOT NULL,
  revoked_json    TEXT,
  at              TEXT NOT NULL,
  registered_by   TEXT NOT NULL,
  PRIMARY KEY (id, version)
);
CREATE TABLE IF NOT EXISTS extension_health (
  -- 외부 확장의 어댑터 `health` 점검 결과 (C7·C13 §4-1). **`extensions`와 따로 둔다** — 만들 때는
  -- 옮기기 수단이 없어 열을 더할 수 없었다(ADR-0065 전). 등록 행(서명 봉투)과 점검 결과는 바뀌는
  -- 때가 달라 그대로 둔다.
  id              TEXT PRIMARY KEY,
  status          TEXT NOT NULL,
  status_reasons  TEXT,
  checked_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS service_apps (
  -- 등록된 서비스 앱 (C7). **주소의 유일한 출처**다 (C13 Service).
  app_id         TEXT PRIMARY KEY,
  base_url       TEXT NOT NULL,
  -- 마지막으로 읽은 C11 manifest 그대로. 모르는 필드도 보관한다 (호환 규칙).
  manifest_json  TEXT,
  manifest_at    TEXT,
  status         TEXT NOT NULL DEFAULT 'unknown',
  status_reasons TEXT,
  checked_at     TEXT,
  registered_at  TEXT NOT NULL,
  registered_by  TEXT NOT NULL
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
  -- 배치 결정은 하트비트 한 주기만 올라온다 (C4·C12). 흘려보내면 「왜 설치가 안 됐나」가
  -- 영영 남지 않아서 쌓아 둔다 (CON-03·CON-12 「최근 배치 결정」).
  --
  -- **이 칸은 「보고한 쪽」이다** — PC(`bui_…`)이거나 서버 실행기(`srv_…`)다. 기준선에는
  -- `bot_ui_id`로 남아 있고 **2판 단계가 `host_id`로 고친다** (`migrations.py`, ADR-0065).
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


def _use_wal(conn: sqlite3.Connection, *, tries: int = 100, pause_s: float = 0.05) -> None:
    """WAL로 바꾼다 — **둘이 동시에 떠도** 한 쪽이 죽지 않게.

    WAL로 바꾸려면 배타 잠금이 필요하고, 다른 연결이 같은 순간 바꾸고 있으면 SQLite는 기다리지
    않고 `database is locked`를 돌려준다(연결의 대기 시간이 듣지 않는다). 옮기기 단계를 짜며
    동시 기동 시험이 그것을 잡았다 — **이 결정 전의 코드에서도 같았다**. 판은 DB 파일에 남으므로
    **이미 WAL이면 바꾸지 않는다**(읽기는 잠금이 필요 없다).
    """
    for attempt in range(tries):
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            if str(mode).lower() in ("wal", "memory"):
                return
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) or attempt == tries - 1:
                raise
            time.sleep(pause_s)


def now_iso() -> str:
    """지금 (ISO 8601 + 시간대). 계약의 `Timestamp`는 시간대를 요구한다."""
    return datetime.now(UTC).isoformat()


class Store:
    """Center의 저장소 하나 — **연결 하나를 락 하나로** 나눠 쓴다 (FastAPI는 스레드 풀에서 돈다).

    락 없이 한 연결을 여러 스레드가 동시에 쓰면 sqlite3가 `InterfaceError: bad parameter or other
    API misuse`를 낸다 — 콘솔이 한 화면에서 여럿을 함께 읽을 때 세션 찾기가 그렇게 깨져
    401·500이 났다. 트랜잭션은 끝날 때까지 락을 쥔다 (다른 스레드의 읽기가 끼지 않게).
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        if str(db_path) != ":memory:":
            db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False + 연결마다 락: 작은 규모에서 가장 단순하다.
        # 재진입 락이다 — 트랜잭션 안에서 같은 스레드가 `rows()`를 부를 수 있다.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        _use_wal(self._conn)
        self._conn.execute("PRAGMA foreign_keys=ON")
        # **모자란 판만 차례로 옮긴다** (ADR-0065) — 기준선은 판 표가 없는 DB에서만 돈다.
        migrate(self._conn, baseline=SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Cursor]:
        """트랜잭션 하나. 예외가 나면 되돌린다."""
        with self._lock:
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
        with self._lock:
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
