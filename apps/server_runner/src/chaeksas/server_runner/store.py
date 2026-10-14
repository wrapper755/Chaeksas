"""기다리는 실행을 담아 두는 곳 — **SQLite 한 파일** (C12 §재시작과 유실, ADR-0054 §3).

**적는 때는 둘이고 지우는 때는 하나다.**

| 때 | 행의 상태 |
| --- | --- |
| 실행을 시작할 때 | `running` (스냅샷은 비어 있다) |
| 실행이 **멈출 때** | `waiting` + 스냅샷 |
| 끝났을 때 (성공·실패·취소) | **지운다** (실행 기록 파일은 남는다 — C3) |

**시작할 때 적는 것을 빠뜨리면** 다시 뜬 실행기가 죽은 실행을 알지 못해 Center의 작업이
`accepted`로 영원히 남는다 (ADR-0054 §3). 그래서 스냅샷이 없어도 행은 먼저 들어간다.

**걸음마다 적지 않는다** — 실행 기록 파일에 이미 걸음이 다 있고, 되살릴 자리는 기다림뿐이다.

**빨아들인 메시지는 스냅샷과 같은 트랜잭션에** 간다 (`absorbed_messages`, ADR-0058) — 따로
적으면 둘이 갈라져 메시지를 두 번 넣거나 영영 잃는다. **담을 때마다 그 실행이 받은 것을 전부
다시 적는다**(멱등) — 한 번 적고 지우면 어긋난 순간이 그대로 굳는다.

스레드가 여럿이라 **연결을 잠근다** — `sqlite3`의 기본 연결은 한 스레드만 쓸 수 있으므로
`check_same_thread=False`로 열고 자물쇠 하나로 감싼다 (ADR-0054 §남은 것이 묻던 자리다).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: 행의 상태 (ADR-0054 §3). 되살릴 것은 `waiting`뿐이다.
RUNNING = "running"
WAITING = "waiting"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id         TEXT PRIMARY KEY,
  bpm_process_id TEXT NOT NULL,
  version        TEXT NOT NULL,
  -- `running`이면 스냅샷이 없을 수 있다 (시작할 때 적은 행이다) — 그때는 되살리지 않고
  -- `runner_restarted`로 닫는다 (ADR-0054 §4 — 보내기는 멱등이 아니다).
  state          TEXT NOT NULL,
  snapshot       TEXT,
  job_id         TEXT,
  started_at     TEXT NOT NULL,
  saved_at       TEXT NOT NULL
);

-- 그 실행이 **이미 빨아들인 메시지** (ADR-0058). 스냅샷과 **같은 트랜잭션**에 들어가고
-- 실행이 끝나면 함께 지워진다 — 둘이 갈라지면 메시지를 두 번 넣거나 영영 잃는다.
--
-- **열을 더하지 않고 표를 따로 둔다** — `CREATE TABLE IF NOT EXISTS`는 이미 만들어진 DB의
-- 표를 고치지 않으므로 `runs`에 열을 더하면 돌던 실행기가 조용히 깨진다 (Center의
-- `extension_health`와 같은 결).
CREATE TABLE IF NOT EXISTS absorbed_messages (
  message_id TEXT PRIMARY KEY,
  run_id     TEXT NOT NULL,
  saved_at   TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Saved:
    """담아 둔 실행 하나."""

    run_id: str
    bpm_process_id: str
    version: str
    state: str
    snapshot: dict[str, Any] | None
    job_id: str | None
    started_at: str

    @property
    def had_wait(self) -> bool:
        """기다린 적이 있나 — **없으면 되살리지 않는다** (ADR-0054 §4)."""
        return self.state == WAITING and self.snapshot is not None


@dataclass
class Store:
    """실행기 하나의 저장소. `path`가 `:memory:`면 메모리에만 둔다 (시험)."""

    path: Path
    _db: sqlite3.Connection | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # 스레드가 여럿이다 (실행마다 하나) — 연결 하나를 자물쇠로 감싼다.
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:  # pragma: no cover - 닫은 뒤에 쓰면 버그다
            raise RuntimeError("저장소가 닫혀 있다")
        return self._db

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    # ── 적기 ──

    def mark_running(
        self, run_id: str, *, bpm_process_id: str, version: str, job_id: str | None, started_at: str
    ) -> None:
        """실행을 시작했다 — **스냅샷 없이** 행만 둔다 (ADR-0054 §3).

        이것이 없으면 다시 뜬 실행기가 **죽은 실행을 알지 못한다**.
        """
        with self._lock:
            self.db.execute(
                "INSERT INTO runs (run_id, bpm_process_id, version, state, snapshot, job_id,"
                " started_at, saved_at) VALUES (?, ?, ?, ?, NULL, ?, ?, ?)"
                " ON CONFLICT(run_id) DO UPDATE SET state = excluded.state, saved_at = excluded.saved_at",
                (run_id, bpm_process_id, version, RUNNING, job_id, started_at, now_iso()),
            )
            self.db.commit()

    def save_waiting(
        self, run_id: str, snapshot: dict[str, Any], *, absorbed: Iterable[str] = ()
    ) -> int:
        """실행이 멈췄다 — 스냅샷을 담는다. 돌려주는 것은 담긴 글의 길이(바이트)다.

        **한 트랜잭션이다** — 쓰다 꺼져도 반만 적힌 행이 남지 않는다.

        `absorbed`는 그 실행이 **이 상태에 이르기까지 빨아들인 메시지**다 (ADR-0058). 스냅샷과
        **함께** 적는 것이 요점이다 — 따로 적으면 「메시지는 받았다는데 상태는 그 전」인 틈이
        생겨 그 메시지를 영영 잃는다.
        """
        body = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        at = now_iso()
        with self._lock:
            self.db.execute(
                "UPDATE runs SET state = ?, snapshot = ?, saved_at = ? WHERE run_id = ?",
                (WAITING, body, at, run_id),
            )
            self.db.executemany(
                "INSERT INTO absorbed_messages (message_id, run_id, saved_at) VALUES (?, ?, ?)"
                " ON CONFLICT(message_id) DO NOTHING",
                [(one, run_id, at) for one in absorbed],
            )
            self.db.commit()
        return len(body)

    def forget(self, run_id: str) -> None:
        """끝났다 — 행을 지운다. **실행 기록 파일은 남는다** (C3 — 파일이 원본이다).

        **빨아들인 메시지도 함께 지운다** — 되살릴 상태가 없으면 그 기억에 쓸 데가 없다
        (ADR-0058 — 그래서 이 표는 기다리는 실행 수만큼만 자란다).
        """
        with self._lock:
            self.db.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            self.db.execute("DELETE FROM absorbed_messages WHERE run_id = ?", (run_id,))
            self.db.commit()

    # ── 읽기 ──

    def all(self) -> list[Saved]:
        """담아 둔 것 전부 (오래된 것부터). 다시 뜰 때 이것을 훑는다."""
        with self._lock:
            rows = self.db.execute("SELECT * FROM runs ORDER BY started_at, run_id").fetchall()
        return [self._row(one) for one in rows]

    def absorbed(self) -> dict[str, str]:
        """담아 둔 실행들이 **이미 빨아들인 메시지** — `message_id` → `run_id` (ADR-0058).

        다시 뜬 실행기가 이것으로 멱등 기억을 되살린다. 행이 남은 실행의 것만 있다 (`forget`이
        함께 지운다).
        """
        with self._lock:
            rows = self.db.execute(
                "SELECT message_id, run_id FROM absorbed_messages ORDER BY saved_at, message_id"
            ).fetchall()
        return {str(one["message_id"]): str(one["run_id"]) for one in rows}

    def get(self, run_id: str) -> Saved | None:
        with self._lock:
            row = self.db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._row(row) if row is not None else None

    def _row(self, row: sqlite3.Row) -> Saved:
        raw = row["snapshot"]
        snapshot = None
        if raw:
            try:
                snapshot = json.loads(raw)
            except ValueError:
                # **읽지 못한 스냅샷은 없는 것으로 본다** — 되살리지 않고 사유를 남긴다
                # (`snapshot_unreadable`). 깨진 글로 실행을 이어 가지 않는다.
                log.error("스냅샷을 읽지 못했다: %s", row["run_id"])
        return Saved(
            run_id=str(row["run_id"]),
            bpm_process_id=str(row["bpm_process_id"]),
            version=str(row["version"]),
            state=str(row["state"]),
            snapshot=snapshot,
            job_id=row["job_id"],
            started_at=str(row["started_at"]),
        )


__all__ = ["RUNNING", "SCHEMA", "WAITING", "Saved", "Store", "now_iso"]
