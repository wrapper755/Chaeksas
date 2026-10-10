"""BUI-11 확장 — 이 PC에 설치된 확장과 각 확장이 더한 것 (C13, ADR-0018).

- **Bot UI는 어느 확장인지 모른다** — 표와 상세의 글은 모두 정의(`extension.json`)에서 온다.
  이 파일에 확장 이름이 없다 (`tests/test_import_direction.py`가 막는다).
- **끄고 켜는 것 말고는 읽기만 한다.** 끈 목록은 **Bot UI 제 설정**이다 (ADR-0043) — Studio(STU-15)의
  것과 **다른 자리**다. 개발 도구에서 끈 것이 현장 Bot을 멈추면 안 된다.
- **「저장」이 없다** (BUI-10과 같은 결) — 누르는 그 자리에서 설정에 적고 확장을 다시 읽는다.
  다시 읽으면 사전 점검 캐시도 비워진다 — 안 비우면 꺼도 「준비됨」이 하트비트로 계속 올라간다.
- **BUI-11에만 있는 것 둘**: 「쓰는 Bot」 열(설치된 Bot 중 그 확장을 요구하는 것)과, 끄기 전에
  「<Bot> N개가 실행 불가가 됩니다」를 묻는 확인 창(기본 「취소」). 설치된 Bot이 요구하는데 **이 PC에
  없는** 확장도 줄로 보인다 (「필요하지만 없음」) — 목록에 없으면 왜 실행이 막히는지 알 수 없다.
- **외부 확장은 들고 있는 명부에서 온다** (C7 → `services.py`). 「새로 고침」만 Center를 부르고,
  **닿지 못하면 들고 있던 것을 쓴다** (ADR-0007 — 현장 PC다. Studio는 그 자리에서 말한다).
  받은 정의는 **봉투를 다시 검증한다** (C13 E6). 외부 확장은 여기서 끄지 않는다 (Center의 일이다).
- 상태 표기는 `status_map`의 「확장」에 있는 것만 쓰고 색도 그 표에서 온다
  (`docs/07-style-guide.md`). **「꺼짐」과 「호환 안 됨」은 섞지 않는다** (ADR-0043).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.bot_ui.agent import Agent
from chaeksas.bot_ui.bots import InstalledBot, installed
from chaeksas.bot_ui.center_client import KeyRejected
from chaeksas.bot_ui.runtimes import STATE_LABELS, RuntimeUnavailable, port_for
from chaeksas.bot_ui.services import Services, external_ids
from chaeksas.bot_ui.settings import data_dir
from chaeksas.contracts._base import Violation
from chaeksas.contracts.extension import (
    PROTOCOL_HTTP_ADAPTER,
    TIER_BUILTIN,
    TIER_EXTERNAL,
    TIER_INTERNAL,
    ExtensionManifest,
)
from chaeksas.contracts.signing import AdminKey, Envelope
from chaeksas.core.extensions import ExtensionHost, LoadedExtension
from chaeksas.extension_api import API_VERSION
from chaeksas.qt import theme

log = logging.getLogger(__name__)

TITLE = "확장"
#: 처음 크기 (표 6열 + 상세).
DEFAULT_SIZE = (900, 620)

COLUMNS = ("확장", "등급", "버전", "기여", "상태", "쓰는 Bot")
NAME, TIER, VERSION, SUMMARY, STATE, USED_BY = range(len(COLUMNS))

#: 등급 (C13 `tier`) — 콘솔(CON-07)·STU-15와 같은 말을 쓴다.
TIER_LABEL = {TIER_BUILTIN: "내장", TIER_INTERNAL: "사내", TIER_EXTERNAL: "외부"}

#: `status_map`의 묶음과 표기. **이 표에 있는 것만 쓴다** — 색을 그 표에서 가져온다.
STATUS_GROUP = "확장"
STATE_ON = "켜짐"
STATE_OFF = "꺼짐"
STATE_BROKEN = "호환 안 됨"
STATE_ABSENT = "필요하지만 없음"

#: 「상태」 칸에 표기 뒤로 붙이는 글 — 왜 그런지가 표기만으로는 모자란 두 자리다.
BAD_SIGNATURE = "서명 확인 안 됨 — 쓰지 않음"

#: 기여 지점 이름 (C13 `contributes_summary()`의 열쇠) → 사람 말.
POINT_LABEL = {
    "task_types": "태스크 종류",
    "studio.editors": "속성 편집기",
    "studio.resource_views": "리소스 탐색기 뿌리",
    "bot_ui.utilities": "유틸리티",
    "bot_ui.panels": "화면 칸",
    "bot_ui.local_runtimes": "로컬 런타임",
    "configuration": "설정 칸",
    "preflight": "사전 점검",
    "console.pages": "관리 콘솔 화면",
    "resources": "리소스 갈래",
}
#: AI 환경은 C7 요약(`contributes_summary`)에 없다 — 상세에서 정의를 직접 읽어 말한다.
ENVIRONMENT_LABEL = "AI 환경"

#: 키를 쓰는 자리 (C13 `requires_keys[].purpose`) — **넣는 화면까지** 말해 준다.
PURPOSE_LABEL = {
    "run": "BPM 프로세스가 작업을 부를 때 — BUI-10 「서비스 앱 키」",
    "utility": "Bot UI 유틸리티가 쓸 때 — BUI-03 「확장별 설정」",
}

#: 외부 확장은 코드를 기여할 수 없다 (C13 E1) — 「기여」 칸에 그렇게 적는다.
EXTERNAL_SUMMARY = "정의만 — 서비스 앱 태스크로 씀"
NOTHING = "(없음)"
NO_SELECTION = "확장을 고르면 그 확장이 더한 것을 봅니다."

#: 끄고 켤 수 없는 줄의 까닭 (U3 — 끄고 가까이에 적는다).
NO_TOGGLE_EXTERNAL = "외부 확장은 Center에 등록된 정의입니다 — 끄고 켜는 일은 Center에서 합니다 (C13 E6)."
NO_TOGGLE_ABSENT = "이 PC에 없는 확장입니다 — 그 확장이 깔린 Bot UI 판으로 올리세요."
NO_TOGGLE_NOTHING = "확장을 고르세요."


@dataclass(frozen=True)
class ExtensionRow:
    """표의 한 줄. `loaded`가 없으면 **설치된 Bot이 요구하는데 이 PC에 없는** 확장이다."""

    loaded: LoadedExtension | None
    #: 이 확장을 쓰는 설치된 Bot의 이름들 (C1 `requires.extensions` + AI 환경 주인).
    used_by: tuple[str, ...] = ()
    #: 없는 확장 줄에만 — 요구한 id와 판 범위.
    wanted_id: str = ""
    wanted_version: str = ""

    @property
    def id(self) -> str:
        return self.loaded.id if self.loaded is not None else self.wanted_id

    @property
    def name(self) -> str:
        return self.loaded.manifest.name if self.loaded is not None else self.wanted_id

    @property
    def is_external(self) -> bool:
        return self.loaded is not None and self.loaded.manifest.is_external


def state_of(row: ExtensionRow) -> tuple[str, str, str]:
    """`(status_map 「확장」의 표기, 줄에 보일 글, 말풍선)`.

    표기는 색을 고르는 데 쓰므로 **표에 있는 값이어야 한다**. 보일 글에는 까닭을 덧붙인다 —
    「호환 안 됨」만으로는 무엇을 고쳐야 할지 모른다 (BUI-04 「준비」와 같은 결).

    **「꺼짐」과 「호환 안 됨」은 다른 것이다** (ADR-0043) — 앞은 사람이 껐다는 뜻이고 뒤는 고쳐야
    할 흠이다. 섞으면 화면이 「켜세요」와 「고치세요」 중 틀린 쪽을 안내한다.
    """
    loaded = row.loaded
    if loaded is None:
        wanted = f" (요구: {row.wanted_version})" if row.wanted_version else ""
        return (
            STATE_ABSENT,
            STATE_ABSENT,
            f"설치된 Bot이 요구하지만 이 PC에 없습니다{wanted} — 그 확장이 깔린 Bot UI 판으로 올리세요.",
        )
    if loaded.off:
        return STATE_OFF, STATE_OFF, "사람이 껐습니다 (BUI-11). 「켜기」로 되돌립니다."
    if not loaded.problems:
        return STATE_ON, STATE_ON, ""
    tip = "; ".join(str(p) for p in loaded.problems)
    rules = {p.rule for p in loaded.problems}
    if "E6" in rules:
        # 봉투가 검증되지 않은 외부 정의다 — 「호환 안 됨」이라고만 하면 서명을 찾아보지 않는다.
        return STATE_BROKEN, BAD_SIGNATURE, tip
    if "E5" in rules and loaded.manifest.api:
        return STATE_BROKEN, f"{STATE_BROKEN} — 확장 API {loaded.manifest.api} 필요", tip
    return STATE_BROKEN, STATE_BROKEN, tip


def summary_of(manifest: ExtensionManifest) -> str:
    """「기여」 한 칸 — 기여 지점마다 개수 (C7 `contributes_summary`와 같은 것을 센다)."""
    if not manifest.can_contribute_code:
        return EXTERNAL_SUMMARY
    found = manifest.contributes_summary()
    if not found:
        return NOTHING
    return " · ".join(f"{POINT_LABEL.get(point, point)} {len(ids)}" for point, ids in found.items())


def users(
    bots: Sequence[InstalledBot], needed: Callable[[InstalledBot], set[str]]
) -> dict[str, tuple[str, ...]]:
    """확장 id → 그 확장을 쓰는 설치된 Bot 이름들.

    **「무엇이 그 확장을 쓰는가」는 Agent가 안다** (`needed_extensions`) — `requires.extensions`에
    적힌 것과, `requires.domains`의 `web`·`desktop` AI 환경을 기여한 확장이다 (ADR-0037). 그림에
    확장을 적지 않아도 끄면 멈추는 Bot이라 함께 센다.
    """
    out: dict[str, list[str]] = {}
    for bot in bots:
        for extension_id in sorted(needed(bot) | {need.id for need in bot.manifest.requires.extensions}):
            out.setdefault(extension_id, []).append(bot.name)
    return {key: tuple(sorted(set(value))) for key, value in out.items()}


def wanted_versions(bots: Sequence[InstalledBot]) -> dict[str, str]:
    """확장 id → 설치된 Bot이 요구한 판 범위 (C1 `requires.extensions[].version`)."""
    out: dict[str, str] = {}
    for bot in bots:
        for need in bot.manifest.requires.extensions:
            out.setdefault(need.id, need.version or "")
    return out


def rows_for(
    loaded: Sequence[LoadedExtension],
    *,
    used_by: Mapping[str, tuple[str, ...]],
    wanted: Mapping[str, str],
) -> list[ExtensionRow]:
    """표의 줄들 — 읽어 들인 확장 + **요구하는데 없는** 확장 (아래쪽, 「필요하지만 없음」).

    순서는 읽은 차례(설치된 것 → 외부)이고, 없는 것은 맨 아래다 — 고칠 거리가 한곳에 모인다.
    """
    rows = [ExtensionRow(loaded=one, used_by=used_by.get(one.id, ())) for one in loaded]
    known = {one.id for one in loaded}
    rows += [
        ExtensionRow(
            loaded=None,
            used_by=names,
            wanted_id=extension_id,
            wanted_version=wanted.get(extension_id, ""),
        )
        for extension_id, names in sorted(used_by.items())
        if extension_id not in known
    ]
    return rows


def detail_sections(
    row: ExtensionRow,
    *,
    service_url: str | None = None,
    runtimes: Mapping[str, str] | None = None,
) -> list[tuple[str, list[str]]]:
    """상세에 보일 것 — `(제목, 줄들)`. **창 없이 시험할 수 있게** 순수 함수로 둔다.

    `service_url`은 **들고 있는 명부**가 말한 주소이고(C7 등록이 정의의 `base_url`을 이긴다),
    `runtimes`는 런타임 id → 지금 상태다. 둘 다 바깥을 부르는 일이라 **창이 미리 재서** 넘긴다.
    """
    loaded = row.loaded
    if loaded is None:
        return [
            (
                STATE_ABSENT,
                [
                    f"{row.wanted_id}" + (f" (요구 판: {row.wanted_version})" if row.wanted_version else ""),
                    "설치된 Bot이 요구하지만 이 PC에 없습니다 — 끄고 켤 수 없습니다.",
                    "확장은 Bot UI 설치 파일에 들어 있습니다 (ADR-0018 §3) — 그 확장이 깔린 판으로 올리세요.",
                ],
            ),
            ("쓰는 Bot", list(row.used_by) or [NOTHING]),
        ]

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

    out.append(("기여", _contribution_lines(m)))
    out.append(("서버 부분", _service_lines(m, service_url)))

    keys = [
        f"{PURPOSE_LABEL.get(k.purpose, k.purpose)}"
        + (f" · 더 필요한 권한 {', '.join(k.extra_scopes)}" if k.extra_scopes else "")
        + (f" · 설정 칸 {k.config_key}" if k.config_key else "")
        for k in m.requires_keys
    ]
    out.append(("필요한 키", keys or [NOTHING]))

    held = runtimes or {}
    runtime_lines = [
        f"{one.label} ({one.id}): {held.get(one.id, '상태를 모릅니다')}"
        for one in m.contributes.bot_ui_local_runtimes
    ]
    out.append(("로컬 런타임", runtime_lines or [NOTHING]))
    out.append(("쓰는 Bot", list(row.used_by) or ["쓰는 Bot 없음"]))
    return out


def _contribution_lines(m: ExtensionManifest) -> list[str]:
    """기여 지점마다 한 줄 — **이름은 정의의 것**이다 (플랫폼이 짓지 않는다)."""
    out = [
        f"{POINT_LABEL.get(point, point)}: {', '.join(ids)}"
        for point, ids in m.contributes_summary().items()
    ]
    # AI 환경은 C7 요약에 없다 (`domain`은 id가 아니다) — 정의에서 직접 읽는다 (ADR-0037).
    domains = [one.domain for one in m.contributes.agent_environments]
    if domains:
        out.append(f"{ENVIRONMENT_LABEL}: {', '.join(domains)}")
    return out or [NOTHING]


def _service_lines(m: ExtensionManifest, service_url: str | None) -> list[str]:
    """서버 부분과 주소.

    **상태는 적지 않는다** — 서비스 앱이 살아 있나는 Center가 60초마다 보는 것이고(C7), Bot UI는
    명부에서 주소만 받아 둔다. 모르는 것을 「정상」이라고 하지 않는다 (CON-07에서 본다).
    """
    if m.service is None:
        return [NOTHING]
    where = service_url or m.service.base_url or ""
    out = [
        f"프로토콜: {m.service.protocol}",
        f"주소: {where or '(Center 리소스 등록에서 — 아직 받지 못했습니다)'}",
        "상태는 Center 콘솔(CON-07 리소스)이 봅니다.",
    ]
    adapter = m.adapter
    if m.service.protocol != PROTOCOL_HTTP_ADAPTER or adapter is None:
        return out
    out.append(f"허용 호스트: {', '.join(adapter.allowed_hosts) or NOTHING}")
    out.append(f"사설망 허용: {'예' if adapter.allow_private_network else '아니오'}")
    out += [
        f"작업 {op.name}: {', '.join(op.modes)}" + (" · 멱등" if op.idempotent else "")
        for op in adapter.operations
    ]
    return out


def _lines(violations: list[Violation]) -> list[str]:
    out = []
    for one in violations:
        out.append(f"[{one.rule}/{one.code}] {one.message}")
        out += [f"    {item}" for item in one.items]
    return out


def render(sections: list[tuple[str, list[str]]]) -> str:
    """상세를 글로 (`detail_sections`의 결과를 그대로 받는다)."""
    out: list[str] = []
    for title, lines in sections:
        out.append(f"■ {title}")
        out += [f"  {line}" for line in lines]
        out.append("")
    return "\n".join(out).rstrip()


def external_from(
    held: Mapping[str, Any], *, keys: Sequence[AdminKey], api_version: str
) -> tuple[list[LoadedExtension], list[str]]:
    """들고 있는 명부의 외부 확장 정의들 → 읽어 들인 확장 + 못 읽은 사유.

    **봉투를 다시 검증한다** (C13 E6) — 정의가 Bot의 키를 어느 주소로 보낼지 정하므로, 실행기와
    같은 관문을 화면도 통과시킨다. 검증에 걸린 것은 **지우지 않고** 「서명 확인 안 됨」으로 보인다.
    """
    host = ExtensionHost(api_version=api_version)
    said: list[str] = []
    for one in held.get("extensions") or []:
        definition = one.get("definition") if isinstance(one, dict) else None
        raw = one.get("envelope") if isinstance(one, dict) else None
        if not isinstance(definition, dict) or not isinstance(raw, dict):
            said.append("정의·봉투가 함께 있지 않은 항목을 건너뛰었습니다")
            continue
        try:
            envelope = Envelope.model_validate(raw)
        except ValueError:
            said.append(f"{definition.get('id') or '이름 모를 확장'}: 봉투가 C2와 맞지 않습니다")
            continue
        if host.add_external(definition, envelope, keys=list(keys)) is None:
            said.append(f"{definition.get('id') or '이름 모를 확장'}: 정의를 읽지 못했습니다")
    return host.all(), said


class ExtensionsDialog(QDialog):
    """BUI-11. 「도구」 → 「확장...」."""

    def __init__(self, agent: Agent, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._agent = agent
        #: 표의 줄 순서 그대로.
        self.rows: list[ExtensionRow] = []
        #: 들고 있는 명부에서 읽은 외부 확장 (「새로 고침」이 다시 받는다).
        self.external: list[LoadedExtension] = []
        #: 끄거나 켠 적이 있나 — 부른 쪽(BUI-02)이 「도구」 메뉴를 다시 그릴지 판단한다.
        self.changed = False

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
        for column in (NAME, TIER, VERSION, STATE, USED_BY):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(SUMMARY, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._show_selected)

        self.detail = QPlainTextEdit()
        self.detail.setObjectName("detail")
        self.detail.setReadOnly(True)

        #: 표 아래 한 줄 — 정의를 읽지도 못한 것, Center 사정, 끄고 켠 결과를 여기로만 말한다.
        self.note = QLabel("")
        self.note.setWordWrap(True)

        self.enable_button = QPushButton("켜기")
        self.enable_button.clicked.connect(lambda: self.set_off(False))
        self.disable_button = QPushButton("끄기")
        self.disable_button.clicked.connect(lambda: self.set_off(True))
        self.refresh_button = QPushButton("새로 고침")
        self.refresh_button.setToolTip("Center에 등록된 외부 확장 정의를 다시 받습니다.")
        self.refresh_button.clicked.connect(self.refresh_external)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table)
        split.addWidget(self.detail)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)

        buttons = QHBoxLayout()
        for one in (self.enable_button, self.disable_button, self.refresh_button):
            buttons.addWidget(one)
        buttons.addStretch(1)
        close = QPushButton("닫기")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(split, 1)
        layout.addWidget(self.note)
        layout.addLayout(buttons)

        # 열 때는 **들고 있는 것만** 읽는다 (Center를 부르지 않는다 — 「새로 고침」이 그 일이다).
        self.load_held()
        self.refresh()

    # ── 표 ──

    def load_held(self) -> None:
        """들고 있는 명부의 외부 확장을 읽는다. **바깥을 부르지 않는다.**"""
        self.external, said = external_from(
            Services(data_dir=data_dir()).cached(),
            keys=list(self._agent.store.state.admin_keys),
            api_version=self._api_version(),
        )
        if said:
            self.note.setText(" / ".join(said))

    def refresh(self) -> None:
        """표와 상세를 다시 그린다. **바깥을 부르지 않는다.**"""
        host = self._agent.host
        bots = installed(data_dir())
        self.rows = rows_for(
            [*(host.all() if host is not None else []), *self.external],
            used_by=users(bots, self._agent.needed_extensions),
            wanted=wanted_versions(bots),
        )
        self.table.setRowCount(len(self.rows))
        for at, row in enumerate(self.rows):
            manifest = row.loaded.manifest if row.loaded is not None else None
            token, shown, tip = state_of(row)
            texts = (
                row.name,
                TIER_LABEL.get(manifest.tier, manifest.tier) if manifest is not None else "—",
                manifest.version if manifest is not None else (row.wanted_version or "—"),
                summary_of(manifest) if manifest is not None else "—",
                shown,
                str(len(row.used_by)) if row.used_by else "쓰는 Bot 없음",
            )
            for column, text in enumerate(texts):
                item = QTableWidgetItem(text)
                if column == NAME:
                    item.setToolTip(row.id)
                if column == USED_BY and row.used_by:
                    item.setToolTip(", ".join(row.used_by))
                if column == STATE:
                    # 색은 **그 표기의 것**을 찾는다 — 「꺼짐」에 「호환 안 됨」의 색을 쓰면 꺼 둔
                    # 것이 고장처럼 보인다 (`status_map` 「확장」, 스타일 가이드 §2-2).
                    color = theme.status_color(STATUS_GROUP, token, part="fg")
                    if color is not None:
                        item.setForeground(QColor(color))
                    item.setToolTip(tip)
                self.table.setItem(at, column, item)
        self._say_failures()
        if self.rows and not self.table.selectedItems():
            self.table.selectRow(0)
        else:
            self._show_selected()

    def _say_failures(self) -> None:
        """정의를 **읽지도 못한** 것 — id를 모르니 표에 줄을 만들 수 없다 (`LoadFailure`)."""
        host = self._agent.host
        said = [f"{one.origin}: {one.message}" for one in (host.failures if host is not None else [])]
        if said:
            self.note.setText("정의를 읽지 못했습니다 — " + " / ".join(said))

    def selected(self) -> ExtensionRow | None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        at = next(iter(sorted(rows)), None)
        return self.rows[at] if at is not None and at < len(self.rows) else None

    def _show_selected(self) -> None:
        found = self.selected()
        self._refresh_toggle(found)
        if found is None:
            self.detail.setPlainText(NO_SELECTION)
            return
        self.detail.setPlainText(
            render(
                detail_sections(
                    found,
                    service_url=self._agent.service_url(found.id) if found.loaded is not None else None,
                    runtimes=self._runtime_states(found),
                )
            )
        )

    def _runtime_states(self, row: ExtensionRow) -> dict[str, str]:
        """그 확장이 기여한 런타임의 지금 상태 (BUI-09와 **같은 표기**를 쓴다).

        **띄우지 않는다** — 감시자가 없으면 아직 띄우지 않은 것이다 (「꺼 둠」).
        """
        agent = self._agent
        if row.loaded is None or agent.host is None:
            return {}
        out: dict[str, str] = {}
        for runtime in row.loaded.manifest.contributes.bot_ui_local_runtimes:
            found = agent.runtimes().supervisors.get(runtime.id)
            state = STATE_LABELS.get(found.state, found.state) if found is not None else STATE_LABELS["off"]
            try:
                state += f" · 포트 {port_for(runtime, agent.settings)}"
            except RuntimeUnavailable:
                state += " · 포트를 모릅니다"
            out[runtime.id] = state
        return out

    def _refresh_toggle(self, row: ExtensionRow | None) -> None:
        """「켜기」/「끄기」 중 **할 수 있는 쪽만** 켠다. 못 하면 이유가 말풍선에 있다 (U3)."""
        why = NO_TOGGLE_NOTHING if row is None else ""
        if row is not None and row.loaded is None:
            why = NO_TOGGLE_ABSENT
        elif row is not None and row.is_external:
            why = NO_TOGGLE_EXTERNAL
        off_now = row.loaded.off if row is not None and row.loaded is not None else False
        for button, wants_off in ((self.enable_button, False), (self.disable_button, True)):
            button.setEnabled(not why and off_now != wants_off)
            button.setToolTip(why)

    # ── 끄고 켜기 (ADR-0043) ──

    def set_off(self, off: bool) -> None:
        """고른 확장을 끄거나 켠다 — **설정에 적고 확장을 다시 읽는다.**

        **끄기는 되돌릴 수 있지만 조용히 하지 않는다** — 쓰는 Bot이 있으면 몇 개가 실행 불가가
        되는지 말하고 확인 창의 기본은 「취소」다 (BUI-10 「삭제...」와 같은 결).
        """
        row = self.selected()
        if row is None or row.loaded is None or row.is_external:
            return
        if off and not self._confirm_off(row):
            return

        agent = self._agent
        kept = tuple(one for one in agent.settings.disabled_extensions if one != row.id)
        made = replace(agent.settings, disabled_extensions=(*kept, row.id) if off else kept)
        made.save()
        agent.settings = made
        # 다시 읽으면 기여가 한꺼번에 들어오거나 빠지고, 사전 점검 캐시도 비워진다 (C4 `readiness`).
        agent.reload_extensions()
        self.changed = True
        self.refresh()
        self._select(row.id)
        self.note.setText(
            f"{row.name}을 {'껐습니다' if off else '켰습니다'}."
            + (
                " 이 확장의 태스크를 쓰는 Bot은 사전 점검에서 막히고, 「도구」의 유틸리티도 사라집니다."
                if off
                else ""
            )
        )

    def _confirm_off(self, row: ExtensionRow) -> bool:
        warning = f"확장 「{row.name}」을 이 Bot UI에서 끕니다. 기여(태스크 종류·유틸리티·점검)가 모두 빠집니다."
        if row.used_by:
            warning += f"\n\n이 확장을 쓰는 Bot {len(row.used_by)}개가 실행 불가가 됩니다: " + ", ".join(row.used_by)
        answer = QMessageBox.question(
            self,
            "확장을 끌까요?",
            warning,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,  # 기본은 「취소」 (U4)
        )
        return answer == QMessageBox.StandardButton.Yes

    def _select(self, extension_id: str) -> None:
        at = next((i for i, one in enumerate(self.rows) if one.id == extension_id), None)
        if at is not None:
            self.table.selectRow(at)

    # ── 「새로 고침」 ──

    def refresh_external(self) -> None:
        """Center에서 외부 확장 정의를 다시 받는다 (C7 → 명부).

        **닿지 못하면 들고 있던 것을 쓴다** (ADR-0007) — 사유는 표 아래 한 줄로 말한다. 받는 것은
        **설치된 Bot이 요구하는 외부 확장**뿐이다 (명부의 규칙이 그렇다 — 필요한 것만 받는다).
        """
        wanted = sorted({one for bot in installed(data_dir()) for one in external_ids(bot.manifest)})
        said: list[str] = []
        try:
            client = self._agent.client()
        except KeyRejected as e:
            client = None
            said.append(f"Center를 부르지 못했습니다 — {e}")
        found = Services(data_dir=data_dir(), client=client)
        held = found.refresh(externals=wanted) if wanted or client is not None else found.cached()
        said += found.problems
        self.external, problems = external_from(
            held, keys=list(self._agent.store.state.admin_keys), api_version=self._api_version()
        )
        said += problems
        self.refresh()
        got = (
            f"외부 확장 {len(self.external)}개를 들고 있습니다."
            if wanted
            else "이 PC의 Bot이 쓰는 외부 확장이 없습니다."
        )
        self.note.setText(f"{got} {' / '.join(said)}" if said else got)

    def _api_version(self) -> str:
        host = self._agent.host
        return host.api_version if host is not None else API_VERSION


__all__ = [
    "COLUMNS",
    "DEFAULT_SIZE",
    "EXTERNAL_SUMMARY",
    "NO_TOGGLE_ABSENT",
    "NO_TOGGLE_EXTERNAL",
    "STATE_ABSENT",
    "STATE_BROKEN",
    "STATE_OFF",
    "STATE_ON",
    "TIER_LABEL",
    "ExtensionRow",
    "ExtensionsDialog",
    "detail_sections",
    "external_from",
    "render",
    "rows_for",
    "state_of",
    "summary_of",
    "users",
    "wanted_versions",
]
