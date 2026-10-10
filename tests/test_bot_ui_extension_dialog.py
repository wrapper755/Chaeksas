"""BUI-11 확장 — 이 PC에 설치된 확장과 끄고 켜기 (M6 조각 16, ADR-0018·ADR-0043).

보는 것:

1. **목록은 정의에서 온다** — 이 창에 확장 이름이 없다. 「쓰는 Bot」은 설치된 Bot이 말한 것이다.
2. **「사람이 껐다」는 「흠이 있다」와 다르다** — 표기도 색도 갈라진다 (`status_map` 「확장」).
3. **끄기는 그 자리에서 저장된다** — Bot UI **제 설정**에 적히고(Studio와 다른 자리), 확장을
   다시 읽어 기여가 빠지고, **사전 점검 캐시가 비워진다**(안 비우면 꺼도 「준비됨」이 올라간다).
   쓰는 Bot이 있으면 **몇 개가 실행 불가가 되는지 말하고** 기본은 「취소」다.
4. **끄고 켤 수 없는 줄**은 외부 확장(Center의 일이다)과 이 PC에 **없는** 확장이다.
5. **요구하는데 없는 확장도 줄로 보인다** (「필요하지만 없음」) — 목록에 없으면 왜 막혔는지 모른다.
6. **외부 확장은 봉투를 다시 검증한다** (C13 E6) — 서명이 맞지 않으면 「서명 확인 안 됨」이고,
   Center에 닿지 못하면 **들고 있던 것을 쓴다** (ADR-0007).
7. **BUI-04 「준비」가 「확장 꺼짐」으로 보인다** — 「확장 없음」으로 뭉치면 틀린 안내다.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeCredentials
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QMessageBox, QTableWidgetItem  # noqa: E402

from chaeksas.bot_ui.agent import Agent  # noqa: E402
from chaeksas.bot_ui.extension_dialog import (  # noqa: E402
    EXTERNAL_SUMMARY,
    NAME,
    NO_TOGGLE_ABSENT,
    NO_TOGGLE_EXTERNAL,
    STATE,
    STATE_ABSENT,
    STATE_BROKEN,
    STATE_OFF,
    STATE_ON,
    STATUS_GROUP,
    SUMMARY,
    TIER,
    USED_BY,
    VERSION,
    ExtensionsDialog,
    detail_sections,
    state_of,
)
from chaeksas.bot_ui.main_window import EXTENSION_OFF, NO_EXTENSION, readiness_label  # noqa: E402
from chaeksas.bot_ui.services import CACHE_NAME  # noqa: E402
from chaeksas.bot_ui.settings import Settings, data_dir  # noqa: E402
from chaeksas.bot_ui.store import Store  # noqa: E402
from chaeksas.contracts import AdminKey, definition_hash, key_id_for, sign  # noqa: E402
from chaeksas.contracts.manifest import (  # noqa: E402
    ExtensionNeed,
    Manifest,
    Requires,
    TaskTypeNeed,
)
from chaeksas.contracts.resources import ExtensionResource  # noqa: E402
from chaeksas.core.extensions import ExtensionHost  # noqa: E402
from chaeksas.core.preflight import EXTENSION_TURNED_OFF  # noqa: E402
from chaeksas.qt.theme import tokens  # noqa: E402

NOW = "2026-10-10T09:00:00+09:00"


# ─────────────────────────── 재료 ───────────────────────────


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
        "service": {"protocol": "chk-c11", "base_url": "http://svc-ocr:8000"},
        "requires_keys": [{"purpose": "run", "extra_scopes": ["ocr_read"]}],
        "contributes": {
            "task_types": [
                {
                    "id": "ocr_task",
                    "label": "문서 인식",
                    "executor": {"entry": "doc_ocr.client:OcrExecutor"},
                    "run_locations": ["pc"],
                }
            ],
            "agent_environments": [{"domain": "desktop", "entry": "doc_ocr.client:Desktop"}],
            "bot_ui.local_runtimes": [
                {
                    "id": "ocr-worker",
                    "label": "OCR 프로세스",
                    "entry": "doc_ocr.worker:serve",
                    "default_port": 8891,
                    "health": "/v1/health",
                }
            ],
        },
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
                        "request": {"method": "POST", "path": "/v2/invoice", "body": {"url": "{{input.url}}"}},
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


def host_with(*definitions: dict[str, Any], off: tuple[str, ...] = ()) -> ExtensionHost:
    host = ExtensionHost(api_version="1.0.0", off=off)
    for one in definitions:
        host.add_installed(json.dumps(one).encode("utf-8"), origin="test", root="chaeksas.ext.ui_automation")
    return host


def install_bot(
    *,
    bot_id: str = "fin.invoice",
    name: str = "청구서 처리",
    extensions: list[ExtensionNeed] | None = None,
    task_types: list[TaskTypeNeed] | None = None,
    domains: list[str] | None = None,
) -> Manifest:
    """설치된 Bot 하나 — **매니페스트 파일만** 둔다 (`bots.installed()`가 그것을 읽는다)."""
    manifest = Manifest.model_validate(
        {
            "schema": 1,
            "id": bot_id,
            "version": "1.0.0",
            "name": name,
            "kind": "bpm_process",
            "run_location": "pc",
            "entry": "main.bpmn",
            "content_hash": "sha256:" + "0" * 64,
            "human": {"approval_center": False, "approval_field": False, "confirmation": False},
            "built": {"by": "studio", "at": NOW, "core": "0.1.0", "spec_version": 1},
            "requires": Requires(
                extensions=extensions or [],
                task_types=task_types or [],
                domains=domains or [],
            ).to_json_dict(),
        }
    )
    folder = data_dir() / "bots" / manifest.id / manifest.version
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    return manifest


def hold_directory(*items: dict[str, Any]) -> None:
    """들고 있는 바깥 앱 명부 (`services.py`의 캐시) — 외부 확장 정의가 거기서 온다."""
    data_dir().mkdir(parents=True, exist_ok=True)
    (data_dir() / CACHE_NAME).write_text(
        json.dumps({"apps": {}, "extensions": list(items)}, ensure_ascii=False), encoding="utf-8"
    )


def make_agent(host: ExtensionHost, *, keys: list[AdminKey] | None = None, tmp_path: Path) -> Agent:
    """시험용 Agent — **확장을 다시 읽는 길도 시험의 것**이다.

    기본 `load_extensions()`는 엔트리 포인트를 읽어 진짜 설치본(`ui-automation`)을 들여온다.
    끄고 켜기는 확장을 다시 읽으므로 그 길을 바꿔 끼워야 손으로 지은 확장이 그대로 남는다.
    """
    definitions = [one.manifest.model_dump(mode="json", by_alias=True) for one in host.all()]
    agent = Agent(
        settings=Settings(disabled_extensions=tuple(sorted(host.off))),
        store=Store.load(tmp_path / "state.json"),
        credentials=FakeCredentials(),
        host=host,
        extensions=host.states(),
        extension_loader=lambda off: host_with(*definitions, off=tuple(off)),
    )
    agent.store.state.admin_keys = list(keys or [])
    return agent


def dialog(host: ExtensionHost, *, keys: list[AdminKey] | None = None, tmp_path: Path) -> ExtensionsDialog:
    return ExtensionsDialog(make_agent(host, keys=keys, tmp_path=tmp_path))


def cell(window: ExtensionsDialog, row: int, column: int) -> QTableWidgetItem:
    item = window.table.item(row, column)
    assert item is not None
    return item


@pytest.fixture(autouse=True)
def _app() -> Any:
    from PySide6.QtWidgets import QApplication

    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    try:
        yield QApplication([])
    except Exception as e:  # pragma: no cover - 환경 문제
        pytest.skip(f"Qt 플랫폼 플러그인을 띄울 수 없다: {e}")


@pytest.fixture(autouse=True)
def modal_question(monkeypatch: Any) -> list[tuple[str, str]]:
    """확인 창은 응답을 기다린다 — 띄운 글만 기록하고 **「취소」를 고른 것으로** 둔다 (U4)."""
    shown: list[tuple[str, str]] = []

    def question(_parent: Any, title: str, text: str, *_args: Any, **_kwargs: Any) -> Any:
        shown.append((title, text))
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", question)
    return shown


def say_yes(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_a, **_k: QMessageBox.StandardButton.Yes,
    )


# ─────────────────────────── 목록 ───────────────────────────


def test_the_list_draws_what_the_definition_says(tmp_path: Path) -> None:
    """이름·등급·버전·기여·상태가 모두 정의에서 온다 (창에 확장 이름이 없다)."""
    window = dialog(host_with(builtin()), tmp_path=tmp_path)
    assert window.table.rowCount() == 1
    assert cell(window, 0, NAME).text() == "문서 인식"
    assert cell(window, 0, NAME).toolTip() == "doc-ocr"
    assert cell(window, 0, TIER).text() == "내장"
    assert cell(window, 0, VERSION).text() == "1.2.0"
    assert cell(window, 0, STATE).text() == STATE_ON
    assert "태스크 종류 1" in cell(window, 0, SUMMARY).text()


def test_used_by_counts_the_installed_bots(tmp_path: Path) -> None:
    """「쓰는 Bot」은 **설치된 Bot이 말한 것**이다 (C1 `requires.extensions`).

    그림에 확장을 적지 않는 길(`requires.domains`의 AI 환경)도 함께 센다 — 끄면 멈출 Bot이다.
    """
    install_bot(extensions=[ExtensionNeed(id="doc-ocr", version=">=1,<2")])
    install_bot(bot_id="ops.scan", name="현장 스캔", domains=["desktop"])
    window = dialog(host_with(builtin()), tmp_path=tmp_path)

    assert cell(window, 0, USED_BY).text() == "2"
    assert cell(window, 0, USED_BY).toolTip() == "청구서 처리, 현장 스캔"


def test_an_extension_nobody_uses_says_so(tmp_path: Path) -> None:
    """**지우라고 하지 않는다** — 쓰는 Bot이 없을 뿐이다 (BUI-10 「쓰는 Bot 없음」과 같은 결)."""
    window = dialog(host_with(builtin()), tmp_path=tmp_path)
    assert cell(window, 0, USED_BY).text() == "쓰는 Bot 없음"


def test_turned_off_and_broken_are_different_states(tmp_path: Path) -> None:
    """ADR-0043 — 하나는 「켜세요」, 하나는 「고치세요」다. **색도 다르다.**"""
    off = dialog(host_with(builtin(), off=("doc-ocr",)), tmp_path=tmp_path)
    assert cell(off, 0, STATE).text() == STATE_OFF
    assert "껐습니다" in cell(off, 0, STATE).toolTip()

    broken = dialog(host_with(builtin(api=">=9,<10")), tmp_path=tmp_path)
    assert cell(broken, 0, STATE).text().startswith(STATE_BROKEN)
    assert "확장 API >=9,<10 필요" in cell(broken, 0, STATE).text()

    status = tokens.STATUS_MAP[STATUS_GROUP]
    assert status[STATE_OFF] != status[STATE_BROKEN], "꺼 둔 것이 고장처럼 보이면 안 된다"


def test_an_extension_the_bots_need_but_this_pc_lacks_gets_a_row(tmp_path: Path) -> None:
    """**목록에 없으면 왜 실행이 막히는지 알 수 없다** — 아래쪽에 「필요하지만 없음」으로 둔다."""
    install_bot(extensions=[ExtensionNeed(id="doc-ocr", version=">=2,<3")])
    window = dialog(host_with(), tmp_path=tmp_path)

    assert window.table.rowCount() == 1
    assert cell(window, 0, NAME).text() == "doc-ocr"
    assert cell(window, 0, STATE).text() == STATE_ABSENT
    assert cell(window, 0, VERSION).text() == ">=2,<3"
    assert not window.disable_button.isEnabled()
    assert window.disable_button.toolTip() == NO_TOGGLE_ABSENT


def test_a_definition_that_could_not_be_read_is_said_below_the_table(tmp_path: Path) -> None:
    """id를 모르니 줄을 만들 수 없다 — 그래도 **조용히 사라지지 않는다** (`LoadFailure`)."""
    host = host_with()
    host.add_installed(b"{ this is not json", origin="entry_point:broken", root="chaeksas.ext.ui_automation")
    window = dialog(host, tmp_path=tmp_path)

    assert window.table.rowCount() == 0
    assert "entry_point:broken" in window.note.text()


# ─────────────────────────── 상세 ───────────────────────────


def test_the_detail_tells_where_the_keys_go(tmp_path: Path) -> None:
    """키마다 **넣는 화면까지** 말해 준다 (실행용은 BUI-10, 유틸리티용은 BUI-03)."""
    window = dialog(host_with(builtin()), tmp_path=tmp_path)
    shown = window.detail.toPlainText()

    assert "BUI-10" in shown
    assert "ocr_read" in shown


def test_the_detail_says_the_server_part_and_who_watches_it(tmp_path: Path) -> None:
    """**상태를 적지 않는다** — 서비스 앱이 살아 있나는 Center가 본다 (C7). 주소만 말한다."""
    window = dialog(host_with(builtin()), tmp_path=tmp_path)
    shown = window.detail.toPlainText()

    assert "http://svc-ocr:8000" in shown
    assert "CON-07" in shown


def test_the_detail_lists_the_ai_environment() -> None:
    """AI 환경은 C7 요약에 없다 (`domain`은 id가 아니다) — 상세는 정의를 직접 읽는다 (ADR-0037)."""
    found = dict(detail_sections(_row(builtin())))
    assert "AI 환경: desktop" in found["기여"]


def test_the_detail_says_the_runtime_is_off_when_nobody_started_it(tmp_path: Path) -> None:
    """**띄우지 않는다** — 감시자가 없으면 아직 띄우지 않은 것이다 (BUI-09와 같은 표기)."""
    window = dialog(host_with(builtin()), tmp_path=tmp_path)
    shown = window.detail.toPlainText()

    assert "OCR 프로세스 (ocr-worker)" in shown
    assert "꺼 둠 (필요할 때 시작)" in shown
    assert "포트 8891" in shown


def _row(definition: dict[str, Any], *, off: tuple[str, ...] = ()) -> Any:
    from chaeksas.bot_ui.extension_dialog import ExtensionRow

    host = host_with(definition, off=off)
    return ExtensionRow(loaded=host.all()[0])


# ─────────────────────────── 끄고 켜기 (ADR-0043) ───────────────────────────


def test_turning_off_saves_to_the_bot_ui_settings_right_away(tmp_path: Path, monkeypatch: Any) -> None:
    """**「저장」이 없다** — 누르는 그 자리에서 Bot UI **제 설정**에 적힌다 (Studio와 다른 자리)."""
    say_yes(monkeypatch)
    window = dialog(host_with(builtin()), tmp_path=tmp_path)
    window.table.selectRow(0)
    window.set_off(True)

    assert window._agent.settings.disabled_extensions == ("doc-ocr",)
    assert Settings.load().disabled_extensions == ("doc-ocr",)
    assert cell(window, 0, STATE).text() == STATE_OFF
    assert window.changed

    window.set_off(False)
    assert not window._agent.settings.disabled_extensions
    assert not Settings.load().disabled_extensions
    assert cell(window, 0, STATE).text() == STATE_ON


def test_turning_off_drops_every_contribution(tmp_path: Path, monkeypatch: Any) -> None:
    """꺼지면 기여가 하나도 들어오지 않는다 — 태스크 종류·런타임·AI 환경이 한꺼번에 빠진다."""
    say_yes(monkeypatch)
    window = dialog(host_with(builtin()), tmp_path=tmp_path)
    host = window._agent.host
    assert host is not None
    assert host.task_type("ocr_task") is not None

    window.table.selectRow(0)
    window.set_off(True)

    after = window._agent.host
    assert after is not None
    assert after.task_type("ocr_task") is None
    assert after.local_runtimes() == []
    assert after.environment_owner("desktop") is None


def test_turning_off_makes_the_next_heartbeat_say_it(tmp_path: Path, monkeypatch: Any) -> None:
    """**사전 점검 캐시를 비운다** — 안 비우면 꺼도 「준비됨」이 하트비트로 계속 올라간다 (C4)."""
    say_yes(monkeypatch)
    install_bot(task_types=[TaskTypeNeed(id="ocr_task", extension="doc-ocr", run_locations=["pc"])])
    window = dialog(host_with(builtin()), tmp_path=tmp_path)
    agent = window._agent
    assert [one.ready for one in agent.readiness()] == [True]

    window.table.selectRow(0)
    window.set_off(True)

    reported = agent.readiness()
    assert [one.ready for one in reported] == [False]
    assert reported[0].blocked == [EXTENSION_TURNED_OFF]
    # C4 `ExtensionState.off` — Center도 「꺼짐」과 「호환 안 됨」을 가른다.
    assert [(one.id, one.off, one.enabled) for one in agent.extensions] == [("doc-ocr", True, False)]


def test_turning_off_says_how_many_bots_stop(tmp_path: Path) -> None:
    """쓰는 Bot이 있으면 **몇 개가 실행 불가가 되는지** 말하고 **기본은 「취소」**다 (U4)."""
    install_bot(extensions=[ExtensionNeed(id="doc-ocr", version=">=1,<2")])
    window = dialog(host_with(builtin()), tmp_path=tmp_path)
    window.table.selectRow(0)
    window.set_off(True)

    assert window._agent.settings.disabled_extensions == (), "「취소」를 골랐으면 아무것도 바뀌지 않는다"
    assert cell(window, 0, STATE).text() == STATE_ON


def test_the_confirmation_names_the_bots(tmp_path: Path, modal_question: list[tuple[str, str]]) -> None:
    install_bot(extensions=[ExtensionNeed(id="doc-ocr", version=">=1,<2")])
    window = dialog(host_with(builtin()), tmp_path=tmp_path)
    window.table.selectRow(0)
    window.set_off(True)

    assert modal_question, "확인 창을 띄워야 한다"
    _title, text = modal_question[-1]
    assert "Bot 1개가 실행 불가가 됩니다" in text
    assert "청구서 처리" in text


def test_turning_on_asks_nothing(tmp_path: Path, modal_question: list[tuple[str, str]]) -> None:
    """켜는 것은 잃을 것이 없다 — 묻지 않는다."""
    window = dialog(host_with(builtin(), off=("doc-ocr",)), tmp_path=tmp_path)
    window.table.selectRow(0)
    window.set_off(False)

    assert not modal_question
    assert window._agent.settings.disabled_extensions == ()


def test_an_external_extension_is_not_turned_off_here(tmp_path: Path) -> None:
    """C13 E6 — 외부 확장은 Center에 등록된 정의다. 끄고 켜는 일은 Center에서 한다."""
    definition = external()
    envelope, keys = signed(definition)
    hold_directory({"definition": definition, "envelope": envelope})
    window = dialog(host_with(), keys=keys, tmp_path=tmp_path)

    assert window.table.rowCount() == 1
    assert cell(window, 0, TIER).text() == "외부"
    assert cell(window, 0, STATE).text() == STATE_ON
    assert cell(window, 0, SUMMARY).text() == EXTERNAL_SUMMARY
    assert not window.disable_button.isEnabled()
    assert window.disable_button.toolTip() == NO_TOGGLE_EXTERNAL

    window.set_off(True)
    assert window._agent.settings.disabled_extensions == ()


# ─────────────────────────── 외부 확장 (C13 E6) ───────────────────────────


def test_an_external_definition_with_a_bad_envelope_says_so(tmp_path: Path) -> None:
    """**봉투를 다시 검증한다** — 관리자 토큰만 새어도 Bot의 키가 다른 주소로 가면 안 된다."""
    definition = external()
    envelope, _keys = signed(definition)
    hold_directory({"definition": definition, "envelope": envelope})
    # 그 서명을 만든 키를 **모르는** PC다 (하트비트로 받은 공개키가 없다).
    window = dialog(host_with(), keys=[], tmp_path=tmp_path)

    assert window.table.rowCount() == 1
    assert cell(window, 0, STATE).text() == "서명 확인 안 됨 — 쓰지 않음"


def test_refresh_keeps_what_we_hold_when_center_cannot_be_called(tmp_path: Path) -> None:
    """ADR-0007 — 현장 PC다. 부르지 못하면 **들고 있던 것을 쓰고** 사유만 말한다.

    여기서는 Center API 키가 없는 PC다 (Studio는 이런 자리에서 그냥 「설정하세요」로 끝낸다 —
    현장은 그럴 수 없다. 들고 있는 정의로 Bot이 계속 돌아야 한다).
    """
    definition = external()
    envelope, keys = signed(definition)
    hold_directory({"definition": definition, "envelope": envelope})
    install_bot(
        extensions=[
            ExtensionNeed(
                id="ext-ocr", version=">=1,<2", definition_hash=definition_hash(definition)
            )
        ]
    )
    window = dialog(host_with(), keys=keys, tmp_path=tmp_path)
    window.refresh_external()

    assert [one.id for one in window.external] == ["ext-ocr"]
    assert "Center를 부르지 못했습니다" in window.note.text()
    assert cell(window, 0, STATE).text() == STATE_ON


def test_refresh_takes_the_definition_from_center(tmp_path: Path) -> None:
    """「새로 고침」은 **설치된 Bot이 요구하는 외부 확장만** 받는다 (명부의 규칙이다).

    받은 것은 들고 있는 명부에 남아, 다음에 창을 열 때 Center 없이도 보인다.
    """
    definition = external()
    envelope, keys = signed(definition)
    install_bot(
        extensions=[
            ExtensionNeed(id="ext-ocr", version=">=1,<2", definition_hash=definition_hash(definition))
        ]
    )

    class FakeCenter:
        def __init__(self) -> None:
            self.asked: list[str] = []

        def service_apps(self) -> list[Any]:
            return []

        def extension(self, extension_id: str) -> Any:
            self.asked.append(extension_id)
            return ExtensionResource(
                id=definition["id"],
                version=definition["version"],
                name=definition["name"],
                tier=definition["tier"],
                definition=definition,
                envelope=envelope,
            )

    fake = FakeCenter()
    agent = make_agent(host_with(), keys=keys, tmp_path=tmp_path)
    agent.credentials = FakeCredentials("chk_ctr_test")
    agent.client_factory = lambda _url, _key: fake  # type: ignore[assignment, return-value]
    window = ExtensionsDialog(agent)
    # 받기 전에는 **요구하는데 없는** 줄이다 (들고 있는 명부가 비어 있다).
    assert cell(window, 0, STATE).text() == STATE_ABSENT

    window.refresh_external()

    assert fake.asked == ["ext-ocr"]
    assert [one.id for one in window.external] == ["ext-ocr"]
    assert cell(window, 0, STATE).text() == STATE_ON
    assert cell(window, 0, TIER).text() == "외부"
    # 받은 것은 **명부에 남는다** — 다음에 창을 열 때 Center 없이도 보인다 (ADR-0007).
    assert ExtensionsDialog(agent).rows[0].loaded is not None


# ─────────────────────────── 메뉴 (BUI-01·BUI-02) ───────────────────────────


def with_utility() -> dict[str, Any]:
    """유틸리티를 기여하는 확장 — 끄면 「도구」 메뉴에서 사라져야 한다."""
    return builtin(
        contributes={
            "bot_ui.utilities": [
                {
                    "id": "scan-things",
                    "label": "문서 담기",
                    "menu": "tools",
                    "entry": "doc_ocr.client:Scan",
                }
            ]
        }
    )


def tools_actions(window: Any) -> list[Any]:
    from PySide6.QtWidgets import QMenu

    tools = next(one for one in window.menuBar().findChildren(QMenu) if one.title() == "도구")
    return list(tools.actions())


def tools_menu(window: Any) -> list[str]:
    return [action.text() for action in tools_actions(window)]


def test_the_tools_menu_opens_this_window(tmp_path: Path) -> None:
    """BUI-01·BUI-02 「도구」 → 「확장...」. **붙기 전까지 꺼져 있던 항목이다.**"""
    from PySide6.QtWidgets import QMenu, QSystemTrayIcon

    from chaeksas.bot_ui.main_window import MainWindow
    from chaeksas.bot_ui.tray import Tray

    agent = make_agent(host_with(builtin()), tmp_path=tmp_path)
    window = MainWindow(agent)
    try:
        found = [one for one in tools_actions(window) if one.text() == "확장..."]
        assert found and found[0].isEnabled()
    finally:
        window.close()

    if not QSystemTrayIcon.isSystemTrayAvailable():
        pytest.skip("이 환경에는 시스템 트레이가 없다")
    tray = Tray(agent)
    asked: list[bool] = []
    tray.open_extensions.connect(lambda: asked.append(True))
    tray.refresh()
    tools = next(one for one in tray.contextMenu().findChildren(QMenu) if one.title() == "도구")
    entry = next(one for one in tools.actions() if one.text() == "확장...")
    assert entry.isEnabled(), "트레이가 주 진입점이다 (창을 닫아도 트레이에 남는다)"
    entry.trigger()
    assert asked == [True], "창은 메인 창이 쥔다 — 트레이는 열어 달라고만 한다"
    tray.hide()
    tray.setParent(None)


def test_turning_an_extension_off_takes_its_utility_out_of_the_menu(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """「도구」는 기여에서 온다 — 꺼지면 **그 자리에서** 빠져야 한다 (다음에 열면 LookupError다)."""
    from chaeksas.bot_ui import extension_dialog as module
    from chaeksas.bot_ui.main_window import MainWindow

    say_yes(monkeypatch)
    agent = make_agent(host_with(with_utility()), tmp_path=tmp_path)
    window = MainWindow(agent)
    try:
        assert "문서 담기..." in tools_menu(window)

        def turn_it_off(dialog: module.ExtensionsDialog) -> int:
            dialog.table.selectRow(0)
            dialog.set_off(True)
            return 0

        monkeypatch.setattr(module.ExtensionsDialog, "exec", turn_it_off)
        window.open_extensions()

        texts = tools_menu(window)
        assert "문서 담기..." not in texts
        assert texts.count("확장...") == 1, "메뉴를 두 번 그리지 않는다"
    finally:
        window.close()


# ─────────────────────────── BUI-04 「준비」 ───────────────────────────


def test_the_ready_column_says_turned_off_not_missing() -> None:
    """**「꺼 뒀다」와 「없다」는 다른 말이다** — 고치는 길이 「켜기」와 「다시 깔기」로 갈린다.

    「사전 점검 실행 불가」로 떨어지면 더 나쁘다 — 점검은 잘 돌았고 답이 「꺼져 있다」다.
    """
    from chaeksas.core.preflight import check as run_preflight

    m = install_bot(task_types=[TaskTypeNeed(id="ocr_task", extension="doc-ocr", run_locations=["pc"])])

    off = run_preflight(m, key_value=lambda _ref: None, host=host_with(builtin(), off=("doc-ocr",)))
    assert readiness_label(off)[0] == EXTENSION_OFF

    absent = run_preflight(m, key_value=lambda _ref: None, host=host_with())
    assert readiness_label(absent)[0] == NO_EXTENSION


def test_the_ready_label_has_its_own_color() -> None:
    """`status_map` 「Bot 준비」에 있는 표기만 쓴다 — 「확장 꺼짐」은 **고장이 아니다**."""
    ready = tokens.STATUS_MAP["Bot 준비"]
    assert ready[EXTENSION_OFF] == "neutral"
    assert ready[NO_EXTENSION] == "failed"


def test_state_of_never_invents_a_label() -> None:
    """표기는 색을 고르는 데 쓴다 — `status_map` 「확장」에 없는 값이 나오면 색이 없다."""
    known = set(tokens.STATUS_MAP[STATUS_GROUP])
    rows = [
        _row(builtin()),
        _row(builtin(), off=("doc-ocr",)),
        _row(builtin(api=">=9,<10")),
    ]
    for row in rows:
        assert state_of(row)[0] in known
