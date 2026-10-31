"""STU-15 확장 — Studio에 켜진 확장과 각 확장이 더한 것 (C13, ADR-0018).

- **Studio는 어느 확장인지 모른다** — 표와 상세의 글은 모두 정의(`extension.json`)에서 온다.
  이 파일에 확장 이름이 없다 (`tests/test_import_direction.py`가 막는다).
- **끄고 켜는 것 말고는 읽기만 한다.** 끈 목록은 **Studio 설정**에 있다 (ADR-0043) — PC 실행기는 제
  설정에 따로 둔다. 개발 도구에서 끈 것이 그 PC의 현장 BPM 프로세스를 멈추면 안 된다.
- **끄면 그 자리에서 사라진다** — 호스트를 다시 읽어 기여(태스크 종류·편집기·런타임·점검)가
  한꺼번에 빠진다. 다음 「실행 전 검사」가 「확장이 꺼져 있습니다」로 막는다 (`core.preflight`).
- **켜지지 않은 확장도 조용히 사라지지 않는다** — 사유(`problems`)를 상세에 그대로 보인다.
  정의를 **읽지도 못한** 것은 id가 없어 표에 줄을 만들 수 없으니 표 아래 한 줄로 말한다.
- 「새로 고침」은 Center의 **외부 확장 정의**를 다시 받아 보인다 — 받은 것은 **이 창만 쓰는
  호스트**에 담는다. 설치된 확장 호스트(팔레트·시험 실행이 쓰는 것)를 건드리지 않는다.
- 상태 표기는 `status_map`의 「확장」에 있는 것만 쓰고 색도 그 표에서 온다
  (`docs/07-style-guide.md`).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts._base import Violation
from chaeksas.contracts.bpmn_ext import ProcessInfo
from chaeksas.contracts.extension import (
    EDITOR_BUILTIN,
    PROTOCOL_HTTP_ADAPTER,
    TIER_BUILTIN,
    TIER_EXTERNAL,
    TIER_INTERNAL,
    ExtensionManifest,
    check_api,
    check_size,
    validate,
)
from chaeksas.contracts.signing import Envelope
from chaeksas.core.extensions import ExtensionHost, LoadedExtension
from chaeksas.qt.theme import status_color
from chaeksas.studio import services
from chaeksas.studio.extensions import Extensions
from chaeksas.studio.settings import Settings

TITLE = "확장"
#: 처음 크기 (STU-15 — 600×480).
DEFAULT_SIZE = (600, 480)

COLUMNS = ("확장", "등급", "버전", "상태", "기여 요약")
NAME, TIER, VERSION, STATE, SUMMARY = range(len(COLUMNS))

#: 등급 (C13 `tier`) — 콘솔(CON-07)과 같은 말을 쓴다.
TIER_LABEL = {TIER_BUILTIN: "내장", TIER_INTERNAL: "사내", TIER_EXTERNAL: "외부"}

#: `status_map`의 묶음과 표기. **이 표에 있는 것만 쓴다** — 색을 그 표에서 가져온다.
STATUS_GROUP = "확장"
STATE_ON = "켜짐"
STATE_OFF = "꺼짐"
STATE_BROKEN = "호환 안 됨"

#: 끄고 켤 수 없는 줄의 까닭 (U3 — 끄고 가까이에 적는다).
NO_TOGGLE_EXTERNAL = "외부 확장은 Center에 등록된 정의입니다 — 끄고 켜는 일은 Center에서 합니다 (C13 E6)."
NO_TOGGLE_NOTHING = "확장을 고르세요."

#: 기여 지점 이름 (C13 `contributes_summary()`의 열쇠) → 사람 말.
POINT_LABEL = {
    "task_types": "태스크 종류",
    "studio.editors": "속성 편집기",
    "studio.resource_views": "리소스 탐색기 뿌리",
    "configuration": "설정 칸",
    "preflight": "사전 점검",
    "console.pages": "관리 콘솔 화면",
    "resources": "리소스 갈래",
}

#: 키를 쓰는 자리 (C13 `requires_keys[].purpose`).
PURPOSE_LABEL = {"run": "BPM 프로세스가 작업을 부를 때"}

NOTHING = "(없음)"
NO_SELECTION = "확장을 고르면 그 확장이 더한 것을 봅니다."
DEFINITION_FILTER = "확장 정의 (extension.json *.json)"


def state_of(loaded: LoadedExtension) -> str:
    """`status_map` 「확장」의 표기 하나.

    **「꺼짐」과 「호환 안 됨」은 다른 것이다** (ADR-0043) — 앞은 사람이 껐다는 뜻이고 뒤는
    고쳐야 할 흠이다. 섞으면 화면이 「켜세요」와 「고치세요」 중 틀린 쪽을 안내한다.
    """
    if loaded.off:
        return STATE_OFF
    return STATE_ON if loaded.enabled else STATE_BROKEN


def _state_tip(loaded: LoadedExtension) -> str:
    """「상태」 칸의 말풍선 — **빈 말풍선을 달지 않는다**(꺼 둔 줄에는 `problems`가 없다)."""
    if loaded.off:
        return "사람이 껐습니다 (STU-15). 「켜기」로 되돌립니다."
    return "; ".join(str(p) for p in loaded.problems)


def summary_of(manifest: ExtensionManifest) -> str:
    """「기여 요약」 한 칸 — 기여 지점마다 개수 (C7 `contributes_summary`와 같은 것을 센다)."""
    found = manifest.contributes_summary()
    if not found:
        return NOTHING
    return ", ".join(f"{POINT_LABEL.get(point, point)} {len(ids)}" for point, ids in found.items())


def _lines(violations: list[Violation]) -> list[str]:
    out = []
    for one in violations:
        out.append(f"[{one.rule}/{one.code}] {one.message}")
        out += [f"    {item}" for item in one.items]
    return out


def detail_sections(loaded: LoadedExtension) -> list[tuple[str, list[str]]]:
    """상세에 보일 것 — `(제목, 줄들)`. **창 없이 시험할 수 있게** 순수 함수로 둔다.

    기여 지점은 STU-15 표가 적은 다섯이다 — 태스크 종류·편집기·리소스 탐색기 뿌리·서비스 앱
    작업·필요한 키. 나머지 지점의 개수는 목록의 「기여 요약」이 말한다.
    """
    m = loaded.manifest
    out: list[tuple[str, list[str]]] = []

    if loaded.off:
        # 맨 위다 — 왜 안 보이나 하고 고른 것이다. **흠이 아니라 뜻이다** (ADR-0043).
        out.append(("꺼 둠", ["사람이 껐습니다 — 기여가 하나도 들어오지 않습니다. 「켜기」로 되돌립니다."]))
    elif loaded.problems:
        out.append(("켜지지 않은 까닭", _lines(list(loaded.problems))))

    head = [
        f"{m.id}@{m.version} · {m.name}",
        f"펴낸 곳: {m.publisher}",
        f"등급: {TIER_LABEL.get(m.tier, m.tier)}",
        f"출처: {loaded.origin}",
        f"정의 해시: {loaded.definition_hash}",
    ]
    if m.description:
        head.insert(1, m.description)
    if m.api:
        head.append(f"필요한 extension_api: {m.api}")
    if m.docs_url:
        head.append(f"설명 문서: {m.docs_url}")
    out.append(("확장", head))

    tasks = []
    for t in m.contributes.task_types:
        where = ", ".join(t.run_locations) if t.run_locations else "제한 없음"
        icon = t.icon or "없음"
        tasks.append(f"{t.label} ({t.id}) · 아이콘 {icon} · 실행 위치 {where} · BPMN {t.bpmn}")
    out.append(("태스크 종류", tasks or [NOTHING]))

    editors = []
    for t in m.contributes.task_types:
        if t.editor is None:
            continue
        if t.editor.kind == EDITOR_BUILTIN:
            editors.append(f"{t.id}: 확장이 준 편집기 ({t.editor.entry})")
        else:
            # kind=schema면 Studio가 입력 스키마로 폼을 만든다 (STU-14 방식).
            editors.append(f"{t.id}: 입력 스키마로 만드는 자동 폼")
    editors += [f"{e.task_type}: 확장이 준 편집기 ({e.entry})" for e in m.contributes.studio_editors]
    out.append(("속성 편집기", editors or [NOTHING]))

    views = [
        f"{v.label} ({v.resource_type})"
        + (f" → 캔버스에 추가하면 {v.creates_task_type}" if v.creates_task_type else " · 태스크를 만들지 않음")
        + (f" (자원 id는 {v.creates_task_field})" if v.creates_task_field else "")
        for v in m.contributes.studio_resource_views
    ]
    out.append(("리소스 탐색기 뿌리", views or [NOTHING]))

    out.append(("서비스 앱 작업", _service_lines(m)))

    keys = [
        f"{PURPOSE_LABEL.get(k.purpose, k.purpose)}"
        + (f" · 더 필요한 권한 {', '.join(k.extra_scopes)}" if k.extra_scopes else "")
        for k in m.requires_keys
    ]
    out.append(("필요한 키", keys or [NOTHING]))
    return out


def _service_lines(m: ExtensionManifest) -> list[str]:
    """서버 부분과 그 작업들.

    **작업 목록이 정의에 있는 것은 외부 확장(HTTP 어댑터)뿐이다** — C11을 따르는 서비스 앱의
    작업은 그 앱의 `/manifest`에서 오고 Center 리소스 목록이 싣고 온다 (C7). 모르는 것을
    지어내지 않고 어디서 오는지만 말한다.
    """
    if m.service is None:
        return [NOTHING]
    out = [f"프로토콜: {m.service.protocol}", f"주소: {m.service.base_url or '(Center 리소스 등록에서)'}"]
    adapter = m.adapter
    if m.service.protocol != PROTOCOL_HTTP_ADAPTER:
        out.append("작업 목록은 그 앱의 manifest에서 옵니다 (C11 — Center 리소스 목록).")
        return out
    if adapter is None:
        return out
    out.append(f"허용 호스트: {', '.join(adapter.allowed_hosts) or NOTHING}")
    out.append(f"사설망 허용: {'예' if adapter.allow_private_network else '아니오'}")
    for op in adapter.operations:
        out.append(f"작업 {op.name}: {', '.join(op.modes)}" + (" · 멱등" if op.idempotent else ""))
    return out


def check_definition(raw: bytes, *, api_version: str) -> list[str]:
    """정의 파일 하나를 **Center에 올리기 전에** 여기서 검사한다 (C13 E1·E3 — Center가 등록할 때와 같은 함수).

    빈 목록이면 흠이 없다. 등록은 Center 콘솔에서 관리자가 한다 (ADR-0090).
    """
    problems = list(check_size(raw))
    try:
        definition = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        return [f"JSON이 아닙니다: {e}"]
    if not isinstance(definition, dict):
        return ["최상위가 객체가 아닙니다."]
    try:
        manifest = ExtensionManifest.model_validate(definition)
    except ValueError as e:
        return [f"정의가 C13과 맞지 않습니다: {str(e).splitlines()[0]}"]
    problems += validate(manifest, from_center=True)
    problems += check_api(manifest, api_version=api_version)
    return _lines(problems)


#: 고정할 수 없는 까닭들 (단추 말풍선 — U3).
NO_PIN_NOTHING = "확장을 고르세요."
NO_PIN_INTERNAL = "내장·사내 확장은 고정하지 않습니다 — 정의가 설치 파일에 있습니다 (C13)."
NO_PIN_UNVERIFIED = "「새로 고침」으로 Center에서 받아 봉투를 검증한 정의만 고정합니다 (C13 E6)."
NO_PIN_NOT_OPEN = "진입 정의가 열려 있을 때만 고정합니다 — 그림을 고치는 일입니다 (STU-06과 같은 규칙)."
NO_PIN_NOT_DECLARED = (
    "그림이 이 확장을 쓴다고 적지 않았습니다 (`bpm:process.extensions`) — "
    "버전 범위를 지어내지 않습니다."
)


def pin_patch(info: ProcessInfo, pins: Mapping[str, str | None]) -> str:
    """고정·해제를 반영한 `bpm:process` 본문 (JSON 글 — `setProperties`의 규약).

    **읽은 것을 통째로 되돌려 쓴다** — `inputs`·`outputs`처럼 이 창이 모르는 칸이 사라지지
    않게 (STU-06과 같은 자리). 값이 `None`이면 **고정을 지운다**.

    **적히지 않은 확장은 더하지 않는다** — 그림이 쓴다고 적지 않은 것에 버전 범위를
    지어내는 것이 되기 때문이다 (부르는 쪽이 먼저 막는다).
    """
    made = info.model_copy(deep=True)
    for need in made.extensions:
        if need.id in pins:
            need.definition_hash = pins[need.id]
    return json.dumps(made.to_json_dict(), ensure_ascii=False, indent=2)


class StudioExtensionsDialog(QDialog):
    """STU-15. 목록 + 상세, 그리고 단추 셋."""

    def __init__(
        self,
        settings: Settings,
        extensions: Extensions,
        *,
        reader: services.CenterReader | None = None,
        process_info: ProcessInfo | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.extensions = extensions
        #: 진입 정의의 `bpm:process` — 고정 상태를 여기서 읽는다. `None`이면 고정할 수 없다
        #: (진입 정의가 열려 있지 않다 — STU-06과 같은 규칙, ADR-0022).
        self.process_info = process_info
        #: 이 창에서 고정·해제한 것 (`확장 id → 해시 또는 None`). 부른 쪽(STU-01)이 캔버스에 넘긴다.
        self.pins: dict[str, str | None] = {}
        #: 시험이 끼우는 Center 읽기 — `None`이면 「새로 고침」 때 설정에서 만든다.
        self.reader = reader
        #: Center에서 받아 **이 창만 쓰는** 외부 확장들 (설치된 호스트를 건드리지 않는다).
        self.external: list[LoadedExtension] = []
        #: 끄거나 켠 적이 있나 — 부른 쪽(STU-01)이 속성 패널을 다시 그릴지 판단한다.
        self.changed = False
        #: 표의 줄 순서 그대로.
        self.rows: list[LoadedExtension] = []

        self.setWindowTitle(TITLE)
        self.resize(*DEFAULT_SIZE)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("extensions")
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for column in (NAME, TIER, VERSION, STATE):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(SUMMARY, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._show_selected)

        self.detail = QPlainTextEdit()
        self.detail.setObjectName("detail")
        self.detail.setReadOnly(True)

        #: 표 아래 한 줄 — 정의를 읽지 못한 것, Center 사정, 검사 결과를 여기로만 말한다.
        self.note = QLabel("")
        self.note.setWordWrap(True)

        self.enable_button = QPushButton("켜기")
        self.enable_button.clicked.connect(lambda: self.set_off(False))
        self.disable_button = QPushButton("끄기")
        self.disable_button.clicked.connect(lambda: self.set_off(True))
        self.pin_button = QPushButton("정의 고정")
        self.pin_button.setToolTip(
            "지금 보고 있는 정의 해시를 그림에 적습니다 — 받는 쪽이 「승인받은 그 정의인가」를 대조합니다."
        )
        self.pin_button.clicked.connect(lambda: self.set_pin(True))
        self.unpin_button = QPushButton("고정 해제")
        self.unpin_button.clicked.connect(lambda: self.set_pin(False))
        self.refresh_button = QPushButton("새로 고침")
        self.refresh_button.setToolTip("Center에 등록된 외부 확장 정의를 다시 받습니다.")
        self.refresh_button.clicked.connect(self.refresh_external)
        self.open_button = QPushButton("정의 파일 열기...")
        self.open_button.setToolTip("Center에 올리기 전에 이 PC에서 C13 검사(E1·E3)를 돌려 봅니다.")
        self.open_button.clicked.connect(self.open_definition)
        self.close_button = QPushButton("닫기")
        self.close_button.clicked.connect(self.reject)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table)
        split.addWidget(self.detail)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)

        buttons = QHBoxLayout()
        for one in (
            self.enable_button,
            self.disable_button,
            self.pin_button,
            self.unpin_button,
            self.refresh_button,
            self.open_button,
        ):
            buttons.addWidget(one)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(split, 1)
        layout.addWidget(self.note)
        layout.addLayout(buttons)

        self.refresh()

    # ── 표 ──

    def refresh(self) -> None:
        """설치된 확장 + 「새로 고침」으로 받아 둔 외부 확장. **바깥을 부르지 않는다.**"""
        host = self.extensions.host
        self.rows = [*host.all(), *self.external]
        self.table.setRowCount(len(self.rows))
        for at, loaded in enumerate(self.rows):
            m = loaded.manifest
            state = state_of(loaded)
            texts = (m.name, TIER_LABEL.get(m.tier, m.tier), m.version, state, summary_of(m))
            for column, text in enumerate(texts):
                item = QTableWidgetItem(text)
                if column == NAME:
                    item.setToolTip(m.id)
                if column == STATE:
                    # 색은 **그 표기의 것**을 찾는다 — 「꺼짐」에 「호환 안 됨」의 색을 쓰면
                    # 꺼 둔 것이 고장처럼 보인다 (`status_map` 「확장」, 스타일 가이드 §2-2).
                    color = status_color(STATUS_GROUP, state, part="fg")
                    if color is not None:
                        item.setForeground(QColor(color))
                    item.setToolTip(_state_tip(loaded))
                self.table.setItem(at, column, item)
        self._say_failures()
        if self.rows and not self.table.selectedItems():
            self.table.selectRow(0)
        else:
            self._show_selected()

    def _say_failures(self) -> None:
        """정의를 **읽지도 못한** 것 — id를 모르니 표에 줄을 만들 수 없다 (`LoadFailure`).

        받아 온 외부 확장이 설치된 확장과 **겹치는지는 보지 않는다** — 외부는 태스크 종류·AI
        환경을 기여할 수 없으므로(E1) 겹칠 자리가 없다. E4·E8은 설치된 확장들 사이에서만
        생기고 그것은 호스트가 이미 `problems`에 적어 둔다.
        """
        said = [f"{one.origin}: {one.message}" for one in self.extensions.host.failures]
        self.note.setText("정의를 읽지 못했습니다 — " + " / ".join(said) if said else "")

    def selected(self) -> LoadedExtension | None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        at = next(iter(sorted(rows)), None)
        return self.rows[at] if at is not None and at < len(self.rows) else None

    def _show_selected(self) -> None:
        found = self.selected()
        self._refresh_toggle(found)
        self._refresh_pin(found)
        if found is None:
            self.detail.setPlainText(NO_SELECTION)
            return
        sections = detail_sections(found)
        if found.manifest.is_external:
            # **고정 상태를 상세에 보인다** — 해시만 보이면 「고정했나」를 알 수 없다 (ADR-0060).
            pinned = self.pinned_hash(found.id)
            said = "그림에 고정됨" if pinned == found.definition_hash else (
                "그림에 **다른** 해시가 고정됨 — 받는 쪽이 거부합니다" if pinned else "고정되지 않음"
            )
            sections = [*sections, ("고정", [said])]
        self.detail.setPlainText(render(sections))

    def _refresh_toggle(self, found: LoadedExtension | None) -> None:
        """「켜기」/「끄기」 중 **할 수 있는 쪽만** 켠다. 못 하면 이유가 말풍선에 있다 (U3).

        외부 확장은 여기서 끄지 않는다 — 설치된 것이 아니라 Center에 등록된 정의다 (C13 E6).
        """
        why = NO_TOGGLE_NOTHING if found is None else ""
        if found is not None and found.manifest.is_external:
            why = NO_TOGGLE_EXTERNAL
        for button, wants_off in ((self.enable_button, False), (self.disable_button, True)):
            can = not why and found is not None and found.off != wants_off
            button.setEnabled(can)
            button.setToolTip(why if why else "")

    def pinned_hash(self, extension_id: str) -> str | None:
        """지금 그림에 적힌 고정 값 (이 창에서 바꾼 것이 이긴다)."""
        if extension_id in self.pins:
            return self.pins[extension_id]
        found = next(
            (one for one in (self.process_info.extensions if self.process_info else []) if one.id == extension_id),
            None,
        )
        return found.definition_hash if found is not None else None

    def _declared(self, extension_id: str) -> bool:
        """그림이 쓴다고 적었나 (`bpm:process.extensions`)."""
        return any(one.id == extension_id for one in (self.process_info.extensions if self.process_info else []))

    def _pin_problem(self, found: LoadedExtension | None) -> str:
        """고정할 수 없는 까닭 한 줄 (없으면 빈 글). **할 수 없으면 까닭을 말한다** (U3)."""
        if found is None:
            return NO_PIN_NOTHING
        if not found.manifest.is_external:
            return NO_PIN_INTERNAL
        if found not in self.external:
            # 설치된 목록에 외부가 섞일 일은 없지만, 「받아서 검증한 것만」을 코드로 지킨다.
            return NO_PIN_UNVERIFIED
        if self.process_info is None:
            return NO_PIN_NOT_OPEN
        if not self._declared(found.id):
            return NO_PIN_NOT_DECLARED
        return ""

    def _refresh_pin(self, found: LoadedExtension | None) -> None:
        why = self._pin_problem(found)
        pinned = found is not None and bool(self.pinned_hash(found.id))
        self.pin_button.setEnabled(not why and not pinned)
        self.unpin_button.setEnabled(not why and pinned)
        for button in (self.pin_button, self.unpin_button):
            button.setToolTip(why if why else button.toolTip())

    def set_pin(self, pin: bool) -> None:
        """고른 외부 확장의 정의를 고정하거나 해제한다 (ADR-0060).

        **그림은 부른 쪽이 캔버스에 넘긴다** — 창이 XML을 만지지 않는다 (ADR-0022). 그래서
        여기서는 `pins`에 적어 두고, 파일로 가는 것은 「저장」(Ctrl+S)이다.
        """
        found = self.selected()
        if found is None or self._pin_problem(found):
            return
        self.pins[found.id] = found.definition_hash if pin else None
        self._refresh_pin(found)
        self._show_selected()
        self.note.setText(
            f"{found.manifest.name} 정의를 그림에 고정했습니다 — 「저장」(Ctrl+S)으로 파일에 씁니다."
            if pin
            else f"{found.manifest.name}의 고정을 해제했습니다 — 정의가 바뀌어도 그대로 돕니다."
        )

    def set_off(self, off: bool) -> None:
        """고른 확장을 끄거나 켠다 — **설정에 적고 호스트를 다시 읽는다** (ADR-0043).

        설정은 **그 자리에서** 저장한다 (이 창에는 「저장」이 없다 — BUI-11과 같은 결이다).
        """
        found = self.selected()
        if found is None or found.manifest.is_external:
            return
        kept = tuple(one for one in self.settings.disabled_extensions if one != found.id)
        self.settings = replace(
            self.settings, disabled_extensions=(*kept, found.id) if off else kept
        )
        self.settings.save()
        self.extensions.reload(off=self.settings.disabled_extensions)
        self.changed = True
        self.refresh()
        self._select(found.id)
        self.note.setText(
            f"{found.manifest.name}을 {'껐습니다' if off else '켰습니다'}."
            + (" 그 확장의 태스크가 있는 BPM 프로세스는 실행 전 검사에서 막힙니다." if off else "")
        )

    def _select(self, extension_id: str) -> None:
        at = next((i for i, one in enumerate(self.rows) if one.id == extension_id), None)
        if at is not None:
            self.table.selectRow(at)

    # ── 단추 ──

    def refresh_external(self) -> None:
        """Center에 등록된 외부 확장 정의를 다시 받는다 (C7 리소스 목록).

        **봉투를 다시 검증한다** (`add_external` → C13 E6) — 정의가 BPM 프로세스의 키를 어느 주소로 보낼지
        정하므로 Studio도 봉투 서명을 직접 본다. 닿지 못하면 **그 자리에서 말한다**
        (들고 있지 않는다 — Studio는 현장이 아니라 개발 도구다, `services.py`).
        """
        reader = self.reader or services.reader_for(self.settings, _center_key())
        if reader is None:
            self.note.setText("Center 주소·Studio 키가 설정되지 않았습니다 (STU-10).")
            return
        try:
            found = [one for one in reader.extensions() if one.tier == TIER_EXTERNAL]
            keys = reader.admin_keys() if found else []
        except services.CenterUnreachable as e:
            self.note.setText(str(e))
            return

        # 이 창만 쓰는 호스트다 — 팔레트·시험 실행이 보는 호스트를 건드리지 않는다.
        host = ExtensionHost(api_version=self.extensions.host.api_version)
        said: list[str] = []
        for one in found:
            if one.definition is None or one.envelope is None:
                said.append(f"{one.id}: 정의·봉투가 함께 오지 않았습니다")
                continue
            try:
                # C7은 봉투를 **그대로** 싣고 온다 (재직렬화하면 해시가 깨진다) — 모델로 한 번 읽는다.
                envelope = Envelope.model_validate(one.envelope)
            except ValueError:
                said.append(f"{one.id}: 봉투가 C2와 맞지 않습니다")
                continue
            if host.add_external(one.definition, envelope, keys=keys) is None:
                said.append(f"{one.id}: 정의를 읽지 못했습니다")
        self.external = host.all()
        self.refresh()
        got = f"외부 확장 {len(self.external)}개를 받았습니다."
        self.note.setText(f"{got} {' / '.join(said)}" if said else got)

    def open_definition(self) -> None:
        """정의 파일 하나를 골라 C13 검사를 돌린다. **등록하지 않는다** — 등록은 Center 콘솔의 관리자가 한다."""
        chosen, _ = QFileDialog.getOpenFileName(self, "확장 정의 파일", "", DEFINITION_FILTER)
        if not chosen:
            return
        path = Path(chosen)
        try:
            raw = path.read_bytes()
        except OSError as e:
            self.note.setText(f"{path.name}을 읽지 못했습니다 — {e}")
            return
        problems = check_definition(raw, api_version=self.extensions.host.api_version)
        title = f"정의 파일 검사: {path.name}"
        if problems:
            self.note.setText(f"{path.name}: 흠 {len(problems)}개 — 아래에 있습니다.")
            self.detail.setPlainText(render([(title, problems)]))
            return
        self.note.setText(f"{path.name}: 흠이 없습니다. 등록은 관리자가 Center 콘솔에서 합니다.")
        self.detail.setPlainText(render([(title, ["흠이 없습니다 (C13 E1·E3·E5)."])]))


def render(sections: list[tuple[str, list[str]]]) -> str:
    """상세를 글로 (`detail_sections`의 결과를 그대로 받는다)."""
    out: list[str] = []
    for title, lines in sections:
        out.append(f"■ {title}")
        out += [f"  {line}" for line in lines]
        out.append("")
    return "\n".join(out).rstrip()


def _center_key() -> str | None:
    from chaeksas.studio.credentials import StudioCredentials  # noqa: PLC0415 — 순환 피함

    return StudioCredentials().center_api_key()


__all__ = [
    "COLUMNS",
    "DEFAULT_SIZE",
    "NO_TOGGLE_EXTERNAL",
    "STATE_BROKEN",
    "STATE_OFF",
    "STATE_ON",
    "TIER_LABEL",
    "StudioExtensionsDialog",
    "check_definition",
    "detail_sections",
    "render",
    "state_of",
    "summary_of",
]
