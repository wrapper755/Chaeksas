"""STU-04 속성 패널과 실행 전 검사 화면 (M3 조각 3e-2).

여기서 거듭 보는 것은 셋이다.

1. **JSON 탭이 C14 모델로 검증한다** — 저장한 뒤 실행 전 검사에서야 아는 것보다 낫다 (B1과
   같은 눈을 편집하는 자리에 둔다).
2. **적용은 캔버스(`modeling`)로 간다** — 그래야 실행 취소와 「저장 안 한 변경」이 함께 움직인다.
   그 왕복을 진짜 bpmn-js에 대고 확인한다.
3. **검사는 오류와 경고를 함께** 내고 **오류만 막는다** (C14 §검사 규칙).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from chaeksas.contracts.bpmn_ext import read_process  # noqa: E402
from chaeksas.studio.preflight import CLEAN, inspect, node_of, summarize  # noqa: E402
from chaeksas.studio.properties import (  # noqa: E402
    CONDITION_KINDS,
    SCRIPT_KINDS,
    as_text,
    check_chk,
    kind_label,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"


# ─────────────────────────── JSON 탭의 검증 (화면 없이) ───────────────────────────


def test_an_empty_json_tab_is_fine() -> None:
    assert check_chk("   ") == ({}, None)


def test_a_good_chk_element_passes_and_comes_back_tidy() -> None:
    found, problem = check_chk('{"aiTask": {"goal": "뽑는다", "domain": "llm"}}')
    assert problem is None
    assert json.loads(found["aiTask"])["domain"] == "llm"


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        ("{not json", "JSON이 아닙니다"),
        ("[1, 2]", "객체여야 합니다"),
        ('{"없는것": {}}', "모르는 `chk:` 요소입니다"),
        ('{"aiTask": {"goal": "x"}}', "chk:aiTask"),  # domain이 빠졌다
        ('{"rule": {"input": {}}}', "chk:rule"),  # decision이 빠졌다
    ],
)
def test_a_bad_chk_element_says_what_is_wrong(text: str, complaint: str) -> None:
    found, problem = check_chk(text)
    assert found == {}
    assert problem is not None and complaint in problem


def test_an_extension_task_keeps_its_xml_attributes_apart() -> None:
    """`chk:task`만 `type`·`extension`이 XML 속성이다 (C14 §태스크 종류)."""
    found, problem = check_chk(
        '{"task": {"type": "ui_task", "extension": "ui-automation", "data": {"page_id": "p"}}}'
    )
    assert problem is None
    assert json.loads(found["task"]) == {
        "type": "ui_task",
        "extension": "ui-automation",
        "data": {"page_id": "p"},
    }, "종류까지 함께 간다 — 캔버스가 XML 속성에 쓴다"


def test_unreadable_stored_text_is_shown_not_hidden() -> None:
    """캔버스에 깨진 본문이 있어도 **글 그대로** 보여 준다 — 조용히 지우지 않는다."""
    assert "망가짐" in as_text({"aiTask": "망가짐{"})


def test_the_header_names_the_kind_in_korean() -> None:
    assert kind_label("UserTask") == "결재"
    assert kind_label("BusinessRuleTask") == "규칙 (DMN)"
    assert kind_label("Mystery") == "Mystery", "모르는 것은 원문 그대로"


def test_only_the_right_elements_get_a_condition_or_script_row() -> None:
    assert "SequenceFlow" in CONDITION_KINDS and "ScriptTask" in SCRIPT_KINDS
    assert "ServiceTask" not in CONDITION_KINDS


# ─────────────────────────── 실행 전 검사 (화면 없이) ───────────────────────────


def test_a_clean_example_has_nothing_to_say() -> None:
    process = read_process((EXAMPLES / "fx02_business_rule.bpmn").read_text(encoding="utf-8"))
    # DMN을 주지 않으면 B14의 대조를 건너뛴다 — 그래도 깨끗해야 한다.
    assert summarize(inspect(process)) == CLEAN


def test_errors_and_warnings_are_counted_apart() -> None:
    """C14 — 오류만 실행을 막고, 경고는 보여 주고 사람이 판단한다."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="t">
    <bpmn:startEvent id="Start"/>
    <bpmn:scriptTask id="T"><bpmn:script>값 = 없는변수</bpmn:script></bpmn:scriptTask>
    <bpmn:sendTask id="Send"><bpmn:extensionElements>
      <chk:webhook>{"url": "https://x.test", "body": "all"}</chk:webhook>
    </bpmn:extensionElements></bpmn:sendTask>
    <bpmn:endEvent id="End"/>
    <bpmn:sequenceFlow id="f1" sourceRef="Start" targetRef="T" />
    <bpmn:sequenceFlow id="f2" sourceRef="T" targetRef="Send" />
    <bpmn:sequenceFlow id="f3" sourceRef="Send" targetRef="End" />
    <bpmn:dataObjectReference id="D"><bpmn:extensionElements>
      <chk:dataOutput>{"path": "a.md", "format": "md"}</chk:dataOutput>
    </bpmn:extensionElements></bpmn:dataObjectReference>
  </bpmn:process>
</bpmn:definitions>"""
    found = inspect(read_process(xml))
    rules = {v.rule for v in found}
    assert "B5" in rules, "파일 출력에 store_as가 없다 (막음)"
    assert "B13" in rules, "웹훅이 변수를 전부 보낸다 (경고)"
    assert "막는 것" in summarize(found) and "경고" in summarize(found)


def test_a_helper_called_the_wrong_way_shows_up_as_b15() -> None:
    """B15 — 작성자가 **실행할 때가 아니라 검사 탭에서** 본다 (C14).

    `validate()`는 도우미 함수를 모른다 (구현이 `core`에 있다) — Studio가 두 검사를 이어 붙인다.
    """
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="t">
    <bpmn:startEvent id="Start"/>
    <bpmn:scriptTask id="Task_Merge"><bpmn:script>주제별 = 세기(전체, '주제')</bpmn:script></bpmn:scriptTask>
    <bpmn:endEvent id="End"/>
    <bpmn:sequenceFlow id="f1" sourceRef="Start" targetRef="Task_Merge" />
    <bpmn:sequenceFlow id="f2" sourceRef="Task_Merge" targetRef="End" />
  </bpmn:process>
</bpmn:definitions>"""
    process = read_process(xml)
    found = [v for v in inspect(process) if v.rule == "B15"]
    assert len(found) == 1, found
    assert found[0].blocks, "부를 수 없는 호출은 경고가 아니라 막는 것이다"
    assert "그렇게 부를 수 없다" in found[0].message
    assert node_of(process, found[0]) == "Task_Merge", "검사 탭에서 그 노드로 뛴다"


def test_a_violation_points_at_a_node_so_the_canvas_can_jump() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="t">
    <bpmn:startEvent id="Start"/>
    <bpmn:userTask id="Approve_Hold"><bpmn:extensionElements>
      <chk:approval>{"title": "t", "show": "보류건수"}</chk:approval>
    </bpmn:extensionElements></bpmn:userTask>
    <bpmn:endEvent id="End"/>
    <bpmn:sequenceFlow id="f1" sourceRef="Start" targetRef="Approve_Hold" />
    <bpmn:sequenceFlow id="f2" sourceRef="Approve_Hold" targetRef="End" />
  </bpmn:process>
</bpmn:definitions>"""
    process = read_process(xml)
    found = inspect(process)
    assert any(node_of(process, v) == "Approve_Hold" for v in found)


def test_the_workspace_feeds_b14_with_dmn_and_call_targets(tmp_path: Path) -> None:
    """**혼자서는 할 수 없는 검사는 인자로 받는다** — Studio는 늘 준다 (그래야 B14가 돈다)."""
    from chaeksas.studio.workspace import Workspace  # noqa: PLC0415

    made = Workspace(tmp_path / "w").ensure().import_example(EXAMPLES, "fx02_business_rule")
    entry = made.entry_definition
    assert entry is not None and entry.process is not None
    assert "discount_policy" in made.decisions(), "DMN을 함께 가져왔다"
    assert [v.rule for v in inspect(entry.process, made) if v.rule == "B14"] == []


# ─────────────────────────── 사전 점검 (이 PC에서 돌 수 있나) ───────────────────────────
#
# 그림 검사(B 규칙)와 **같은 관문**에 들어간다 — 용어집이 사전 점검에 「서비스 앱 키 참조가 이 PC에
# 있는지」를 넣어 두었다. 「실행 전 검사」 하나만 보면 돌릴 수 있는지 알 수 있어야 한다.


def opened(tmp_path: Path, example: str) -> Any:
    from chaeksas.studio.workspace import Workspace  # noqa: PLC4015,PLC0415

    return Workspace(tmp_path / "w").ensure().import_example(EXAMPLES, example)


def studio_extensions() -> Any:
    from chaeksas.studio.extensions import Extensions  # noqa: PLC0415

    return Extensions.load()


def test_a_missing_service_app_key_blocks_the_run(tmp_path: Path) -> None:
    """ADR-0013 §사전 점검 — 키가 없으면 그 태스크에서 죽는다. **시작하기 전에** 막는다."""
    from chaeksas.core.preflight import MISSING_KEYS  # noqa: PLC0415
    from chaeksas.studio.preflight import KEY_FIX_HINT, PREFLIGHT_RULE, readiness  # noqa: PLC0415

    found = readiness(opened(tmp_path, "bx36_legacy_migration"), key_value=lambda _ref: None)

    assert [v.code for v in found] == [MISSING_KEYS]
    only = found[0]
    assert only.blocks
    assert only.rule == PREFLIGHT_RULE, "B 규칙과 갈라 보여야 한다 (그림의 흠이 아니다)"
    assert only.items == ["it-crm"], "무엇이 빠졌는지 말해야 고칠 수 있다"
    assert KEY_FIX_HINT in only.message, "어디서 고치는지도 말한다 (STU-10)"


def test_registering_the_key_clears_it(tmp_path: Path) -> None:
    from chaeksas.studio.preflight import readiness  # noqa: PLC0415

    found = readiness(opened(tmp_path, "bx36_legacy_migration"), key_value=lambda _ref: "chk_svc_x")
    assert not [v for v in found if v.blocks]


def test_a_diagram_that_calls_nothing_says_nothing(tmp_path: Path) -> None:
    """**거짓 경고를 막는 자리다.** 서비스 앱도 UI도 쓰지 않는 그림에는 할 말이 없다.

    조건 없이 한마디씩 하면 B11에서 겪은 일이 되풀이된다 — 거짓 경고가 쌓여 아무도 읽지 않는다.
    """
    from chaeksas.studio.preflight import readiness  # noqa: PLC0415

    ext = studio_extensions()
    found = readiness(
        opened(tmp_path, "fx19_manual_task_pc"),
        key_value=lambda _ref: None,
        host=ext.host,
        context=ext.context,
    )
    assert found == [], [str(v) for v in found]


def test_unsaved_edits_are_admitted_not_hidden(tmp_path: Path) -> None:
    """요구 사항은 **저장된 파일**에서 모은다 — 방금 더한 키 참조를 「없다」고 하면 엉뚱한 데를 고친다."""
    from chaeksas.studio.preflight import UNSAVED, readiness  # noqa: PLC0415

    found = readiness(opened(tmp_path, "fx19_manual_task_pc"), key_value=lambda _ref: None, dirty=True)

    assert [v.message for v in found] == [UNSAVED]
    assert not found[0].blocks, "저장하지 않았다는 것으로 실행을 막지는 않는다"


def test_a_broken_extension_check_warns_without_blocking(tmp_path: Path) -> None:
    """`PreflightCheck` 규약 — **점검이 실행을 막지 않는다.** 다만 조용히 넘어가지도 않는다."""
    from chaeksas.core.extensions import Contribution, ExtensionHost  # noqa: PLC0415
    from chaeksas.studio.preflight import readiness  # noqa: PLC0415

    class Broken:
        def check(self, target: Any) -> Any:
            raise NotImplementedError("아직 못 만들었다")

    class Host(ExtensionHost):
        def preflight_checks(self) -> Any:
            return [Contribution(extension_id="x", extension_version="1.0.0", value=Broken())]

    found = readiness(
        opened(tmp_path, "fx19_manual_task_pc"),
        key_value=lambda _ref: None,
        host=Host(),
        context=lambda _id: object(),  # type: ignore[arg-type,return-value]
    )
    assert [v.code for v in found] == ["check_skipped"]
    assert not found[0].blocks
    assert "아직 못 만들었다" in found[0].message


def test_the_ui_page_check_is_quiet_when_no_page_is_used() -> None:
    """확장의 점검도 **쓰는 것이 없으면 아무 말도 하지 않는다** (거짓 경고 방지).

    아직 레지스트리(C9)를 부를 수 없어 「모른다」밖에 할 말이 없는데, 그것을 조건 없이 내면
    UI를 쓰지 않는 그림 전부에 경고가 뜬다.
    """
    from chaeksas.ext.ui_automation.client.preflight import (  # noqa: PLC0415
        UNVERIFIED,
        PagesRegisteredCheck,
    )
    from chaeksas.extension_api import PreflightTarget  # noqa: PLC0415

    none = _manifest_requiring()
    assert PagesRegisteredCheck().check(PreflightTarget(extension=None, manifest=none)) == ()  # type: ignore[arg-type]

    some = _manifest_requiring({"type": "ui_page", "id": "erp.order.form"})
    (told,) = PagesRegisteredCheck().check(PreflightTarget(extension=None, manifest=some))  # type: ignore[arg-type]
    assert told.id == UNVERIFIED and told.items == ("erp.order.form",)
    assert not told.blocks, "「모른다」로 실행을 막지 않는다"


def _manifest_requiring(*resources: dict[str, str]) -> Any:
    from chaeksas.contracts.manifest import Manifest  # noqa: PLC0415

    return Manifest.model_validate(
        {
            "schema": 1,
            "kind": "bpm_process",
            "id": "t.one",
            "version": "1.0.0",
            "run_location": "pc",
            "entry": "main.bpmn",
            "content_hash": "sha256:" + "0" * 64,
            "human": {"approval_center": False, "approval_field": False, "confirmation": False},
            "built": {"by": "studio", "at": "2026-10-09T00:00:00+09:00", "core": "0.1.0", "spec_version": 1},
            "requires": {"resources": list(resources)},
        }
    )


# ─────────────────────────── 캔버스 왕복 (진짜 bpmn-js) ───────────────────────────


@pytest.fixture(scope="session")
def app() -> Any:
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    try:
        found = QApplication.instance() or QApplication([])
        from PySide6.QtWebEngineWidgets import QWebEngineView

        QWebEngineView()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"QtWebEngine을 띄울 수 없다: {type(e).__name__}: {e}")
    return found


@pytest.fixture
def canvas(app: Any) -> Any:
    from PySide6.QtCore import QEventLoop, QTimer

    from chaeksas.studio.canvas import Canvas

    found = Canvas()
    loop = QEventLoop()
    found.opened.connect(loop.quit)
    QTimer.singleShot(30_000, loop.quit)
    found.boot()
    loop.exec()
    if not found.live:
        pytest.skip("캔버스가 30초 안에 뜨지 않았다")
    found.call_sync("importXML", (EXAMPLES / "fx02_business_rule.bpmn").read_text(encoding="utf-8"))
    return found


def test_the_canvas_hands_over_what_the_panel_shows(canvas: Any) -> None:
    found = canvas.call_sync("properties", "Task_Rule")
    assert found["found"] and found["type"] == "BusinessRuleTask"
    assert found["name"] == "할인 정하기"
    assert json.loads(found["chk"]["rule"])["decision"] == "discount_policy"


def test_applying_a_name_and_a_chk_body_comes_back_in_the_saved_xml(canvas: Any) -> None:
    """적용 → 저장까지 한 바퀴. `modeling`을 거치므로 「저장 안 한 변경」도 켜진다."""
    rule = {"decision": "discount_policy", "input": {"amount": "금액", "grade": "등급"},
            "output": {"할인율": "discount"}}
    canvas.call_sync(
        "setProperties",
        "Task_Rule",
        {"name": "할인 다시", "documentation": "설명 한 줄", "chk": {"rule": json.dumps(rule, ensure_ascii=False)}},
    )
    # 저장하기 **전에** 본다 — `saveXML`이 「저장 안 한 변경」을 끈다.
    assert canvas.call_sync("stats")["dirty"] is True, "실행 취소·저장 안 한 변경이 함께 움직인다"

    again = read_process(canvas.save_xml())
    node = again.node("Task_Rule")
    assert node is not None and node.name == "할인 다시"
    assert node.prop("rule") is not None and node.prop("rule").output == {"할인율": "discount"}

    # 실행 취소가 먹는다. 표준 속성은 한 걸음이지만 `chk:*`를 함께 고쳤으면 걸음이 여럿이다.
    for _ in range(3):
        canvas.call_sync("undo")
    back = read_process(canvas.save_xml()).node("Task_Rule")
    assert back is not None and back.name == "할인 정하기"


def test_a_chk_element_can_be_added_and_removed(canvas: Any) -> None:
    loop = '{"collection": "목록", "item": "건", "collect_into": "모음"}'
    canvas.call_sync("setProperties", "Task_Price", {"chk": {"loop": loop}})
    node = read_process(canvas.save_xml()).node("Task_Price")
    assert node is not None and node.prop("loop") is not None

    canvas.call_sync("setProperties", "Task_Price", {"chk": {"loop": None}})
    node = read_process(canvas.save_xml()).node("Task_Price")
    assert node is not None and node.prop("loop") is None


def test_a_flow_condition_round_trips(canvas: Any) -> None:
    canvas.call_sync("setProperties", "Flow_02", {"condition": "할인율 > 0"})
    found = canvas.call_sync("properties", "Flow_02")
    assert found["condition"] == "할인율 > 0"
    flow = next(f for f in read_process(canvas.save_xml()).flows if f.id == "Flow_02")
    assert flow.condition == "할인율 > 0"


def test_asking_about_a_node_that_is_not_there_says_so(canvas: Any) -> None:
    assert canvas.call_sync("properties", "없는노드")["found"] is False
