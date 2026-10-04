"""Studio 작업 폴더·탐색기 모델 (STU-02·STU-05) — 화면 없이 도는 것만.

**디스크가 원본이다** — 화면은 `Workspace.groups()`를 읽어 그린다. 그래서 여기서 보는 것은
폴더 모양(C1 패키지와 같은 이름)과 가져오기·만들기 규칙이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chaeksas.studio.workspace import (
    DEFAULT_GROUP,
    Workspace,
    WorkspaceError,
    read_record,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"

MINIMAL = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="{process_id}" name="{name}">
    <bpmn:extensionElements><chk:process>{{}}</chk:process></bpmn:extensionElements>
    <bpmn:startEvent id="Start_1"/>
    <bpmn:endEvent id="End_1"/>
    <bpmn:sequenceFlow id="f1" sourceRef="Start_1" targetRef="End_1" />
  </bpmn:process>
</bpmn:definitions>
"""


def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "workspace").ensure()


def test_a_new_workspace_always_has_the_default_group(tmp_path: Path) -> None:
    """STU-02 — 「기본」은 맨 위에 있고 지울 수 없다."""
    found = workspace(tmp_path)
    assert [g.name for g in found.groups()] == [DEFAULT_GROUP]
    assert (found.root / DEFAULT_GROUP).is_dir()


def test_creating_a_process_lays_out_the_package_folders(tmp_path: Path) -> None:
    """C1 패키지와 같은 이름을 쓴다 — 「패키지로 내보내기」가 거의 복사가 되게."""
    found = workspace(tmp_path)
    made = found.create("finance.reconcile", name="청구서 대사", version="1.2.0")
    assert made.folder == found.root / DEFAULT_GROUP / "finance.reconcile"
    assert (made.folder / "process").is_dir() and (made.folder / "cases").is_dir()
    assert read_record(made.folder)["name"] == "청구서 대사"
    assert made.definitions == [], "정의 파일은 캔버스가 저장할 때 생긴다"


@pytest.mark.parametrize("bad", ["Finance", "-nope", "큰이름", "has space", ""])
def test_a_bad_id_is_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(WorkspaceError, match="id는"):
        workspace(tmp_path).create(bad)


def test_the_same_id_twice_is_refused(tmp_path: Path) -> None:
    found = workspace(tmp_path)
    found.create("a.b")
    with pytest.raises(WorkspaceError, match="같은 id"):
        found.create("a.b")


def test_saving_a_definition_writes_utf8_and_shows_up_in_the_tree(tmp_path: Path) -> None:
    found = workspace(tmp_path)
    made = found.create("a.b", name="한글 이름")
    path = found.save_definition(made, "main.bpmn", MINIMAL.format(process_id="Proc_a_b", name="한글 이름"))
    assert path.read_text(encoding="utf-8").count("한글 이름") == 1

    again = found.find("a.b")
    assert again is not None
    assert [d.name for d in again.definitions] == ["main"]
    entry = again.entry_definition
    assert entry is not None and entry.process is not None and entry.process.id == "Proc_a_b"


def test_a_definition_that_does_not_read_keeps_its_reason(tmp_path: Path) -> None:
    """읽지 못한 정의를 **숨기지 않는다** — 탐색기가 사유를 보인다."""
    found = workspace(tmp_path)
    made = found.create("a.b")
    (made.folder / "process" / "broken.bpmn").write_text("<not xml", encoding="utf-8")
    again = found.find("a.b")
    assert again is not None
    (broken,) = again.definitions
    assert broken.process is None and broken.problem


def test_a_non_bpmn_definition_name_is_refused(tmp_path: Path) -> None:
    found = workspace(tmp_path)
    made = found.create("a.b")
    with pytest.raises(WorkspaceError, match=r"`\.bpmn`"):
        found.save_definition(made, "main.xml", MINIMAL.format(process_id="P", name="x"))


def test_groups_sort_with_the_default_first(tmp_path: Path) -> None:
    found = workspace(tmp_path)
    found.create_group("재무")
    found.create_group("가나")
    assert [g.name for g in found.groups()] == [DEFAULT_GROUP, "가나", "재무"]


def test_a_duplicate_group_is_refused(tmp_path: Path) -> None:
    found = workspace(tmp_path)
    found.create_group("재무")
    with pytest.raises(WorkspaceError, match="같은 이름의 그룹"):
        found.create_group("재무")


# ─────────────────────────── 예제 가져오기 ───────────────────────────


def test_importing_an_example_brings_its_dmn_and_cases(tmp_path: Path) -> None:
    """STU-01 파일 메뉴 — BPMN·DMN·케이스를 함께 가져온다. **예제 폴더는 읽기만** 한다."""
    before = sorted(p.name for p in EXAMPLES.iterdir())
    found = workspace(tmp_path)
    made = found.import_example(EXAMPLES, "fx02_business_rule")

    assert made.id == "fx02-business-rule"
    assert [d.path.name for d in made.definitions] == ["fx02_business_rule.bpmn"]
    assert (made.folder / "process" / "discount_policy.dmn").is_file(), "규칙 태스크가 쓰는 DMN"
    assert (made.folder / "cases" / "fx02_business_rule.cases.json").is_file()
    assert sorted(p.name for p in EXAMPLES.iterdir()) == before, "예제 폴더는 건드리지 않는다"


def test_an_imported_example_hands_the_engine_what_it_needs(tmp_path: Path) -> None:
    """`RunEnv`가 바라는 모양 그대로 — DMN 결정과 호출 대상."""
    made = workspace(tmp_path).import_example(EXAMPLES, "fx02_business_rule")
    assert "discount_policy" in made.decisions()
    assert "Proc_fx02_business_rule" in made.processes()
    assert made.memory().specs == [], "아직 배운 것이 없다"


def test_importing_an_example_that_is_not_there_says_so(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError, match="예제를 찾지 못했다"):
        workspace(tmp_path).import_example(EXAMPLES, "없는예제")


def test_the_record_is_json_with_utf8(tmp_path: Path) -> None:
    found = workspace(tmp_path)
    made = found.create("a.b", name="한글")
    raw = json.loads((made.folder / "process.json").read_text(encoding="utf-8"))
    assert raw == {"schema": 1, "id": "a.b", "name": "한글", "version": "0.1.0", "entry": "main.bpmn"}
