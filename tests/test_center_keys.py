"""C7 Center API 키 관리 (CON-11).

키가 그 Bot UI의 신원이므로(ADR-0013), **원문은 발급 응답에 한 번만** 실리고 그 뒤로는
앞자리만 보인다. 여기서는 그 규칙과 상태 계산을 고정한다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chaeksas.contracts import (
    CenterKeyCreated,
    CenterKeyCreateRequest,
    CenterKeyInfo,
    center_key_prefix_of,
    center_key_state,
    expires_soon,
    validate_center_key_create,
)
from chaeksas.contracts.center_keys import (
    DEFAULT_EXPIRY_DAYS,
    EXPIRY_WARNING_DAYS,
    ISSUABLE_KEY_TYPES,
    KEY_PREFIX,
    PREFIX_LEN,
)

NOW = "2026-10-01T10:00:00+09:00"
RAW = KEY_PREFIX + "A" * 40


def info(**over: object) -> CenterKeyInfo:
    base: dict[str, object] = {
        "key_id": "ck_1a2b3c4d",
        "name": "현장PC-1",
        "type": "bot_ui",
        "prefix": center_key_prefix_of(RAW),
        "state": "active",
        "created_at": NOW,
    }
    return CenterKeyInfo.model_validate(base | over)


# ─────────────── 발급 ───────────────


def test_only_four_key_types_are_issuable() -> None:
    assert ISSUABLE_KEY_TYPES == {"bot_ui", "studio", "server_runner", "integration"}
    for t in sorted(ISSUABLE_KEY_TYPES):
        assert validate_center_key_create(CenterKeyCreateRequest(name="x", type=t)) == []


def test_unknown_key_type_is_refused() -> None:
    v = validate_center_key_create(CenterKeyCreateRequest(name="x", type="superuser"))
    assert [x.code for x in v] == ["key_type_unknown"]
    assert v[0].items == sorted(ISSUABLE_KEY_TYPES)  # 고를 수 있는 값을 알려 준다


def test_raw_key_is_only_in_the_create_response() -> None:
    """목록 모델에는 원문을 담을 자리가 없다 — 실수로 흘릴 수 없게."""
    assert "key" not in CenterKeyInfo.model_fields
    assert "key" in CenterKeyCreated.model_fields
    created = CenterKeyCreated.model_validate(info().to_json_dict() | {"key": RAW})
    assert created.key == RAW


def test_raw_key_shape_is_checked() -> None:
    for bad in (KEY_PREFIX + "A" * 39, KEY_PREFIX + "A" * 41, "chk_svc_" + "A" * 40, "A" * 48):
        with pytest.raises(ValidationError):
            CenterKeyCreated.model_validate(info().to_json_dict() | {"key": bad})


def test_prefix_is_the_first_16_chars() -> None:
    assert center_key_prefix_of(RAW) == KEY_PREFIX + "A" * 8
    assert len(center_key_prefix_of(RAW)) == PREFIX_LEN


def test_key_id_shape() -> None:
    assert info().key_id == "ck_1a2b3c4d"
    with pytest.raises(ValidationError):
        info(key_id="1a2b3c4d")


# ─────────────── 상태 ───────────────


def test_active_key() -> None:
    assert center_key_state(now=NOW) == "active"
    assert center_key_state(now=NOW, expires_at="2027-10-01T10:00:00+09:00") == "active"


def test_expired_key() -> None:
    assert center_key_state(now=NOW, expires_at="2026-09-30T10:00:00+09:00") == "expired"
    # 딱 그 순간도 만료로 본다
    assert center_key_state(now=NOW, expires_at=NOW) == "expired"


def test_revoked_wins_over_expired() -> None:
    """폐기가 만료보다 앞선다 — 폐기된 키는 만료 여부와 무관하게 폐기됨이다."""
    assert center_key_state(now=NOW, expires_at="2026-09-30T10:00:00+09:00", revoked_at=NOW) == "revoked"
    assert center_key_state(now=NOW, revoked_at="2026-05-01T10:00:00+09:00") == "revoked"


def test_expiry_warning_window() -> None:
    """만료 14일 전부터 CON-11과 그 Bot UI 알림(BUI-05)에 보인다."""
    assert EXPIRY_WARNING_DAYS == 14
    assert expires_soon(now=NOW, expires_at="2026-10-10T10:00:00+09:00")
    assert expires_soon(now=NOW, expires_at="2026-10-15T10:00:00+09:00")  # 14일 경계
    assert not expires_soon(now=NOW, expires_at="2026-10-16T10:00:00+09:00")
    assert not expires_soon(now=NOW, expires_at=None)  # 무기한


def test_already_expired_is_not_expiring_soon() -> None:
    """이미 만료된 것은 「만료」 상태로 보이므로 「곧 만료」로 또 알리지 않는다."""
    assert not expires_soon(now=NOW, expires_at="2026-09-01T10:00:00+09:00")


def test_default_expiry_is_a_year() -> None:
    assert DEFAULT_EXPIRY_DAYS == 365


# ─────────────── 묶음 ───────────────


def test_bound_to_records_the_machine() -> None:
    """Bot UI용·서버 실행기용 키는 처음 등록한 PC에 묶인다 (C4). 다른 PC에서 쓰면 409."""
    k = info(bound_to={"type": "bot_ui", "id": "bui_a81c22d0", "name": "현장PC-1",
                       "machine_name": "FACTORY-PC-01", "first_seen": NOW})
    assert k.bound_to is not None
    assert k.bound_to.machine_name == "FACTORY-PC-01"


def test_unbound_key_has_no_binding() -> None:
    assert info().bound_to is None


def test_unknown_state_is_accepted() -> None:
    assert info(state="뭔가_새로운").state == "뭔가_새로운"
