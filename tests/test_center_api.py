"""C5 Center API — 패키지·배포·작업의 모양과 검사.

배포 검사는 C1(매니페스트)·C2(봉투)와 맞물리므로, 여기서 세 계약이 함께 도는지도 본다.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from chaeksas.contracts import (
    DEPLOYMENT_REFUSAL_STATUS,
    ENVELOPE_REFUSAL_STATUS,
    AdminKey,
    JobCreateRequest,
    JobInfo,
    JobTarget,
    ListParams,
    PackageInfo,
    cancel_outcome,
    deployment_refusal,
    key_id_for,
    sign,
    validate_deployment,
    validate_job_create,
)

NOW = "2026-10-01T12:00:00+09:00"
HASH = "sha256:" + "41" * 32
OTHER_HASH = "sha256:" + "99" * 32


def admin() -> tuple[Ed25519PrivateKey, AdminKey]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    return private, AdminKey(key_id=key_id_for(public), public_key=base64.b64encode(public).decode("ascii"))


def package(**over: Any) -> PackageInfo:
    base: dict[str, Any] = {
        "id": "erp.order-entry",
        "version": "2.1.0",
        "kind": "bpm_process",
        "run_location": "pc",
        "status": "approved",
        "content_hash": HASH,
        "uploaded_by": "studio-key",
        "uploaded_at": NOW,
    }
    return PackageInfo.model_validate(base | over)


def deployment_envelope(private: Ed25519PrivateKey, **over: Any) -> Any:
    payload: dict[str, Any] = {
        "kind": "deployment",
        "deployment_id": "dep_3f9a1c07",
        "target": {"type": "bot_ui", "id": "bui_a81c22d0"},
        "bpm_process_id": "erp.order-entry",
        "version": "2.1.0",
        "content_hash": HASH,
    }
    return sign(payload | over, private, signed_at=NOW)


def job(**over: Any) -> JobCreateRequest:
    base: dict[str, Any] = {
        "bpm_process_id": "erp.order-entry",
        "target": {"type": "bot_ui", "id": "bui_a81c22d0"},
        "inputs": {"주문번호": "PO-2608-001"},
    }
    return JobCreateRequest.model_validate(base | over)


# ─────────────── 배포 검사 (C1 + C2 + C5) ───────────────


def test_valid_deployment_passes() -> None:
    private, key = admin()
    env = deployment_envelope(private)
    assert validate_deployment(env, package=package(), keys=[key], now=NOW) == []


def test_unapproved_package_is_refused() -> None:
    private, key = admin()
    env = deployment_envelope(private)
    codes = [v.code for v in validate_deployment(env, package=package(status="candidate"), keys=[key], now=NOW)]
    assert codes == ["not_approved"]
    codes = [v.code for v in validate_deployment(env, package=package(status="revoked"), keys=[key], now=NOW)]
    assert codes == ["not_approved"]


def test_deprecated_package_is_refused_with_its_own_code() -> None:
    private, key = admin()
    env = deployment_envelope(private)
    codes = [v.code for v in validate_deployment(env, package=package(status="deprecated"), keys=[key], now=NOW)]
    assert codes == ["deprecated"]


def test_hash_must_match_the_package() -> None:
    private, key = admin()
    env = deployment_envelope(private, content_hash=OTHER_HASH)
    codes = [v.code for v in validate_deployment(env, package=package(), keys=[key], now=NOW)]
    assert codes == ["hash_mismatch"]


def test_target_type_must_match_run_location() -> None:
    """PC 패키지를 서버 실행기에 배포하거나 그 반대를 막는다.

    **코드는 `wrong_target` 하나다** (ADR-0047) — C2 V6이 같은 조건에 쓰는 이름이고 Center가
    답하는 이름이다. `target_mismatch`는 **작업 쪽**(모르는 대상 종류)에만 남는다.
    """
    private, key = admin()
    env = deployment_envelope(private, target={"type": "server_runner", "id": "srv_1"})
    codes = [v.code for v in validate_deployment(env, package=package(run_location="pc"), keys=[key], now=NOW)]
    assert codes == ["wrong_target", "server_runner_not_available"]

    env = deployment_envelope(private)  # bot_ui 대상
    codes = [v.code for v in validate_deployment(env, package=package(run_location="server"), keys=[key], now=NOW)]
    assert codes == ["wrong_target"]


def test_a_pc_deployment_cannot_target_everything() -> None:
    """**`"*"`는 서버 실행기만** (C2 §배포 대상 규칙, ADR-0046).

    `DeploymentTarget.matches`가 그렇게 맞추니 PC 쪽 `"*"`는 **모든 PC가 V6으로 거부할** 봉투다.
    받아 두면 CON-03이 거짓 ⛔로 차고 운영자는 승인·해시·키를 뒤진다(막은 것은 대상인데).
    """
    private, key = admin()
    env = deployment_envelope(private, target={"type": "bot_ui", "id": "*"})
    codes = [v.code for v in validate_deployment(env, package=package(), keys=[key], now=NOW)]
    assert codes == ["wrong_target"]

    # PC를 하나 적으면 통과한다 — 막는 것은 `"*"`뿐이다.
    one = deployment_envelope(private, target={"type": "bot_ui", "id": "bui_a81c22d0"})
    assert validate_deployment(one, package=package(), keys=[key], now=NOW) == []


def test_an_unregistered_target_is_refused() -> None:
    """**등록되지 않은 PC에는 배포하지 않는다** (ADR-0049) — 404 `target_not_found`.

    찾아보는 것은 Center이고 여기로는 **이미 읽어 온 사실**이 온다 (`package`와 같은 결,
    ADR-0047 §다시 볼 조건 ②). 등록 전에는 `bot_ui_id`가 없으니(Center가 등록에서 만든다)
    명부에 없는 id는 **미리 배포해 둔 것이 아니라 오타**다.
    """
    private, key = admin()
    env = deployment_envelope(private)
    codes = [
        v.code
        for v in validate_deployment(
            env, package=package(), keys=[key], now=NOW, target_registered=False
        )
    ]
    assert codes == ["target_not_found"]

    assert (
        validate_deployment(env, package=package(), keys=[key], now=NOW, target_registered=True) == []
    )
    # **`None`은 「묻지 않았다」**다 — 찾아볼 표가 없는 대상 종류를 없는 규칙으로 막지 않는다.
    assert (
        validate_deployment(env, package=package(), keys=[key], now=NOW, target_registered=None) == []
    )


def test_a_wrong_target_wins_over_a_missing_one() -> None:
    """**「대상이 틀렸다」가 「대상이 없다」를 이긴다** (ADR-0049).

    PC 배포의 `"*"`는 그 id도 등록되어 있지 않지만, 운영자가 할 일은 「대상을 하나 적는다」다 —
    「`*`라는 PC가 없다」고 하면 없는 PC를 찾아 헤맨다.
    """
    private, key = admin()
    env = deployment_envelope(private, target={"type": "bot_ui", "id": "*"})
    problems = validate_deployment(
        env, package=package(), keys=[key], now=NOW, target_registered=False
    )
    assert [v.code for v in problems] == ["wrong_target", "target_not_found"]
    picked = deployment_refusal(problems)
    assert picked is not None
    assert (picked[0], picked[1].code) == (409, "wrong_target")


def test_server_deployment_is_refused_until_m7() -> None:
    private, key = admin()
    env = deployment_envelope(private, target={"type": "server_runner", "id": "*"})
    pkg = package(run_location="server")
    codes = [v.code for v in validate_deployment(env, package=pkg, keys=[key], now=NOW)]
    assert codes == ["server_runner_not_available"]
    # M7에서 켜면 통과한다
    assert validate_deployment(env, package=pkg, keys=[key], now=NOW, server_runner_available=True) == []


def test_every_deployment_rule_has_a_status_in_the_table() -> None:
    """**규칙과 상태 표가 맞물린다** (ADR-0047, C5 §오류).

    상태를 고르는 자리가 `deployment_refusal()` 하나이므로, 규칙을 더하고
    `DEPLOYMENT_REFUSAL_STATUS`에 적지 않으면 그 함수가 409로 **어림한다**. 어림이 문서의 표와
    갈라지는 것이 이 작업에서 고친 바로 그 병이라 여기서 막는다.
    """
    private, key = admin()
    tried = (
        (deployment_envelope(private), package(status="candidate"), None),
        (deployment_envelope(private), package(status="deprecated"), None),
        (deployment_envelope(private, content_hash=OTHER_HASH), package(), None),
        (deployment_envelope(private, target={"type": "bot_ui", "id": "*"}), package(), None),
        (deployment_envelope(private), package(run_location="server"), None),
        (deployment_envelope(private, target={"type": "server_runner", "id": "srv_1"}),
         package(run_location="server"), None),
        (deployment_envelope(private), package(), False),
    )
    found = {
        v.code
        for env, pkg, registered in tried
        for v in validate_deployment(
            env, package=pkg, keys=[key], now=NOW, target_registered=registered
        )
        if v.rule == "C5"
    }
    assert found == set(DEPLOYMENT_REFUSAL_STATUS), "규칙과 표가 어긋났다"


def test_the_contract_picks_the_status_not_the_caller() -> None:
    """상태는 **계약이** 고른다 (`cancel_outcome`과 같은 결) — 부르는 쪽이 고르면 표와 갈라진다.

    배포 규칙은 **상태 충돌이라 409**, 봉투·시간(C2 `V…`)은 403, 「아직 없는 기능」은 422다.
    """
    private, key = admin()
    assert deployment_refusal([]) is None

    picked = deployment_refusal(validate_deployment(
        deployment_envelope(private), package=package(status="candidate"), keys=[key], now=NOW
    ))
    assert picked is not None
    assert (picked[0], picked[1].code) == (409, "not_approved")

    env = deployment_envelope(private, target={"type": "server_runner", "id": "srv_1"})
    picked = deployment_refusal(validate_deployment(
        env, package=package(run_location="server"), keys=[key], now=NOW
    ))
    assert picked is not None
    assert (picked[0], picked[1].code) == (422, "server_runner_not_available")

    # **봉투가 틀린 것이 먼저다** — 키가 거부됐는데 「승인되지 않았다」고 하면 엉뚱한 곳을 뒤진다.
    other, _ = admin()
    picked = deployment_refusal(validate_deployment(
        deployment_envelope(other), package=package(status="candidate"), keys=[key], now=NOW
    ))
    assert picked is not None
    assert picked[0] == ENVELOPE_REFUSAL_STATUS
    assert picked[1].rule.startswith("V")


def test_scheduled_deployment_is_accepted_but_expired_is_not() -> None:
    """Center는 예약 배포(`not_before` 미래)를 받아 둔다. 만료된 것은 받지 않는다."""
    private, key = admin()
    future = deployment_envelope(private, not_before="2026-12-01T00:00:00+09:00")
    assert validate_deployment(future, package=package(), keys=[key], now=NOW) == []

    expired = deployment_envelope(private, expires_at="2026-09-30T23:59:59+09:00")
    codes = [v.code for v in validate_deployment(expired, package=package(), keys=[key], now=NOW)]
    assert codes == ["expired"]


def test_bad_signature_is_caught_before_anything_else_matters() -> None:
    private, key = admin()
    env = deployment_envelope(private)
    tampered = env.model_copy(
        update={"payload": env.payload | {"target": {"type": "bot_ui", "id": "bui_attacker"}}}
    )
    codes = [v.code for v in validate_deployment(tampered, package=package(), keys=[key], now=NOW)]
    assert "bad_signature" in codes


def test_wrong_kind_envelope_is_caught() -> None:
    private, key = admin()
    approval = sign({"kind": "package", "id": "x", "version": "1.0.0", "content_hash": HASH},
                    private, signed_at=NOW)
    codes = [v.code for v in validate_deployment(approval, package=package(), keys=[key], now=NOW)]
    assert "wrong_kind" in codes


# ─────────────── 작업 ───────────────


def test_bot_ui_target_requires_an_id() -> None:
    """어느 PC인지 Center가 고를 수 없다."""
    with pytest.raises(ValidationError, match="id가 필요하다"):
        JobTarget(type="bot_ui")


def test_server_runner_target_may_omit_the_id() -> None:
    assert JobTarget(type="server_runner").id is None
    assert JobTarget(type="server_runner", id="*").id == "*"


def test_note_length_is_capped() -> None:
    assert job(note="x" * 500).note is not None
    with pytest.raises(ValidationError):
        job(note="x" * 501)


def test_inputs_must_be_an_object() -> None:
    with pytest.raises(ValidationError):
        job(inputs=["not", "an", "object"])


def test_requested_by_is_not_taken_from_the_body() -> None:
    """행위자는 키 이름이나 X-CHK-Actor 헤더로 Center가 채운다 — 본문의 값은 신원이 아니다."""
    req = job(requested_by="사칭")
    assert "requested_by" not in JobCreateRequest.model_fields
    assert req.to_json_dict()["requested_by"] == "사칭"  # 보관은 하지만 모델 필드가 아니다


def test_job_info_carries_center_side_state() -> None:
    info = JobInfo.model_validate(
        job().to_json_dict()
        | {"job_id": "job_8f3e0011", "requested_by": "콘솔:kim", "requested_at": NOW,
           "state": "queued", "state_reason": "global_limit", "queue_position": 2}
    )
    assert info.state == "queued"
    assert info.cancel_requested is False
    assert info.run_status is None


def test_unknown_job_state_is_accepted() -> None:
    """상태는 열린 문자열 — 콘솔은 모르는 값을 그대로 보인다."""
    info = JobInfo.model_validate(
        job().to_json_dict()
        | {"job_id": "job_8f3e0011", "requested_by": "x", "requested_at": NOW, "state": "something_new"}
    )
    assert info.state == "something_new"


def test_bad_job_id_is_refused() -> None:
    with pytest.raises(ValidationError):
        JobInfo.model_validate(
            job().to_json_dict() | {"job_id": "8f3e", "requested_by": "x", "requested_at": NOW, "state": "pending"}
        )


# ─────────────── 작업 검사 ───────────────


def test_job_without_deployment_is_refused() -> None:
    assert [v.code for v in validate_job_create(job(), deployed_versions=[])] == ["no_deployment"]


def test_version_may_be_omitted_when_only_one_is_deployed() -> None:
    assert validate_job_create(job(), deployed_versions=["2.1.0"]) == []


def test_version_ambiguous_when_two_are_deployed() -> None:
    v = validate_job_create(job(), deployed_versions=["2.1.0", "2.2.0"])
    assert [x.code for x in v] == ["version_ambiguous"]
    assert v[0].items == ["2.1.0", "2.2.0"]


def test_explicit_version_must_be_deployed() -> None:
    assert validate_job_create(job(version="2.1.0"), deployed_versions=["2.1.0", "2.2.0"]) == []
    v = validate_job_create(job(version="9.9.9"), deployed_versions=["2.1.0"])
    assert [x.code for x in v] == ["no_deployment"]


def test_deployment_check_is_skipped_without_center_state() -> None:
    """대상의 활성 배포는 Center만 안다 — 모르면 그 검사를 하지 않는다."""
    assert validate_job_create(job()) == []


# ─────────────── 취소 ───────────────


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("pending", (200, None)),
        ("dispatched", (202, None)),
        ("queued", (202, None)),
        ("accepted", (409, "already_started")),
        ("cancelled", (409, "not_cancellable")),
        ("expired", (409, "not_cancellable")),
        ("무언가_새로운_상태", (409, "not_cancellable")),
    ],
)
def test_cancel_outcome_table(state: str, expected: tuple[int, str | None]) -> None:
    assert cancel_outcome(state) == expected


# ─────────────── 목록 ───────────────


def test_list_params_bounds() -> None:
    assert ListParams().limit == 100
    assert ListParams(limit=1000).limit == 1000
    with pytest.raises(ValidationError):
        ListParams(limit=1001)
    with pytest.raises(ValidationError):
        ListParams(offset=-1)


def test_package_info_embeds_the_c1_manifest() -> None:
    from chaeksas.contracts import Manifest

    m = Manifest.model_validate(
        {"schema": 1, "kind": "bpm_process", "id": "erp.order-entry", "version": "2.1.0",
         "run_location": "pc", "entry": "process/main.bpmn", "process_id": "order_entry",
         "requires": {}, "human": {},
         "built": {"by": "studio", "at": NOW, "core": "0.3.0", "spec_version": 1}, "content_hash": HASH}
    )
    info = package(manifest=m.to_json_dict(), preflight={"warnings": ["W1"], "blocked": []})
    assert info.manifest is not None
    # 패키지 행의 run_location은 매니페스트에서 옮겨 적은 값이다 — 둘이 같아야 한다.
    assert info.manifest.run_location == info.run_location == "pc"
    assert info.preflight.warnings == ["W1"]
