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
    """옮기는 걸음 하나. `statements`는 **한 트랜잭션**에서 차례로 돈다.

    `guard`는 **아무 줄도 돌려주지 않아야 하는 SELECT**다 (ADR-0066) — 데이터가 그 단계의
    전제를 어기면 문을 하나도 돌리지 않고 멈추고, 나온 줄과 `guard_help`를 말한다.
    **짐작해 고치지 않는다** — 고칠 수 있는 것은 문이 하고, 사람이 골라야 하는 것만 막는다.
    """

    version: int
    about: str
    statements: tuple[str, ...]
    guard: str | None = None
    guard_help: str = ""


#: 키 묶기를 어긴 행 — `(표, 칸, 값, 행 id)`. **겹친 무리의 모든 행**을 돌려준다
#: (`GROUP_CONCAT`처럼 SQLite에만 있는 함수를 쓰지 않는다 — PostgreSQL 길을 닫지 않는다).
#: 3판의 지킴이자 `chk-center hosts duplicates`가 쓰는 질의다 — **한 자리에 둔다**.
DUPLICATE_HOSTS = """
SELECT 'bot_uis' AS host_table, 'key_id' AS host_column, key_id AS shared, bot_ui_id AS host_id
  FROM bot_uis WHERE key_id IN (SELECT key_id FROM bot_uis GROUP BY key_id HAVING COUNT(*) > 1)
UNION ALL
SELECT 'bot_uis', 'machine_id', machine_id, bot_ui_id
  FROM bot_uis WHERE machine_id IN (SELECT machine_id FROM bot_uis GROUP BY machine_id HAVING COUNT(*) > 1)
UNION ALL
SELECT 'server_runners', 'key_id', key_id, server_runner_id
  FROM server_runners WHERE key_id IN (SELECT key_id FROM server_runners GROUP BY key_id HAVING COUNT(*) > 1)
UNION ALL
SELECT 'server_runners', 'machine_id', machine_id, server_runner_id
  FROM server_runners
  WHERE machine_id IN (SELECT machine_id FROM server_runners GROUP BY machine_id HAVING COUNT(*) > 1)
ORDER BY 1, 2, 3, 4
"""


#: **더하기만 한다.** 지우거나 고치지 않는다 — 이미 이 단계를 지난 DB가 있다. 잘못 간 단계는
#: 새 단계로 바로잡는다. 판은 2부터 빈틈 없이 오른다 (시험이 본다).
MIGRATIONS: tuple[Step, ...] = (
    Step(
        2,
        "deployment_results.bot_ui_id → host_id (PC와 서버 실행기를 함께 담는다, C4·C12)",
        ("ALTER TABLE deployment_results RENAME COLUMN bot_ui_id TO host_id",),
    ),
    Step(
        3,
        "키 묶기를 DB도 지킨다 — key_id·machine_id는 한 행에만 (C4·C12, ADR-0066)",
        (
            "CREATE UNIQUE INDEX bot_uis_key_id ON bot_uis (key_id)",
            "CREATE UNIQUE INDEX bot_uis_machine_id ON bot_uis (machine_id)",
            "CREATE UNIQUE INDEX server_runners_key_id ON server_runners (key_id)",
            "CREATE UNIQUE INDEX server_runners_machine_id ON server_runners (machine_id)",
        ),
        guard=DUPLICATE_HOSTS,
        guard_help=(
            "같은 키·같은 기계가 여러 행에 있다 (2026-10-08 전에 만든 DB에서 생길 수 있다). "
            "**어느 행을 남길지는 사람이 고른다** — `chk-center hosts duplicates`로 보고 "
            "`chk-center hosts retire <id>`로 나머지를 은퇴시킨 뒤 다시 띄우세요 (docs/04-setup.md)"
        ),
    ),
    Step(
        4,
        "패키지를 내어 준 횟수·마지막 때 (C5 `download_count`·`last_downloaded_at`, CON-06)",
        (
            "ALTER TABLE packages ADD COLUMN download_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE packages ADD COLUMN last_downloaded_at TEXT",
        ),
    ),
    Step(
        5,
        "결재 담당자·대리 답의 경로, 작업의 대신 부른 사람 (C6 `assignees`·`answered_via`, "
        "C5 `on_behalf_of`, ADR-0080·0081)",
        (
            "ALTER TABLE approvals ADD COLUMN assignees_json TEXT",
            "ALTER TABLE approvals ADD COLUMN answered_via TEXT",
            "ALTER TABLE jobs ADD COLUMN on_behalf_of TEXT",
        ),
    ),
    Step(
        6,
        "위임 대상 종류 — 서버 BPM 프로세스에도 맡긴다 (C12 §PC 위임, ADR-0082). 옛 행은 모두 PC다",
        ("ALTER TABLE delegations ADD COLUMN target_type TEXT NOT NULL DEFAULT 'bot_ui'",),
    ),
    Step(
        7,
        "결재 검토 자료의 지문 — 값을 지운 뒤에도 남는다 (C6 `review_digest`, ADR-0083)",
        ("ALTER TABLE approvals ADD COLUMN review_digest TEXT",),
    ),
    Step(
        8,
        "가상 직원 — 등록만 둔다, 일괄·자식은 읽을 때 잇는다 (C5 §가상 직원, ADR-0085)",
        (
            "CREATE TABLE virtual_workers ("
            " id TEXT PRIMARY KEY, name TEXT NOT NULL, supervisors_json TEXT NOT NULL,"
            " intake TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
            "CREATE INDEX virtual_workers_intake ON virtual_workers (intake)",
        ),
    ),
    Step(
        9,
        "관리자 계정·세션·Center 서명 키, 승인·배포를 누가 했나 (ADR-0090)",
        (
            "CREATE TABLE accounts ("
            " username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, role TEXT NOT NULL,"
            " created_at TEXT NOT NULL, created_by TEXT NOT NULL, disabled_at TEXT,"
            " password_changed_at TEXT NOT NULL, last_login_at TEXT)",
            "CREATE TABLE account_sessions ("
            " token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, created_at TEXT NOT NULL,"
            " expires_at TEXT NOT NULL)",
            "CREATE INDEX account_sessions_user ON account_sessions (username)",
            # 개인키는 raw 32바이트 base64. **DB와 같이 백업되고 같이 지켜진다** (ADR-0090 §5).
            "CREATE TABLE center_signing_keys ("
            " key_id TEXT PRIMARY KEY, private_key TEXT NOT NULL, created_at TEXT NOT NULL,"
            " active INTEGER NOT NULL)",
            "ALTER TABLE packages ADD COLUMN approved_by TEXT",
            "ALTER TABLE packages ADD COLUMN revoked_by TEXT",
            "ALTER TABLE deployments ADD COLUMN deployed_by TEXT",
            "ALTER TABLE deployments ADD COLUMN revoked_by TEXT",
            "ALTER TABLE extensions ADD COLUMN revoked_by TEXT",
        ),
    ),
    Step(
        10,
        "등록 요청과 승인, 키 회전 — 키는 Center가 만들어 봉해 내려 준다 (C4·C12·C5, ADR-0092)",
        (
            # 요청 본문은 그대로 둔다 — 승인해도 `register`가 다시 보낸다. 봉한 키는 **받을 때까지만**.
            "CREATE TABLE enrollments ("
            " enrollment_id TEXT PRIMARY KEY, type TEXT NOT NULL, machine_id TEXT NOT NULL,"
            " name TEXT NOT NULL, os TEXT NOT NULL, request_json TEXT NOT NULL, public_key TEXT NOT NULL,"
            " code TEXT NOT NULL, remote_addr TEXT, requested_at TEXT NOT NULL, expires_at TEXT NOT NULL,"
            " state TEXT NOT NULL, decided_by TEXT, decided_at TEXT, reason TEXT, key_id TEXT,"
            " sealed_json TEXT, replaced_key_id TEXT)",
            "CREATE INDEX enrollments_state ON enrollments (state)",
            "CREATE INDEX enrollments_machine ON enrollments (type, machine_id)",
            "ALTER TABLE center_keys ADD COLUMN enrollment_id TEXT",
            # 회전에 쓰는 그 기계의 공개키, 갈아 줄 새 키, 새 키를 봉한 것 (새 키의 행에 둔다).
            "ALTER TABLE center_keys ADD COLUMN public_key TEXT",
            "ALTER TABLE center_keys ADD COLUMN successor_id TEXT",
            "ALTER TABLE center_keys ADD COLUMN sealed_json TEXT",
        ),
    ),
    Step(
        11,
        "계정 권한과 Studio 로그인 — 키가 계정·PC 이름에 묶인다 (C5 §계정 권한과 Studio 로그인, ADR-0092)",
        (
            "ALTER TABLE accounts ADD COLUMN permissions_json TEXT",
            "ALTER TABLE center_keys ADD COLUMN account TEXT",
            "ALTER TABLE center_keys ADD COLUMN machine_name TEXT",
            "CREATE INDEX center_keys_account ON center_keys (account)",
        ),
    ),
    Step(
        12,
        "서비스 앱 키를 Center가 짓고 나른다 — 외부 앱 키 보관, 셀렉터 등록, 앱의 신뢰 (C4·C7·C11, ADR-0094)",
        (
            # 원문은 두지 않는다 — **봉한 덩이만** 받았다는 ack까지 (`sealed_json`). 해시는 앱이 검증한다.
            "CREATE TABLE service_keys ("
            " service_key_id TEXT PRIMARY KEY, source TEXT NOT NULL, purpose TEXT NOT NULL,"
            " app_id TEXT NOT NULL, bpm_process_id TEXT, target_type TEXT NOT NULL, target_id TEXT NOT NULL,"
            " key_refs_json TEXT, issued_for_json TEXT, key_hash TEXT, prefix TEXT,"
            " allowed_ops_json TEXT, extra_scopes_json TEXT, expires_at TEXT, created_at TEXT NOT NULL,"
            " state TEXT NOT NULL, sealed_json TEXT, acked_at TEXT, replaces TEXT,"
            " revoke_reason TEXT, revoked_at TEXT, dropped_at TEXT, last_error TEXT, last_try_at TEXT)",
            "CREATE INDEX service_keys_target ON service_keys (target_type, target_id)",
            "CREATE INDEX service_keys_state ON service_keys (state)",
            # 외부 앱 키 — 운영(`run`)·시험용(`test`). **암호화해** 둔다 (감싸는 키는 `center_secrets`).
            "CREATE TABLE external_app_keys ("
            " extension_id TEXT NOT NULL, slot TEXT NOT NULL, ciphertext TEXT NOT NULL,"
            " set_at TEXT NOT NULL, set_by TEXT NOT NULL, PRIMARY KEY (extension_id, slot))",
            "CREATE TABLE center_secrets (name TEXT PRIMARY KEY, value TEXT NOT NULL, created_at TEXT NOT NULL)",
            # CON-03 「셀렉터 등록」 (ADR-0094 §6).
            "ALTER TABLE bot_uis ADD COLUMN selector_registration INTEGER NOT NULL DEFAULT 0",
            # 앱이 Center 발급을 받나 (C11 `GET /center/v1/trust`, C7 `trust`).
            "ALTER TABLE service_apps ADD COLUMN trust_json TEXT",
        ),
    ),
    Step(
        13,
        "외부 확장의 주소를 Center가 덮어쓴다 — 정의의 허용 호스트 안에서만 (C7 §외부 확장 주소, ADR-0097)",
        (
            # 확장 id에 붙는다(판이 아니다) — 새 판을 올려도 주소는 남고, 밖이 되면 읽을 때 거른다.
            "CREATE TABLE extension_addresses ("
            " extension_id TEXT PRIMARY KEY, base_url TEXT NOT NULL,"
            " set_at TEXT NOT NULL, set_by TEXT NOT NULL)",
        ),
    ),
    Step(
        14,
        "작업이 어느 가상 직원의 일인가 — id만 남기고 값은 내려줄 때 읽는다 (C5 `virtual_worker`, ADR-0099)",
        ("ALTER TABLE jobs ADD COLUMN virtual_worker TEXT",),
    ),
    Step(
        15,
        "외부 작업과 일꾼 — 바깥 기능은 Pull로 (C15, ADR-0102)",
        (
            # 일감 하나. **값(`input_json`·`output_json`)은 결과를 부른 쪽이 받으면 지운다** (원칙 6 예외).
            "CREATE TABLE external_tasks ("
            " task_id TEXT PRIMARY KEY, topic TEXT NOT NULL, operation TEXT NOT NULL, mode TEXT NOT NULL,"
            " origin TEXT NOT NULL, idempotency_json TEXT NOT NULL, caller_json TEXT NOT NULL,"
            " business_key TEXT, body_hash TEXT NOT NULL, poster_key_id TEXT NOT NULL,"
            " want_result INTEGER NOT NULL, input_json TEXT, output_json TEXT, result_json TEXT,"
            " state TEXT NOT NULL, created_at TEXT NOT NULL, deadline TEXT NOT NULL,"
            " locked_by TEXT, lockers_json TEXT, lock_until TEXT, deliveries INTEGER NOT NULL DEFAULT 0,"
            " finished_at TEXT, acked_at TEXT)",
            "CREATE INDEX external_tasks_waiting ON external_tasks (topic, state, created_at)",
            "CREATE INDEX external_tasks_poster ON external_tasks (poster_key_id)",
            # 일꾼 하나 — 키는 `center_keys`(종류 `consumer`)이고 토픽은 **승인할 때** 정해진다.
            "CREATE TABLE consumers ("
            " consumer_id TEXT PRIMARY KEY, key_id TEXT NOT NULL UNIQUE, machine_id TEXT NOT NULL UNIQUE,"
            " name TEXT NOT NULL, topics_json TEXT NOT NULL, manifest_json TEXT,"
            " approved_at TEXT NOT NULL, approved_by TEXT NOT NULL, last_fetch_at TEXT)",
        ),
    ),
    Step(
        16,
        "Center는 바깥 기능의 주소도 키도 들지 않는다 — 서비스 앱 등록·키·외부 앱 키·주소 덮어쓰기를 걷는다 (ADR-0102)",
        (
            # 서비스 앱은 일꾼으로 들어온다(`consumers`) — 주소 등록·상태 읽기가 없다.
            "DROP TABLE IF EXISTS service_apps",
            "DROP TABLE IF EXISTS extension_health",
            # 서비스 앱 키·외부 앱 키(암호문)와 그 감싸는 키 — 키는 일꾼 쪽에만 있다.
            "DROP TABLE IF EXISTS service_keys",
            "DROP TABLE IF EXISTS external_app_keys",
            "DROP TABLE IF EXISTS center_secrets",
            "DROP TABLE IF EXISTS extension_addresses",
        ),
    ),
    Step(
        17,
        "타이머 시작의 일정 — 쏜 차례와 분마다 한 번의 쓸기 (C5 §일정, ADR-0110)",
        (
            # 차례 하나. **기본 키가 잡기다** — 둘이 같이 쓸어도 하나만 넣는다 (ADR-0110 §6).
            # 잡은 뒤 작업을 만들면 `job_id`, Center가 거부하면 `error`(코드)를 적는다.
            "CREATE TABLE timer_fires ("
            " trigger_key TEXT NOT NULL, slot TEXT NOT NULL, bpm_process_id TEXT NOT NULL,"
            " version TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL,"
            " expression TEXT NOT NULL, missed INTEGER NOT NULL DEFAULT 0, fired_at TEXT NOT NULL,"
            " job_id TEXT, error TEXT, PRIMARY KEY (trigger_key, slot))",
            "CREATE TABLE timer_sweeps (id INTEGER PRIMARY KEY CHECK (id = 1), at TEXT NOT NULL)",
        ),
    ),
    Step(
        18,
        "서버 실행기 재시작 — 요청한 시각, 다시 등록하면 지운다 (C12 운영 API, ADR-0117)",
        ("ALTER TABLE server_runners ADD COLUMN restart_requested_at TEXT",),
    ),
    Step(
        19,
        "CON-03 「셀렉터 등록」을 걷는다 — UI 자동화 확장과 함께 (ADR-0114)",
        ("ALTER TABLE bot_uis DROP COLUMN selector_registration",),
    ),
    Step(
        20,
        "외부 확장이 어디서 들어왔나 — 콘솔(NULL)·일꾼(`worker`, 맡은 일꾼이 빠지면 거둔다) (ADR-0121)",
        ("ALTER TABLE extensions ADD COLUMN source TEXT",),
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
            _apply(
                conn, one.version, one.about, list(one.statements), now,
                guard=one.guard, guard_help=one.guard_help,
            )
        return current(conn)
    finally:
        conn.isolation_level = saved


def _apply(
    conn: sqlite3.Connection,
    version: int,
    about: str,
    statements: Sequence[str],
    now: str | None,
    *,
    guard: str | None = None,
    guard_help: str = "",
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
        if guard is not None:
            # **문을 하나도 돌리기 전에** 본다 — 잠금을 잡은 뒤라 그 사이 데이터가 바뀌지 않는다.
            broken = conn.execute(guard).fetchall()
            if broken:
                lines = "\n".join("  " + " · ".join(str(cell) for cell in row) for row in broken)
                raise MigrationError(f"{version}판으로 옮길 수 없다 — {about}\n{lines}\n{guard_help}")
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
    "DUPLICATE_HOSTS",
    "MIGRATIONS",
    "VERSIONS_TABLE",
    "MigrationError",
    "Step",
    "current",
    "latest",
    "migrate",
    "statements_of",
]
