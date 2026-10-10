"""Studio 캔버스 — QtWebEngine 안의 bpmn-js가 **진짜로** 돌아가는지 (ADR-0022·ADR-0029).

S3 스파이크가 Windows에서 확인한 것을 제품 코드로 옮겨 다시 본다: 우리 BPMN(C14 `chk:*`,
한글 JSON 본문)이 불러오기·저장 왕복에서 **의미상** 보존되는가. bpmn-js는 DI 순서를 바꾸고
기본값 속성을 빼므로 **글자 비교를 쓰지 않는다** (ADR-0022).

WebEngine이 뜨지 않는 환경(그래픽 라이브러리가 없는 최소 컨테이너)에서는 건너뛴다 — Qt 테마
시험과 같은 태도다. CI는 필요한 라이브러리를 깔고 실제로 돈다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

# PySide6를 불러오기 **전에** 정한다. 화면 없이, GPU 없이, 샌드박스 없이 돌린다.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from chaeksas.contracts.bpmn_ext import read_process  # noqa: E402
from chaeksas.studio.canvas import WEB_DIR, Canvas, CanvasError  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"

#: 왕복시켜 볼 예제 — `chk:*` 13종이 골고루 들어가게 고른다.
SAMPLES = (
    "fx02_business_rule",  # chk:rule
    "fx07_email",  # chk:email + chk:dataOutput
    "bx03_expense_approval",  # chk:approval + 경계 타이머 + chk:webhook
    "bx05_month_end_close",  # chk:receive + 이정표 + 병렬
)


@pytest.fixture(scope="session")
def app() -> Any:
    """QApplication 하나 (한 프로세스에 하나만). WebEngine이 못 뜨면 건너뛴다."""
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    try:
        found = QApplication.instance() or QApplication([])
        from PySide6.QtWebEngineWidgets import QWebEngineView

        QWebEngineView()
    except Exception as e:  # noqa: BLE001 — 환경 문제면 건너뛴다
        pytest.skip(f"QtWebEngine을 띄울 수 없다: {type(e).__name__}: {e}")
    return found


@pytest.fixture
def canvas(app: Any) -> Any:
    """뜬 캔버스 하나. `opened`가 올 때까지 기다린다."""
    from PySide6.QtCore import QEventLoop, QTimer

    found = Canvas()
    loop = QEventLoop()
    found.opened.connect(loop.quit)
    QTimer.singleShot(30_000, loop.quit)
    found.boot()
    loop.exec()
    if not found.live:
        pytest.skip("캔버스가 30초 안에 뜨지 않았다 (WebEngine이 이 환경에서 막혀 있다)")
    return found


def meaning(xml: str) -> tuple[Any, ...]:
    """글자가 아니라 **뜻**으로 견준다 (ADR-0022 — bpmn-js가 모양을 바꾼다)."""
    found = read_process(xml)
    return (
        found.id,
        sorted(n.id for n in found.all_nodes()),
        sorted((f.source, f.target) for f in found.flows),
        sorted((n.id, name) for n in found.all_nodes() for name in n.props),
    )


def test_the_vendored_bpmn_js_is_in_place() -> None:
    """ADR-0029 — 배포본은 커밋된 생성물이다. 없으면 캔버스가 뜰 수 없다."""
    assert (WEB_DIR / "index.html").is_file()
    assert (WEB_DIR / "chk-moddle.js").is_file()
    assert (WEB_DIR / "vendor" / "bpmn-modeler.production.min.js").is_file()
    assert "bpmn-js " in (WEB_DIR / "vendor" / "VERSION.txt").read_text(encoding="utf-8")


def test_a_missing_canvas_says_how_to_build_it(app: Any, tmp_path: Path) -> None:
    """생성물이 없으면 **무엇을 돌려야 하는지** 말한다 (ADR-0029)."""
    with pytest.raises(CanvasError, match="bpmn-canvas"):
        Canvas().boot(tmp_path)


@pytest.mark.parametrize("name", SAMPLES)
def test_an_example_survives_the_canvas_round_trip(canvas: Any, name: str) -> None:
    """C14 「표준 BPMN 도구(bpmn-js)로 열고 그릴 수 있어야 한다」 — `chk:*`가 살아남는다."""
    original = (EXAMPLES / f"{name}.bpmn").read_text(encoding="utf-8")
    found = canvas.call_sync("importXML", original)
    assert found.get("warnings") == [], found.get("warnings")

    again = canvas.save_xml()
    assert meaning(again) == meaning(original)
    assert "chk:" in again, "확장 요소가 그대로 있다"


def test_the_canvas_reports_what_it_holds(canvas: Any) -> None:
    canvas.call_sync("importXML", (EXAMPLES / "fx02_business_rule.bpmn").read_text(encoding="utf-8"))
    stats = canvas.call_sync("stats")
    assert stats["elements"] > 4
    assert stats["dirty"] is False, "불러온 직후는 「저장 안 한 변경」이 아니다"


def test_an_empty_diagram_gets_our_process_id_and_name(canvas: Any) -> None:
    """STU-05 — 새 BPM 프로세스는 빈 정의 하나로 시작한다."""
    canvas.create_empty("Proc_new_one", "새 업무")
    found = read_process(canvas.save_xml())
    assert found.id == "Proc_new_one" and found.name == "새 업무"
    assert [n.kind for n in found.nodes] == ["startEvent"]


def test_a_bad_xml_comes_back_as_an_error_not_a_crash(canvas: Any) -> None:
    """JS 쪽 예외는 `CanvasError`로 올라온다 — 창이 죽지 않는다."""
    with pytest.raises(CanvasError):
        canvas.call_sync("importXML", "<not bpmn")


def test_an_unknown_function_says_so(canvas: Any) -> None:
    with pytest.raises(CanvasError, match="모르는 함수"):
        canvas.call_sync("없는함수")


def test_an_extension_task_keeps_its_kind_through_an_edit(canvas: Any) -> None:
    """`chk:task`의 `type`·`extension`은 **XML 속성**이다 (C14) — 고쳐도 날아가면 안 된다.

    날아가면 패키지가 그 확장을 요구하지 않게 되고(C1), 실행할 때 「모르는 태스크」가 된다.
    """
    canvas.create_empty("Proc_ui", "UI 업무")
    made = canvas.call_sync(
        "setProperties",
        "Proc_ui",
        {
            "chk": {
                "task": json.dumps(
                    {"type": "ui_task", "extension": "ui-automation", "data": {"page_id": "erp.order.form"}},
                    ensure_ascii=False,
                )
            }
        },
    )
    assert made.get("found") is True

    found = canvas.call_sync("properties", "Proc_ui")
    body = json.loads(found["chk"]["task"])
    assert body["type"] == "ui_task" and body["extension"] == "ui-automation"
    assert body["data"] == {"page_id": "erp.order.form"}

    # 한 번 더 고쳐도 종류가 남는다 (STU-13이 `data`만 바꿔 보낸다).
    canvas.call_sync(
        "setProperties",
        "Proc_ui",
        {"chk": {"task": json.dumps({**body, "data": {"page_id": "erp.order.list"}}, ensure_ascii=False)}},
    )
    again = json.loads(canvas.call_sync("properties", "Proc_ui")["chk"]["task"])
    assert again["type"] == "ui_task", "고쳐도 종류가 그대로다"
    assert again["data"]["page_id"] == "erp.order.list"

    xml = canvas.save_xml()
    assert 'type="ui_task"' in xml and 'extension="ui-automation"' in xml, "XML 속성으로 남는다"


def added(canvas: Any, chk: dict[str, str], name: str = "주문 등록") -> str:
    """STU-03 「캔버스에 추가」를 한 번 — 만들어진 노드 id (답이 올 때까지 기다린다)."""
    from PySide6.QtCore import QEventLoop

    loop = QEventLoop()
    box: dict[str, Any] = {}

    def done(found: dict[str, Any]) -> None:
        box.update(found)
        loop.quit()

    canvas.create_task("bpmn:ServiceTask", name, chk, then=done)
    loop.exec()
    assert box.get("ok"), box
    return str(box["id"])


def test_a_resource_becomes_a_node_in_one_undo_step(canvas: Any) -> None:
    """STU-03 「캔버스에 추가」 — `chk:*`를 달고 **한 번에** 만든다.

    만든 뒤에 고치면 실행 취소가 두 걸음이 되어 사람이 한 번 되돌렸는데 빈 태스크가 남는다.
    """
    canvas.create_empty("Proc_add", "추가 시험")
    before = canvas.call_sync("stats")["elements"]
    body = {"type": "ui_task", "extension": "ui-automation", "data": {"page_id": "erp.order.form"}}
    node_id = added(canvas, {"task": json.dumps(body, ensure_ascii=False)})

    found = read_process(canvas.save_xml())
    node = next(n for n in found.all_nodes() if n.id == node_id)
    assert node.kind == "serviceTask" and node.name == "주문 등록"
    task = node.prop("task")
    assert task is not None
    assert (task.type, task.extension) == ("ui_task", "ui-automation")
    assert task.data == {"page_id": "erp.order.form"}

    canvas.call_sync("undo")
    assert canvas.call_sync("stats")["elements"] == before, "한 번 되돌리면 흔적이 없다"
    assert node_id not in [n.id for n in read_process(canvas.save_xml()).all_nodes()]


def test_a_service_app_operation_becomes_a_service_call(canvas: Any) -> None:
    """서비스 앱 작업은 `chk:serviceCall`이다 (C14) — 같은 명령이 둘 다 만든다."""
    canvas.create_empty("Proc_call", "호출 시험")
    body = {"app_id": "svc-invoice", "operation": "issue"}
    node_id = added(canvas, {"serviceCall": json.dumps(body, ensure_ascii=False)}, name="세금계산서 issue")
    call = next(n for n in read_process(canvas.save_xml()).all_nodes() if n.id == node_id).prop("serviceCall")
    assert call is not None
    assert (call.app_id, call.operation) == ("svc-invoice", "issue")
    assert call.key_ref is None, "키 참조는 BPM 프로세스에서 상속한다 (ADR-0013)"


def shape_at(xml_text: str, node_id: str) -> tuple[str | None, str | None] | None:
    """저장된 XML의 DI에서 그 노드가 놓인 자리 (시험만 쓴다 — 캔버스에 길을 더하지 않는다)."""
    import xml.etree.ElementTree as ET  # noqa: N817

    di = "{http://www.omg.org/spec/BPMN/20100524/DI}"
    dc = "{http://www.omg.org/spec/DD/20100524/DC}"
    for shape in ET.fromstring(xml_text).iter(f"{di}BPMNShape"):
        if shape.get("bpmnElement") != node_id:
            continue
        bounds = shape.find(f"{dc}Bounds")
        return (bounds.get("x"), bounds.get("y")) if bounds is not None else None
    return None


def test_two_added_nodes_do_not_land_on_the_same_spot(canvas: Any) -> None:
    """잇달아 더해도 한 점에 쌓이지 않는다 — 겹치면 사람이 하나만 있는 줄 안다."""
    canvas.create_empty("Proc_two", "둘 시험")
    body = json.dumps({"app_id": "svc-invoice", "operation": "issue"}, ensure_ascii=False)
    first = added(canvas, {"serviceCall": body}, name="하나")
    second = added(canvas, {"serviceCall": body}, name="둘")
    xml = canvas.save_xml()
    assert shape_at(xml, first) is not None
    assert shape_at(xml, first) != shape_at(xml, second)
