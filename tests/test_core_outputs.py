"""올라가는 PC 위임의 결과 — 출력 파일 (C4 `JobAck.outputs`, ADR-0062 §4).

**실행 기록은 값을 나르지 않는다** (원칙 6). 그래서 값은 이 파일로만 간다 — 쓰는 것은
실행기, 나르는 것은 PC 실행기, **지우는 것도 PC 실행기다**(읽는 그 자리에서).
"""

from __future__ import annotations

from pathlib import Path

from chaeksas.core import outputs


def test_only_the_declared_names_are_picked() -> None:
    """거르는 자리는 **선언한 `outputs`**다 (C1) — 그것이 「부르는 쪽이 받을 것」이다."""
    found = outputs.pick(["결과코드", "처리시각"], {"결과코드": "OK", "메모": "버린다"})
    assert found == {"결과코드": "OK"}, "선언하지 않은 변수가 섞였다"


def test_a_name_without_a_value_is_left_out() -> None:
    """**없는 이름은 넣지 않는다** — `None`을 넣으면 받는 쪽이 「안 왔다」와 가를 수 없다.

    서버 엔진은 **적은 값이 오지 않으면 업무 실패**로 다루어야 한다 (ADR-0062 §2).
    """
    assert outputs.pick(["결과코드"], {}) == {}


def test_writing_and_taking_leaves_nothing_behind(tmp_path: Path) -> None:
    """읽기와 지우기는 **한 걸음**이다 — 떼어 놓으면 값이 디스크에 남는 길이 생긴다."""
    path = outputs.outputs_path(tmp_path, "run_20261015_090000_aaaaaa")
    outputs.write(path, {"결과코드": "OK"})
    assert path.is_file()

    assert outputs.take(path) == {"결과코드": "OK"}
    assert not path.exists()
    assert outputs.take(path) == {}, "없으면 빈 벌이다 (두 번 받아도 터지지 않는다)"


def test_an_empty_result_is_still_a_result(tmp_path: Path) -> None:
    """**비어도 쓴다** — 「끝났는데 돌려줄 것이 없다」도 사실이다 (서버 쪽이 업무 실패로 본다)."""
    path = outputs.outputs_path(tmp_path, "run_20261015_090000_bbbbbb")
    outputs.write(path, {})
    assert outputs.read(path) == {}


def test_a_half_written_file_is_nothing(tmp_path: Path) -> None:
    """실행기가 쓰다 죽었으면 **없는 것으로 본다** — 그 작업은 `failed`로 간다."""
    path = outputs.outputs_path(tmp_path, "run_20261015_090000_cccccc")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"결과코드": "O', encoding="utf-8")
    assert outputs.read(path) is None and outputs.take(path) == {}
    assert not path.exists(), "읽지 못한 것도 치운다 (다음 실행이 남의 값을 보지 않는다)"


def test_the_shipping_queue_skips_it(tmp_path: Path) -> None:
    """같은 `runs/`에 있지만 **C3가 아니다** — 실행 기록 전송이 건너뛴다 (제어·요청 파일과 같다)."""
    from chaeksas.core.run_log import RunLog, log_path
    from chaeksas.core.run_shipping import Queue

    run_id = "run_20261015_090000_dddddd"
    RunLog(run_id=run_id, path=log_path(tmp_path, run_id)).emit("log", level="info", message="한 줄")
    outputs.write(outputs.outputs_path(tmp_path, run_id), {"결과코드": "OK"})

    files = Queue(data_dir=tmp_path).files()
    assert [one.name for one in files] == [f"{run_id}.jsonl"]
