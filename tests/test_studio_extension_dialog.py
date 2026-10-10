"""STU-15 확장 — Studio에 켜진 확장과 각 확장이 더한 것 (M6 조각 13).

보는 것:

1. **목록은 정의에서 온다** — 이 창에 확장 이름이 없다 (ADR-0018). 설치된 확장을 그대로 그린다.
2. **켜지지 않은 확장도 사라지지 않는다** — 상태는 `status_map`의 표기, 까닭은 상세 맨 위.
   정의를 **읽지도 못한** 것은 id가 없어 표 아래 한 줄로 말한다.
3. **「켜기/끄기」는 꺼져 있고 이유가 붙어 있다** (U3) — 「사람이 껐다」를 어디에 둘지 아직
   정하지 않았다.
4. **「새로 고침」은 봉투를 다시 검증한다** (C13 E6) — 서명이 맞지 않는 정의는 켜지지 않고,
   받아 온 것이 **설치된 확장 호스트를 건드리지 않는다**(팔레트·시험 실행이 보는 것).
   닿지 못하면 **그 자리에서 말한다** (Studio는 현장이 아니다).
5. **「정의 파일 열기...」는 `chk-admin`과 같은 함수로 본다** (E1·E3·E5). 등록·서명은 하지 않는다.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QTableWidgetItem  # noqa: E402

from chaeksas.contracts import (  # noqa: E402
    AdminKey,
    definition_hash,
    key_id_for,
    sign,
)
from chaeksas.contracts.resources import ExtensionResource  # noqa: E402
from chaeksas.core.extensions import ExtensionHost  # noqa: E402
from chaeksas.qt.theme import tokens  # noqa: E402
from chaeksas.studio import services  # noqa: E402
from chaeksas.studio.extension_dialog import (  # noqa: E402
    LATER_TOGGLE,
    NAME,
    STATE,
    STATE_BROKEN,
    STATE_ON,
    STATUS_GROUP,
    SUMMARY,
    TIER,
    VERSION,
    StudioExtensionsDialog,
    check_definition,
    detail_sections,
    state_of,
)
from chaeksas.studio.extensions import Extensions  # noqa: E402
from chaeksas.studio.settings import Settings  # noqa: E402

NOW = "2026-10-10T09:00:00+09:00"


def builtin(**over: Any) -> dict[str, Any]:
    """내장 확장 정의 하나 (C13 검사를 통과하는 최소 모양)."""
    base: dict[str, Any] = {
        "schema": 2,
        "id": "doc-ocr",
        "version": "1.2.0",
        "name": "문서 인식",
        "publisher": "Chaeksas",
        "tier": "builtin",
        "api": ">=1,<2",
        "contributes": {
            "task_types": [
                {
                    "id": "ocr_task",
                    "label": "문서 인식",
                    "icon": "scan",
                    "editor": {"kind": "builtin", "entry": "doc_ocr.client:OcrEditor"},
                    "executor": {"entry": "doc_ocr.client:OcrExecutor"},
                    "run_locations": ["pc", "server"],
                }
            ],
            "studio.resource_views": [
                {"id": "forms", "label": "서식", "resource_type": "ocr_form", "creates_task_type": "ocr_task"}
            ],
        },
        "requires_keys": [{"purpose": "run", "extra_scopes": ["ocr_read"]}],
    }
    base.update(over)
    return base


def external(**over: Any) -> dict[str, Any]:
    """외부 확장 정의 하나 (HTTP 어댑터). **코드 기여가 없다** (E1)."""
    base: dict[str, Any] = {
        "schema": 2,
        "id": "ext-ocr",
        "version": "1.0.0",
        "name": "외부 OCR",
        "publisher": "외부 업체",
        "tier": "external",
        "service": {
            "protocol": "http-adapter",
            "base_url": "https://ocr.example.com",
            "adapter": {
                "allowed_hosts": ["ocr.example.com"],
                "auth": {"type": "bearer"},
                "operations": [
                    {
                        "name": "read_invoice",
                        "request": {"method": "POST", "path": "/v2/invoice", "body": {"url": "{{input.file_url}}"}},
                        "response": {"output": {"biz_no": "$.result.bizNo"}},
                    }
                ],
            },
        },
    }
    base.update(over)
    return base


def signed(definition: dict[str, Any]) -> tuple[dict[str, Any], list[AdminKey]]:
    """정의에 Admin 서명 봉투 하나 (C2 `extension`) — 실행하는 쪽이 다시 검증할 것."""
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    claim = {
        "kind": "extension",
        "id": definition["id"],
        "version": definition["version"],
        "definition_hash": definition_hash(definition),
    }
    envelope = sign(claim, private, signed_at=NOW)
    key = AdminKey(key_id=key_id_for(public), public_key=base64.b64encode(public).decode())
    return envelope.to_json_dict(), [key]


class FakeCenter(services.CenterReader):
    """Center를 읽는 척 — 리소스 목록(C7)과 Admin 공개키만 준다."""

    def __init__(
        self,
        items: list[ExtensionResource],
        keys: list[AdminKey],
        *,
        unreachable: str | None = None,
    ) -> None:
        super().__init__(base_url="http://center.test", api_key="chk_studio_" + "a" * 40)
        self.items = items
        self.keys = keys
        self.unreachable = unreachable

    def extensions(self) -> list[ExtensionResource]:
        if self.unreachable:
            raise services.CenterUnreachable(self.unreachable)
        return self.items

    def admin_keys(self) -> list[AdminKey]:
        if self.unreachable:
            raise services.CenterUnreachable(self.unreachable)
        return self.keys


def resource(definition: dict[str, Any], envelope: dict[str, Any] | None) -> ExtensionResource:
    return ExtensionResource(
        id=definition["id"],
        version=definition["version"],
        name=definition["name"],
        tier=definition["tier"],
        definition=definition,
        envelope=envelope,
    )


def host_with(*definitions: dict[str, Any], api_version: str = "1.0.0") -> ExtensionHost:
    host = ExtensionHost(api_version=api_version)
    for one in definitions:
        host.add_installed(json.dumps(one).encode("utf-8"), origin="test", root="chaeksas.ext.ui_automation")
    return host


def dialog(host: ExtensionHost, *, reader: services.CenterReader | None = None) -> StudioExtensionsDialog:
    return StudioExtensionsDialog(Settings(), Extensions(host=host), reader=reader)


def cell(window: StudioExtensionsDialog, row: int, column: int) -> QTableWidgetItem:
    item = window.table.item(row, column)
    assert item is not None
    return item


@pytest.fixture(autouse=True)
def _app() -> Any:
    """창을 만들려면 QApplication 하나가 있어야 한다 (`offscreen`)."""
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


# ─────────────────────────── 목록 ───────────────────────────


def test_list_draws_what_the_definition_says() -> None:
    """이름·등급·버전·상태·기여 요약이 모두 정의에서 온다 (창에 확장 이름이 없다)."""
    window = dialog(host_with(builtin()))
    assert window.table.rowCount() == 1
    assert cell(window, 0, NAME).text() == "문서 인식"
    assert cell(window, 0, NAME).toolTip() == "doc-ocr"  # id는 말풍선에 (U10)
    assert cell(window, 0, TIER).text() == "내장"
    assert cell(window, 0, VERSION).text() == "1.2.0"
    assert cell(window, 0, STATE).text() == STATE_ON
    summary = cell(window, 0, SUMMARY).text()
    assert "태스크 종류 1" in summary
    assert "리소스 탐색기 뿌리 1" in summary


def test_state_labels_come_only_from_the_status_map() -> None:
    """상태 표기는 `status_map`의 「확장」에 있는 것만 쓴다 (스타일 가이드 §2-2)."""
    allowed = tokens.STATUS_MAP[STATUS_GROUP]
    assert STATE_ON in allowed
    assert STATE_BROKEN in allowed


def test_detail_shows_the_five_contribution_points() -> None:
    """STU-15 표가 적은 다섯 — 태스크 종류·편집기·리소스 탐색기 뿌리·서비스 앱 작업·필요한 키."""
    window = dialog(host_with(builtin()))
    titles = [title for title, _ in detail_sections(window.rows[0])]
    assert titles == ["확장", "태스크 종류", "속성 편집기", "리소스 탐색기 뿌리", "서비스 앱 작업", "필요한 키"]
    shown = window.detail.toPlainText()
    assert "문서 인식 (ocr_task)" in shown
    assert "실행 위치 pc, server" in shown
    assert "아이콘 scan" in shown
    assert "서식 (ocr_form) → 끌어다 놓으면 ocr_task" in shown


def test_c11_service_app_does_not_invent_an_operation_list() -> None:
    """C11 앱의 작업은 그 앱의 manifest에서 온다 — 정의에 없는 것을 지어내지 않는다 (C7)."""
    window = dialog(host_with(builtin(service={"protocol": "chk-c11", "base_url": "http://svc:8000"})))
    shown = window.detail.toPlainText()
    assert "작업 목록은 그 앱의 manifest에서 옵니다" in shown


def test_adapter_operations_and_allowed_hosts_are_shown(tmp_path: Path) -> None:
    """외부 확장은 **정의에 작업이 있다** — 허용 호스트와 함께 보인다 (C13 §4)."""
    definition = external()
    envelope, keys = signed(definition)
    window = dialog(host_with(), reader=FakeCenter([resource(definition, envelope)], keys))
    window.refresh_external()
    shown = window.detail.toPlainText()
    assert "허용 호스트: ocr.example.com" in shown
    assert "사설망 허용: 아니오" in shown
    assert "작업 read_invoice: autonomous" in shown


# ─────────────────────────── 켜지지 않은 것 ───────────────────────────


def test_incompatible_extension_says_why_at_the_top() -> None:
    """`extension_api`가 맞지 않으면 「호환 안 됨」이고 까닭이 상세 **맨 위**다 (E5)."""
    window = dialog(host_with(builtin(api=">=1,<2"), api_version="2.0.0"))
    loaded = window.rows[0]
    assert state_of(loaded) == STATE_BROKEN
    assert cell(window, 0, STATE).text() == STATE_BROKEN
    assert cell(window, 0, STATE).toolTip()  # 말풍선에 사유가 있다
    first, lines = detail_sections(loaded)[0]
    assert first == "켜지지 않은 까닭"
    assert any("api_incompatible" in line for line in lines)


def test_unreadable_definition_is_said_below_the_table() -> None:
    """정의를 **읽지도 못한** 것은 id가 없어 줄을 만들 수 없다 — 한 줄로 말한다."""
    host = ExtensionHost()
    host.add_installed(b"not json at all", origin="entry_point:broken", root="chaeksas.ext.ui_automation")
    window = dialog(host)
    assert window.table.rowCount() == 0
    assert "정의를 읽지 못했습니다" in window.note.text()
    assert "entry_point:broken" in window.note.text()


def test_no_rows_says_so_instead_of_an_empty_detail() -> None:
    window = dialog(ExtensionHost())
    assert window.table.rowCount() == 0
    assert "확장을 고르면" in window.detail.toPlainText()


# ─────────────────────────── 단추 ───────────────────────────


def test_toggle_is_off_with_the_reason_in_reach() -> None:
    """「켜기/끄기」는 아직이다 — 끄고 이유를 가까이에 적는다 (U3)."""
    window = dialog(host_with(builtin()))
    for button in (window.enable_button, window.disable_button):
        assert not button.isEnabled()
        assert button.toolTip() == LATER_TOGGLE
    assert "docs/09-gaps.md" in LATER_TOGGLE


def test_refresh_verifies_the_envelope_again() -> None:
    """외부 정의는 봉투가 맞아야 켜진다 (C13 E6) — Studio도 Admin 서명을 직접 본다."""
    definition = external()
    envelope, keys = signed(definition)
    window = dialog(host_with(builtin()), reader=FakeCenter([resource(definition, envelope)], keys))
    window.refresh_external()
    assert window.table.rowCount() == 2
    row = next(at for at in range(2) if cell(window, at, NAME).text() == "외부 OCR")
    assert cell(window, row, TIER).text() == "외부"
    assert cell(window, row, STATE).text() == STATE_ON
    assert "외부 확장 1개를 받았습니다" in window.note.text()


def test_refresh_refuses_a_definition_the_envelope_does_not_cover() -> None:
    """정의가 바뀌면 해시가 달라져 켜지지 않는다 — 「켜짐」으로 보이면 거짓이다."""
    definition = external()
    envelope, keys = signed(definition)
    tampered = external(service={**definition["service"], "base_url": "https://evil.example.com"})
    window = dialog(host_with(), reader=FakeCenter([resource(tampered, envelope)], keys))
    window.refresh_external()
    assert cell(window, 0, STATE).text() == STATE_BROKEN
    lines = detail_sections(window.rows[0])[0][1]
    assert any("hash_mismatch" in line for line in lines)


def test_refresh_does_not_touch_the_installed_host() -> None:
    """팔레트·시험 실행이 보는 호스트는 그대로다 — 받은 것은 이 창만 쓴다."""
    definition = external()
    envelope, keys = signed(definition)
    host = host_with(builtin())
    window = dialog(host, reader=FakeCenter([resource(definition, envelope)], keys))
    window.refresh_external()
    assert [one.id for one in host.all()] == ["doc-ocr"]
    assert [one.value.id for one in host.task_types()] == ["ocr_task"]


def test_refresh_says_it_when_center_is_out_of_reach() -> None:
    """닿지 못하면 **그 자리에서** 말한다 — 들고 있지 않는다 (`services.py`)."""
    window = dialog(host_with(builtin()), reader=FakeCenter([], [], unreachable="Center에 닿지 못했습니다"))
    window.refresh_external()
    assert "닿지 못했습니다" in window.note.text()
    assert window.table.rowCount() == 1  # 설치된 것은 그대로 보인다


def test_refresh_says_it_when_the_definition_came_without_an_envelope() -> None:
    definition = external()
    window = dialog(host_with(), reader=FakeCenter([resource(definition, None)], []))
    window.refresh_external()
    assert "정의·봉투가 함께 오지 않았습니다" in window.note.text()
    assert window.table.rowCount() == 0


def test_refresh_skips_builtin_rows_center_reports() -> None:
    """내장·사내는 정의가 설치 파일에 있다 (E2) — Center가 보고한 줄을 다시 담지 않는다."""
    reported = ExtensionResource(id="doc-ocr", version="1.2.0", tier="builtin")
    window = dialog(host_with(builtin()), reader=FakeCenter([reported], []))
    window.refresh_external()
    assert window.table.rowCount() == 1


def test_refresh_without_center_settings_points_at_stu_10() -> None:
    window = dialog(host_with(builtin()))
    window.settings = Settings(center_url="")
    window.refresh_external()
    assert "STU-10" in window.note.text()


# ─────────────────────────── 정의 파일 열기 ───────────────────────────


def test_checking_a_definition_file_uses_the_same_rules_as_chk_admin() -> None:
    """E1·E3·E5를 여기서 돌려 본다 — Center에 올리기 전에 알면 싸다."""
    assert check_definition(json.dumps(external()).encode("utf-8"), api_version="1.0.0") == []

    coded = external(contributes={"bot_ui.utilities": [{"id": "u", "label": "u", "entry": "x:Y"}]})
    problems = check_definition(json.dumps(coded).encode("utf-8"), api_version="1.0.0")
    assert any("external_code_not_allowed" in line for line in problems)

    off_host = external(
        service={
            "protocol": "http-adapter",
            "base_url": "https://elsewhere.example.com",
            "adapter": {
                "allowed_hosts": ["ocr.example.com"],
                "operations": [
                    {"name": "x", "request": {"method": "GET", "path": "/x"}, "response": {}}
                ],
            },
        }
    )
    problems = check_definition(json.dumps(off_host).encode("utf-8"), api_version="1.0.0")
    assert any("adapter_invalid" in line for line in problems), problems


def test_a_file_that_is_not_a_definition_says_so_plainly() -> None:
    """**한 줄로 말한다** — 어디가 깨졌는지는 사유에 담긴다."""
    broken = check_definition(b"{nope", api_version="1.0.0")
    assert len(broken) == 1
    assert broken[0].startswith("JSON이 아닙니다: ")
    assert check_definition(b"[]", api_version="1.0.0") == ["최상위가 객체가 아닙니다."]
    missing = check_definition(b'{"schema": 2, "id": "x"}', api_version="1.0.0")
    assert len(missing) == 1
    assert missing[0].startswith("정의가 C13과 맞지 않습니다")


def test_opening_a_definition_file_shows_the_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """고른 파일의 검사 결과는 상세에, 한 줄 요약은 안내 줄에. **등록하지 않는다**."""
    path = tmp_path / "extension.json"
    path.write_text(json.dumps(external()), encoding="utf-8")
    window = dialog(host_with(builtin()))
    monkeypatch.setattr(
        "chaeksas.studio.extension_dialog.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(path), "")),
    )
    window.open_definition()
    assert "흠이 없습니다" in window.note.text()
    assert "Admin이 서명해 올립니다" in window.note.text()
    assert "정의 파일 검사: extension.json" in window.detail.toPlainText()
    # 받아 둔 외부 확장이 생기지 않는다 — 검사일 뿐이다.
    assert window.external == []


def test_cancelling_the_file_dialog_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    window = dialog(host_with(builtin()))
    before = window.detail.toPlainText()
    monkeypatch.setattr(
        "chaeksas.studio.extension_dialog.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: ("", "")),
    )
    window.open_definition()
    assert window.detail.toPlainText() == before
    assert window.note.text() == ""
