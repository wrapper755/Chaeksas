"""C2 서명 봉투 — 검증 규칙 V1~V8.

이 관문이 뚫리면 관리자 토큰이나 Center API 키가 새는 것만으로 배포를 만들 수 있게 된다.
그래서 "통과한다"만 보지 않고 **각 규칙이 실제로 막는지**를 하나씩 확인한다.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from chaeksas.contracts import (
    AdminKey,
    DeploymentClaim,
    Envelope,
    key_id_for,
    parse_claim,
    sign,
    verify,
    verify_admin_key_addition,
    verify_package,
    verify_target,
    verify_time,
)

NOW = "2026-10-01T12:00:00+09:00"
HASH = "sha256:" + "41" * 32


def admin() -> tuple[Ed25519PrivateKey, AdminKey]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    return private, AdminKey(
        key_id=key_id_for(public),
        public_key=base64.b64encode(public).decode("ascii"),
        label="시험용",
    )


def deployment_payload(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "deployment",
        "deployment_id": "dep_3f9a1c07",
        "target": {"type": "bot_ui", "id": "bui_a81c22d0"},
        "bpm_process_id": "erp.order-entry",
        "version": "2.1.0",
        "content_hash": HASH,
    }
    return base | over


# ─────────────── 서명·검증 왕복 ───────────────


def test_sign_then_verify_passes() -> None:
    private, key = admin()
    env = sign(deployment_payload(), private, signed_at=NOW)
    assert env.alg == "ed25519"
    assert env.key_id == key.key_id
    assert verify(env, keys=[key], expect_kind="deployment") == []


def test_key_id_is_derived_from_the_public_key() -> None:
    private, key = admin()
    assert key.key_id == key_id_for(private.public_key().public_bytes_raw())
    assert len(key.key_id) == 16
    with pytest.raises(ValueError, match="32바이트"):
        key_id_for(b"too short")


def test_payload_survives_the_round_trip() -> None:
    """모르는 필드도 서명 대상이라 그대로 보존된다 (C2 호환 규칙)."""
    private, key = admin()
    env = sign(deployment_payload(future_field={"x": 1}), private, signed_at=NOW)
    again = Envelope.model_validate(env.to_json_dict())
    assert again.payload["future_field"] == {"x": 1}
    assert verify(again, keys=[key]) == []


def test_key_order_in_payload_does_not_break_the_signature() -> None:
    """canonical_json이 키를 정렬하므로, 전송 중 순서가 바뀌어도 서명은 유효하다."""
    private, key = admin()
    env = sign(deployment_payload(), private, signed_at=NOW)
    shuffled = dict(reversed(list(env.payload.items())))
    assert verify(env.model_copy(update={"payload": shuffled}), keys=[key]) == []


# ─────────────── V1~V4 (모두가 검사) ───────────────


def test_v1_other_algorithms_are_refused() -> None:
    private, key = admin()
    env = sign(deployment_payload(), private, signed_at=NOW)
    with pytest.raises(ValueError):  # 모델이 먼저 막는다
        Envelope.model_validate(env.to_json_dict() | {"alg": "rsa"})
    # 모델을 거치지 않고 들어온 값도 코드가 잡는다
    bad = env.model_copy(update={"alg": "rsa"})
    assert [v.code for v in verify(bad, keys=[key])] == ["unsupported_alg"]


def test_v2_unknown_key_is_refused() -> None:
    private, _ = admin()
    _, other = admin()
    env = sign(deployment_payload(), private, signed_at=NOW)
    assert [v.code for v in verify(env, keys=[other])] == ["unknown_key"]
    assert [v.code for v in verify(env, keys=[])] == ["unknown_key"]


def test_v2_revoked_key_is_refused_but_signature_still_checked() -> None:
    private, key = admin()
    env = sign(deployment_payload(), private, signed_at=NOW)
    revoked = key.model_copy(update={"revoked_at": NOW})
    assert [v.code for v in verify(env, keys=[revoked])] == ["revoked_key"]


def test_v3_tampered_payload_is_caught() -> None:
    """배포 대상만 자기 PC로 바꿔치기하는 공격을 막는 지점."""
    private, key = admin()
    env = sign(deployment_payload(), private, signed_at=NOW)
    tampered = env.model_copy(
        update={"payload": deployment_payload(target={"type": "bot_ui", "id": "bui_attacker"})}
    )
    assert [v.code for v in verify(tampered, keys=[key])] == ["bad_signature"]


def test_v3_signature_from_another_key_is_caught() -> None:
    private, key = admin()
    other_private, _ = admin()
    env = sign(deployment_payload(), private, signed_at=NOW)
    forged = sign(deployment_payload(), other_private, signed_at=NOW)
    assert [v.code for v in verify(env.model_copy(update={"sig": forged.sig}), keys=[key])] == ["bad_signature"]


def test_v3_garbage_signature_is_caught_not_crashed() -> None:
    private, key = admin()
    env = sign(deployment_payload(), private, signed_at=NOW)
    assert [v.code for v in verify(env.model_copy(update={"sig": "not base64!"}), keys=[key])] == ["bad_signature"]


def test_v4_wrong_kind_is_caught() -> None:
    private, key = admin()
    env = sign(deployment_payload(), private, signed_at=NOW)
    assert [v.code for v in verify(env, keys=[key], expect_kind="package")] == ["wrong_kind"]


# ─────────────── V5~V8 (역할별) ───────────────


def test_v5a_expired_deployment_is_refused_by_everyone() -> None:
    private, _ = admin()
    env = sign(deployment_payload(expires_at="2026-09-30T23:59:59+09:00"), private, signed_at=NOW)
    assert [v.code for v in verify_time(env, now=NOW, check_not_before=True)] == ["expired"]
    assert [v.code for v in verify_time(env, now=NOW, check_not_before=False)] == ["expired"]


def test_v5b_not_before_is_only_checked_by_the_runner() -> None:
    """Center는 예약 배포를 받아 두고, 실행하는 쪽만 "아직 아니다"를 본다."""
    private, _ = admin()
    env = sign(deployment_payload(not_before="2026-12-01T00:00:00+09:00"), private, signed_at=NOW)
    assert [v.code for v in verify_time(env, now=NOW, check_not_before=True)] == ["not_yet"]
    assert verify_time(env, now=NOW, check_not_before=False) == []


def test_v5_null_time_window_means_always() -> None:
    private, _ = admin()
    env = sign(deployment_payload(not_before=None, expires_at=None), private, signed_at=NOW)
    assert verify_time(env, now=NOW, check_not_before=True) == []


def test_v6_target_must_be_me() -> None:
    private, _ = admin()
    env = sign(deployment_payload(), private, signed_at=NOW)
    assert verify_target(env, runner_kind="bot_ui", runner_id="bui_a81c22d0") == []
    assert [v.code for v in verify_target(env, runner_kind="bot_ui", runner_id="bui_other")] == ["wrong_target"]
    # 종류가 다르면 id가 같아도 아니다
    assert [v.code for v in verify_target(env, runner_kind="server_runner", runner_id="bui_a81c22d0")] == [
        "wrong_target"
    ]


def test_v6_server_wildcard_matches_every_server_runner() -> None:
    private, _ = admin()
    env = sign(deployment_payload(target={"type": "server_runner", "id": "*"}), private, signed_at=NOW)
    assert verify_target(env, runner_kind="server_runner", runner_id="srv_anything") == []
    # 와일드카드는 서버 실행기에만 쓴다 — Bot UI는 받지 않는다
    assert [v.code for v in verify_target(env, runner_kind="bot_ui", runner_id="bui_a81c22d0")] == ["wrong_target"]


def test_v7_package_hash_and_signature() -> None:
    private, key = admin()
    env = sign(deployment_payload(), private, signed_at=NOW)
    approval = sign(
        {"kind": "package", "id": "erp.order-entry", "version": "2.1.0", "content_hash": HASH},
        private, signed_at=NOW,
    )
    assert verify_package(env, package_hash=HASH, package_signature=approval, keys=[key]) == []

    other = "sha256:" + "99" * 32
    codes = [v.code for v in verify_package(env, package_hash=other, package_signature=approval, keys=[key])]
    assert codes == ["hash_mismatch"]

    codes = [v.code for v in verify_package(env, package_hash=HASH, package_signature=None, keys=[key])]
    assert codes == ["unsigned_package"]


def test_v7_package_signature_must_itself_verify() -> None:
    """승인 서명이 다른(모르는) 키로 되어 있으면 설치하지 않는다."""
    private, key = admin()
    rogue_private, _ = admin()
    env = sign(deployment_payload(), private, signed_at=NOW)
    rogue = sign({"kind": "package", "id": "x", "version": "1.0.0", "content_hash": HASH},
                 rogue_private, signed_at=NOW)
    v = verify_package(env, package_hash=HASH, package_signature=rogue, keys=[key])
    assert [x.code for x in v] == ["unsigned_package"]
    assert any("unknown_key" in item for item in v[0].items)


def test_v8_a_key_cannot_add_itself() -> None:
    """자기 서명으로 키를 추가할 수 있으면 아무나 Admin이 된다."""
    private, key = admin()
    payload = {"kind": "admin_key", "key_id": key.key_id, "public_key": key.public_key, "label": "나"}
    env = sign(payload, private, signed_at=NOW)
    assert [v.code for v in verify_admin_key_addition(env, keys=[key])] == ["self_signed_key"]


def test_v8_another_admin_may_add_a_key() -> None:
    first_private, first = admin()
    _, second = admin()
    payload = {"kind": "admin_key", "key_id": second.key_id, "public_key": second.public_key}
    env = sign(payload, first_private, signed_at=NOW)
    assert verify_admin_key_addition(env, keys=[first]) == []


# ─────────────── claim 읽기 ───────────────


def test_parse_claim_reads_the_typed_shape() -> None:
    private, _ = admin()
    env = sign(deployment_payload(max_concurrency=5), private, signed_at=NOW)
    claim = parse_claim(env)
    assert isinstance(claim, DeploymentClaim)
    assert claim.target.type == "bot_ui"
    assert claim.max_concurrency == 5


def test_parse_claim_refuses_unknown_kind() -> None:
    private, _ = admin()
    env = sign({"kind": "what_is_this"}, private, signed_at=NOW)
    with pytest.raises(ValueError, match="모르는 claim 종류"):
        parse_claim(env)


def test_revoke_claim_is_readable() -> None:
    private, _ = admin()
    env = sign({"kind": "revoke", "deployment_id": "dep_3f9a1c07", "reason": "사고",
                "revoked_at": NOW}, private, signed_at=NOW)
    claim = parse_claim(env)
    assert claim.kind == "revoke"


def test_float_in_payload_cannot_be_signed() -> None:
    from chaeksas.contracts import FloatInPayloadError

    private, _ = admin()
    with pytest.raises(FloatInPayloadError):
        sign(deployment_payload(max_concurrency=5.0), private, signed_at=NOW)
