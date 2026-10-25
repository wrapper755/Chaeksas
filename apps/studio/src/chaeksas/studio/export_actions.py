"""파일 메뉴의 패키지 넷 — 내보내기 둘·올리기 둘 (STU-12, C1·C5).

**메인 창에서 떼어 낸 글루다.** 창이 쥐는 것(열린 BPM 프로세스·설정·상태 줄)이 필요하므로
창을 받아 쓰지만, 창 자체가 이 일을 알 필요는 없다 — STU-01은 **무엇을 어디에 붙이나**만
알고 있으면 된다 (`main_window.py`가 500줄 선을 넘어 가른 자리다, CLAUDE.md §4).

넷이 **같은 관문 하나**를 쓴다 (`window.saved_to_disk()`): 적용 안 한 편집을 확인하고 저장한다
— **담는 것은 디스크의 파일**이기 때문이다. 올리기는 거기에 하나를 더 쓴다: **설정을 먼저
묻는다** (패키지를 만든 뒤에 「Center 설정이 없습니다」라고 하면 사람이 한 일이 버려진다).
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog, QMessageBox

from chaeksas.studio import upload
from chaeksas.studio.dialogs import ShareDefinitionsDialog
from chaeksas.studio.packaging import PackageError, default_lib_name, default_name, export, export_lib

if TYPE_CHECKING:  # pragma: no cover - 순환 import를 피한다 (창이 이 모듈을 부른다)
    from chaeksas.studio.main_window import MainWindow

PACKAGE_FILTER = "패키지 (*.zip)"

#: Center가 필요한 동작을 설정 없이 눌렀을 때 (STU-10 맨 아래).
NO_CENTER_SETTINGS = "Center에 로그인하지 않았습니다.\n\n지금 설정 → Center를 열까요?"

NO_PROCESS = "열린 BPM 프로세스가 없습니다."


# ─────────────────────────── 내보내기 (C1) ───────────────────────────


def export_package(window: MainWindow) -> None:
    """C1 패키지 zip. **저장하지 않은 편집은 들어가지 않는다** — 먼저 저장한다."""
    process = window.process
    if process is None:
        window.say(NO_PROCESS)
        return
    if not window.saved_to_disk():
        return
    target = _pick(window, "패키지로 내보내기", default_name(process))
    if target is None:
        return
    # 확장 태스크의 실행 위치는 **확장 정의만** 안다 (C13) — 매니페스트에 진짜 값이 들어가야
    # Center의 R2가 거짓으로 막지 않는다. 모르는 종류는 넣지 않는다.
    where = window.task_type_locations()
    keyless = window.keyless_apps()  # 키를 받지 않는 앱에는 참조를 적지 않는다 (ADR-0091)
    _write(
        window,
        "패키지",
        lambda: export(process, target, task_type_locations=where, keyless_apps=keyless),
    )


def export_shared(window: MainWindow) -> None:
    """STU-12. 고른 정의를 공유 BPM 프로세스 패키지(`process_lib`)로 내보낸다.

    **저장하지 않은 편집은 들어가지 않는다** — 담는 것은 디스크의 파일이다 (`export_package`와
    같은 관문을 쓴다).
    """
    process = window.process
    if process is None:
        window.say(NO_PROCESS)
        return
    if not window.saved_to_disk():
        return
    picked = ShareDefinitionsDialog.ask(window, process)
    if not picked:
        return
    target = _pick(window, "공유 BPM 프로세스로 내보내기", default_lib_name(process))
    if target is None:
        return
    where = window.task_type_locations()
    keyless = window.keyless_apps()
    _write(
        window,
        "공유 BPM 프로세스 패키지",
        lambda: export_lib(process, picked, target, task_type_locations=where, keyless_apps=keyless),
    )


def _pick(window: MainWindow, title: str, name: str) -> Path | None:
    found, _ = QFileDialog.getSaveFileName(
        window, title, str(window.settings.outputs_dir / name), PACKAGE_FILTER
    )
    return Path(found) if found else None


def _write(window: MainWindow, what: str, make: Callable[[], Path]) -> None:
    try:
        written = make()
    except PackageError as error:
        QMessageBox.warning(window, window.windowTitle(), str(error))
        window.say(f"{what}를 만들지 못했습니다: {error}")
        return
    window.say(f"{what}를 만들었습니다: {written}")


# ─────────────────────────── Center로 올리기 (C5) ───────────────────────────


def uploader(window: MainWindow) -> upload.CenterUploader | None:
    """올릴 자리. 설정이 없으면 **STU-10을 열어 주고 다시 본다** (STU-10 맨 아래).

    사람이 「아니오」를 고르거나 저장하지 않으면 `None`이다 — 그때는 부르는 쪽이 조용히
    그만둔다 (이미 창으로 말했다).
    """
    found = upload.from_settings(window.settings)
    if found is not None:
        return found
    answer = QMessageBox.question(
        window,
        window.windowTitle(),
        NO_CENTER_SETTINGS,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return None
    window.open_settings()
    return upload.from_settings(window.settings)


def upload_package(window: MainWindow) -> None:
    """STU-12 「Center로 올리기」 — **내보내는 것과 같은 zip**을 올린다 (C5).

    파일을 남기지 않는다 — 올리기는 내보내기가 아니다. 사람이 파일을 보고 싶으면 「패키지로
    내보내기...」가 그 일을 한다 (같은 `export`를 쓰므로 내용이 같다).
    """
    process = window.process
    if process is None:
        window.say(NO_PROCESS)
        return
    if not window.saved_to_disk():
        return
    locations = window.task_type_locations()
    keyless = window.keyless_apps()
    _upload(
        window,
        "패키지",
        lambda where: export(
            process, where / default_name(process), task_type_locations=locations, keyless_apps=keyless
        ),
    )


def upload_shared(window: MainWindow) -> None:
    """STU-12 「공유 BPM 프로세스 Center로 올리기」 — 고른 정의만 담아 올린다."""
    process = window.process
    if process is None:
        window.say(NO_PROCESS)
        return
    if not window.saved_to_disk():
        return
    picked = ShareDefinitionsDialog.ask(window, process)
    if not picked:
        return
    locations = window.task_type_locations()
    keyless = window.keyless_apps()
    _upload(
        window,
        "공유 BPM 프로세스 패키지",
        lambda where: export_lib(
            process,
            picked,
            where / default_lib_name(process),
            task_type_locations=locations,
            keyless_apps=keyless,
        ),
    )


def _upload(window: MainWindow, what: str, make: Callable[[Path], Path]) -> None:
    """만들어서 올린다 — 담는 것은 **저장된 파일**이다 (부르는 쪽이 관문을 지났다).

    순서가 중요하다 — **설정을 먼저 묻는다.** 패키지를 만들고 나서 「Center 설정이 없습니다」
    라고 하면 사람이 한 일이 버려진다.
    """
    found = uploader(window)
    if found is None:
        return

    with tempfile.TemporaryDirectory() as folder:
        try:
            made = make(Path(folder))
        except PackageError as error:
            QMessageBox.warning(window, window.windowTitle(), str(error))
            window.say(f"{what}를 만들지 못했습니다: {error}")
            return
        window.say(f"{what}를 만들었습니다 — Center에 올립니다...")
        try:
            answer = found.upload(made)
        except upload.UploadFailed as error:
            QMessageBox.warning(window, window.windowTitle(), str(error))
            window.say(f"올리지 못했습니다: {error}")
            return
    QMessageBox.information(window, window.windowTitle(), answer.message)
    window.say(answer.message)


__all__ = [
    "NO_CENTER_SETTINGS",
    "NO_PROCESS",
    "PACKAGE_FILTER",
    "export_package",
    "export_shared",
    "upload_package",
    "upload_shared",
    "uploader",
]
