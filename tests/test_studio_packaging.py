"""Studio 패키지 내보내기 (M3 조각 3e-4) — 작업 폴더 → C1 패키지 zip.

거듭 보는 것 넷.

1. **매니페스트는 그림에서 모은다** — 사람이 도구·서비스 앱·결재 종류를 두 번 적지 않는다.
2. **`content_hash`는 받는 쪽이 다시 계산해 맞아야 한다** (C2) — `content_hash_zip`으로 본다.
3. **시험 케이스는 들어가지 않는다** (C1) — 작업 폴더에만 있다.
4. **실행 위치는 처음부터 들어간다** (C1 R1·ADR-0016 — 생략하면 서버).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from chaeksas.contracts.hashing import content_hash_zip
from chaeksas.contracts.manifest import Manifest
from chaeksas.studio.packaging import (
    EXCLUDED,
    MANIFEST_NAME,
    PackageError,
    build_manifest,
    check,
    collect_human,
    collect_requires,
    default_name,
    export,
    gather,
)
from chaeksas.studio.workspace import BpmProcess, Workspace

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"

#: 도구·서비스 앱·결재·DMN이 골고루 들어 있는 예제들.
RECONCILIATION = "bx01_invoice_reconciliation"
CREDIT = "bx06_bulk_credit_check"
EXPENSE = "bx03_expense_approval"


def imported(tmp_path: Path, example: str) -> BpmProcess:
    return Workspace(tmp_path / "작업").ensure().import_example(EXAMPLES, example)


# ─────────────────────────── 그림에서 모으기 ───────────────────────────


def test_the_manifest_is_collected_from_the_drawing(tmp_path: Path) -> None:
    """AI 태스크의 영역·도구가 `requires`로 간다 — 사람이 다시 적지 않는다."""
    found = collect_requires(imported(tmp_path, RECONCILIATION))
    assert found.domains == ["doc"]
    assert "pdf_text_tool" in found.tools and "excel_parser_tool" in found.tools


def test_a_service_app_call_becomes_a_requirement_with_a_key_reference(tmp_path: Path) -> None:
    """**키 값이 아니라 참조 이름**이 간다 (C1 R5 — 패키지에 비밀을 넣지 않는다)."""
    found = collect_requires(imported(tmp_path, CREDIT))
    (app,) = found.service_apps
    assert app.app_id == "ext-credit"
    assert app.operations == ["lookup"]
    assert app.key_ref == "finance-credit"


def test_approvals_say_what_kind_of_human_is_needed(tmp_path: Path) -> None:
    found = collect_human(imported(tmp_path, EXPENSE))
    assert found.approval_center is True


def test_the_run_location_is_in_the_manifest_from_the_start(tmp_path: Path) -> None:
    """생략하면 서버다 (C1 R1·ADR-0016). 「나중에 정한다」가 없다."""
    manifest = build_manifest(imported(tmp_path, EXPENSE))
    assert manifest.run_location in ("pc", "server")
    assert manifest.entry and manifest.process_id


def test_a_timer_start_event_is_a_schedule_trigger(tmp_path: Path) -> None:
    manifest = build_manifest(imported(tmp_path, RECONCILIATION))
    assert [t.kind for t in manifest.triggers] == ["schedule"]


# ─────────────────────────── 무엇이 들어가는가 ───────────────────────────


def test_the_dmn_next_to_the_drawing_goes_in(tmp_path: Path) -> None:
    files = gather(imported(tmp_path, CREDIT))
    assert "process/credit_grade.dmn" in files
    assert f"process/{CREDIT}.bpmn" in files


def test_test_cases_do_not_go_in(tmp_path: Path) -> None:
    """케이스는 작업 폴더에만 있다 (C1) — 배포된 Bot이 시험 입력을 들고 다니지 않는다."""
    made = imported(tmp_path, EXPENSE)
    case_file = made.folder / "cases" / f"{EXPENSE}.cases.json"
    case_file.parent.mkdir(parents=True, exist_ok=True)
    case_file.write_text('{"schema": 1, "cases": []}', encoding="utf-8")

    files = gather(made)
    assert case_file.is_file()
    assert not [name for name in files if name.split("/")[0] in EXCLUDED]


# ─────────────────────────── zip과 해시 ───────────────────────────


def test_the_package_hash_is_what_the_receiving_side_computes(tmp_path: Path) -> None:
    """Center가 `content_hash_zip`으로 다시 계산한다 (C2) — 여기서 맞춰 둔다."""
    made = imported(tmp_path, CREDIT)
    written = export(made, tmp_path / default_name(made))

    with zipfile.ZipFile(written) as zf:
        manifest = Manifest.model_validate_json(zf.read(MANIFEST_NAME))
    assert manifest.content_hash == content_hash_zip(written)


def test_the_manifest_is_readable_utf8_json(tmp_path: Path) -> None:
    """한글 이름이 `\\uXXXX`로 깨져 나가지 않는다 (사람이 읽는 파일이다)."""
    made = imported(tmp_path, EXPENSE)
    written = export(made, tmp_path / default_name(made))
    with zipfile.ZipFile(written) as zf:
        raw = zf.read(MANIFEST_NAME).decode("utf-8")
    assert json.loads(raw)["name"]
    assert "\\u" not in raw


def test_the_name_is_id_and_version(tmp_path: Path) -> None:
    made = imported(tmp_path, EXPENSE)
    assert default_name(made) == f"{made.id}-{made.version}.zip"


def test_export_makes_the_parent_folder(tmp_path: Path) -> None:
    made = imported(tmp_path, EXPENSE)
    written = export(made, tmp_path / "없던" / "폴더" / default_name(made))
    assert written.is_file()


# ─────────────────────────── 막는 것 ───────────────────────────


def test_a_process_without_a_definition_cannot_be_packaged(tmp_path: Path) -> None:
    made = Workspace(tmp_path / "작업").ensure().create("empty-one", name="빈 것")
    with pytest.raises(PackageError, match="진입 정의"):
        export(made, tmp_path / "empty-one.zip")


def test_a_missing_entry_file_blocks_the_export(tmp_path: Path) -> None:
    """매니페스트만 보는 `validate()`는 모르는 것 — 만드는 쪽에서 잡는다."""
    made = imported(tmp_path, EXPENSE)
    manifest = build_manifest(made)
    blocking = [v for v in check(made, manifest, {}) if v.blocks]
    assert blocking and "진입 정의가 패키지에 없다" in blocking[0].message
