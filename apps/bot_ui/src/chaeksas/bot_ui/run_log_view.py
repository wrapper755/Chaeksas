"""BUI-02 「실행 기록」 탭 — `runs/<run_id>.jsonl`을 줄로 그린다.

**원본은 파일이다** (ADR-0031·C3) — 실행기가 먼저 쓰고, 이 화면은 그것을 읽을 뿐이다. 화면이
기록을 만들지 않으므로, Bot UI를 닫았다 열어도 같은 것이 보인다.

줄 형식은 `bot-ui.md`의 「<시각> [<Bot>] <노드> <내용>」이고, **실패한 실행은 한 줄 요약을 먼저**
놓는다 (U13 — 왜 실패했나를 찾으려고 수백 줄을 거슬러 올라가지 않게).

**업무 값은 없다.** `data`는 기록될 때 이미 걸러진 것이고(`core.run_log`의 `sanitize()`), 여기서는
**개수·상태 같은 센 것만** 글로 옮긴다 (README 원칙 6).
"""

from __future__ import annotations

from pathlib import Path

from chaeksas.contracts.events import RunEvent
from chaeksas.core.run_log import RunLog, run_dir

#: 화면에 올리는 줄 수 상한 (BUI-02). 넘으면 **오래된 쪽을 버린다** — 방금 일이 더 급하다.
MAX_LINES = 5000

#: 최근 몇 개의 실행까지 읽나. 파일이 수천 개여도 화면 한 판이면 충분하다.
MAX_RUNS = 50

EMPTY = "아직 실행 기록이 없습니다. Bot을 실행하면 여기에 쌓입니다."

#: `kind`를 사람 말로. **모르는 종류는 그대로 보인다** (C3 — 받는 쪽은 관대하게).
KIND_LABEL = {
    "run_started": "실행 시작",
    "run_finished": "실행 끝",
    "node_state": "노드",
    "service_call": "서비스 앱 호출",
    "ai_task": "AI 태스크",
    "ui_session": "UI 태스크",
    "human_requested": "사람에게 물음",
    "human_answered": "사람이 답함",
    "error": "오류",
}

#: 줄 뒤에 붙여도 되는 `data` 키 — **업무 값이 아닌 것만** 고른다 (원칙 6).
SAFE_KEYS = (
    "bpm_process_id",
    "version",
    "state",
    "status",
    "code",
    "message",
    "node_kind",
    "app_id",
    "operation",
    "mode_used",
    "page_id",
    "result",
    "attempt",
    "replayed",
    "healed",
)


def _clock(ts: str) -> str:
    """`2026-10-09T01:02:03Z` → `01:02:03`. 모양이 다르면 **그대로** 보인다."""
    return ts[11:19] if len(ts) >= 19 and ts[10:11] == "T" else ts


def _detail(event: RunEvent) -> str:
    parts = [f"{key}={event.data[key]}" for key in SAFE_KEYS if key in event.data]
    return " ".join(parts)


def line_of(event: RunEvent, bot: str) -> str:
    """한 줄 — 「<시각> [<Bot>] <노드> <내용>」."""
    kind = KIND_LABEL.get(event.kind, event.kind)
    where = event.node_id or "—"
    detail = _detail(event)
    return f"{_clock(event.ts)} [{bot or '?'}] {where} {kind}{' ' + detail if detail else ''}"


def _bot_of(events: list[RunEvent]) -> str:
    for event in events:
        found = event.data.get("bpm_process_id")
        if found:
            return str(found)
    return ""


def _failure_of(events: list[RunEvent], bot: str) -> str | None:
    """실패한 실행의 한 줄 요약 (U13). 실패가 아니면 `None`."""
    for event in reversed(events):
        if event.kind == "run_finished":
            state = str(event.data.get("status") or event.data.get("state") or "")
            if state not in {"failed", "cancelled"}:
                return None
            reason = str(event.data.get("message") or event.data.get("code") or state)
            return f"{_clock(event.ts)} [{bot or '?'}] — {state}: {reason}"
    return None


def _read(path: Path) -> list[RunEvent]:
    """한 실행의 기록. **깨진 줄 하나가 화면을 비우지 않는다** — 읽은 데까지 보인다."""
    out: list[RunEvent] = []
    try:
        for event in RunLog.read(path):
            out.append(event)
    except (OSError, ValueError):
        pass
    return out


def lines(data_dir: Path, *, limit: int = MAX_LINES, runs: int = MAX_RUNS) -> list[str]:
    """화면에 올릴 줄들 — **새 실행이 위**다 (방금 일을 먼저 본다).

    실행 안에서는 시간 순서이고, 실패한 실행은 그 블록 맨 위에 요약 한 줄이 붙는다 (U13).
    """
    folder = run_dir(data_dir)
    if not folder.is_dir():
        return []
    found = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:runs]
    out: list[str] = []
    for path in found:
        events = _read(path)
        if not events:
            continue
        bot = _bot_of(events)
        block = [line_of(event, bot) for event in events]
        failure = _failure_of(events, bot)
        if failure is not None:
            block.insert(0, failure)
        out.extend(block)
        if len(out) >= limit:
            break
    return out[:limit]
