"""M3 인수 시험 — 업무 예제의 M3 묶음을 **Studio 시험 실행**으로 돌린다 (조각 3f).

로드맵의 M3 마지막 기준이다: 「[업무 예제](08-business-examples/README.md)의 M3 묶음이 Studio
시험 실행에서 케이스 모두 통과 (AI 태스크는 자율 수행 → 결정 수행 재생 둘 다)」.

**바깥에 나가지 않는다.** 모델은 127.0.0.1에 띄운 작은 OpenAI 호환 스텁이고(S7이 쓰던 수법),
표본 파일은 시험이 그 자리에서 만든다 (PDF·엑셀·CSV). 저장소에 이진 파일을 두지 않는다.

**묶음 목록은 예제에서 읽는다** — `README.md`의 표를 사람이 옮겨 적으면 어긋난다.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from canned_answers import canned
from sample_files import make_samples
from stub_model import StubModel

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts.bpmn_ext import Case, read_process  # noqa: E402
from chaeksas.studio.receiver import Receiver  # noqa: E402
from chaeksas.studio.run_dialog import AUTONOMOUS, DETERMINISTIC  # noqa: E402
from chaeksas.studio.runner import (  # noqa: E402
    NO_EXPECT,
    PASS,
    CaseRun,
    Outcome,
    Plan,
    read_cases,
)
from chaeksas.studio.settings import Settings  # noqa: E402
from chaeksas.studio.workspace import BpmProcess, Workspace  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples"
EXAMPLES = DOCS / "bpmn"


def bundle() -> list[str]:
    """M3 묶음의 예제 파일 이름 — `README.md`의 「마일스톤별 인수 시험 묶음」 표에서 읽는다."""
    body = (DOCS / "README.md").read_text(encoding="utf-8")
    row = next(line for line in body.splitlines() if line.startswith("| M3 |"))
    ids = [x.strip().lower().replace("-", "") for x in row.split("|")[2].split(",")]
    found = []
    for one in ids:
        match = next((p.stem for p in sorted(EXAMPLES.glob(f"{one}_*.bpmn"))), None)
        assert match, f"묶음에 적힌 {one}에 맞는 예제 파일이 없다"
        found.append(match)
    return found


M3 = bundle()


# ─────────────────────────── 스텁 모델 ───────────────────────────


#: BX-01이 쓰는 발주 대장 — 지급 2건·보류 5건·미청구 2건이 나오게 짰다.


#: 청구서 7장 — 지급 2(PO-1·PO-2), 미등록 1, 금액 불일치 1, 미입고 1, 중복 2(PO-6).
#: 「문제 없는 달」 — 보류가 없어야 한다.


@pytest.fixture(scope="module")
def model() -> Iterator[StubModel]:
    with StubModel(canned) as made:
        yield made


@pytest.fixture(scope="session")
def app() -> Any:
    from PySide6.QtWidgets import QApplication

    try:
        return QApplication.instance() or QApplication([])
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Qt를 띄울 수 없다: {type(e).__name__}: {e}")


# ─────────────────────────── 표본 파일 ───────────────────────────


# ─────────────────────────── 돌리기 ───────────────────────────


def studio(tmp_path: Path, example: str, model: StubModel) -> tuple[BpmProcess, Settings]:
    data = tmp_path / "studio"
    settings = replace(
        Settings(), data_dir=data, llm_base_url=model.base_url, llm_model="stub", readable_dirs=()
    )
    made = Workspace(settings.workspace_dir).ensure().import_example(EXAMPLES, example)
    # 상대 경로의 기준은 **출력 폴더**다 (ADR-0026) — 표본을 거기에 만든다.
    outputs = settings.outputs_dir / made.id
    outputs.mkdir(parents=True, exist_ok=True)
    make_samples(outputs)
    return made, settings


def drive(run: CaseRun, *, timeout_ms: int = 30_000) -> Outcome:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    box: list[Outcome] = []
    def done(outcome: Outcome) -> None:
        box.append(outcome)
        loop.quit()

    run.ended.connect(done)
    QTimer.singleShot(timeout_ms, loop.quit)
    run.start()
    loop.exec()
    if not box:
        pytest.fail(f"시험 실행이 {timeout_ms}ms 안에 끝나지 않았다")
    return box[0]


def ai_tasks(example: str) -> list[str]:
    """그 예제의 AI 태스크 노드 id — 재생이 있어야 하는 자리들."""
    found = read_process((EXAMPLES / f"{example}.bpmn").read_text(encoding="utf-8"))
    return [n.id for n in found.all_nodes() if n.prop("aiTask") is not None]


def run_all(
    tmp_path: Path, example: str, model: StubModel, *, mode: str = AUTONOMOUS
) -> list[tuple[Case, Outcome]]:
    made, settings = studio(tmp_path, example, model)
    definition = made.entry_definition
    assert definition is not None
    # 웹훅은 **시험 수신기로만** 간다 (메인 창도 실행 전에 이것을 켠다).
    receiver = Receiver(port=0).start()
    out = []
    try:
        for case in read_cases(made, definition):
            if case.manual:
                continue  # 사람이 창을 보는 케이스 — 자동으로 돌릴 것이 아니다
            plan = Plan(
                process=made, definition=definition, case=case, mode=mode, settings=replace(settings)
            )
            out.append((case, drive(CaseRun(plan, receiver))))
    finally:
        receiver.stop()
    return out


#: 아직 초록이 아닌 예제와 **그 이유**. 비어 있으면 묶음이 다 돈다는 뜻이다.
#:
#: 하나라도 새로 막히면 여기에 **이유를 적고** 넣는다. 조용히 빼면 묶음이 거짓말을 한다.
REMAINING: dict[str, str] = {}

#: 케이스가 모두 통과하는 예제. 줄어들면 회귀다.
GREEN = [one for one in M3 if one not in REMAINING]


def test_the_bundle_is_read_from_the_examples() -> None:
    """묶음 목록을 사람이 옮겨 적지 않는다 — 어긋나는 순간 시험이 거짓말을 한다."""
    assert len(M3) == 24
    assert set(REMAINING) <= set(M3), "남은 목록에 묶음 밖 예제가 있다"
    assert len(GREEN) == 24, f"초록이 {len(GREEN)}개다 — 막힌 것이 있으면 REMAINING에 이유를 적는다"


@pytest.mark.parametrize("example", GREEN)
def test_an_m3_example_passes_all_its_cases(
    app: Any, tmp_path: Path, model: StubModel, example: str
) -> None:
    """케이스가 **모두 통과**한다 (기대 결과가 없는 케이스는 비교하지 않는다)."""
    results = run_all(tmp_path, example, model)
    assert results, f"{example}: 돌릴 케이스가 없다"
    bad = [(c.name, o.verdict, o.detail) for c, o in results if o.verdict not in (PASS, NO_EXPECT)]
    assert not bad, f"{example}: {bad}"


@pytest.mark.parametrize("example", sorted(REMAINING))
def test_a_remaining_example_still_fails_for_the_written_reason(
    app: Any, tmp_path: Path, model: StubModel, example: str
) -> None:
    """아직 안 되는 것은 **안 된다고 적어 둔다** — 조용히 초록이 되면 목록이 썩는다."""
    results = run_all(tmp_path, example, model)
    bad = [(c.name, o.verdict) for c, o in results if o.verdict not in (PASS, NO_EXPECT)]
    assert bad, f"{example}: 이제 통과한다 — REMAINING에서 지운다 ({REMAINING[example]})"


# ─────────────────────────── 결정 수행 (재생) ───────────────────────────

#: AI 태스크가 있어도 **배우는 것이 없는** 예제와 그 이유.
NO_LEARNING = {
    "fx08_error_boundary": "AI 태스크가 실패하는 길만 시험한다 — 실패한 수행은 배우지 않는다",
}

#: AI 태스크가 있고 배울 거리도 있는 예제 — 재생을 볼 수 있다.
WITH_AI = [one for one in GREEN if ai_tasks(one) and one not in NO_LEARNING]


def test_some_of_the_bundle_has_ai_tasks() -> None:
    """재생 시험이 **아무것도 안 돌리는** 일을 막는다."""
    assert len(WITH_AI) >= 8, WITH_AI


@pytest.mark.parametrize("example", WITH_AI)
def test_the_same_cases_pass_again_as_a_replay(
    app: Any, tmp_path: Path, model: StubModel, example: str
) -> None:
    """**자율 수행 → 결정 수행**. 로드맵 M3 인수 기준의 남은 반쪽이다.

    자율 수행이 배운 것을 Studio가 패키지(`memory/specs.json`)에 적고, 결정 수행이 그것을
    되밟는다 (ADR-0028). 보는 것 둘.

    1. **판정이 같다** — 재생이 결과를 바꾸면 운영 실행이 개발 실행과 달라진다.
    2. **정말 되밟았다** — `node_state: replayed`가 남는다 (C3 `replayed_tasks`가 센다).
       이것을 안 보면 「재생이 안 되고 그냥 또 자율로 돌았다」를 통과로 읽는다.
    """
    made, settings = studio(tmp_path, example, model)
    definition = made.entry_definition
    assert definition is not None
    replayed_at_least_once: list[str] = []
    receiver = Receiver(port=0).start()
    try:
        for case in read_cases(made, definition):
            if case.manual:
                continue
            first = drive(CaseRun(_plan(made, definition, case, settings, AUTONOMOUS), receiver))
            again = drive(CaseRun(_plan(made, definition, case, settings, DETERMINISTIC), receiver))

            assert again.verdict == first.verdict, f"{example}/{case.name}: {again.detail}"
            # **배운 것이 있을 때만** 되밟을 거리가 있다 — 조건 때문에 AI 태스크를 지나지
            # 않거나(BX-11 유찰·FX-09 빈 목록) 실패한 길(FX-08)은 배우는 것이 없다.
            if first.learned:
                assert _replayed(again) >= 1, f"{example}/{case.name}: 되밟은 AI 태스크가 없다"
                replayed_at_least_once.append(f"{example}/{case.name}")
    finally:
        receiver.stop()
    assert replayed_at_least_once, f"{example}: 되밟은 케이스가 하나도 없다 (배운 것이 없다)"


def _plan(made: BpmProcess, definition: Any, case: Case, settings: Settings, mode: str) -> Plan:
    return Plan(process=made, definition=definition, case=case, mode=mode, settings=replace(settings))


def _replayed(outcome: Outcome) -> int:
    """`node_state: replayed`가 몇 번 남았나 (C3)."""
    if outcome.run is None:
        return 0
    return sum(
        1
        for event in outcome.run.log.events
        if event.kind == "node_state" and event.data.get("state") == "replayed"
    )
