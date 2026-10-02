"""계약 모델의 호환 규칙과 검사 규칙.

여기서 지키는 것은 대부분 **프로토타입에서 실제로 났던 사고**다 (계약 README "이미 알려진 결함").
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from chaeksas.contracts import (
    Built,
    HeartbeatRequest,
    HumanNeeds,
    Manifest,
    Queue,
    Requires,
    RunEvent,
    ServiceAppNeed,
    TaskTypeNeed,
    ToolpackRef,
    WorkerState,
    missing_data_keys,
    validate,
)

HASH = "sha256:" + "ab" * 32
TS = "2026-10-01T10:00:00+09:00"


def manifest(**over: Any) -> Manifest:
    """최소한으로 올바른 bpm_process 매니페스트."""
    base: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": "finance.invoice-issue",
        "version": "1.0.0",
        "entry": "process/main.bpmn",
        "process_id": "invoice_issue",
        "requires": {},
        "human": {},
        "built": {"by": "studio", "at": TS, "core": "0.3.0", "spec_version": 1},
        "content_hash": HASH,
    }
    return Manifest.model_validate(base | over)


def event(**over: Any) -> RunEvent:
    base: dict[str, Any] = {
        "schema": 1,
        "run_id": "run_20261001_101500_a1b2c3",
        "seq": 1,
        "ts": TS,
        "kind": "log",
        "data": {"level": "info", "message": "x"},
    }
    return RunEvent.model_validate(base | over)


# ─────────────── 호환 규칙 (README 원칙 2~4) ───────────────


def test_unknown_optional_field_is_kept_not_rejected() -> None:
    """원칙 3 — 모르는 선택 필드는 거부하지 않고 **보관**한다."""
    e = RunEvent.model_validate(
        {"schema": 1, "run_id": "run_20261001_101500_a1b2c3", "seq": 1, "ts": TS,
         "kind": "log", "data": {"level": "info", "message": "x"}, "future_field": {"a": 1}}
    )
    assert e.to_json_dict()["future_field"] == {"a": 1}


def test_higher_schema_is_rejected() -> None:
    """원칙 2 — 더 높은 schema는 거부한다 (아는 필드의 뜻이 바뀌었을 수 있다)."""
    with pytest.raises(ValidationError, match="모르는"):
        event(schema=2)


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RunEvent.model_validate({"schema": 1, "seq": 1, "ts": TS, "kind": "log"})  # run_id 없음


def test_json_key_is_schema_not_schema_version() -> None:
    assert "schema" in event().to_json_dict()
    assert "schema_version" not in event().to_json_dict()


def test_naive_timestamp_is_rejected() -> None:
    """시간대 없는 시각은 받지 않는다 (PC와 서버의 시간대가 다르다)."""
    with pytest.raises(ValidationError, match="시간대"):
        event(ts="2026-10-01T10:00:00")


def test_bad_run_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        event(run_id="run_1")


def test_studio_test_run_id_is_accepted() -> None:
    assert event(run_id="test_20261001_101500_a1b2c3").run_id.startswith("test_")


# ─────────────── C3: kind는 열린 문자열 ───────────────


def test_unknown_event_kind_is_accepted() -> None:
    """모르는 `kind` 하나를 거부하면 seq가 단조라서 그 실행의 기록이 영원히 막힌다."""
    e = event(kind="something_new_in_v2", data={})
    assert e.kind == "something_new_in_v2"
    assert missing_data_keys(e) == []  # 모르는 종류는 data를 검사하지 않는다


def test_known_kind_missing_data_keys_are_reported() -> None:
    e = event(kind="run_finished", data={"status": "success"})
    assert missing_data_keys(e) == [
        "ai_tasks", "duration_s", "human_requests", "replayed_tasks", "service_calls", "ui_tasks"
    ]


def test_known_kind_with_all_keys_passes() -> None:
    e = event(
        kind="run_finished",
        data={"status": "success", "duration_s": 12, "ai_tasks": 1, "replayed_tasks": 0,
              "ui_tasks": 0, "service_calls": 2, "human_requests": 0},
    )
    assert missing_data_keys(e) == []


# ─────────────── C4: 열린 상태 값, 실행 자리 1건 ───────────────


def heartbeat(**over: Any) -> HeartbeatRequest:
    base: dict[str, Any] = {
        "schema": 1,
        "status": "idle",
        "current_run": None,
        "queue": {"max": 20, "items": []},
        "worker": {"state": "off", "version": "0.3.0", "restarts": 0, "session": "idle"},
    }
    return HeartbeatRequest.model_validate(base | over)


def test_unknown_status_does_not_reject_the_heartbeat() -> None:
    """프로토타입 결함 — 상태 값이 닫힌 목록이라 모르는 상태 하나로 하트비트 전체가 422였다."""
    assert heartbeat(status="updating_itself").status == "updating_itself"
    assert heartbeat(worker={"state": "weird", "restarts": 0}).worker.state == "weird"


def test_current_run_cannot_hold_two_runs() -> None:
    """ADR-0014를 계약으로 강제한다 — 단일 객체라 2건을 표현할 수 없다."""
    with pytest.raises(ValidationError):
        heartbeat(current_run=[{"run_id": "a"}, {"run_id": "b"}])


def test_current_run_is_required_but_may_be_null() -> None:
    assert heartbeat().current_run is None
    with pytest.raises(ValidationError):
        HeartbeatRequest.model_validate(
            {"schema": 1, "status": "idle", "queue": {"max": 20}, "worker": {"state": "off"}}
        )


def test_queue_and_worker_are_required() -> None:
    assert Queue(max=20).items == []
    assert WorkerState(state="off").restarts == 0


# ─────────────── C1: 검사 규칙 ───────────────


def test_run_location_defaults_to_server() -> None:
    """서버 우선 (ADR-0016). 생략하면 server로 읽는다."""
    assert manifest().run_location == "server"
    assert validate(manifest()) == []


def test_r1_missing_entry_is_caught() -> None:
    m = Manifest.model_validate(
        {"schema": 1, "kind": "bpm_process", "id": "a", "version": "1.0.0", "requires": {},
         "human": {}, "built": {"by": "studio", "at": TS, "core": "0.3.0", "spec_version": 1},
         "content_hash": HASH}
    )
    v = validate(m)
    assert [x.rule for x in v] == ["R1"]
    assert v[0].items == ["entry", "process_id"]


def test_r1_run_location_on_toolpack_is_caught() -> None:
    m = Manifest.model_validate(
        {"schema": 1, "kind": "toolpack", "id": "a", "version": "1.0.0", "run_location": "pc",
         "requires": {}, "human": {}, "built": {"by": "studio", "at": TS, "core": "0.3.0", "spec_version": 1},
         "content_hash": HASH}
    )
    assert [x.rule for x in validate(m)] == ["R1"]


def test_r2_server_with_pc_only_things_is_caught() -> None:
    m = manifest(
        run_location="server",
        requires=Requires(
            domains=["llm", "web"],
            task_types=[TaskTypeNeed(id="ui_task", extension="ui-automation", run_locations=["pc"])],
        ),
        human=HumanNeeds(approval_field=True, confirmation=True),
    )
    v = validate(m)
    assert len(v) == 1
    assert v[0].code == "server_incompatible"
    assert v[0].items == ["domains:web", "task_types:ui_task", "human.approval_field", "human.confirmation"]


def test_r2_pc_location_allows_everything() -> None:
    m = manifest(
        run_location="pc",
        requires=Requires(domains=["desktop"], task_types=[
            TaskTypeNeed(id="ui_task", extension="ui-automation", run_locations=["pc"])]),
        human=HumanNeeds(approval_field=True, confirmation=True),
    )
    assert validate(m) == []


def test_r3_needs_lib_locations_and_is_skipped_without_them() -> None:
    m = manifest(run_location="server", requires=Requires(libs=["shared.pc-helper@1.0.0"]))
    assert validate(m) == []  # 라이브러리 실행 위치를 모르면 건너뛴다
    v = validate(m, lib_locations={"shared.pc-helper@1.0.0": "pc"})
    assert [x.code for x in v] == ["delegation_not_supported"]


def test_r4_key_ref_with_underscore_is_caught() -> None:
    """규칙상 `_`가 없으므로 키 값(`chk_ctr_…`)이 키 참조 자리에 들어갈 수 없다."""
    m = manifest(requires=Requires(service_apps=[
        ServiceAppNeed(app_id="tax-invoice", operations=["issue"], key_ref="chk_ctr_secret_value")]))
    v = validate(m)
    assert [x.code for x in v] == ["invalid_key_ref"]
    assert v[0].items == ["chk_ctr_secret_value"]


def test_r4_checks_task_key_refs_too() -> None:
    m = manifest(requires=Requires(service_apps=[
        ServiceAppNeed(app_id="a", operations=["x"], key_ref="ok-ref", task_key_refs=["Bad Ref"])]))
    assert validate(m)[0].items == ["Bad Ref"]


def test_r6_hash_mismatch_is_caught_only_when_computed() -> None:
    m = manifest()
    assert validate(m) == []
    v = validate(m, computed_hash="sha256:" + "cd" * 32)
    assert [x.code for x in v] == ["hash_mismatch"]


def test_r7_empty_toolpack_hash_is_caught() -> None:
    m = manifest(requires=Requires(toolpacks=[ToolpackRef(id="tp", version="1.0.0", content_hash="")]))
    assert [x.rule for x in validate(m)] == ["R7"]


def test_bad_semver_and_id_are_rejected_by_the_type() -> None:
    with pytest.raises(ValidationError):
        manifest(version="1.0")
    with pytest.raises(ValidationError):
        manifest(id="Finance.Invoice")  # 대문자


def test_content_hash_must_be_full_sha256() -> None:
    with pytest.raises(ValidationError):
        manifest(content_hash="sha256:abc")


def test_built_at_requires_timezone() -> None:
    with pytest.raises(ValidationError, match="시간대"):
        manifest(built=Built.model_validate(
            {"by": "studio", "at": "2026-10-01T10:00:00", "core": "0.3.0", "spec_version": 1}))


# ─────────────── 생성물 ───────────────


def test_generated_json_schemas_are_current() -> None:
    """모델을 고치고 `scripts/gen_schemas.py`를 다시 돌리지 않으면 여기가 깨진다 (원칙 5)."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, str(root / "scripts" / "gen_schemas.py"), "--check"],
        capture_output=True, text=True, cwd=root,
    )
    assert r.returncode == 0, f"스키마가 모델과 다르다 — gen_schemas.py를 다시 돌려라\n{r.stdout}{r.stderr}"
