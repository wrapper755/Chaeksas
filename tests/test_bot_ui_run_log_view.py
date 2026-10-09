"""BUI-02 「실행 기록」 탭이 `runs/<run_id>.jsonl`을 읽어 줄로 그린다 — docs/09-gaps.md §4-1.

붙이기 전까지 그 탭에는 자리표시 라벨 하나가 있었다. **원본은 이미 쌓여 있었다** (C3) —
읽어 그리는 쪽이 없었을 뿐이다 (「문서에 돈다고 적혀 있다」 ≠ 「부르는 쪽이 있다」).

여기서 지키는 것: 줄 형식(「<시각> [<Bot>] <노드> <내용>」), **실패 요약이 그 실행 맨 위**(U13),
줄 수 상한, **새 실행이 위**, 깨진 줄 하나가 화면을 비우지 않는 것, 그리고 **업무 값이 새지
않는 것**(README 원칙 6).
"""

from __future__ import annotations

import json
from pathlib import Path

from chaeksas.bot_ui import run_log_view
from chaeksas.core.run_log import run_dir


def write(data_dir: Path, run_id: str, events: list[dict[str, object]]) -> Path:
    folder = run_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{run_id}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for seq, event in enumerate(events, start=1):
            line = {"schema": 1, "run_id": run_id, "seq": seq, "ts": f"2026-10-09T01:02:0{seq % 10}Z", **event}
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return path


def started(bot: str = "fx19-invoice") -> dict[str, object]:
    return {
        "kind": "run_started",
        "data": {"bpm_process_id": bot, "version": "1.0.0", "run_location": "pc",
                 "executor": "bot_ui", "mode": "deterministic", "source": "manual"},
    }


def finished(status: str = "success", **extra: object) -> dict[str, object]:
    return {
        "kind": "run_finished",
        "data": {"status": status, "duration_s": 1.5, "ai_tasks": 0, "replayed_tasks": 0,
                 "ui_tasks": 0, "service_calls": 0, "human_requests": 0, **extra},
    }


def test_an_empty_data_dir_says_so_instead_of_breaking(tmp_path: Path) -> None:
    assert run_log_view.lines(tmp_path) == []


def test_a_line_carries_the_time_the_bot_the_node_and_what_happened(tmp_path: Path) -> None:
    write(tmp_path, "run_20261009_010203_aaaaaa", [started(), {"kind": "node_state", "node_id": "Task_1",
                                                               "data": {"state": "done"}}])
    found = run_log_view.lines(tmp_path)
    assert found[0].startswith("01:02:01 [fx19-invoice] — 실행 시작")
    assert "01:02:02 [fx19-invoice] Task_1 노드 state=done" == found[1]


def test_a_failed_run_puts_its_one_line_summary_on_top(tmp_path: Path) -> None:
    """U13 — 왜 실패했나를 찾으려고 수백 줄을 거슬러 올라가지 않는다."""
    write(tmp_path, "run_20261009_010203_bbbbbb", [
        started(), {"kind": "node_state", "node_id": "Task_1", "data": {"state": "done"}},
        finished("failed", message="서비스 앱이 500을 돌려주었습니다"),
    ])
    found = run_log_view.lines(tmp_path)
    assert found[0] == "01:02:03 [fx19-invoice] — failed: 서비스 앱이 500을 돌려주었습니다"
    assert any("실행 시작" in line for line in found[1:]), "요약은 더해지고 줄은 그대로 남는다"


def test_a_successful_run_gets_no_summary_line(tmp_path: Path) -> None:
    write(tmp_path, "run_20261009_010203_cccccc", [started(), finished()])
    found = run_log_view.lines(tmp_path)
    assert "실행 시작" in found[0], "맨 위는 기록의 첫 줄이다 (요약이 끼지 않는다)"
    assert len(found) == 2


def test_the_newest_run_comes_first(tmp_path: Path) -> None:
    old = write(tmp_path, "run_20261009_010203_dddddd", [started("old-bot"), finished()])
    new = write(tmp_path, "run_20261009_010203_eeeeee", [started("new-bot"), finished()])
    import os  # noqa: PLC0415

    os.utime(old, (1_700_000_000, 1_700_000_000))
    os.utime(new, (1_800_000_000, 1_800_000_000))
    found = run_log_view.lines(tmp_path)
    assert "new-bot" in found[0] and any("old-bot" in line for line in found)


def test_the_screen_keeps_at_most_the_line_limit(tmp_path: Path) -> None:
    events: list[dict[str, object]] = [started()]
    events += [{"kind": "node_state", "node_id": f"T{i}", "data": {}} for i in range(50)]
    write(tmp_path, "run_20261009_010203_ffffff", events)
    assert len(run_log_view.lines(tmp_path, limit=10)) == 10


def test_a_broken_line_does_not_empty_the_screen(tmp_path: Path) -> None:
    path = write(tmp_path, "run_20261009_010203_0a0a0a", [started()])
    with path.open("a", encoding="utf-8") as f:
        f.write("{이건 JSON이 아니다\n")
    assert run_log_view.lines(tmp_path), "읽은 데까지는 보인다"


def test_business_values_do_not_reach_the_screen(tmp_path: Path) -> None:
    """원칙 6. `data`는 이미 걸러진 것이고, 화면은 **아는 칸만** 옮긴다."""
    write(tmp_path, "run_20261009_010203_0b0b0b", [
        started(),
        {"kind": "service_call", "node_id": "Call_1",
         "data": {"app_id": "erp", "operation": "po.create", "거래처": "모든상사", "금액": 1234567}},
    ])
    joined = "\n".join(run_log_view.lines(tmp_path))
    assert "app_id=erp" in joined and "operation=po.create" in joined
    assert "모든상사" not in joined and "1234567" not in joined
