"""Studio → Center 올리기와 STU-11 Center 공유 자원 (M6 조각 20).

보는 것:

1. **올리는 길은 Studio 키로 열린다** (C5 권한표) — 진짜 Center를 띄워 **진짜 패키지**를
   올린다. 관리자 토큰을 설계자 PC에 두지 않는다 (ADR-0013).
2. **올린 것은 후보다** (C2) — 승인·배포는 Admin의 일이고 결과 한 줄이 그렇게 말한다.
3. **「이미 있다」와 「다른 내용으로 있다」를 가른다** — 뭉개면 사람이 버전을 올려야 할 때를
   모른다.
4. **STU-11은 읽기만 한다** — 「설치」·「제거」는 끄고 까닭을 적고(U3), 닿지 못하면 그 자리에서
   말한다 (들고 있지 않는다).
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.center.app import create_app  # noqa: E402
from chaeksas.center.settings import Settings as CenterSettings  # noqa: E402
from chaeksas.center.storage import Store  # noqa: E402
from chaeksas.contracts.center_api import PackageInfo  # noqa: E402
from chaeksas.contracts.hashing import content_hash_zip  # noqa: E402
from chaeksas.studio import center_resources, services, upload  # noqa: E402

ADMIN = {"Authorization": "Bearer t-admin"}
AT = "2026-10-11T09:00:00+09:00"


def package_bytes(
    package_id: str = "invoice-check",
    version: str = "1.0.0",
    *,
    kind: str = "bpm_process",
    extra: dict[str, Any] | None = None,
    files: dict[str, str] | None = None,
) -> bytes:
    """C1 패키지 하나. `content_hash`는 **자기 자신을 뺀** 내용의 해시다 (C2)."""
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": kind,
        "id": package_id,
        "version": version,
        "name": "청구서 점검",
        "requires": {},
        "human": {},
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }
    if kind == "bpm_process":
        manifest |= {"run_location": "pc", "entry": "process/main.bpmn", "process_id": "Proc_x"}
    manifest.update(extra or {})
    body = files or {"process/main.bpmn": "<definitions />"}

    def made(text: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in body.items():
                archive.writestr(name, content)
            archive.writestr("manifest.json", text)
        return out.getvalue()

    staged = made(json.dumps(manifest, ensure_ascii=False))
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder) / "p.zip"
        tmp.write_bytes(staged)
        manifest["content_hash"] = content_hash_zip(tmp)
    return made(json.dumps(manifest, ensure_ascii=False))


def lib_bytes(package_id: str = "shared.approval", version: str = "1.1.0") -> bytes:
    """공유 BPM 프로세스 패키지 (`kind=process_lib`). `provides`가 「정의 N개」를 말한다."""
    return package_bytes(
        package_id,
        version,
        kind="process_lib",
        extra={
            "name": "공통 결재",
            "provides": {
                "processes": [
                    {"process_id": "Proc_approve", "file": "process/approve.bpmn", "name": "팀장 결재"}
                ]
            }
        },
        files={"process/approve.bpmn": "<definitions />"},
    )


@pytest.fixture
def center(tmp_path: Path) -> Iterator[TestClient]:
    settings = CenterSettings(
        admin_token="t-admin", read_token="t-read", package_dir=tmp_path / "packages"
    )
    store = Store(Path(":memory:"))
    app = create_app(settings, store=store)
    with TestClient(app) as found:
        yield found
    store.close()


@pytest.fixture
def studio_key(center: TestClient) -> str:
    """CON-11에서 **Studio용**으로 발급한 키 한 개 (ADR-0013 — Bot UI의 것과 값이 다르다)."""
    created = center.post(
        "/api/v1/center-keys", json={"name": "설계자 PC", "type": "studio"}, headers=ADMIN
    )
    assert created.status_code == 201, created.text
    return str(created.json()["key"])


def uploader(center: TestClient, key: str) -> upload.CenterUploader:
    return upload.CenterUploader(base_url="http://center.test", api_key=key, client=center)


def reader(center: TestClient, key: str) -> services.CenterReader:
    return services.CenterReader(base_url="http://center.test", api_key=key, client=center)


def cell(tab: Any, row: int, column: int) -> str:
    item = tab.table.item(row, column)
    assert item is not None
    return str(item.text())


def written(tmp_path: Path, raw: bytes, name: str = "p.zip") -> Path:
    target = tmp_path / name
    target.write_bytes(raw)
    return target


# ─────────────────────────── 올리기 (C5) ───────────────────────────


def test_a_studio_key_uploads_a_package_as_a_candidate(
    center: TestClient, studio_key: str, tmp_path: Path
) -> None:
    """**진짜 Center에 진짜 패키지를** 올린다. 올린 것은 후보다 (C2 — 서명이 관문이다)."""
    found = uploader(center, studio_key).upload(written(tmp_path, package_bytes()))
    assert (found.package_id, found.version, found.status) == ("invoice-check", "1.0.0", "candidate")
    assert found.created
    assert upload.CANDIDATE_NOTE in found.message

    # 올라간 것을 **같은 키로** 목록에서 본다 (STU-11·STU-03이 읽는 길이다).
    [listed] = reader(center, studio_key).packages("bpm_process")
    assert (listed.id, listed.status, listed.uploaded_by) == ("invoice-check", "candidate", "설계자 PC")


def test_uploading_the_same_bytes_again_says_it_is_already_there(
    center: TestClient, studio_key: str, tmp_path: Path
) -> None:
    """같은 내용이면 Center가 **200**이다 (재시도) — 화면은 「이미 올라가 있습니다」라고 한다."""
    path = written(tmp_path, package_bytes())
    assert uploader(center, studio_key).upload(path).created
    again = uploader(center, studio_key).upload(path)
    assert not again.created
    assert "이미 올라가 있습니다" in again.message


def test_the_same_version_with_other_contents_tells_you_to_bump_it(
    center: TestClient, studio_key: str, tmp_path: Path
) -> None:
    """**뭉개지 않는다** — 「이미 있다」와 「다르다」는 사람이 할 일이 다르다 (버전을 올린다)."""
    assert uploader(center, studio_key).upload(written(tmp_path, package_bytes())).created
    changed = package_bytes(files={"process/main.bpmn": "<definitions id='다름' />"})
    with pytest.raises(upload.UploadFailed) as caught:
        uploader(center, studio_key).upload(written(tmp_path, changed, "other.zip"))
    assert "버전을 올려서" in str(caught.value)
    assert "version_conflict" in str(caught.value), "Center의 코드도 싣는다"


def test_a_bot_ui_key_cannot_upload_and_the_message_points_at_the_setting(
    center: TestClient, tmp_path: Path
) -> None:
    """키 종류를 틀리면 **어디를 고칠지** 말한다 (C5 권한표 — Studio 키여야 한다)."""
    created = center.post(
        "/api/v1/center-keys", json={"name": "현장 PC", "type": "bot_ui"}, headers=ADMIN
    )
    with pytest.raises(upload.UploadFailed) as caught:
        uploader(center, str(created.json()["key"])).upload(written(tmp_path, package_bytes()))
    assert "Studio용 Center API 키" in str(caught.value)
    assert "설정 → Center" in str(caught.value)


def test_an_unknown_key_is_refused_without_leaking_it(
    center: TestClient, tmp_path: Path
) -> None:
    """**키 값은 결과 글에 들어가지 않는다** (STU-10 「연결 테스트」와 같은 규칙)."""
    secret = "chk_ctr_" + "z" * 40
    with pytest.raises(upload.UploadFailed) as caught:
        uploader(center, secret).upload(written(tmp_path, package_bytes()))
    assert secret not in str(caught.value)
    assert "거부되었습니다" in str(caught.value)


def test_a_broken_zip_carries_centers_own_code(
    center: TestClient, studio_key: str, tmp_path: Path
) -> None:
    """모르는 코드를 「알 수 없는 오류」로 덮지 않는다 — 운영자가 찾을 글이다."""
    with pytest.raises(upload.UploadFailed) as caught:
        uploader(center, studio_key).upload(written(tmp_path, "zip이 아니다".encode()))
    assert "not_a_zip" in str(caught.value)


def test_no_address_or_key_means_no_uploader() -> None:
    """설정이 **둘 다** 있을 때만 만든다 (`services.reader_for`와 같은 규칙)."""

    class Fake:
        center_url = "http://center.test"

    assert upload.uploader_for(Fake(), None) is None
    assert upload.uploader_for(Fake(), "chk_ctr_x") is not None

    class NoUrl:
        center_url = "  "

    assert upload.uploader_for(NoUrl(), "chk_ctr_x") is None


# ─────────────────────────── STU-11 (읽기 전용) ───────────────────────────


def test_the_dialog_lists_both_kinds_from_the_package_table(
    center: TestClient, studio_key: str, tmp_path: Path
) -> None:
    """두 탭은 **C5 패키지 표**에서 온다 — 「개수」는 매니페스트의 `provides`다 (C1)."""
    key = studio_key
    uploader(center, key).upload(written(tmp_path, lib_bytes()))
    pack = package_bytes(
        "ops.excel-tools",
        "2.0.0",
        kind="toolpack",
        extra={"provides": {"tools": [{"name": "xlsx_read", "domain": "doc"}]}},
        files={"tools/xlsx.py": "# 도구"},
    )
    uploader(center, key).upload(written(tmp_path, pack, "pack.zip"))

    libs = center_resources.listing(reader(center, key), center_resources.KIND_LIB)
    [one] = libs.rows
    assert (one.label, one.version, one.status_text, one.count_text) == (
        "공통 결재",
        "1.1.0",
        "후보",
        "1",
    )
    assert one.installed == "", "받아 둘 자리가 아직 없다"

    packs = center_resources.listing(reader(center, key), center_resources.KIND_TOOLPACK)
    assert [(r.package_id, r.count_text) for r in packs.rows] == [("ops.excel-tools", "1")]


def test_a_package_without_provides_says_so_instead_of_zero() -> None:
    """**0이 아니라 「매니페스트에 없음」**이다 (CON-06과 같은 규칙)."""
    bare = PackageInfo.model_validate(
        {
            "id": "shared.x",
            "version": "1.0.0",
            "kind": "process_lib",
            "status": "approved",
            "content_hash": "sha256:" + "c" * 64,
            "uploaded_by": "설계자 PC",
            "uploaded_at": AT,
        }
    )
    assert center_resources.count_of(bare, center_resources.KIND_LIB) is None
    assert center_resources.row_of(bare, center_resources.KIND_LIB).count_text == (
        center_resources.NO_PROVIDES
    )


def test_an_unknown_status_is_shown_as_it_came() -> None:
    """상태는 **열린 문자열**이다 (계약 원칙 10) — 모르는 값을 지우지 않는다."""
    row = center_resources.Row(package_id="x", version="1.0.0", status="삭제중", count=0)
    assert row.status_text == "삭제중"


def test_no_center_means_no_knocking() -> None:
    """주소·키가 없으면 **두드리지 않는다** — 까닭 한 줄을 보인다 (STU-03과 같은 규칙)."""
    found = center_resources.listing(None, center_resources.KIND_LIB)
    assert found.rows == () and found.note == center_resources.NO_CENTER


def test_an_unreachable_center_says_so_and_holds_nothing() -> None:
    """Studio는 현장이 아니다 — 낡은 목록을 들고 있지 않고 그 자리에서 말한다."""

    class Dead(services.CenterReader):
        def packages(self, kind: str) -> list[PackageInfo]:
            raise services.CenterUnreachable("Center에 닿지 못했습니다 (ConnectError)")

    found = center_resources.listing(Dead(base_url="http://x", api_key="k"), center_resources.KIND_LIB)
    assert found.rows == ()
    assert "닿지 못했습니다" in found.note


def test_an_empty_center_says_it_is_empty(center: TestClient, studio_key: str) -> None:
    found = center_resources.listing(reader(center, studio_key), center_resources.KIND_LIB)
    assert found.note == center_resources.EMPTY_LIB


@pytest.fixture
def qt_app() -> Iterator[Any]:
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def test_the_dialog_keeps_install_and_remove_but_turns_them_off(
    qt_app: Any, center: TestClient, studio_key: str, tmp_path: Path
) -> None:
    """**끄고 까닭을 적는다** (U3) — 단추를 지우면 「어디서 설치하나」가 된다."""
    uploader(center, studio_key).upload(written(tmp_path, lib_bytes()))
    window = center_resources.CenterResourcesDialog(reader(center, studio_key))
    assert window.libs.table.rowCount() == 1
    assert cell(window.libs, 0, center_resources.NAME) == "공통 결재"
    assert cell(window.libs, 0, center_resources.INSTALLED) == center_resources.NOT_INSTALLED
    for one in (window.install_button, window.remove_button):
        assert not one.isEnabled()
        assert "§4-5" in one.toolTip()
    assert window.note.text() != ""


def test_the_dialog_says_why_a_tab_is_empty(qt_app: Any) -> None:
    """한 탭을 못 받아도 **나머지는 그린다** — 아래 한 줄이 둘을 다 말한다."""
    window = center_resources.CenterResourcesDialog(None)
    assert window.libs.table.rowCount() == 0
    assert center_resources.NO_CENTER in window.note.text()
    assert "공유 BPM 프로세스" in window.note.text() and "툴팩" in window.note.text()


# ─────────────────────────── 메인 창에 붙은 자리 (STU-01 메뉴) ───────────────────────────

_PROBE: list[Any] = []


@pytest.fixture
def webengine(qt_app: Any) -> Any:
    """캔버스(QtWebEngine)가 뜨는 환경인가 — 못 뜨면 건너뛴다 (`test_studio_resources`와 같다)."""
    if _PROBE:
        return True
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView

        _PROBE.append(QWebEngineView())
    except Exception as e:  # noqa: BLE001 — 환경 문제면 건너뛴다
        pytest.skip(f"QtWebEngine을 띄울 수 없다: {type(e).__name__}: {e}")
    return True


@pytest.fixture
def window(tmp_path: Path, webengine: Any) -> Any:
    """STU-01 메인 창 하나. 캔버스가 뜨기를 **기다리지 않는다** — 보는 것은 붙은 자리다."""
    from chaeksas.studio.main_window import MainWindow
    from chaeksas.studio.settings import Settings

    return MainWindow(Settings(data_dir=tmp_path))


def test_the_file_menu_no_longer_says_later(window: Any) -> None:
    """「올리기」 둘과 STU-11이 **말풍선이 아니라 동작**이다 (STU-01 메뉴 표)."""
    files = next(one for one in window.menuBar().actions() if one.text() == "파일")
    labels = [one.text() for one in files.menu().actions()]
    assert "Center로 올리기" in labels
    assert "공유 BPM 프로세스 Center로 올리기" in labels
    assert "Center 공유 자원..." in labels


def test_uploading_without_an_open_process_says_so(window: Any) -> None:
    """열린 BPM 프로세스가 없으면 **Center를 두드리지 않고** 말한다."""
    window.upload_package()
    assert "열린 BPM 프로세스가 없습니다" in window.log_view.toPlainText()
    window.upload_shared()
    assert window.log_view.toPlainText().count("열린 BPM 프로세스가 없습니다") == 2


def test_no_center_settings_means_no_uploader(window: Any, monkeypatch: Any) -> None:
    """설정이 없으면 **묻고**, 사람이 「아니오」면 `None`이다 (STU-10 맨 아래)."""
    from PySide6.QtWidgets import QMessageBox

    from chaeksas.studio.main_window import NO_CENTER_SETTINGS

    asked: list[str] = []

    def no(parent: Any, title: str, text: str, buttons: Any) -> Any:
        asked.append(text)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(no))
    assert window.uploader() is None
    assert asked == [NO_CENTER_SETTINGS]


def test_the_center_resources_dialog_opens_from_the_explorer(window: Any, monkeypatch: Any) -> None:
    """STU-03 문맥 메뉴와 파일 메뉴가 **같은 창**을 연다 — 창은 메인 창이 쥔다."""
    opened: list[Any] = []
    monkeypatch.setattr(
        center_resources.CenterResourcesDialog, "exec", lambda self: opened.append(self.reader)
    )
    window.resource_tree.opening_center.emit()
    assert len(opened) == 1
    assert opened[0] is None, "Center 설정이 없으면 읽는 쪽을 만들지 않는다"
