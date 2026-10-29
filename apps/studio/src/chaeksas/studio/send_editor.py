"""STU-04 보내기 편집기 — `chk:email`·`chk:webhook` (C14 §보내기).

속성 패널이 보내기(`sendTask`)를 만나면 탭으로 끼운다. **규약은 결재·STU-14와 같다**
(`load`/`dump`/`problems`/`changed`) — 다른 것은 하나다: 이 편집기는 `chk:` 요소 **둘 중 하나**를
고르므로 `dump()`가 `{"email": 본문}` 또는 `{"webhook": 본문}`을 준다(속성 패널이 고르지 않은 쪽을 지운다).

- **적어 둔 것을 조용히 바꾸지 않는다.** 편집기가 다루지 않는 칸은 읽은 그대로 돌려준다.
- 채널을 **바꾸면 다른 쪽 설정은 지운다** — 둘이 다 있으면 엔진은 메일만 쓰므로(`handle_send`)
  남겨 두면 보이지 않는 설정이 된다. 읽은 그림에 둘이 다 있으면 메일을 보이고 경고한다.
- 「적용」을 막는 것은 **엔진이 거부하거나 반드시 실패할 것**뿐이다 — 받는 사람 없음(`SEND_FAILED`),
  URL 없음, 틀린 변수 이름, 빈 「선택 변수」. 「변수 전부」는 경고다(B13).
- **C14에 없는 칸을 두지 않는다** (웹훅 헤더·메일 HTML 여부) — 엔진이 읽지 않는 칸은 거짓 약속이다.
- 마지막 관문은 계약 모델(`Email`·`Webhook`)이다 — 여기서 놓친 것도 그것이 잡는다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import QStringListModel, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import WEBHOOK_BODY_ALL, Email, Webhook, is_var_name
from chaeksas.qt.theme import set_role
from chaeksas.qt.theme.tokens import SPACE_2, SPACE_3
from chaeksas.studio.name_pick import attach

#: 탭 이름.
TAB_LABEL = "보내기"

#: `chk:` 요소 이름 — 채널이 곧 요소다 (C14).
CHANNEL_EMAIL = "email"
CHANNEL_WEBHOOK = "webhook"
CHANNELS = (CHANNEL_EMAIL, CHANNEL_WEBHOOK)

#: 고를 수 있는 메서드 — 본문을 싣는 것만 (그림에 다른 것이 있으면 지우지 않고 더해 보인다).
METHODS = ("POST", "PUT", "PATCH")

#: 웹훅 본문 적는 법 (C14 — `all` | `fields:[…]` | `template:"…"`). 엔진(`core.nodes`)과 같은 해석.
BODY_ALL = "all"
BODY_FIELDS = "fields"
BODY_TEMPLATE = "template"
BODY_KINDS = (
    (BODY_ALL, "변수 전부"),
    (BODY_FIELDS, "선택 변수"),
    (BODY_TEMPLATE, "템플릿"),
)
_FIELDS = re.compile(r"^fields\s*:\s*\[(.*)\]$", re.S)
_TEMPLATE = re.compile(r"^template\s*:\s*(.*)$", re.S)

ALL_WARNING = "「변수 전부」는 실행 변수를 모두 보냅니다 — 비밀이 섞일 수 있습니다 (B13)."
BOTH_WARNING = (
    "이 태스크에는 메일과 웹훅이 둘 다 적혀 있습니다 — 엔진은 메일만 씁니다. 「적용」하면 보이는 채널만 남습니다."
)


class SendEditor(QWidget):
    """보내기 태스크 하나."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None, *, names: QStringListModel | None = None) -> None:
        super().__init__(parent)
        self._loaded: dict[str, dict[str, Any]] = {}
        self._quiet = False

        self.channel_picks: dict[str, QRadioButton] = {
            CHANNEL_EMAIL: QRadioButton("메일", self),
            CHANNEL_WEBHOOK: QRadioButton("웹훅", self),
        }
        self.channel_group = QButtonGroup(self)
        for one in self.channel_picks.values():
            self.channel_group.addButton(one)
        self.channel_picks[CHANNEL_EMAIL].setChecked(True)

        lines = self.fontMetrics().lineSpacing()

        # 메일
        self.to_box = QLineEdit(self)
        self.to_box.setPlaceholderText("주소 또는 {변수}, 쉼표로 여럿 (필수)")
        self.cc_box = QLineEdit(self)
        self.cc_box.setPlaceholderText("비우면 참조 없음")
        self.subject_box = QLineEdit(self)
        self.body_box = QPlainTextEdit(self)
        self.body_box.setPlaceholderText("{변수}로 값을 채웁니다")
        self.body_box.setFixedHeight(lines * 6)
        self.attachments_box = QLineEdit(self)
        self.attachments_box.setPlaceholderText("변수 이름, 쉼표로 여럿 — 값은 파일 경로")
        self.attachments_box.setToolTip("대개 데이터 객체(파일 출력)의 「경로 저장」 변수입니다.")
        self.email_store_box = QLineEdit(self)
        self.email_store_box.setPlaceholderText("변수 이름 — 비우면 남기지 않습니다")
        self.email_store_box.setToolTip('보낸 결과 요약 {"ok", "to", "id"}가 이 변수에 들어갑니다.')

        # 웹훅
        self.url_box = QLineEdit(self)
        self.url_box.setPlaceholderText("https://… — {변수}를 쓸 수 있습니다 (필수)")
        self.url_box.setToolTip("허용 호스트는 운영자가 설정에 적은 것만 열립니다 (기본은 닫힘).")
        self.method_box = QComboBox(self)
        self.method_box.addItems(list(METHODS))
        self.timeout_box = QSpinBox(self)
        self.timeout_box.setRange(0, 3600)
        self.timeout_box.setSuffix(" 초")
        self.timeout_box.setSpecialValueText("설정의 기본")
        self.body_kind = QComboBox(self)
        for value, text in BODY_KINDS:
            self.body_kind.addItem(text, value)
        self.fields_box = QLineEdit(self)
        self.fields_box.setPlaceholderText("보낼 변수 이름, 쉼표로 여럿")
        self.template_box = QPlainTextEdit(self)
        self.template_box.setPlaceholderText("{변수}로 채운 글을 그대로 보냅니다")
        self.template_box.setFixedHeight(lines * 6)
        self.webhook_store_box = QLineEdit(self)
        self.webhook_store_box.setPlaceholderText("변수 이름 — 비우면 남기지 않습니다")
        self.webhook_store_box.setToolTip('응답 요약 {"ok", "status", "body"}가 이 변수에 들어갑니다.')

        self.warning = QLabel("", self)
        self.warning.setWordWrap(True)
        set_role(self.warning, "error")
        self.note = QLabel("", self)
        self.note.setWordWrap(True)
        set_role(self.note, "muted")

        # 고르지 않은 쪽은 **숨긴다** — 쌓아 두면 가장 큰 쪽의 높이가 늘 빈자리로 남는다.
        self.channel_boxes = {CHANNEL_EMAIL: self._email_box(), CHANNEL_WEBHOOK: self._webhook_box()}
        self._build_layout()
        for line in (self.email_store_box, self.webhook_store_box):
            attach(line, names)

        self._wire()
        self._refresh()

    # ── 짜기 ──

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE_3)
        box = QGroupBox("채널", self)
        column = QVBoxLayout(box)
        _tight(column)
        for one in self.channel_picks.values():
            column.addWidget(one)
        layout.addWidget(box)
        for shown in self.channel_boxes.values():
            layout.addWidget(shown)
        layout.addWidget(self.note)
        layout.addWidget(self.warning)
        layout.addStretch(1)

    def _email_box(self) -> QGroupBox:
        box = QGroupBox("메일", self)
        form = QFormLayout(box)
        _tight(form)
        form.addRow("받는 사람", self.to_box)
        form.addRow("참조", self.cc_box)
        form.addRow("제목", self.subject_box)
        form.addRow("본문", self.body_box)
        form.addRow("첨부", self.attachments_box)
        form.addRow("결과 저장", self.email_store_box)
        return box

    def _webhook_box(self) -> QGroupBox:
        box = QGroupBox("웹훅", self)
        form = QFormLayout(box)
        _tight(form)
        form.addRow("URL", self.url_box)
        form.addRow("메서드", self.method_box)
        form.addRow("제한 시간", self.timeout_box)
        form.addRow("본문", self.body_kind)
        form.addRow("선택 변수", self.fields_box)
        form.addRow("템플릿", self.template_box)
        form.addRow("응답 저장", self.webhook_store_box)
        self._webhook_form = form
        return box

    def _wire(self) -> None:
        for line in (
            self.to_box, self.cc_box, self.subject_box, self.attachments_box, self.email_store_box,
            self.url_box, self.fields_box, self.webhook_store_box,
        ):
            line.textChanged.connect(self._touched)
        for area in (self.body_box, self.template_box):
            area.textChanged.connect(self._touched)
        self.method_box.currentIndexChanged.connect(self._touched)
        self.timeout_box.valueChanged.connect(self._touched)
        self.body_kind.currentIndexChanged.connect(self._touched)
        self.channel_group.buttonToggled.connect(self._touched)

    # ── 규약 ──

    def load(self, chk: Mapping[str, Any]) -> None:
        """`{"email": 본문, "webhook": 본문}` 중 있는 것을 그린다 (둘 다 없으면 빈 메일)."""
        self._quiet = True
        self._loaded = {k: dict(v) for k, v in chk.items() if k in CHANNELS and isinstance(v, Mapping)}
        email = self._loaded.get(CHANNEL_EMAIL, {})
        webhook = self._loaded.get(CHANNEL_WEBHOOK, {})
        # 엔진은 메일을 먼저 본다 — 둘 다 있으면 메일이 쓰이는 쪽이다.
        only_webhook = CHANNEL_WEBHOOK in self._loaded and CHANNEL_EMAIL not in self._loaded
        channel = CHANNEL_WEBHOOK if only_webhook else CHANNEL_EMAIL
        self.channel_picks[channel].setChecked(True)

        self.to_box.setText(_joined(email.get("to")))
        self.cc_box.setText(_joined(email.get("cc")))
        self.subject_box.setText(str(email.get("subject") or ""))
        self.body_box.setPlainText(str(email.get("body") or ""))
        self.attachments_box.setText(_joined(email.get("attachments")))
        self.email_store_box.setText(str(email.get("store_as") or ""))

        self.url_box.setText(str(webhook.get("url") or ""))
        method = str(webhook.get("method") or "POST").upper()
        if self.method_box.findText(method) < 0:
            self.method_box.addItem(method)  # 모르는 메서드도 지우지 않는다 — 보내는 쪽이 말한다
        self.method_box.setCurrentText(method)
        timeout = webhook.get("timeout_s")
        self.timeout_box.setValue(int(timeout) if isinstance(timeout, int) and timeout > 0 else 0)
        kind, names, template = _read_body(str(webhook.get("body") or WEBHOOK_BODY_ALL))
        self.body_kind.setCurrentIndex(self.body_kind.findData(kind))
        self.fields_box.setText(", ".join(names))
        self.template_box.setPlainText(template)
        self.webhook_store_box.setText(str(webhook.get("store_as") or ""))
        self._quiet = False
        self._refresh()

    def channel(self) -> str:
        return CHANNEL_WEBHOOK if self.channel_picks[CHANNEL_WEBHOOK].isChecked() else CHANNEL_EMAIL

    def dump(self) -> dict[str, Any]:
        """`{고른 채널: 본문}` — 본문은 **읽은 것 위에** 고친 칸만 얹는다."""
        if self.channel() == CHANNEL_WEBHOOK:
            return {CHANNEL_WEBHOOK: self._webhook()}
        return {CHANNEL_EMAIL: self._email()}

    def problems(self) -> tuple[list[str], list[str]]:
        """`(적용을 막는 것, 경고)`."""
        errors: list[str] = []
        warnings: list[str] = []
        if self.channel() == CHANNEL_EMAIL:
            if not _split(self.to_box.text()):
                errors.append("받는 사람을 적으세요.")
            errors.extend(
                f"첨부 변수 이름으로 쓸 수 없습니다: {name}"
                for name in _split(self.attachments_box.text())
                if not is_var_name(name)
            )
            store = self.email_store_box
        else:
            if not self.url_box.text().strip():
                errors.append("URL을 적으세요.")
            kind = self.body_kind.currentData()
            if kind == BODY_FIELDS:
                picked = _split(self.fields_box.text())
                if not picked:
                    errors.append("보낼 변수를 적으세요 (「선택 변수」).")
                errors.extend(f"보낼 변수 이름으로 쓸 수 없습니다: {name}" for name in picked if not is_var_name(name))
            elif kind == BODY_ALL:
                warnings.append(ALL_WARNING)
            store = self.webhook_store_box
        name = store.text().strip()
        if name and not is_var_name(name):
            errors.append(f"저장할 변수 이름으로 쓸 수 없습니다: {name}")
        if len(self._loaded) == len(CHANNELS):
            warnings.append(BOTH_WARNING)
        if not errors:
            model = Webhook if self.channel() == CHANNEL_WEBHOOK else Email
            try:
                model.model_validate(self.dump()[self.channel()])
            except ValidationError as e:
                first = e.errors()[0]
                where = ".".join(str(p) for p in first.get("loc", ()))
                errors.append(f"보내기 칸이 계약과 맞지 않습니다 ({where}): {first.get('msg')}")
        self.warning.setText(errors[0] if errors else "")
        self.note.setText(" ".join(warnings))
        return errors, warnings

    # ── 안쪽 ──

    def _email(self) -> dict[str, Any]:
        out = dict(self._loaded.get(CHANNEL_EMAIL, {}))
        out["to"] = _split(self.to_box.text())
        _put(out, "cc", _split(self.cc_box.text()) or None)
        _put(out, "subject", self.subject_box.text().strip() or None)
        _put(out, "body", self.body_box.toPlainText() or None)
        _put(out, "attachments", _split(self.attachments_box.text()) or None)
        _put(out, "store_as", self.email_store_box.text().strip() or None)
        return out

    def _webhook(self) -> dict[str, Any]:
        out = dict(self._loaded.get(CHANNEL_WEBHOOK, {}))
        out["url"] = self.url_box.text().strip()
        method = self.method_box.currentText()
        # 기본값(`POST`)은 적지 않는다 — 읽은 그림에 있었으면 그대로 둔다.
        _put(out, "method", method if method != "POST" or "method" in out else None)
        _put(out, "timeout_s", self.timeout_box.value() or None)
        kind = self.body_kind.currentData()
        if kind == BODY_FIELDS:
            body: str | None = f"fields:[{', '.join(_split(self.fields_box.text()))}]"
        elif kind == BODY_TEMPLATE:
            # 늘 따옴표로 감싼다 — 엔진은 양 끝이 같은 따옴표일 때만 벗긴다(글이 따옴표로 시작·끝나도 산다).
            body = f'template:"{self.template_box.toPlainText()}"'
        else:
            body = WEBHOOK_BODY_ALL if "body" in out else None
        _put(out, "body", body)
        _put(out, "store_as", self.webhook_store_box.text().strip() or None)
        return out

    def _touched(self, *_args: object) -> None:
        if self._quiet:
            return
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        for name, box in self.channel_boxes.items():
            box.setVisible(name == self.channel())
        kind = self.body_kind.currentData()
        self._webhook_form.setRowVisible(self.fields_box, kind == BODY_FIELDS)
        self._webhook_form.setRowVisible(self.template_box, kind == BODY_TEMPLATE)
        self.problems()


def _read_body(body: str) -> tuple[str, list[str], str]:
    """`body` 글 → `(종류, 선택 변수, 템플릿)`. 엔진(`core.nodes._webhook_body`)과 같은 해석이다.

    모르는 모양은 **템플릿 칸에 글 그대로** 보인다 — 지우지 않는다(검사·실행이 말한다).
    """
    text = body.strip()
    if text == WEBHOOK_BODY_ALL:
        return BODY_ALL, [], ""
    found = _FIELDS.match(text)
    if found is not None:
        return BODY_FIELDS, _split(found.group(1)), ""
    found = _TEMPLATE.match(text)
    if found is not None:
        inner = found.group(1).strip()
        if len(inner) >= 2 and inner[0] == inner[-1] and inner[0] in "\"'":
            inner = inner[1:-1]
        return BODY_TEMPLATE, [], inner
    return BODY_TEMPLATE, [], text


def _joined(value: Any) -> str:
    return ", ".join(str(v) for v in value) if isinstance(value, list) else ""


def _put(out: dict[str, Any], key: str, value: Any) -> None:
    """값이 없으면 칸을 **지운다** (빈 글·빈 목록을 그림에 남기지 않는다)."""
    if value is None:
        out.pop(key, None)
    else:
        out[key] = value


def _split(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,，]", text) if part.strip()]


def _tight(layout: Any) -> None:
    """묶음 안쪽 여백 — 결재 편집기와 같다."""
    layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)


__all__ = [
    "ALL_WARNING",
    "BODY_ALL",
    "BODY_FIELDS",
    "BODY_TEMPLATE",
    "BOTH_WARNING",
    "CHANNEL_EMAIL",
    "CHANNEL_WEBHOOK",
    "METHODS",
    "TAB_LABEL",
    "SendEditor",
]
