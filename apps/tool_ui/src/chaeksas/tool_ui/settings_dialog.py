"""TOL-02 Tool UI 설정 — 확장이 선언한 `scope: tool_ui` 칸만 (ADR-0077).

**확장마다 탭 하나**이고 탭 이름은 확장 이름이다. 「저장」 전에는 아무것도 바뀌지 않는다 —
비밀 칸은 OS 비밀 저장소로 가고(못 쓰면 **창을 닫지 않는다**), 나머지는 설정 파일로 간다.
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts import SCOPE_TOOL_UI, ConfigurationItem
from chaeksas.core.extensions import ExtensionHost
from chaeksas.qt.theme import set_role
from chaeksas.tool_ui.credentials import SecretsUnavailable, ToolCredentials, extension_secret_env
from chaeksas.tool_ui.settings import ToolSettings

TITLE = "설정 — Chaeksas Tool UI"
MIN_WIDTH = 520
NO_FIELDS = "이 PC의 확장이 Tool UI 설정을 선언하지 않았습니다."
KEY_STORED = "저장됨 — 바꾸려면 새 값을 넣으세요"
KEY_FROM_ENV = "환경변수로 들어옵니다 — 여기서 바꿀 수 없습니다"


class ToolSettingsDialog(QDialog):
    """`(확장, 칸)` → (기여, 입력 칸). `saved`는 「저장」을 누른 뒤의 설정이다."""

    def __init__(
        self,
        host: ExtensionHost,
        settings: ToolSettings,
        credentials: ToolCredentials,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.host = host
        self.settings = settings
        self.credentials = credentials
        self.saved: ToolSettings | None = None
        self.fields: dict[tuple[str, str], tuple[ConfigurationItem, QLineEdit]] = {}
        self.setWindowTitle(TITLE)
        self.setMinimumWidth(MIN_WIDTH)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        for found in host.enabled():
            items = [one for one in found.manifest.contributes.configuration if one.scope == SCOPE_TOOL_UI]
            if items:
                self.tabs.addTab(self._page(found.id, items), found.manifest.name)
        if self.tabs.count():
            layout.addWidget(self.tabs)
        else:
            empty = QLabel(NO_FIELDS)
            empty.setWordWrap(True)
            layout.addWidget(empty)

        self.error = QLabel("")
        set_role(self.error, "error")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _page(self, extension_id: str, items: list[ConfigurationItem]) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        stored = self.settings.extension(extension_id)
        for item in items:
            field = QLineEdit()
            field.setObjectName(f"ext:{extension_id}:{item.key}")
            if item.secret:
                field.setEchoMode(QLineEdit.EchoMode.Password)
                if os.environ.get(extension_secret_env(extension_id, item.key)):
                    field.setPlaceholderText(KEY_FROM_ENV)
                    field.setEnabled(False)
                elif self.credentials.stored_extension_secret(extension_id, item.key):
                    field.setPlaceholderText(KEY_STORED)
            else:
                value = stored.get(item.key)
                field.setText("" if value is None else str(value))
            form.addRow(item.label, field)
            self.fields[(extension_id, item.key)] = (item, field)
        return page

    def plain_values(self) -> dict[str, dict[str, Any]]:
        """비밀이 **아닌** 칸만. 창에 보이지 않은 칸(꺼 둔 확장의 것)은 그대로 둔다."""
        out: dict[str, dict[str, Any]] = {}
        for (extension_id, key), (item, field) in self.fields.items():
            if item.secret:
                continue
            out.setdefault(extension_id, self.settings.extension(extension_id))
            text = field.text().strip()
            if text:
                out[extension_id][key] = text
            else:
                out[extension_id].pop(key, None)
        return out

    def save(self) -> None:
        """비밀은 저장소로, 나머지는 설정 파일로. 비밀을 못 쓰면 **창을 닫지 않는다**."""
        try:
            for (extension_id, key), (item, field) in self.fields.items():
                if item.secret and field.isEnabled() and field.text().strip():
                    self.credentials.set_extension_secret(extension_id, key, field.text().strip())
        except SecretsUnavailable as e:
            self.error.setText(f"키를 저장하지 못했습니다 — {e}")
            return
        made = ToolSettings(extensions={**self.settings.extensions, **self.plain_values()})
        made.save()
        self.saved = made
        self.accept()


__all__ = ["KEY_FROM_ENV", "KEY_STORED", "NO_FIELDS", "TITLE", "ToolSettingsDialog"]
