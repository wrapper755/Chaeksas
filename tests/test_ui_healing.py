"""치유 — UI 자동화 앱이 모델에게 대체 로케이터를 묻는다 (C8 `heal`, ADR-0034, M4 조각 21).

모델은 시험이 정한 답을 주는 `RecordingLlm`이다 — 시험하는 것은 모델의 똑똑함이 아니라
**묻는 것·거르는 것·한 바퀴가 맞물리는가**다.

1. 모델에게 가는 것은 시맨틱 정보 + **가린** 화면 + 이미 실패한 것이다.
2. 쓸 수 없는 답(JSON 아님·다른 플랫폼 전략·이미 실패한 것)은 `locator: null`과 이유다 (200).
3. 모델이 없으면 503 `llm_unavailable` — 지어낸 답을 주지 않는다.
4. **한 바퀴:** 진짜 Worker의 사다리가 다 실패 → 치유 → Worker가 지금 화면에서 확인 → 스텝 성공 →
   보고 → 레지스트리에 `unverified`로 더해진다. 치유·보고는 **Center의 외부 작업**으로 가고 앱은
   일꾼으로 가져간다 (C15, ADR-0102) — 진짜 소켓 Center다.

앱의 답만 볼 때는 작업 수행기(`app.state.ops`)를 바로 부른다. 옛 「HTTP 상태」(404·413·503)는 C15
실패에 없다 — **코드**로 본다.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from uia_center import execute, running

from chaeksas.ext.ui_automation.client.registry_client import RegistryClient
from chaeksas.ext.ui_automation.contracts.plan import (
    Failure,
    HealRequest,
    HealResponse,
    LocatorSpec,
    WindowSpec,
)
from chaeksas.ext.ui_automation.contracts.registry import ElementHint, PageRegistration
from chaeksas.ext.ui_automation.contracts.worker_local import Caller, SessionRequest, StepRequest
from chaeksas.ext.ui_automation.service.app import create
from chaeksas.ext.ui_automation.service.healing import ARIA_MAX, answer_from, messages_for
from chaeksas.ext.ui_automation.worker import plans_for
from chaeksas.ext.ui_automation.worker.app import Worker
from chaeksas.ext.ui_automation.worker.ladder import Match
from chaeksas.llm import RecordingLlm, Reply
from chaeksas.service_kit import Outcome, ServiceLlm

PAGE = "erp.order.form"
SNAPSHOT = '- textbox "수량": •••\n- button "주문 저장"\n- button "취소"'


def page(**extra: Any) -> PageRegistration:
    body: dict[str, Any] = {
        "schema": 1,
        "page_id": PAGE,
        "platform": "web",
        "name": "주문 입력",
        "url_pattern": "https://erp.example/orders",
        "locators": {
            "order.qty": [LocatorSpec(type="css", value="#qty")],
            "order.save": [LocatorSpec(type="css", value="#save"), LocatorSpec(type="test_id", value="save")],
        },
        "elements": {
            "order.qty": ElementHint(name="수량", role="textbox"),
            "order.save": ElementHint(name="저장", role="button", description="주문을 저장한다"),
        },
    }
    body.update(extra)
    return PageRegistration(**body)


def said(locator: dict[str, Any] | None, reasoning: str = "저장 버튼 이름이 바뀌었다") -> Reply:
    return Reply(text=json.dumps({"locator": locator, "reasoning": reasoning}, ensure_ascii=False), model="m-heal",
                 input_tokens=120, output_tokens=30)


def llm_of(model: RecordingLlm | None) -> ServiceLlm:
    return ServiceLlm(model, model="m-heal") if model is not None else ServiceLlm()


def served(tmp_path: Path, model: RecordingLlm | None, registered: PageRegistration | None = None) -> Any:
    """앱 하나 + 화면 하나. 등록도 작업 수행기로 한다 (등록 권한은 Center의 일이다)."""
    app = create(db_path=tmp_path / "uia.sqlite3", admin_token="t-admin", llm=llm_of(model))
    made = execute(app, "registry_register", {"page": (registered or page()).to_json_dict()}, run_id="reg_00000001")
    assert made.ok, made
    return app


def heal_body(**over: Any) -> dict[str, Any]:
    asked = HealRequest(
        schema=1,
        page_id=PAGE,
        semantic_key="order.save",
        role="button",
        failure=Failure(tried=["css|#save|", "test_id|save|"], reasons=["0개", "0개"], url="https://erp.example/orders"),
        aria_snapshot=SNAPSHOT,
    ).to_json_dict()
    asked.update(over)
    return asked


def call(app: Any, body: dict[str, Any], *, mode: str = "deterministic") -> Outcome:
    found: Outcome = execute(app, "heal", body, mode=mode, run_id="run_20261005_100000_a1b2c3", node_id="Task_Order")
    return found


# ─────────────────────────── 묻는 것 ───────────────────────────


def test_the_model_sees_meaning_masked_screen_and_what_failed() -> None:
    asked = HealRequest.model_validate(heal_body())
    system, user = messages_for(asked, page())
    assert "role, test_id, css, xpath" in system["content"], "화면의 플랫폼에 맞는 전략만 알려 준다"
    body = user["content"]
    assert "주문을 저장한다" in body and "order.save" in body, "시맨틱 정보"
    assert "css|#save|" in body and "test_id|save|" in body, "이미 실패한 것을 다시 내지 말라고"
    assert "•••" in body, "Worker가 가린 화면 그대로"


def test_a_desktop_page_offers_only_desktop_strategies() -> None:
    desktop = page(
        platform="desktop",
        url_pattern=None,
        window=WindowSpec(title="^ERP"),
        locators={"order.save": [LocatorSpec(type="automation_id", value="save", platform="desktop")]},
    )
    asked = HealRequest.model_validate(heal_body())
    assert "automation_id, class_name, control_name" in messages_for(asked, desktop)[0]["content"]
    wrong = answer_from('{"locator": {"type": "css", "value": "#x"}}', asked, desktop)
    assert wrong.locator is None and "desktop" in wrong.reasoning


# ─────────────────────────── 거르는 것 ───────────────────────────


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("저장 버튼을 쓰세요", "JSON이 아니다"),
        ('{"locator": "button"}', "객체가 아니다"),
        ('{"locator": {"type": "role", "value": "button"}}', "이름이 없다"),
        ('{"locator": {"type": "css", "value": "#save"}}', "이미 실패"),
        ('{"locator": {"type": "automation_id", "value": "save"}}', "없는 전략"),
    ],
)
def test_an_unusable_answer_becomes_null_with_a_reason(text: str, why: str) -> None:
    asked = HealRequest.model_validate(heal_body())
    found = answer_from(text, asked, page())
    assert found.locator is None
    assert why in found.reasoning


def test_a_usable_answer_is_unverified_and_fenced_json_is_fine() -> None:
    asked = HealRequest.model_validate(heal_body())
    text = '```json\n{"locator": {"type": "role", "value": "button", "name": "주문 저장", "status": "active",' \
           ' "priority": 0}, "reasoning": "이름이 바뀌었다"}\n```'
    found = answer_from(text, asked, page())
    assert found.locator is not None
    assert (found.locator.type, found.locator.value, found.locator.name) == ("role", "button", "주문 저장")
    assert found.locator.status == "unverified", "모델이 active라고 해도 앱이 정한다"
    assert found.locator.priority is None


# ─────────────────────────── 앱 ───────────────────────────


def test_heal_answers_with_a_suggestion_and_usage(tmp_path: Path) -> None:
    model = RecordingLlm(replies=[said({"type": "role", "value": "button", "name": "주문 저장"})])
    answer = call(served(tmp_path, model), heal_body())
    assert answer.ok and answer.response is not None, answer
    found = HealResponse.model_validate(answer.response.output)
    assert found.locator is not None and found.locator.name == "주문 저장"
    assert answer.complete_body()["usage"] == {"model": "m-heal", "input_tokens": 120, "output_tokens": 30}
    assert len(model.asked) == 1, "한 번 치유에 한 번 묻는다"


def test_heal_works_in_deterministic_mode_as_c8_says(tmp_path: Path) -> None:
    """치유는 폴백이 아니라 정해진 기능이다 — 결정 수행에서도 된다 (C8 수행 모드 표)."""
    answer = call(served(tmp_path, RecordingLlm(replies=[said(None, "모르겠다")])), heal_body(), mode="deterministic")
    assert answer.ok and answer.response is not None
    assert answer.response.output.get("locator") is None
    assert answer.response.output["reasoning"] == "모르겠다"


def test_without_a_model_heal_fails_llm_unavailable(tmp_path: Path) -> None:
    answer = call(served(tmp_path, None), heal_body())
    assert (answer.ok, answer.code) == (False, "llm_unavailable")


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"page_id": "없는.화면"}, "page_not_found"),
        ({"semantic_key": "order.nope"}, "unknown_semantic_key"),
        ({"aria_snapshot": "가" * ARIA_MAX}, "snapshot_too_large"),
    ],
)
def test_heal_refuses_what_it_cannot_use(tmp_path: Path, over: dict[str, Any], code: str) -> None:
    model = RecordingLlm(replies=[said(None)])
    answer = call(served(tmp_path, model), heal_body(**over))
    assert (answer.ok, answer.code, answer.retryable) == (False, code, False)
    assert not model.asked, "거절할 것은 모델에게 묻기 전에 거절한다"


def test_the_manifest_declares_heal_in_both_modes(tmp_path: Path) -> None:
    heal = served(tmp_path, None).state.ops.manifest.operation("heal")
    assert heal is not None and heal.modes == ["deterministic", "autonomous"]


# ─────────────────────────── 한 바퀴 ───────────────────────────


class Screen:
    """저장 버튼의 id·test_id가 바뀐 화면 — **새 이름**(`주문 저장`)으로만 찾힌다."""

    def __init__(self) -> None:
        self.clicked: list[str] = []

    def find(self, locator: LocatorSpec, *, timeout_ms: int) -> Match:
        if locator.type == "role" and locator.name == "주문 저장":
            return Match(count=1, handle="save")
        if locator.type == "css" and locator.value == "#qty":
            return Match(count=1, handle="qty")
        return Match(count=0)

    def act(self, handle: object, step: Any, *, timeout_ms: int) -> str | None:
        self.clicked.append(str(handle))
        return None

    def snapshot(self) -> tuple[str, str]:
        return SNAPSHOT, ""

    def url(self) -> str:
        return "https://erp.example/orders"


class Backend:
    def __init__(self, screen: Screen) -> None:
        self.screen = screen

    def open(self, request: Any, plan: Any = None) -> str:
        return "https://erp.example/orders"

    def finder(self, business_key: str) -> Screen:
        return self.screen

    def goto(self, session_id: str, url: str) -> str:
        return url

    def close(self, session_id: str) -> None:
        pass


def session(token: str, *, heal: bool = True) -> SessionRequest:
    """시험 실행(`test_…`)의 UI 세션 — Studio 호출 토큰으로 Center에 올린다 (C10 `call_token`)."""
    return SessionRequest(
        schema=1,
        caller=Caller(type="studio", run_id="test_20261005_a1b2c3", node_id="Task_Order"),
        mode="deterministic",
        business_key="test_20261005_a1b2c3:Task_Order:1:1",
        page_id=PAGE,
        call_token=token,
        heal=heal,
    )


def test_a_broken_ladder_heals_end_to_end_and_the_registry_learns_it(tmp_path: Path) -> None:
    model = RecordingLlm(replies=[said({"type": "role", "value": "button", "name": "주문 저장"})])
    with running(tmp_path, llm=llm_of(model)) as center:
        writer = RegistryClient(base_url=center.url, call_token=center.pc_token())
        writer.register(page())
        screen = Screen()
        worker = Worker(
            token="t", admin_token="a", backend=Backend(screen),
            plans_factory=plans_for(tmp_path / "worker", center.url),  # type: ignore[arg-type]
        )
        info, _ = worker.open(session(center.studio_token()))
        result = worker.step(
            info.session_id, info.session_secret, StepRequest(semantic_key="order.save", action="click")
        )
        assert result.ok and result.healed, result
        assert screen.clicked == ["save"], "확인된 제안으로 눌렀다"
        sent = model.asked[0][1]["content"]
        assert "•••" in sent and "css|#save|" in sent

        closed = worker.close(info.session_id, info.session_secret)
        assert closed.report == "sent"
        # 보고는 결과를 기다리지 않는다 (C15 `want_result: false`) — 일꾼이 가져갈 때까지 본다.
        deadline = time.monotonic() + 10
        added: list[Any] = []
        while not added and time.monotonic() < deadline:
            found, _ = writer.get_page(PAGE)
            added = [one for one in found.locators["order.save"] if one.type == "role"]
            if not added:
                time.sleep(0.1)
        assert [(one.name, one.status) for one in added] == [("주문 저장", "unverified")], (
            "치유로 찾은 것은 사다리에 더해진다"
        )


def test_a_session_that_turned_healing_off_does_not_ask(tmp_path: Path) -> None:
    """C10 `heal: false`(STU-13 「자가 치유 사용」 끔)면 묻지 않고 전환한다."""
    model = RecordingLlm(replies=[said({"type": "role", "value": "button", "name": "주문 저장"})])
    with running(tmp_path, llm=llm_of(model)) as center:
        RegistryClient(base_url=center.url, call_token=center.pc_token()).register(page())
        worker = Worker(
            token="t", admin_token="a", backend=Backend(Screen()),
            plans_factory=plans_for(tmp_path / "worker", center.url),  # type: ignore[arg-type]
        )
        info, _ = worker.open(session(center.studio_token(), heal=False))
        result = worker.step(
            info.session_id, info.session_secret, StepRequest(semantic_key="order.save", action="click")
        )
        assert not result.ok and not result.healed
        assert not model.asked, "세션이 치유를 껐다"
        worker.force_close(info.session_id)


def test_the_c8_example_answer_passes_the_filter() -> None:
    """문서(C8 「앱이 모델에게 묻는 것」)의 예시 답이 실제 거르기를 지난다 — 어긋나면 문서가 거짓말이다."""
    import re  # noqa: PLC0415

    doc = (Path(__file__).resolve().parent.parent / "docs" / "03-contracts" / "C8-ui-automation-plan-heal-report.md")
    blocks = re.findall(r"```json\n(.*?)```", doc.read_text(encoding="utf-8"), re.S)
    example = next(one for one in blocks if '"reasoning"' in one)
    asked = HealRequest.model_validate(heal_body())
    found = answer_from(example, asked, page())
    assert found.locator is not None and found.locator.status == "unverified"
