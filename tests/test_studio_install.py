"""공유 BPM 프로세스 설치 (STU-11 「설치」, ADR-0048) — 진짜 Center에서 받아 `libs/`에 푼다.

거듭 보는 것 다섯.

1. **자리가 실행기와 같다** — 받은 것이 `libs/*.bpmn`으로 가고, 거기서 **호출이 찾는다**
   (`BpmProcess.processes()`). 그래서 시험 실행·B14와 현장이 **같은 것**을 본다.
2. **편집 대상이 아니다** — `definitions`(탐색기·저장)에는 들어가지 않는다.
3. **내보내기가 판을 붙인다** — `requires.libs`가 C1대로 `<id>@<version>`이다.
4. **갱신은 갈아 치운다** — 옛 판의 파일이 남으면 `libs/*.bpmn`을 글롭하는 쪽이 둘을 읽는다.
5. **아무 패키지나 풀지 않는다** — 갈래·id·버전이 받으려던 것과 같아야 한다.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.center.storage import Store
from chaeksas.contracts.hashing import content_hash_zip
from chaeksas.studio import center_resources, install, packaging, services, upload
from chaeksas.studio.workspace import LIBS_DIR, BpmProcess, Workspace

ADMIN = {"Authorization": "Bearer t-admin"}

LIB_ID = "shared.approval"
LIB_VERSION = "1.1.0"
CALLED = "Proc_approve"

DEFINITION = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="{process_id}" name="{name}">
    <bpmn:extensionElements><chk:process>{{}}</chk:process></bpmn:extensionElements>
    <bpmn:startEvent id="Start_1"/>
    {body}
    <bpmn:endEvent id="End_1"/>
    <bpmn:sequenceFlow id="f1" sourceRef="Start_1" targetRef="End_1" />
  </bpmn:process>
</bpmn:definitions>
"""

CALLER = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="Proc_main" name="주문">
    <bpmn:extensionElements><chk:process>{{}}</chk:process></bpmn:extensionElements>
    <bpmn:startEvent id="Start_1"/>
    <bpmn:callActivity id="Call_1" name="결재" calledElement="{called}">
      <bpmn:extensionElements><chk:call>{{"input": {{}}, "output": {{}}}}</chk:call></bpmn:extensionElements>
    </bpmn:callActivity>
    <bpmn:endEvent id="End_1"/>
    <bpmn:sequenceFlow id="f1" sourceRef="Start_1" targetRef="Call_1" />
    <bpmn:sequenceFlow id="f2" sourceRef="Call_1" targetRef="End_1" />
  </bpmn:process>
</bpmn:definitions>
"""

#: 규칙 태스크가 있는 정의 — 결정표가 함께 설치되지 않는다는 말을 보려고 (§다섯).
RULE_BODY = (
    '<bpmn:businessRuleTask id="Rule_1" name="등급">'
    '<bpmn:extensionElements><chk:rule>{"decision": "grade", "input": {}, "output": {}}'
    "</chk:rule></bpmn:extensionElements></bpmn:businessRuleTask>"
)


def lib_zip(
    *,
    package_id: str = LIB_ID,
    version: str = LIB_VERSION,
    kind: str = "process_lib",
    files: dict[str, str] | None = None,
) -> bytes:
    """공유 BPM 프로세스 패키지 하나 (C1 `kind=process_lib`)."""
    inside = files or {
        "process/approve.bpmn": DEFINITION.format(process_id=CALLED, name="팀장 결재", body="")
    }
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": kind,
        "id": package_id,
        "version": version,
        "name": "공통 결재",
        "requires": {},
        "human": {},
        "provides": {
            "processes": [
                {"process_id": CALLED, "file": "process/approve.bpmn", "name": "팀장 결재"}
            ]
        },
        "built": {"by": "studio", "at": "2026-10-12T09:00:00+09:00", "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }
    if kind == "bpm_process":  # R1 — 진입이 있어야 한다
        manifest["entry"] = "process/approve.bpmn"
        manifest["process_id"] = CALLED
        manifest["run_location"] = "pc"
        manifest.pop("provides")

    def made(body: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, text in inside.items():
                archive.writestr(name, text)
            archive.writestr("manifest.json", body)
        return out.getvalue()

    staged = made(json.dumps(manifest, ensure_ascii=False))
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder) / "p.zip"
        tmp.write_bytes(staged)
        manifest["content_hash"] = content_hash_zip(tmp)
    return made(json.dumps(manifest, ensure_ascii=False))


@pytest.fixture
def center(tmp_path: Path) -> Iterator[TestClient]:
    settings = CenterSettings(
        admin_token="t-admin", read_token="t-read", package_dir=tmp_path / "packages"
    )
    store = Store(Path(":memory:"))
    with TestClient(create_app(settings, store=store)) as found:
        yield found
    store.close()


@pytest.fixture
def studio_key(center: TestClient) -> str:
    created = center.post(
        "/api/v1/center-keys", json={"name": "설계자 PC", "type": "studio"}, headers=ADMIN
    )
    assert created.status_code == 201, created.text
    return str(created.json()["key"])


@pytest.fixture
def reader(center: TestClient, studio_key: str) -> services.CenterReader:
    return services.CenterReader(base_url="http://center.test", api_key=studio_key, client=center)


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "workspace").ensure()


@pytest.fixture
def process(workspace: Workspace) -> BpmProcess:
    """진입 정의가 **공유 BPM 프로세스를 부르는** BPM 프로세스 하나."""
    made = workspace.create("erp.order", name="주문")
    workspace.save_definition(made, "main.bpmn", CALLER.format(called=CALLED))
    return workspace.read(made.folder, made.group)


def cell(tab: Any, row: int, column: int) -> str:
    item = tab.table.item(row, column)
    assert item is not None
    return str(item.text())


def upload_lib(center: TestClient, studio_key: str, raw: bytes, tmp_path: Path) -> None:
    target = tmp_path / "lib.zip"
    target.write_bytes(raw)
    upload.CenterUploader(
        base_url="http://center.test", api_key=studio_key, client=center
    ).upload(target)


# ─────────────────────────── 받아서 푼다 ───────────────────────────


def test_an_installed_lib_can_be_called_and_is_not_editable(
    center: TestClient, studio_key: str, reader: services.CenterReader,
    workspace: Workspace, process: BpmProcess, tmp_path: Path,
) -> None:
    """**자리가 실행기와 같다** — `libs/`에 풀고 호출이 거기서 찾는다 (ADR-0048).

    받기 전에는 호출 대상이 없고(그래서 C14 B14가 막는다) 받은 뒤에는 있다. 그러면서도
    **편집 대상은 아니다** — 탐색기·저장이 보는 `definitions`에는 들어가지 않는다.
    """
    assert CALLED not in process.processes(), "받기 전에는 부를 수 없다"

    upload_lib(center, studio_key, lib_zip(), tmp_path)
    done = install.install(
        workspace, process, reader, package_id=LIB_ID, version=LIB_VERSION
    )

    assert done.lib.ref == f"{LIB_ID}@{LIB_VERSION}"
    assert done.lib.processes == (CALLED,)
    assert done.warnings == ()
    # 파일은 **평평하게** `libs/`에 (실행기가 `libs/*.bpmn`을 글롭한다).
    assert [p.name for p in sorted((process.folder / LIBS_DIR).glob("*.bpmn"))] == list(done.lib.files)

    again = workspace.read(process.folder, process.group)
    assert CALLED in again.processes(), "받은 뒤에는 부를 수 있다"
    assert CALLED not in {d.id for d in again.definitions}, "편집 대상은 아니다"
    assert again.lib_of(CALLED) == done.lib


def test_the_check_accepts_the_call_once_it_is_installed(
    center: TestClient, studio_key: str, reader: services.CenterReader,
    workspace: Workspace, process: BpmProcess, tmp_path: Path,
) -> None:
    """**C14 B14가 받아들인다** — 설치 전에는 「호출 대상이 패키지에 없다」로 막았다.

    실행 전 검사(F6)와 시험 실행이 **같은 사전**을 쓰므로(`processes()`) 둘이 함께 열린다.
    """
    from chaeksas.studio.preflight import inspect

    opened = process.definitions[0].process
    assert opened is not None
    before = inspect(opened, process)
    assert any(v.rule == "B14" and CALLED in v.message for v in before)

    upload_lib(center, studio_key, lib_zip(), tmp_path)
    install.install(workspace, process, reader, package_id=LIB_ID, version=LIB_VERSION)

    after = workspace.read(process.folder, process.group)
    reopened = after.definitions[0].process
    assert reopened is not None
    assert not [v for v in inspect(reopened, after) if v.rule == "B14"]


def test_the_export_pins_the_version(
    center: TestClient, studio_key: str, reader: services.CenterReader,
    workspace: Workspace, process: BpmProcess, tmp_path: Path,
) -> None:
    """**내보내기가 판을 붙인다** — C1 `requires.libs`는 `<id>@<version>`이다 (ADR-0048).

    설치 기록이 어느 패키지가 그 정의를 주는지 안다. 설치하지 않은 호출은 id만 적히는데 그
    그림은 B14가 막는다.
    """
    assert packaging.collect_requires(process).libs == [CALLED], "설치 전에는 id만"

    upload_lib(center, studio_key, lib_zip(), tmp_path)
    install.install(workspace, process, reader, package_id=LIB_ID, version=LIB_VERSION)
    after = workspace.read(process.folder, process.group)

    assert packaging.collect_requires(after).libs == [f"{LIB_ID}@{LIB_VERSION}"]


def test_the_package_carries_the_lib_files(
    center: TestClient, studio_key: str, reader: services.CenterReader,
    workspace: Workspace, process: BpmProcess, tmp_path: Path,
) -> None:
    """패키지에 `libs/`가 **담겨 나간다** (C1 §패키지 구성) — `INCLUDED`가 이미 그 폴더를 안다."""
    upload_lib(center, studio_key, lib_zip(), tmp_path)
    install.install(workspace, process, reader, package_id=LIB_ID, version=LIB_VERSION)
    after = workspace.read(process.folder, process.group)

    made = packaging.export(after, tmp_path / "out.zip")
    with zipfile.ZipFile(made) as archive:
        inside = [name for name in archive.namelist() if name.startswith(f"{LIBS_DIR}/")]
    assert inside, "받아 둔 정의가 패키지로 간다 (현장 실행기가 그것을 읽는다)"


def test_an_update_replaces_the_old_version(
    center: TestClient, studio_key: str, reader: services.CenterReader,
    workspace: Workspace, process: BpmProcess, tmp_path: Path,
) -> None:
    """**갱신은 갈아 치운다** — 옛 판이 남으면 `libs/*.bpmn`을 읽는 쪽이 둘을 본다."""
    upload_lib(center, studio_key, lib_zip(), tmp_path)
    upload_lib(center, studio_key, lib_zip(version="1.2.0"), tmp_path)
    install.install(workspace, process, reader, package_id=LIB_ID, version=LIB_VERSION)
    mid = workspace.read(process.folder, process.group)
    install.install(workspace, mid, reader, package_id=LIB_ID, version="1.2.0")

    after = workspace.read(process.folder, process.group)
    assert [one.ref for one in after.libs] == [f"{LIB_ID}@1.2.0"]
    assert len(list((process.folder / LIBS_DIR).glob("*.bpmn"))) == 1


def test_removing_deletes_only_that_libs_files(
    center: TestClient, studio_key: str, reader: services.CenterReader,
    workspace: Workspace, process: BpmProcess, tmp_path: Path,
) -> None:
    """제거는 **기록이 적어 둔 파일만** 지운다 — `libs/`를 비우면 다른 판까지 날아간다."""
    other = DEFINITION.format(process_id="Proc_other", name="다른 것", body="")
    upload_lib(center, studio_key, lib_zip(), tmp_path)
    upload_lib(
        center, studio_key,
        lib_zip(package_id="shared.other", version="1.0.0", files={"process/other.bpmn": other}),
        tmp_path,
    )
    install.install(workspace, process, reader, package_id=LIB_ID, version=LIB_VERSION)
    mid = workspace.read(process.folder, process.group)
    install.install(workspace, mid, reader, package_id="shared.other", version="1.0.0")
    full = workspace.read(process.folder, process.group)
    assert len(full.libs) == 2

    message = install.remove(workspace, full, package_id=LIB_ID)
    assert LIB_ID in message
    after = workspace.read(process.folder, process.group)
    assert [one.package_id for one in after.libs] == ["shared.other"]
    assert "Proc_other" in after.processes() and CALLED not in after.processes()


def test_callers_are_counted_before_removing(
    center: TestClient, studio_key: str, reader: services.CenterReader,
    workspace: Workspace, process: BpmProcess, tmp_path: Path,
) -> None:
    """제거는 되돌릴 수 없어 **부르는 곳을 먼저 말한다** (U9)."""
    upload_lib(center, studio_key, lib_zip(), tmp_path)
    done = install.install(workspace, process, reader, package_id=LIB_ID, version=LIB_VERSION)
    after = workspace.read(process.folder, process.group)
    assert install.callers_of(after, done.lib) == ["main: Call_1"]


# ─────────────────────────── 받지 않는 것 ───────────────────────────


def test_a_bot_package_is_not_installed_as_a_lib(
    center: TestClient, studio_key: str, reader: services.CenterReader,
    workspace: Workspace, process: BpmProcess, tmp_path: Path,
) -> None:
    """**갈래를 본다** — `bpm_process`를 남의 `libs/`에 풀면 진입 정의가 거기서 돌게 된다."""
    upload_lib(center, studio_key, lib_zip(package_id="erp.bot", kind="bpm_process"), tmp_path)
    with pytest.raises(install.InstallFailed, match="공유 BPM 프로세스 패키지가 아닙니다"):
        install.install(workspace, process, reader, package_id="erp.bot", version=LIB_VERSION)
    assert not (process.folder / LIBS_DIR).exists()


def test_a_package_that_is_not_what_we_asked_for_is_refused(tmp_path: Path) -> None:
    """받은 것이 **다른 패키지**면 풀지 않는다 (Center가 엉뚱한 것을 줘도 디스크에 쓰지 않는다)."""
    with pytest.raises(install.InstallFailed, match="받은 패키지가"):
        install.definitions_in(lib_zip(), package_id=LIB_ID, version="9.9.9")


def test_no_open_process_means_no_install(
    workspace: Workspace, reader: services.CenterReader
) -> None:
    """설치는 **BPM 프로세스 하나에** 하는 일이다 (ADR-0048)."""
    with pytest.raises(install.InstallFailed, match="열린 BPM 프로세스가 없습니다"):
        install.install(workspace, None, reader, package_id=LIB_ID, version=LIB_VERSION)


def test_a_lib_with_a_rule_task_says_the_decision_is_missing(
    center: TestClient, studio_key: str, reader: services.CenterReader,
    workspace: Workspace, process: BpmProcess, tmp_path: Path,
) -> None:
    """**결정표는 함께 설치되지 않는다** — 읽는 쪽이 `process/*.dmn`만 글롭한다.

    조용히 두면 「왜 규칙 태스크에서 멈추나」가 된다. 설치는 하고 **그렇게 말한다** (U3).
    """
    with_rule = DEFINITION.format(process_id=CALLED, name="팀장 결재", body=RULE_BODY)
    upload_lib(center, studio_key, lib_zip(files={"process/approve.bpmn": with_rule}), tmp_path)
    done = install.install(workspace, process, reader, package_id=LIB_ID, version=LIB_VERSION)
    assert done.warnings == (install.RULE_WARNING,)
    assert install.RULE_WARNING in done.message


# ─────────────────────────── STU-11 화면 ───────────────────────────


@pytest.fixture
def qt_app() -> Iterator[Any]:
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def test_the_dialog_installs_into_the_open_process(
    qt_app: Any, center: TestClient, studio_key: str, reader: services.CenterReader,
    workspace: Workspace, process: BpmProcess, tmp_path: Path,
) -> None:
    """STU-11 — 고르고 「설치」를 누르면 「설치본」이 채워지고 단추가 「갱신」이 된다."""
    upload_lib(center, studio_key, lib_zip(), tmp_path)
    window = center_resources.CenterResourcesDialog(
        reader, workspace=workspace, process=process
    )
    assert window.libs.table.rowCount() == 1
    window.libs.table.selectRow(0)
    assert window.install_button.isEnabled() and window.install_button.text() == "설치"
    assert not window.remove_button.isEnabled()

    window.install_selected()
    assert LIB_VERSION in window.note.text()
    assert cell(window.libs, 0, center_resources.INSTALLED) == LIB_VERSION
    window.libs.table.selectRow(0)
    assert window.install_button.text() == "갱신"
    assert window.remove_button.isEnabled()


def test_the_dialog_turns_install_off_without_an_open_process(
    qt_app: Any, center: TestClient, studio_key: str, reader: services.CenterReader,
    workspace: Workspace, tmp_path: Path,
) -> None:
    """**끄고 까닭을 적는다** (U3) — 열린 BPM 프로세스가 없으면 읽기만 되는 자리다."""
    upload_lib(center, studio_key, lib_zip(), tmp_path)
    window = center_resources.CenterResourcesDialog(reader, workspace=workspace, process=None)
    window.libs.table.selectRow(0)
    assert not window.install_button.isEnabled()
    assert center_resources.NO_PROCESS in window.install_button.toolTip()


def test_the_toolpack_tab_still_says_why_it_is_off(
    qt_app: Any, reader: services.CenterReader, workspace: Workspace, process: BpmProcess
) -> None:
    """툴팩은 **자리가 아니라 싣는 길**이 없다 (ADR-0048 §왜 툴팩을 가르나)."""
    window = center_resources.CenterResourcesDialog(
        reader, workspace=workspace, process=process
    )
    window.tabs.setCurrentWidget(window.toolpacks)
    window.update_buttons()
    assert not window.install_button.isEnabled()
    assert center_resources.NO_TOOLPACK_INSTALL in window.install_button.toolTip()


def test_a_lib_that_center_no_longer_has_is_local_only(
    reader: services.CenterReader, workspace: Workspace, process: BpmProcess,
    center: TestClient, studio_key: str, tmp_path: Path,
) -> None:
    """설치해 둔 것이 Center에 없으면 **「로컬만」 줄로 남는다** (STU-11) — 제거할 수 있어야 한다."""
    upload_lib(center, studio_key, lib_zip(), tmp_path)
    install.install(workspace, process, reader, package_id=LIB_ID, version=LIB_VERSION)
    after = workspace.read(process.folder, process.group)
    center.delete(f"/api/v1/packages/{LIB_ID}/{LIB_VERSION}", headers=ADMIN)

    found = center_resources.listing(reader, center_resources.KIND_LIB, after)
    assert [(one.package_id, one.status, one.installed) for one in found.rows] == [
        (LIB_ID, center_resources.LOCAL_ONLY, LIB_VERSION)
    ]
