"""STU-04 보내기 편집기 (`studio/send_editor.py`) — 화면 없이.

보는 것은 넷이다: 그림에 적힌 것이 **다 보이는가**, 고친 것이 **C14 모델로 그대로 읽히는가**
(웹훅 본문은 **엔진이 읽는 모양**으로), 엔진이 거부하거나 반드시 실패할 것을 **「적용」 전에 막는가**,
채널을 바꾸면 **다른 쪽이 그림에서 지워지는가**.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts.bpmn_ext import Email, Webhook  # noqa: E402
from chaeksas.studio.send_editor import (  # noqa: E402
    ALL_WARNING,
    BODY_FIELDS,
    BODY_TEMPLATE,
    BOTH_WARNING,
    CHANNEL_EMAIL,
    CHANNEL_WEBHOOK,
    SendEditor,
    _read_body,
)

EMAIL: dict[str, Any] = {
    "to": ["finance@example.com", "{담당자메일}"],
    "cc": ["boss@example.com"],
    "subject": "{대상월} 대사 결과",
    "body": "보류 {보류건수}건",
    "attachments": ["보고서경로"],
    "store_as": "메일결과",
}
WEBHOOK: dict[str, Any] = {
    "url": "https://hooks.example.com/{채널}",
    "method": "PUT",
    "body": "fields:[신청번호, 결과]",
    "timeout_s": 15,
    "store_as": "응답",
}


@pytest.fixture(autouse=True)
def _app() -> Any:
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def loaded(chk: dict[str, Any]) -> SendEditor:
    made = SendEditor()
    made.load(chk)
    return made


def test_everything_in_an_email_is_shown() -> None:
    made = loaded({"email": EMAIL})
    assert made.channel() == CHANNEL_EMAIL
    assert made.to_box.text() == "finance@example.com, {담당자메일}"
    assert made.cc_box.text() == "boss@example.com"
    assert made.subject_box.text() == "{대상월} 대사 결과"
    assert made.body_box.toPlainText() == "보류 {보류건수}건"
    assert made.attachments_box.text() == "보고서경로"
    assert made.email_store_box.text() == "메일결과"


def test_everything_in_a_webhook_is_shown() -> None:
    made = loaded({"webhook": WEBHOOK})
    assert made.channel() == CHANNEL_WEBHOOK
    assert made.url_box.text() == WEBHOOK["url"]
    assert made.method_box.currentText() == "PUT"
    assert made.timeout_box.value() == 15
    assert made.body_kind.currentData() == BODY_FIELDS
    assert made.fields_box.text() == "신청번호, 결과"
    assert made.webhook_store_box.text() == "응답"


@pytest.mark.parametrize("chk", [{"email": EMAIL}, {"webhook": WEBHOOK}])
def test_an_untouched_dump_reads_back_the_same(chk: dict[str, Any]) -> None:
    made = loaded(chk)
    assert made.problems()[0] == []
    assert made.dump() == chk


def test_unknown_keys_survive() -> None:
    made = loaded({"email": {**EMAIL, "future": 1}})
    assert made.dump()["email"]["future"] == 1


def test_every_example_send_task_round_trips() -> None:
    """업무 예제의 보내기가 **손대지 않으면 같은 뜻으로** 돌아온다 — 편집기가 조용히 바꾸지 않는다."""
    from chaeksas.contracts.bpmn_ext import read_process  # noqa: PLC0415

    seen = 0
    for path in sorted(Path("docs/08-business-examples/bpmn").glob("*.bpmn")):
        for node in read_process(path.read_text(encoding="utf-8")).all_nodes():
            bodies = {
                name: model.model_dump(exclude_unset=True)
                for name in ("email", "webhook")
                if (model := node.prop(name)) is not None
            }
            if not bodies:
                continue
            seen += 1
            made = loaded(bodies)
            # 뜻으로 견준다 — 빈 목록·`null`로 적힌 선택 칸은 적지 않은 것과 같다 (결재 편집기와 같은 결).
            for name, body in made.dump().items():
                model = Email if name == "email" else Webhook
                assert model.model_validate(body) == node.prop(name), f"{path.name}:{node.id}"
    assert seen > 10, "예제의 보내기를 찾았다"


@pytest.mark.parametrize(
    ("body", "kind", "names", "template"),
    [
        ("all", "all", [], ""),
        ("fields:[a, b]", BODY_FIELDS, ["a", "b"], ""),
        ('template:"{a}건"', BODY_TEMPLATE, [], "{a}건"),
        ('template:""따옴표""', BODY_TEMPLATE, [], '"따옴표"'),
        ("모르는 모양", BODY_TEMPLATE, [], "모르는 모양"),
    ],
)
def test_the_body_is_read_as_the_engine_reads_it(body: str, kind: str, names: list[str], template: str) -> None:
    assert _read_body(body) == (kind, names, template)


def test_a_template_body_keeps_its_quotes_through_the_engine() -> None:
    """글이 따옴표로 시작하고 끝나도 엔진이 그 따옴표까지 벗기지 않는다 — 늘 감싸 적는다."""
    made = loaded({"webhook": WEBHOOK})
    made.body_kind.setCurrentIndex(made.body_kind.findData(BODY_TEMPLATE))
    made.template_box.setPlainText('"인용"')
    body = made.dump()["webhook"]["body"]
    assert _read_body(body) == (BODY_TEMPLATE, [], '"인용"')


@pytest.mark.parametrize(
    ("chk", "change", "said"),
    [
        ({"email": EMAIL}, lambda m: m.to_box.setText(" , "), "받는 사람을 적으세요"),
        ({"email": EMAIL}, lambda m: m.attachments_box.setText("보고서 경로"), "첨부 변수 이름"),
        ({"email": EMAIL}, lambda m: m.email_store_box.setText("1결과"), "저장할 변수 이름"),
        ({"webhook": WEBHOOK}, lambda m: m.url_box.setText(""), "URL을 적으세요"),
        ({"webhook": WEBHOOK}, lambda m: m.fields_box.setText(""), "보낼 변수를 적으세요"),
        ({"webhook": WEBHOOK}, lambda m: m.fields_box.setText("신청 번호"), "보낼 변수 이름"),
    ],
)
def test_what_would_fail_blocks_apply(chk: dict[str, Any], change: Any, said: str) -> None:
    made = loaded(chk)
    change(made)
    errors, _ = made.problems()
    assert errors and said in errors[0]


def test_all_variables_is_a_warning_not_an_error() -> None:
    made = loaded({"webhook": {**WEBHOOK, "body": "all"}})
    errors, warnings = made.problems()
    assert errors == [] and warnings == [ALL_WARNING]


def test_switching_channel_writes_only_the_picked_one() -> None:
    made = loaded({"email": EMAIL})
    made.channel_picks[CHANNEL_WEBHOOK].setChecked(True)
    assert made.problems()[0] == ["URL을 적으세요."]
    made.url_box.setText("https://hooks.example.com/x")
    out = made.dump()
    assert list(out) == ["webhook"]
    assert Webhook.model_validate(out["webhook"]).url == "https://hooks.example.com/x"


def test_a_new_send_task_opens_as_an_empty_email() -> None:
    made = loaded({})
    assert made.channel() == CHANNEL_EMAIL
    made.to_box.setText("a@example.com")
    assert made.problems()[0] == []
    assert Email.model_validate(made.dump()["email"]).to == ["a@example.com"]


def test_defaults_are_not_written() -> None:
    """기본값(`POST`·설정의 제한 시간·`all`)과 빈 칸은 그림에 남기지 않는다."""
    made = loaded({})
    made.channel_picks[CHANNEL_WEBHOOK].setChecked(True)
    made.url_box.setText("https://hooks.example.com/x")
    assert made.dump() == {"webhook": {"url": "https://hooks.example.com/x"}}


def test_both_channels_in_the_drawing_shows_the_email_and_warns() -> None:
    made = loaded({"email": EMAIL, "webhook": WEBHOOK})
    assert made.channel() == CHANNEL_EMAIL, "엔진은 메일을 먼저 쓴다"
    assert BOTH_WARNING in made.problems()[1]


# ── 속성 패널 ──


def panel_with(chk: dict[str, Any]) -> Any:
    from chaeksas.studio.properties import Properties  # noqa: PLC0415

    panel = Properties()
    panel.show_element({
        "id": "Send_1", "type": "SendTask", "name": "알림",
        "chk": {name: json.dumps(body, ensure_ascii=False) for name, body in chk.items()},
    })
    return panel


def test_the_properties_panel_attaches_it_and_applies_the_whole_body() -> None:
    panel = panel_with({"email": EMAIL})
    assert panel.tabs.tabText(1) == "보내기"
    editor: Any = panel._editor  # noqa: SLF001
    editor.subject_box.setText("바뀐 제목")
    changes, problem = panel.patch()
    assert problem is None
    assert list(changes["chk"]) == ["email"]
    assert json.loads(changes["chk"]["email"])["subject"] == "바뀐 제목"


def test_switching_channel_in_the_panel_removes_the_other() -> None:
    panel = panel_with({"email": EMAIL})
    editor: Any = panel._editor  # noqa: SLF001
    editor.channel_picks[CHANNEL_WEBHOOK].setChecked(True)
    editor.url_box.setText("https://hooks.example.com/x")
    changes, problem = panel.patch()
    assert problem is None
    assert changes["chk"]["email"] is None, "캔버스가 chk:email을 지운다"
    assert json.loads(changes["chk"]["webhook"])["url"] == "https://hooks.example.com/x"


def test_an_untouched_send_task_sends_nothing() -> None:
    panel = panel_with({})
    assert panel.tabs.tabText(1) == "보내기"
    assert panel.patch() == ({}, None)


def test_a_blocking_problem_blocks_the_panel() -> None:
    panel = panel_with({"webhook": WEBHOOK})
    editor: Any = panel._editor  # noqa: SLF001
    editor.url_box.setText("")
    changes, problem = panel.patch()
    assert changes == {} and problem == "URL을 적으세요."
