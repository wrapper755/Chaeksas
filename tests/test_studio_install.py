"""공유 BPM 프로세스 설치 (STU-11 「설치」, ADR-0048) — 진짜 Center에서 받아 `libs/`에 푼다.

거듭 보는 것 다섯.

1. **자리가 실행기와 같다** — 받은 것이 `libs/*.bpmn`으로 가고, 거기서 **호출이 찾는다**
   (`BpmProcess.processes()`). 그래서 시험 실행·B14와 현장이 **같은 것**을 본다.
2. **편집 대상이 아니다** — `definitions`(탐색기·저장)에는 들어가지 않는다.
3. **내보내기가 판을 붙인다** — `requires.libs`가 C1대로 `<id>@<version>`이다.
4. **갱신은 갈아 치운다** — 옛 판의 파일이 남으면 `libs/*.bpmn`을 글롭하는 쪽이 둘을 읽는다.
5. **결정표도 함께 온다** — 규칙 태스크를 쓰는 lib이 **진짜로 돈다** (Studio·실행기 양쪽).
6. **아무 패키지나 풀지 않는다** — 갈래·id·버전이 받으려던 것과 같아야 한다.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
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

#: 규칙 태스크가 있는 정의 — 결정표가 함께 와야 도는 자리다 (§다섯).
RULE_BODY = (
    '<bpmn:businessRuleTask id="Rule_1" name="등급">'
    '<bpmn:extensionElements><chk:rule>'
    '{"decision": "grade", "input": {"score": "점수"}, "output": {"등급": "grade"}}'
    "</chk:rule></bpmn:extensionElements></bpmn:businessRuleTask>"
)

#: 그 규칙 태스크가 찾는 결정표 (C1 — lib 패키지의 `process/*.dmn`).
DECISION = """<?xml version="1.0" encoding="UTF-8"?>
<dmn:definitions xmlns:dmn="https://www.omg.org/spec/DMN/20191111/MODEL/" id="Defs_grade"
                 name="등급" namespace="urn:chaeksas:test">
  <dmn:decision id="{decision_id}" name="등급">
    <dmn:decisionTable id="DT_grade" hitPolicy="FIRST">
      <dmn:input id="In_0" label="점수">
        <dmn:inputExpression id="InE_0" typeRef="number"><dmn:text>score</dmn:text></dmn:inputExpression>
      </dmn:input>
      <dmn:output id="Out_0" name="grade" typeRef="string" />
      <dmn:rule id="Rule_0">
        <dmn:inputEntry id="R0_I0"><dmn:text>&gt;= 600</dmn:text></dmn:inputEntry>
        <dmn:outputEntry id="R0_O0"><dmn:text>"{high}"</dmn:text></dmn:outputEntry>
      </dmn:rule>
      <dmn:rule id="Rule_1">
        <dmn:inputEntry id="R1_I0"><dmn:text>-</dmn:text></dmn:inputEntry>
        <dmn:outputEntry id="R1_O0"><dmn:text>"위험"</dmn:text></dmn:outputEntry>
      </dmn:rule>
    </dmn:decisionTable>
  </dmn:decision>
</dmn:definitions>
"""


def rule_lib(*, decision_id: str = "grade", high: str = "정상") -> dict[str, str]:
    """규칙 태스크를 쓰는 공유 BPM 프로세스 한 벌 — 정의 + 결정표."""
    return {
        "process/approve.bpmn": DEFINITION.format(
            process_id=CALLED, name="팀장 결재", body=RULE_BODY
        ),
        "process/grade.dmn": DECISION.format(decision_id=decision_id, high=high),
    }


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
    assert done.decisions == 0, "이 lib은 결정표를 쓰지 않는다"
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


def test_a_libs_decision_table_comes_along_and_is_found(
    center: TestClient, studio_key: str, reader: services.CenterReader,
    workspace: Workspace, process: BpmProcess, tmp_path: Path,
) -> None:
    """**결정표도 함께 푼다** (ADR-0048) — 규칙 태스크를 쓰는 lib이 돌아야 한다.

    전에는 정의만 받아 가서 설치해도 그 태스크가 멈췄다(읽는 쪽이 `process/*.dmn`만 봤다).
    """
    upload_lib(center, studio_key, lib_zip(files=rule_lib()), tmp_path)
    done = install.install(workspace, process, reader, package_id=LIB_ID, version=LIB_VERSION)

    assert done.decisions == 1
    assert "결정표 1개" in done.message
    assert [one for one in done.lib.files if one.endswith(".dmn")], "기록이 결정표도 들고 있다"

    after = workspace.read(process.folder, process.group)
    assert "grade" in after.decisions(), "규칙 태스크가 찾을 자리에 있다"


def test_my_own_decision_wins_over_a_libs(
    center: TestClient, studio_key: str, reader: services.CenterReader,
    workspace: Workspace, process: BpmProcess, tmp_path: Path,
) -> None:
    """**내 것이 이긴다** — 같은 결정 id면 내 `process/`를 쓴다 (`processes()`와 같은 결)."""
    upload_lib(center, studio_key, lib_zip(files=rule_lib(high="lib의 것")), tmp_path)
    install.install(workspace, process, reader, package_id=LIB_ID, version=LIB_VERSION)
    (process.folder / "process" / "grade.dmn").write_text(
        DECISION.format(decision_id="grade", high="내 것"), encoding="utf-8"
    )

    after = workspace.read(process.folder, process.group)
    found = after.decisions()["grade"]
    assert found.rules[0].values == ("내 것",)


def test_the_runner_reads_the_same_two_places(
    center: TestClient, studio_key: str, reader: services.CenterReader,
    workspace: Workspace, process: BpmProcess, tmp_path: Path,
) -> None:
    """**실행기도 `libs/`를 읽는다** — 한쪽만 고치면 「Studio에서는 되는데 현장에서 안 된다」다.

    내보낸 패키지를 **실행기 쪽 코드로** 읽어 본다 (`bot_ui.runner_main.Package`).
    """
    from chaeksas.bot_ui.runner_main import Package

    upload_lib(center, studio_key, lib_zip(files=rule_lib()), tmp_path)
    install.install(workspace, process, reader, package_id=LIB_ID, version=LIB_VERSION)
    after = workspace.read(process.folder, process.group)

    made = packaging.export(after, tmp_path / "out.zip")
    unpacked = tmp_path / "installed"
    with zipfile.ZipFile(made) as archive:
        archive.extractall(unpacked)

    package = Package.read(unpacked)
    assert "grade" in package.decisions(), "현장에서도 규칙 태스크가 결정을 찾는다"
    assert CALLED in package.processes(), "호출 대상도 그대로다"


# ─────────────────────────── STU-11 화면 ───────────────────────────
#
# **창에는 진짜 Center를 붙이지 않는다.** `center_resources.py`가 「담는 것」을 Qt 없이
# 시험하도록 갈라 둔 그 결이고(그 파일의 §담는 것), 여기에는 까닭이 하나 더 있다 — Qt가 떠
# 있는 채로 `TestClient`를 들고 있으면 anyio 포털 스레드와 QtWebEngine 스레드가 같은
# 프로세스에 쌓여 **ubuntu x86_64 CI에서 실행이 통째로 죽었다**(SIGSEGV, 돌던 시험과
# 무관한 자리에서). 위의 설치 시험들이 **진짜 Center로** 그 길을 이미 다 본다.


class FakeReader(services.CenterReader):
    """목록과 패키지 파일을 **메모리에서** 주는 읽기 전용 클라이언트 (스레드가 없다)."""

    def __init__(self, packages: dict[tuple[str, str], bytes]) -> None:
        super().__init__(base_url="http://center.test", api_key="k")
        self.files = packages

    def packages(self, kind: str) -> list[Any]:
        from chaeksas.contracts.center_api import PackageInfo
        from chaeksas.contracts.manifest import Manifest

        out = []
        for (package_id, version), raw in sorted(self.files.items()):
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                manifest = Manifest.model_validate_json(archive.read("manifest.json"))
            if manifest.kind != kind:
                continue
            out.append(
                PackageInfo(
                    id=package_id,
                    version=version,
                    kind=manifest.kind,
                    name=manifest.name,
                    status="approved",
                    content_hash=manifest.content_hash,
                    uploaded_by="studio-key",
                    uploaded_at="2026-10-12T09:00:00+09:00",
                    manifest=manifest,
                )
            )
        return out

    def package_zip(self, package_id: str, version: str) -> bytes:
        found = self.files.get((package_id, version))
        if found is None:
            raise services.CenterUnreachable("Center가 404로 답했습니다")
        return found


@pytest.fixture
def qt_app() -> Iterator[Any]:
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@contextmanager
def dialog(**extra: Any) -> Iterator[Any]:
    """창 하나를 열고 **반드시 닫는다** — 뒤 시험이 도는 중에 Qt 객체가 죽으면 안 된다."""
    window = center_resources.CenterResourcesDialog(**extra)
    try:
        yield window
    finally:
        window.close()
        window.deleteLater()


def test_the_dialog_installs_into_the_open_process(
    qt_app: Any, workspace: Workspace, process: BpmProcess
) -> None:
    """STU-11 — 고르고 「설치」를 누르면 「설치본」이 채워지고 단추가 「갱신」이 된다."""
    reader = FakeReader({(LIB_ID, LIB_VERSION): lib_zip()})
    with dialog(reader=reader, workspace=workspace, process=process) as window:
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

    # 디스크가 원본이다 — 창이 아니라 작업 폴더에 남는다.
    assert [one.ref for one in workspace.read(process.folder, process.group).libs] == [
        f"{LIB_ID}@{LIB_VERSION}"
    ]


def test_the_dialog_turns_install_off_without_an_open_process(
    qt_app: Any, workspace: Workspace
) -> None:
    """**끄고 까닭을 적는다** (U3) — 열린 BPM 프로세스가 없으면 읽기만 되는 자리다."""
    reader = FakeReader({(LIB_ID, LIB_VERSION): lib_zip()})
    with dialog(reader=reader, workspace=workspace, process=None) as window:
        window.libs.table.selectRow(0)
        assert not window.install_button.isEnabled()
        assert center_resources.NO_PROCESS in window.install_button.toolTip()


def test_the_toolpack_tab_still_says_why_it_is_off(
    qt_app: Any, workspace: Workspace, process: BpmProcess
) -> None:
    """툴팩은 **자리가 아니라 싣는 길**이 없다 (ADR-0048 §왜 툴팩을 가르나)."""
    with dialog(reader=FakeReader({}), workspace=workspace, process=process) as window:
        window.tabs.setCurrentWidget(window.toolpacks)
        window.update_buttons()
        assert not window.install_button.isEnabled()
        assert center_resources.NO_TOOLPACK_INSTALL in window.install_button.toolTip()


def test_a_lib_that_center_no_longer_has_is_local_only(
    workspace: Workspace, process: BpmProcess
) -> None:
    """설치해 둔 것이 Center에 없으면 **「로컬만」 줄로 남는다** (STU-11) — 제거할 수 있어야 한다."""
    reader = FakeReader({(LIB_ID, LIB_VERSION): lib_zip()})
    install.install(workspace, process, reader, package_id=LIB_ID, version=LIB_VERSION)
    after = workspace.read(process.folder, process.group)

    gone = FakeReader({})  # Center에서 지워졌다
    found = center_resources.listing(gone, center_resources.KIND_LIB, after)
    assert [(one.package_id, one.status, one.installed) for one in found.rows] == [
        (LIB_ID, center_resources.LOCAL_ONLY, LIB_VERSION)
    ]


# ─────────── 진짜로 도나 (엔진) ───────────
#
# 설치가 「파일을 옮겼다」로 끝나면 안 된다 — **규칙 태스크가 결정을 찾아 도는지**를 엔진으로
# 본다. Qt도 Center도 끼우지 않는다 (가짜 읽기 클라이언트 + 엔진).

RULE_FLOW = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="{process_id}" name="등급 매기기">
    <bpmn:extensionElements>
      <chk:process>{{"inputs": [{{"name": "점수", "type": "number"}}]}}</chk:process>
    </bpmn:extensionElements>
    <bpmn:startEvent id="Start_1"/>
    <bpmn:businessRuleTask id="Rule_1" name="등급">
      <bpmn:extensionElements><chk:rule>
        {{"decision": "grade", "input": {{"score": "점수"}}, "output": {{"등급": "grade"}}}}
      </chk:rule></bpmn:extensionElements>
    </bpmn:businessRuleTask>
    <bpmn:endEvent id="End_1"/>
    <bpmn:sequenceFlow id="f1" sourceRef="Start_1" targetRef="Rule_1" />
    <bpmn:sequenceFlow id="f2" sourceRef="Rule_1" targetRef="End_1" />
  </bpmn:process>
</bpmn:definitions>
"""

CALLER_WITH_INPUT = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="Proc_main" name="주문">
    <bpmn:extensionElements>
      <chk:process>{{"inputs": [{{"name": "점수", "type": "number"}}]}}</chk:process>
    </bpmn:extensionElements>
    <bpmn:startEvent id="Start_1"/>
    <bpmn:callActivity id="Call_1" name="등급" calledElement="{called}">
      <bpmn:extensionElements>
        <chk:call>{{"input": {{"점수": "점수"}}, "output": {{}}}}</chk:call>
      </bpmn:extensionElements>
    </bpmn:callActivity>
    <bpmn:endEvent id="End_1"/>
    <bpmn:sequenceFlow id="f1" sourceRef="Start_1" targetRef="Call_1" />
    <bpmn:sequenceFlow id="f2" sourceRef="Call_1" targetRef="End_1" />
  </bpmn:process>
</bpmn:definitions>
"""


def run_it(found: BpmProcess) -> Any:
    """진입 정의를 끝까지 민다 — `RunEnv`는 **작업 폴더가 주는 것**이다 (시험 실행과 같은 둘)."""
    from chaeksas.core.engine import Engine, RunEnv
    from chaeksas.core.run_log import RunLog

    entry = found.definitions[0].process
    assert entry is not None
    engine = Engine()
    log = RunLog(run_id="test_20261012_090000_abc123")
    run = engine.start(
        entry,
        run_id=log.run_id,
        log=log,
        now=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
        env=RunEnv(processes=found.processes(), decisions=found.decisions()),
        inputs={"점수": 700},
    )
    return engine.run_until_blocked(run), run


def test_a_rule_task_inside_a_lib_really_runs(workspace: Workspace) -> None:
    """**설치하면 lib의 규칙 태스크가 돈다** (ADR-0048) — 결정표가 함께 왔기 때문이다."""
    from chaeksas.core.run_state import State

    made = workspace.create("erp.grade", name="등급")
    workspace.save_definition(made, "main.bpmn", CALLER_WITH_INPUT.format(called=CALLED))
    process = workspace.read(made.folder, made.group)
    reader = FakeReader(
        {
            (LIB_ID, LIB_VERSION): lib_zip(
                files={
                    "process/approve.bpmn": RULE_FLOW.format(process_id=CALLED),
                    "process/grade.dmn": DECISION.format(decision_id="grade", high="정상"),
                }
            )
        }
    )
    install.install(workspace, process, reader, package_id=LIB_ID, version=LIB_VERSION)

    state, run = run_it(workspace.read(made.folder, made.group))
    assert state is State.DONE, run.error
    assert run.error is None


def test_without_the_decision_table_the_rule_task_fails(workspace: Workspace) -> None:
    """**결정표가 빠지면 멈춘다** — 이 시험이 위의 시험이 공짜가 아님을 말해 준다.

    결정표만 지우고 같은 그림을 돌린다 (전에는 설치가 늘 이 꼴이었다).
    """
    from chaeksas.core.run_state import State

    made = workspace.create("erp.grade", name="등급")
    workspace.save_definition(made, "main.bpmn", CALLER_WITH_INPUT.format(called=CALLED))
    process = workspace.read(made.folder, made.group)
    reader = FakeReader(
        {
            (LIB_ID, LIB_VERSION): lib_zip(
                files={
                    "process/approve.bpmn": RULE_FLOW.format(process_id=CALLED),
                    "process/grade.dmn": DECISION.format(decision_id="grade", high="정상"),
                }
            )
        }
    )
    done = install.install(workspace, process, reader, package_id=LIB_ID, version=LIB_VERSION)
    for name in done.lib.files:
        if name.endswith(".dmn"):
            (process.folder / LIBS_DIR / name).unlink()

    state, run = run_it(workspace.read(made.folder, made.group))
    assert state is not State.DONE
    assert run.error is not None
