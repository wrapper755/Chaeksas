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

from chaeksas.contracts.bpmn_ext import Loop, read_process  # noqa: E402
from chaeksas.studio.canvas import VIEW_PAGE, WEB_DIR, Canvas, CanvasError  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"

#: 드롭 뒤 캔버스가 답할 때까지 기다릴 시간 (ms) — 답하지 않아도 멈추지 않게 상한을 둔다.
DROP_TIMEOUT_MS = 15_000

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
    """ADR-0029 — 배포본은 커밋된 생성물이다. 없으면 캔버스가 뜰 수 없다.

    **뷰어도 함께 싣는다** (ADR-0051) — STU-03 「열기 (읽기 전용)」이 그 페이지를 띄운다.
    """
    assert (WEB_DIR / "index.html").is_file()
    assert (WEB_DIR / VIEW_PAGE).is_file()
    assert (WEB_DIR / "chk-moddle.js").is_file()
    assert (WEB_DIR / "vendor" / "bpmn-modeler.production.min.js").is_file()
    assert (WEB_DIR / "vendor" / "bpmn-navigated-viewer.production.min.js").is_file()
    assert (WEB_DIR / "vendor" / "bpmn-auto-layout.min.js").is_file()  # ADR-0088
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


def sized(canvas: Any, width: int, height: int) -> None:
    """캔버스를 그 크기로 띄우고 페이지가 크기를 받을 때까지 기다린다."""
    from PySide6.QtCore import QEventLoop, QTimer

    canvas.resize(width, height)
    canvas.show()
    loop = QEventLoop()
    QTimer.singleShot(500, loop.quit)
    loop.exec()


def test_opening_shows_the_diagram_at_normal_zoom_in_the_middle(canvas: Any) -> None:
    """STU-01 [C] — 열면 보통 크기(100%)이고, 화면에 들어가는 그림은 가운데에 온다."""
    sized(canvas, 1600, 900)
    canvas.call_sync("importXML", (EXAMPLES / "fx02_business_rule.bpmn").read_text(encoding="utf-8"))
    stats = canvas.call_sync("stats")
    view, inner = stats["view"], stats["inner"]
    assert stats["scale"] == pytest.approx(1)
    assert inner["width"] + 240 <= view["width"], "이 예제는 화면에 들어간다"
    for axis, size in (("x", "width"), ("y", "height")):
        assert inner[axis] + inner[size] / 2 == pytest.approx(view[axis] + view[size] / 2, abs=1)


def test_a_wide_diagram_starts_from_the_left_at_normal_zoom(canvas: Any) -> None:
    """그림이 화면보다 넓으면 시작 쪽을 맞춘다 — 가운데를 맞추면 시작 이벤트가 밖에 있다."""
    sized(canvas, 400, 600)
    canvas.call_sync("importXML", (EXAMPLES / "fx02_business_rule.bpmn").read_text(encoding="utf-8"))
    stats = canvas.call_sync("stats")
    view, inner = stats["view"], stats["inner"]
    assert stats["scale"] == pytest.approx(1)
    assert inner["width"] > view["width"]
    assert inner["x"] - view["x"] == pytest.approx(120, abs=1)


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


def test_the_process_info_round_trips_through_the_canvas(canvas: Any) -> None:
    """STU-06이 쓰는 길 — `chk:process`는 **그림**이라 캔버스를 거친다 (ADR-0022).

    창이 다루지 않는 칸(`inputs`)까지 통째로 되돌려 쓰므로, 왕복해도 그것이 남아야 한다.
    """
    from chaeksas.contracts.bpmn_ext import ProcessInfo

    canvas.create_empty("Proc_info", "청구서 점검")
    # 옛 칸(`service_keys`, ADR-0102)은 **모르는 칸**이다 — 그것도 왕복해 남아야 한다 (C14 B7이 말한다).
    info = ProcessInfo.model_validate(
        {
            "run_location": "pc",
            "service_keys": {"ext-credit": "finance-credit"},
            "inputs": [{"name": "금액", "type": "number", "required": True}],
            "outputs": ["승인"],
        }
    )
    made = canvas.call_sync(
        "setProperties",
        "Proc_info",
        {"chk": {"process": json.dumps(info.to_json_dict(), ensure_ascii=False)}},
    )
    assert made.get("found") is True

    body = json.loads(canvas.call_sync("properties", "Proc_info")["chk"]["process"])
    assert body["run_location"] == "pc"
    assert body["service_keys"] == {"ext-credit": "finance-credit"}
    assert [one["name"] for one in body["inputs"]] == ["금액"], "창이 모르는 칸도 남는다"

    # 저장한 XML을 계약이 다시 읽어도 같다 (글자가 아니라 **뜻**으로 본다).
    again = read_process(canvas.save_xml())
    assert again.info.run_location == "pc"
    assert again.info.model_extra == {"service_keys": {"ext-credit": "finance-credit"}}
    assert [one.name for one in again.info.inputs] == ["금액"]
    assert again.info.outputs == ["승인"]


def added(
    canvas: Any,
    chk: dict[str, str],
    name: str = "주문 등록",
    *,
    bpmn: str = "bpmn:ServiceTask",
    attrs: dict[str, str] | None = None,
) -> str:
    """STU-03 「캔버스에 추가」를 한 번 — 만들어진 노드 id (답이 올 때까지 기다린다)."""
    from PySide6.QtCore import QEventLoop

    loop = QEventLoop()
    box: dict[str, Any] = {}

    def done(found: dict[str, Any]) -> None:
        box.update(found)
        loop.quit()

    canvas.create_task(bpmn, name, chk, attrs=attrs, then=done)
    loop.exec()
    assert box.get("ok"), box
    return str(box["id"])


def test_called_element_and_chk_call_round_trip(canvas: Any) -> None:
    """STU-04 「호출」 — 표준 `calledElement`도 `properties`·`setProperties`로 오간다 (`chk:call`과 함께)."""
    canvas.create_empty("Proc_call", "호출 시험")
    node_id = added(canvas, {}, "ERP 입력", bpmn="bpmn:CallActivity", attrs={"calledElement": "Proc_erp"})
    found = canvas.call_sync("properties", node_id)
    assert found["type"] == "CallActivity" and found["calledElement"] == "Proc_erp"

    call = {"delegate": {"bpm_process_id": "other-bot"}, "output": {"결과": "결과코드"}}
    patch = {"calledElement": "Proc_other", "chk": {"call": json.dumps(call, ensure_ascii=False)}}
    canvas.call_sync("setProperties", node_id, patch)
    assert canvas.call_sync("properties", node_id)["calledElement"] == "Proc_other"
    node = next(n for n in read_process(canvas.save_xml()).all_nodes() if n.id == node_id)
    assert node.called_element == "Proc_other"
    spec = node.prop("call")
    assert spec is not None and spec.delegate is not None and spec.delegate.bpm_process_id == "other-bot"


def test_the_loop_marker_and_chk_loop_round_trip(canvas: Any) -> None:
    """STU-04 「반복」 — 표준 반복 표시(`isSequential`)도 `properties`·`setProperties`로 오가고, 끄면 둘 다 사라진다."""
    canvas.create_empty("Proc_loop", "반복 시험")
    node_id = added(canvas, {}, "신용 조회")
    assert canvas.call_sync("properties", node_id)["multiInstance"] == ""

    loop = {"collection": "거래처목록", "item": "거래처", "result": "신용", "collect_into": "신용목록"}
    canvas.call_sync(
        "setProperties", node_id, {"multiInstance": "parallel", "chk": {"loop": json.dumps(loop, ensure_ascii=False)}}
    )
    assert canvas.call_sync("properties", node_id)["multiInstance"] == "parallel"
    node = next(n for n in read_process(canvas.save_xml()).all_nodes() if n.id == node_id)
    assert node.is_sequential is False and node.prop("loop") == Loop.model_validate(loop)

    canvas.call_sync("setProperties", node_id, {"multiInstance": "sequential"})
    node = next(n for n in read_process(canvas.save_xml()).all_nodes() if n.id == node_id)
    assert node.is_sequential is True and node.prop("loop") is not None, "표시만 바꾸면 본문은 남는다"

    canvas.call_sync("setProperties", node_id, {"multiInstance": "", "chk": {"loop": None}})
    node = next(n for n in read_process(canvas.save_xml()).all_nodes() if n.id == node_id)
    assert node.is_sequential is None and node.prop("loop") is None


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


def test_a_real_drop_makes_a_node_where_it_landed(canvas: Any) -> None:
    """STU-03 끌어다 놓기 ([ADR-0044](../docs/decisions/0044-canvas-drag-and-drop.md)).

    **진짜 드롭 이벤트를 보낸다.** 「필터를 달았다」까지만 보면 PySide6가 내부 위젯을 다르게
    만들었을 때 드롭이 **조용히** 안 되는 것을 놓친다 — 그래서 뷰가 아니라 그 자식에게 보내고,
    노드가 **놓은 자리에** 생기는 것까지 본다.
    """
    from PySide6.QtCore import QEventLoop, QMimeData, QPoint, Qt, QTimer
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtWidgets import QApplication

    from chaeksas.studio import resources

    canvas.create_empty("Proc_drop", "드롭 시험")
    canvas.resize(900, 700)
    canvas.accept_drops_of(resources.MIME_TYPE)
    before = canvas.call_sync("stats")["elements"]

    create = resources.Create(
        bpmn="bpmn:ServiceTask",
        name="끌어 온 화면",
        chk={"task": json.dumps(
            {"type": "ui_task", "extension": "ui-automation", "data": {"page_id": "erp.order.form"}},
            ensure_ascii=False,
        )},
    )
    data = QMimeData()
    data.setData(resources.MIME_TYPE, resources.as_payload(create).encode("utf-8"))

    got: list[tuple[str, int, int]] = []
    canvas.dropped.connect(lambda payload, x, y: got.append((payload, x, y)))

    target = canvas.focusProxy()
    assert target is not None, "내부 렌더 위젯이 없다 — 드롭은 그쪽으로 간다 (ADR-0044)"
    at = QPoint(420, 310)
    for kind in (QDragEnterEvent, QDropEvent):
        event = kind(at, Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(target, event)
        assert event.isAccepted(), f"{kind.__name__}을 받지 않았다"

    assert len(got) == 1, "드롭이 한 번 올라와야 한다"
    assert resources.from_payload(got[0][0]) == create, "실은 것이 그대로 오지 않았다"
    assert got[0][1:] == (at.x(), at.y())

    # 올라온 자리로 **노드를 만든다** — 「캔버스에 추가」와 같은 명령이다 (실행 취소도 한 걸음).
    loop = QEventLoop()
    box: dict[str, Any] = {}

    def done(found: dict[str, Any]) -> None:
        box.update(found)
        loop.quit()

    canvas.create_task(create.bpmn, create.name, create.chk, at=got[0][1:], then=done)
    QTimer.singleShot(DROP_TIMEOUT_MS, loop.quit)
    loop.exec()
    assert box.get("ok"), box

    # 놓은 자리가 노드의 가운데다 (처음 축척은 1, 뷰박스는 왼쪽 위에서 시작한다).
    assert abs(float(box["x"]) - at.x()) <= 2, box
    assert abs(float(box["y"]) - at.y()) <= 2, box

    found = read_process(canvas.save_xml())
    node = next(n for n in found.all_nodes() if n.id == box["id"])
    task = node.prop("task")
    assert task is not None and task.data == {"page_id": "erp.order.form"}

    canvas.call_sync("undo")
    assert canvas.call_sync("stats")["elements"] == before, "한 번 되돌리면 흔적이 없다"


def test_a_drop_of_something_else_is_left_to_the_page(canvas: Any) -> None:
    """우리 형식이 아니면 **가던 길로 보낸다** — 페이지 안 bpmn-js 팔레트 드래그가 산다."""
    from PySide6.QtCore import QMimeData, QPoint, Qt
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QApplication

    from chaeksas.studio import resources

    canvas.accept_drops_of(resources.MIME_TYPE)
    got: list[Any] = []
    canvas.dropped.connect(lambda *a: got.append(a))

    data = QMimeData()
    data.setText("그냥 글")
    event = QDropEvent(QPoint(10, 10), Qt.DropAction.CopyAction, data,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(canvas.focusProxy(), event)
    assert got == [], "우리 것이 아닌 드롭을 가로챘다"


def test_a_service_app_operation_becomes_a_service_call(canvas: Any) -> None:
    """서비스 앱 작업은 `chk:serviceCall`이다 (C14) — 같은 명령이 둘 다 만든다."""
    canvas.create_empty("Proc_call", "호출 시험")
    body = {"app_id": "svc-invoice", "operation": "issue"}
    node_id = added(canvas, {"serviceCall": json.dumps(body, ensure_ascii=False)}, name="세금계산서 issue")
    call = next(n for n in read_process(canvas.save_xml()).all_nodes() if n.id == node_id).prop("serviceCall")
    assert call is not None
    assert (call.app_id, call.operation) == ("svc-invoice", "issue")
    assert not call.model_extra, "키 참조는 없다 (ADR-0102)"


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


def test_a_shared_process_becomes_a_call_activity_with_its_called_element(canvas: Any) -> None:
    """STU-03 공유 BPM 프로세스 → Call Activity
    ([ADR-0051](../docs/decisions/0051-shared-process-conveniences.md)).

    `calledElement`는 `chk:*`가 아니라 **그냥 BPMN 속성**이라 `attrs`로 간다 — 만드는 길은
    하나여야(ADR-0044) 실행 취소가 한 걸음이다. **`chk:call`은 넣지 않는다** (입력·출력 짝은
    내 변수 이름을 알아야 하는 일이라 속성 패널에서 적는다).
    """
    canvas.create_empty("Proc_caller", "호출하는 쪽")
    node_id = added(
        canvas,
        {},
        name="팀장 결재",
        bpmn="bpmn:CallActivity",
        attrs={"calledElement": "Proc_approve"},
    )
    node = next(n for n in read_process(canvas.save_xml()).all_nodes() if n.id == node_id)
    assert node.kind == "callActivity" and node.name == "팀장 결재"
    assert node.called_element == "Proc_approve"
    assert node.prop("call") is None, "입력·출력 짝은 지어내지 않는다"

    canvas.call_sync("undo")
    assert node_id not in [n.id for n in read_process(canvas.save_xml()).all_nodes()]


@pytest.fixture
def viewer_page(app: Any) -> Any:
    """읽기 전용 **뷰어** 페이지 하나 (ADR-0051). 모델러와 같은 다리를 쓴다."""
    from PySide6.QtCore import QEventLoop, QTimer

    found = Canvas()
    loop = QEventLoop()
    found.opened.connect(loop.quit)
    QTimer.singleShot(30_000, loop.quit)
    found.boot(page=VIEW_PAGE)
    loop.exec()
    if not found.live:
        pytest.skip("뷰어가 30초 안에 뜨지 않았다 (WebEngine이 이 환경에서 막혀 있다)")
    return found


def test_the_viewer_draws_our_bpmn_and_cannot_edit_it(viewer_page: Any) -> None:
    """**정말 못 고친다** (ADR-0051) — 팔레트를 가린 편집기가 아니라 편집 기능이 없는 뷰어다.

    그래서 모델러에게만 있는 길(`saveXML`·`createTask`·`undo`)이 **아예 없다**. 그림은 `chk:*`가
    든 우리 예제로 보고, 경고 없이 들어가는 것까지 본다(moddle 설명을 뷰어도 쓴다).
    """
    original = (EXAMPLES / "bx03_expense_approval.bpmn").read_text(encoding="utf-8")
    found = viewer_page.call_sync("importXML", original)
    assert found.get("warnings") == [], found.get("warnings")
    assert viewer_page.call_sync("stats")["elements"] > 4

    for name in ("saveXML", "createTask", "undo", "setProperties"):
        with pytest.raises(CanvasError, match="모르는 함수"):
            viewer_page.call_sync(name)


# ─────────────────────────── 그림 좌표 없는 정의 (ADR-0088) ───────────────────────────


def without_di(xml: str) -> str:
    """DI와 노드의 `incoming`·`outgoing`을 걷는다 — 다른 도구가 흔히 쓰는 모양이다.

    둘 다 걷는 것이 요점이다: `incoming`·`outgoing`이 없으면 배치기가 선을 하나도 긋지 않았다.
    """
    import re  # noqa: PLC0415

    xml = re.sub(r"<bpmndi:BPMNDiagram.*?</bpmndi:BPMNDiagram>", "", xml, flags=re.S)
    return re.sub(r"\s*<bpmn:(incoming|outgoing)>[^<]*</bpmn:\1>", "", xml)


def test_a_definition_without_di_is_laid_out_and_left_unsaved(canvas: Any) -> None:
    original = (EXAMPLES / "bx03_expense_approval.bpmn").read_text(encoding="utf-8")
    bare = without_di(original)
    assert "BPMNDiagram" not in bare and "<bpmn:outgoing>" not in bare

    found = canvas.call_sync("importXML", bare)
    assert found.get("laid_out") is True
    assert found.get("warnings") == [], found.get("warnings")
    assert canvas.call_sync("stats")["dirty"] is True, "배치했으면 디스크와 다르다"

    again = canvas.save_xml()
    assert meaning(again) == meaning(original), "뜻은 그대로이고 좌표만 생긴다"
    flows = len(read_process(original).flows)
    assert again.count("<bpmndi:BPMNEdge") == flows, "흐름마다 선이 그어진다"


def test_a_definition_with_di_is_not_laid_out_again(canvas: Any) -> None:
    """사람이 놓은 자리를 덮지 않는다."""
    original = (EXAMPLES / "bx03_expense_approval.bpmn").read_text(encoding="utf-8")
    found = canvas.call_sync("importXML", original)
    assert found.get("laid_out") is False
    assert canvas.call_sync("stats")["dirty"] is False


def test_the_viewer_lays_out_too(viewer_page: Any) -> None:
    bare = without_di((EXAMPLES / "bx03_expense_approval.bpmn").read_text(encoding="utf-8"))
    found = viewer_page.call_sync("importXML", bare)
    assert found.get("laid_out") is True and found.get("warnings") == []
    assert viewer_page.call_sync("stats")["elements"] > 4


def test_clearing_takes_the_diagram_down(canvas: Any) -> None:
    """STU-01 「BPM 프로세스 닫기」."""
    canvas.call_sync("importXML", (EXAMPLES / "bx03_expense_approval.bpmn").read_text(encoding="utf-8"))
    canvas.clear()
    stats = canvas.call_sync("stats")
    assert (stats["elements"], stats["dirty"]) == (0, False)


# ─────────────────────────── STU-06a 나누기 (ADR-0071) ───────────────────────────


UI_TASK = json.dumps(
    {"type": "ui_task", "extension": "ui-automation", "data": {"page_id": "erp.order.form"}}, ensure_ascii=False
)


def test_a_chain_is_appended_after_the_start_with_its_flows(canvas: Any) -> None:
    """빈 그림에 시작 → 노드 → 끝 — **흐름까지** 캔버스가 짓는다 (파이썬은 XML을 만지지 않는다)."""
    canvas.create_empty("Proc_erp_pc", "ERP 입력")
    ids = canvas.append_chain(
        [
            {"bpmn": "bpmn:ServiceTask", "name": "발주 입력", "chk": {"task": UI_TASK}},
            {"bpmn": "bpmn:EndEvent", "name": "끝", "chk": {}},
        ]
    )
    found = read_process(canvas.save_xml())
    task, end = ids
    start = next(n.id for n in found.all_nodes() if n.kind == "startEvent")
    assert sorted((f.source, f.target) for f in found.flows) == sorted([(start, task), (task, end)])
    moved = found.node(task)
    assert moved is not None and moved.name == "발주 입력"
    body = json.loads(canvas.call_sync("properties", task)["chk"]["task"])
    assert body["type"] == "ui_task" and body["extension"] == "ui-automation", "본문 그대로 옮긴다"


def test_a_node_becomes_a_delegated_call_keeping_flows_and_boundaries(canvas: Any) -> None:
    """바꾸기는 **흐름·경계 이벤트를 그대로** 둔다 — 그림이 조용히 달라지지 않는다."""
    canvas.call_sync("importXML", (EXAMPLES / "bx03_expense_approval.bpmn").read_text(encoding="utf-8"))
    before = read_process(canvas.save_xml())
    edges = sorted((f.source, f.target) for f in before.flows if "Approve_Expense" in (f.source, f.target))
    call = json.dumps({"delegate": {"bpm_process_id": "bx03-pc"}, "input": {"금액": "금액"}, "output": {}})
    made = canvas.delegate_node("Approve_Expense", name="결재 (PC 위임)", called="Proc_bx03_pc", call=call)

    after = read_process(canvas.save_xml())
    node = after.node(made)
    assert node is not None and node.kind == "callActivity"
    assert list(node.props) == ["call"], "옛 `chk:approval`은 남지 않는다"
    assert json.loads(canvas.call_sync("properties", made)["chk"]["call"])["delegate"]["bpm_process_id"] == "bx03-pc"
    moved = sorted((made if s == "Approve_Expense" else s, made if t == "Approve_Expense" else t) for s, t in edges)
    assert sorted((f.source, f.target) for f in after.flows if made in (f.source, f.target)) == moved
    attached = {n.id: n.attached_to for n in after.all_nodes() if n.kind == "boundaryEvent"}
    assert attached["Bnd_Remind"] == made and attached["Bnd_Deadline"] == made, "경계 이벤트가 따라온다"


def test_delegating_a_node_is_one_undo_step(canvas: Any) -> None:
    canvas.create_empty("Proc_one", "하나")
    task, _ = canvas.append_chain(
        [{"bpmn": "bpmn:ServiceTask", "name": "화면", "chk": {"task": UI_TASK}}, {"bpmn": "bpmn:EndEvent"}]
    )
    before = meaning(canvas.save_xml())
    canvas.delegate_node(task, name="화면 (PC 위임)", called="Proc_x", call='{"delegate": {"bpm_process_id": "x"}}')
    assert meaning(canvas.save_xml()) != before
    canvas.call_sync("undo")
    assert meaning(canvas.save_xml()) == before, "실행 취소 **한 번**에 돌아온다"


def test_delegating_a_missing_node_says_so(canvas: Any) -> None:
    canvas.create_empty("Proc_none", "없음")
    with pytest.raises(CanvasError):
        canvas.delegate_node("Nope", name="", called="", call="{}")


# ── 테마 (ADR-0101) ──


def js_value(canvas: Any, script: str) -> Any:
    """페이지에서 식 하나를 읽는다 (다리를 거치지 않는다)."""
    from PySide6.QtCore import QEventLoop, QTimer

    found: dict[str, Any] = {}
    loop = QEventLoop()

    def keep(value: Any) -> None:
        found["value"] = value
        loop.quit()

    canvas.page().runJavaScript(script, 0, keep)
    QTimer.singleShot(5_000, loop.quit)
    loop.exec()
    return found.get("value")


def test_the_pages_draw_with_theme_variables_and_write_no_colors() -> None:
    """두 페이지가 같은 변수로 그리고, 색 값은 토큰에서만 온다 (CLAUDE.md §5)."""
    import re

    from chaeksas.studio.canvas import CANVAS_TOKENS, EDIT_PAGE

    for page in (EDIT_PAGE, VIEW_PAGE):
        text = (WEB_DIR / page).read_text(encoding="utf-8")
        assert "window.chkTheme" in text, page
        for key in ("defaultFillColor", "defaultStrokeColor", "defaultLabelColor"):
            assert re.search(rf'{key}: "var\(--chk-[a-z-]+, [a-z]+\)"', text), (page, key)
        used = set(re.findall(r"var\((--chk-[a-z-]+)", text))
        assert used <= set(CANVAS_TOKENS), (page, used - set(CANVAS_TOKENS))
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", text.split("<script")[0]), page


def test_every_canvas_variable_is_a_token_in_both_themes() -> None:
    from chaeksas.studio.canvas import CANVAS_TOKENS, canvas_colors

    light, dark = canvas_colors("light"), canvas_colors("dark")
    assert set(light) == set(dark) == set(CANVAS_TOKENS)
    assert light["--chk-surface"] != dark["--chk-surface"]


def test_the_diagram_follows_the_app_theme_without_reloading(canvas: Any) -> None:
    """어둡게 → 밝게로 바꾸면 그림을 다시 읽지 않고 색만 바뀐다."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from chaeksas.qt.theme import apply_theme
    from chaeksas.studio.canvas import canvas_colors

    app = QApplication.instance()
    assert isinstance(app, QApplication)

    def rgb(value: str) -> str:
        color = QColor(value)
        return f"rgb({color.red()}, {color.green()}, {color.blue()})"

    fill = "getComputedStyle(document.querySelector('.djs-element[data-element-id] .djs-visual rect')).fill"
    try:
        apply_theme(app, choice="dark")
        canvas.load_xml((EXAMPLES / "bx01_invoice_reconciliation.bpmn").read_text(encoding="utf-8"))
        canvas.call_sync("stats")
        assert js_value(canvas, fill) == rgb(canvas_colors("dark")["--chk-surface"])
        before = canvas.call_sync("stats")

        apply_theme(app, choice="light")
        app.processEvents()
        canvas.call_sync("stats")
        assert js_value(canvas, fill) == rgb(canvas_colors("light")["--chk-surface"])
        assert canvas.call_sync("stats")["elements"] == before["elements"]
    finally:
        apply_theme(app, choice="light")


#: STU-04 「게이트웨이」·「이벤트」 왕복용 — 표준 이벤트 정의를 골고루 단 작은 그림 (좌표는 배치기가 짓는다).
EVENTS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs" targetNamespace="t">
  <bpmn:message id="Msg_order" name="주문 접수" />
  <bpmn:message id="Msg_shared" name="함께 쓰는 이름" />
  <bpmn:error id="Err_task" name="TASK_FAILED" errorCode="TASK_FAILED" />
  <bpmn:process id="Proc_events" isExecutable="true">
    <bpmn:startEvent id="Start"><bpmn:messageEventDefinition messageRef="Msg_order" /></bpmn:startEvent>
    <bpmn:exclusiveGateway id="Gw" />
    <bpmn:serviceTask id="Task" name="신용 조회" />
    <bpmn:boundaryEvent id="Timer_b" attachedToRef="Task">
      <bpmn:timerEventDefinition><bpmn:timeDuration>PT30M</bpmn:timeDuration></bpmn:timerEventDefinition>
    </bpmn:boundaryEvent>
    <bpmn:boundaryEvent id="Error_b" attachedToRef="Task">
      <bpmn:errorEventDefinition errorRef="Err_task" />
    </bpmn:boundaryEvent>
    <bpmn:intermediateCatchEvent id="Wait">
      <bpmn:messageEventDefinition messageRef="Msg_shared" />
    </bpmn:intermediateCatchEvent>
    <bpmn:intermediateCatchEvent id="Other">
      <bpmn:messageEventDefinition messageRef="Msg_shared" />
    </bpmn:intermediateCatchEvent>
    <bpmn:intermediateThrowEvent id="Throw"><bpmn:signalEventDefinition /></bpmn:intermediateThrowEvent>
    <bpmn:endEvent id="End" />
    <bpmn:sequenceFlow id="F0" sourceRef="Start" targetRef="Gw" />
    <bpmn:sequenceFlow id="F_big" name="큰 금액" sourceRef="Gw" targetRef="Task">
      <bpmn:conditionExpression>금액 &gt; 100</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="F_else" sourceRef="Gw" targetRef="Throw" />
    <bpmn:sequenceFlow id="F1" sourceRef="Task" targetRef="Wait" />
    <bpmn:sequenceFlow id="F2" sourceRef="Wait" targetRef="Other" />
    <bpmn:sequenceFlow id="F3" sourceRef="Other" targetRef="End" />
    <bpmn:sequenceFlow id="F4" sourceRef="Throw" targetRef="End" />
    <bpmn:sequenceFlow id="F5" sourceRef="Timer_b" targetRef="End" />
    <bpmn:sequenceFlow id="F6" sourceRef="Error_b" targetRef="End" />
  </bpmn:process>
</bpmn:definitions>
"""


def node_in(xml: str, node_id: str) -> tuple[Any, Any]:
    process = read_process(xml)
    return process, next(n for n in process.all_nodes() if n.id == node_id)


def test_the_gateway_default_round_trips(canvas: Any) -> None:
    """STU-04 「게이트웨이」 — 흐름 요약을 주고, 표준 `default`가 `setProperties`로 오간다."""
    canvas.call_sync("importXML", EVENTS_XML)
    found = canvas.call_sync("properties", "Gw")["gateway"]
    assert found["default"] == "" and [one["from"] for one in found["incoming"]] == ["Start"]
    assert {one["id"]: (one["to"], one["condition"]) for one in found["outgoing"]} == {
        "F_big": ("신용 조회", "금액 > 100"), "F_else": ("Throw", ""),
    }
    assert canvas.call_sync("properties", "Task")["gateway"] is None

    canvas.call_sync("setProperties", "Gw", {"default": "F_else"})
    assert canvas.call_sync("properties", "Gw")["gateway"]["default"] == "F_else"
    flows = {f.id: f for f in read_process(canvas.save_xml()).flows}
    assert flows["F_else"].is_default and not flows["F_big"].is_default

    canvas.call_sync("setProperties", "Gw", {"default": ""})
    assert not any(f.is_default for f in read_process(canvas.save_xml()).flows)


def test_event_fields_are_shown_as_the_engine_reads_them(canvas: Any) -> None:
    canvas.call_sync("importXML", EVENTS_XML)
    start = canvas.call_sync("properties", "Start")["event"]
    assert start["definition"] == "Message" and start["message"] == "주문 접수"
    timer = canvas.call_sync("properties", "Timer_b")["event"]
    assert timer["definition"] == "Timer" and timer["attachedTo"] == "신용 조회"
    assert timer["timer"] == {"kind": "timeDuration", "value": "PT30M"} and timer["cancelActivity"] is True
    assert canvas.call_sync("properties", "Error_b")["event"]["error"] == "TASK_FAILED"
    assert canvas.call_sync("properties", "End")["event"]["definition"] == ""
    assert canvas.call_sync("properties", "Gw")["event"] is None


def test_event_fields_round_trip_through_the_canvas(canvas: Any) -> None:
    """타이머·중단·오류 코드·신호 이름이 bpmn-js 명령으로 바뀌고 계약이 같은 뜻으로 읽는다."""
    canvas.call_sync("importXML", EVENTS_XML)
    timer_patch = {"timer": {"kind": "timeDuration", "value": "P1D"}, "cancelActivity": False}
    canvas.call_sync("setProperties", "Timer_b", {"event": timer_patch})
    canvas.call_sync("setProperties", "Error_b", {"event": {"error": "ESCALATED"}})
    canvas.call_sync("setProperties", "Throw", {"event": {"signal": "검토 끝"}})
    process, timer = node_in(canvas.save_xml(), "Timer_b")
    assert timer.timer is not None and (timer.timer.kind, timer.timer.value) == ("timeDuration", "P1D")
    assert timer.cancel_activity is False
    _, error = node_in(canvas.save_xml(), "Error_b")
    assert process.errors.get("ESCALATED") == error.error_ref, "없던 코드는 bpmn:error를 만든다"
    _, throw = node_in(canvas.save_xml(), "Throw")
    assert process.signal_name(throw.signal_ref) == "검토 끝"

    canvas.call_sync("setProperties", "Error_b", {"event": {"error": ""}})
    _, error = node_in(canvas.save_xml(), "Error_b")
    assert error.error_ref is None, "비우면 코드 없는 경계 — 모든 업무 실패를 받는다"


def test_renaming_a_message_points_elsewhere_and_leaves_the_shared_one(canvas: Any) -> None:
    """함께 쓰던 `bpmn:message`의 이름을 바꾸지 않는다 — 이 이벤트만 다른 이름을 가리킨다."""
    canvas.call_sync("importXML", EVENTS_XML)
    canvas.call_sync("setProperties", "Wait", {"event": {"message": "결산 완료"}})
    process, wait = node_in(canvas.save_xml(), "Wait")
    _, other = node_in(canvas.save_xml(), "Other")
    assert process.message_name(wait.message_ref) == "결산 완료"
    assert process.message_name(other.message_ref) == "함께 쓰는 이름"

    canvas.call_sync("setProperties", "Other", {"event": {"message": "주문 접수"}})
    process, other = node_in(canvas.save_xml(), "Other")
    assert other.message_ref == "Msg_order", "같은 이름이 있으면 그것을 가리킨다"


def test_a_receive_task_message_round_trips(canvas: Any) -> None:
    canvas.create_empty("Proc_recv", "받기 시험")
    node_id = added(canvas, {}, "입금 받기", bpmn="bpmn:ReceiveTask")
    assert canvas.call_sync("properties", node_id)["event"]["definition"] == "Message"
    canvas.call_sync(
        "setProperties", node_id,
        {"event": {"message": "입금"}, "chk": {"receive": json.dumps({"correlation": "주문번호"}, ensure_ascii=False)}},
    )
    assert canvas.call_sync("properties", node_id)["event"]["message"] == "입금"
    process, node = node_in(canvas.save_xml(), node_id)
    assert process.message_name(node.message_ref) == "입금"
    receive = node.prop("receive")
    assert receive is not None and receive.correlation == "주문번호"
