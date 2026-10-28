"""Center에서 읽어 와 화면에 꽂는 자리 — 서비스 앱 카탈로그·리소스 탐색기·STU-11.

메인 창에서 떼어 낸 글루다 (`main_window.py`가 500줄 선을 넘어 가른 자리, CLAUDE.md §4).
**읽기만 한다** — Center에 쓰는 길은 `upload.py` 하나다.

지키는 것 셋.

- **열 때마다 Center를 두드리지 않는다.** 정의를 열 때, 설정을 저장한 뒤, 「새로 고침」을
  누를 때, **설치·제거 뒤**(줄의 「설치됨」이 바뀐다)만 받는다. 그래서 `refresh_resources()`는
  `reader`를 **받아서** 쓴다 — 이 함수가 몰래 네트워크를 타지 않는다.
- **같은 것을 두 번 받지 않는다.** STU-14의 고를 거리(`service_catalog`)를 STU-03이 그대로
  쓴다 (`catalog=`).
- **들고 있지 않는다.** 닿지 못하면 그 자리에서 말한다 — Studio는 현장이 아니라 개발 도구다
  (ADR-0007의 「들고 있던 것을 쓴다」는 현장 쪽 규칙이다).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox

from chaeksas.studio import file_actions, install, resources, service_catalog, services
from chaeksas.studio.center_resources import CenterResourcesDialog
from chaeksas.studio.viewer import DiagramViewer
from chaeksas.studio.workspace import BpmProcess, InstalledLib

if TYPE_CHECKING:  # pragma: no cover - 순환 import를 피한다 (창이 이 모듈을 부른다)
    from chaeksas.studio.main_window import MainWindow

log = logging.getLogger(__name__)

NO_DEFINITION = "열린 정의가 없습니다 — 먼저 BPM 프로세스를 여세요."
#: 셋은 **열린 BPM 프로세스**의 `libs/`를 보는 일이다 (ADR-0048·0051).
NO_PROCESS = "열린 BPM 프로세스가 없습니다 — 받아 둔 공유 BPM 프로세스는 BPM 프로세스마다입니다."
COPY_TITLE = "내 BPM 프로세스로 복사"
#: 복사가 **무엇을 만드는지** 적어 보인다 (겹치면 비낀 이름이 여기 보인다, ADR-0051).
COPY_TEXT = (
    "{ref}의 정의 {process_id}을 이 BPM 프로세스로 복사합니다.\n\n"
    "만들 파일: process/{file_name}\n\n"
    "복사한 뒤로는 **내 정의가 이깁니다** (같은 id면 받아 둔 것을 가립니다). "
    "내보낼 때 `requires.libs`에서는 빠집니다."
)


def refresh_catalog(window: MainWindow) -> None:
    """Center 리소스 목록(C7)을 받아 **STU-14와 STU-03이 같은 것을 본다**.

    받지 못하면 로그에 적고 편집기가 「등록된 서비스 앱이 없습니다」, 탐색기가 까닭 한 줄을
    보인다 (**들고 있지 않는다**).
    """
    found = services.from_settings(window.settings)
    window.properties.catalog = service_catalog.from_center(found.reader)
    for why in window.properties.catalog.problems:
        window.say(f"서비스 앱 목록: {why}")
    refresh_resources(window, reader=found.reader)


def refresh_resources(window: MainWindow, *, reader: services.CenterReader | None) -> None:
    """STU-03 — 뿌리는 **확장 선언**에서, 목록은 Center에서. 서비스 앱은 받아 둔 것을 쓴다.

    `reader`가 `None`이면 **Center를 두드리지 않는다** — 뿌리만 그리고 까닭을 적는다.
    """
    window.resource_tree.show_tree(
        resources.collect(
            window.extensions.host.resource_views(),
            catalog=window.properties.catalog,
            reader=reader,
            # 받아 둔 판은 **열린 BPM 프로세스**의 것이다 (ADR-0051 — STU-11과 같은 함수다).
            installed=install.installed_of(window.process),
        )
    )


def add_to_canvas(
    window: MainWindow, create: object, *, at: tuple[int, int] | None = None
) -> None:
    """STU-03 「캔버스에 추가」 — 캔버스 명령 하나가 만든다 (XML을 파이썬이 만지지 않는다).

    `at`은 **끌어다 놓은 자리**다 (ADR-0044) — 문맥 메뉴·더블클릭은 주지 않아 캔버스가 빈
    곳을 찾는다. **두 길이 같은 명령을 쓰므로** 실행 취소가 양쪽에서 한 걸음이다.
    """
    if not isinstance(create, resources.Create):
        return
    if window.definition is None:
        window.say(NO_DEFINITION)
        return

    def done(found: dict[str, object]) -> None:
        if not found.get("ok"):
            window.say(f"캔버스에 추가하지 못했습니다: {found.get('error')}")
            return
        window.say(f"캔버스에 추가했습니다: {create.name} ({found.get('id')})")

    window.canvas.create_task(
        create.bpmn, create.name, create.chk, attrs=create.attrs, at=at, then=done
    )


def drop_on_canvas(window: MainWindow, payload: str, x: int, y: int) -> None:
    """STU-03 → 캔버스 끌어다 놓기 (ADR-0044). **뜻을 푸는 것은 여기다** — 캔버스는 모른다.

    모양이 아니면 **조용히 버린다** — 우리 MIME 형식만 캔버스가 받으므로 여기 오는 것은
    우리가 실은 것이고, 그래도 깨졌으면 사람에게 할 말이 없다 (로그만 남긴다).
    """
    create = resources.from_payload(payload)
    if create is None:
        log.warning("캔버스에 떨어진 것을 읽지 못했다: %r", payload[:200])
        return
    add_to_canvas(window, create, at=(x, y))


def _held(window: MainWindow, shared: object) -> tuple[BpmProcess, InstalledLib] | None:
    """그 줄이 가리키는 **받아 둔 판**을 지금 디스크에서 확인한다 (ADR-0051).

    탐색기의 줄이 이미 끄고 있지만(`Shared.off`) **그 줄은 받아 온 순간의 것**이다 — 그사이
    제거됐을 수 있으니 하는 쪽이 다시 본다. 없으면 까닭을 말하고 아무 일도 하지 않는다.
    """
    if not isinstance(shared, resources.Shared):
        return None
    process = window.process
    if process is None:
        window.say(NO_PROCESS)
        return None
    lib = install.installed_of(process).get(shared.package_id)
    if lib is None or lib.version != shared.version:
        window.say(f"{shared.process_id}: {resources.NOT_INSTALLED}")
        return None
    return process, lib


def view_shared(window: MainWindow, shared: object) -> None:
    """STU-03 「열기 (읽기 전용)」 — 받아 둔 `libs/`의 그 파일을 뷰어로 띄운다 (ADR-0051).

    **Center를 부르지 않는다** — 보는 것과 실행이 같은 파일이다.
    """
    found = _held(window, shared)
    if found is None or not isinstance(shared, resources.Shared):
        return
    process, lib = found
    path = install.definition_file(process, lib, shared.process_id)
    if path is None:
        window.say(f"{shared.process_id}: {install.NOT_PROVIDED}")
        return
    try:
        xml = path.read_text(encoding="utf-8")
    except OSError as e:
        window.say(f"{path.name}을 읽지 못했습니다: {e}")
        return
    dialog = DiagramViewer(f"{lib.ref} / {shared.process_id}", xml, window)
    window.say(f"열었습니다 (읽기 전용): {lib.ref} / {shared.process_id}")
    dialog.exec()
    # 캔버스를 든 창이라 **치운다** — 모아 두면 WebEngine 프로필이 쌓인다.
    dialog.deleteLater()


def copy_shared(window: MainWindow, shared: object) -> None:
    """STU-03 「내 BPM 프로세스로 복사」 — 묻고, 쓰고, 그것을 연다 (ADR-0051).

    **덮어쓰지 않는다** — 겹치면 비낀 이름이 묻는 창에 적혀 보인다. 저장 안 한 편집은 여는
    자리가 **같은 관문**으로 묻는다 (`file_actions.open_definition`, U11).
    """
    found = _held(window, shared)
    if found is None or not isinstance(shared, resources.Shared):
        return
    process, lib = found
    try:
        plan = install.plan_copy(process, lib, shared.process_id)
    except install.InstallFailed as e:
        window.say(str(e))
        return
    answer = QMessageBox.question(
        window,
        COPY_TITLE,
        COPY_TEXT.format(ref=lib.ref, process_id=shared.process_id, file_name=plan.file_name),
        QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
        QMessageBox.StandardButton.Yes,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return
    try:
        path = install.copy_into(window.workspace, process, plan)
    except install.InstallFailed as e:
        window.say(str(e))
        return
    window.say(f"복사했습니다: process/{plan.file_name}")
    file_actions.open_definition(window, path.as_posix())


def open_center_resources(window: MainWindow) -> None:
    """STU-11. 파일 메뉴와 STU-03 문맥 메뉴가 **같은 창**을 연다.

    창이 제 손으로 Center를 읽는다 — 설정이 없으면 창 안에서 그렇게 말하므로(U3) 여기서 미리
    묻지 않는다 (읽기만 하는 자리다).

    **열린 BPM 프로세스와 작업 폴더를 함께 넘긴다** — 설치는 그 BPM 프로세스의 `libs/`에 푸는
    일이라 (ADR-0048) 대상이 없으면 창이 단추를 끄고 까닭을 적는다. 창을 닫고 나면 받아 둔
    것이 탐색기·검사에 보여야 하므로 **다시 읽는다**.
    """
    reader = services.from_settings(window.settings).reader
    CenterResourcesDialog(
        reader, window, workspace=window.workspace, process=window.process
    ).exec()
    if window.process is not None:
        # 설치가 `process.json`과 `libs/`를 바꿨다 — 창이 들고 있는 것을 **디스크에서** 다시 읽는다.
        window.process = window.workspace.read(window.process.folder, window.process.group)
        window.explorer.refresh(
            opened=window.definition.as_posix() if window.definition is not None else ""
        )
        # STU-03의 줄에 「설치됨」이 붙고 셋이 켜져야 한다 (ADR-0051) — 설치·제거 **뒤**도
        # Center를 읽는 때다 (열 때마다가 아니라 바뀐 때다).
        refresh_resources(window, reader=reader)


__all__ = [
    "COPY_TEXT",
    "COPY_TITLE",
    "NO_DEFINITION",
    "NO_PROCESS",
    "add_to_canvas",
    "copy_shared",
    "drop_on_canvas",
    "open_center_resources",
    "refresh_catalog",
    "refresh_resources",
    "view_shared",
]
