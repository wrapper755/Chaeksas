"""Admin 서명과 Center의 승인 — **서명이 유일한 관문**이다 (C2·C5, M5 조각 1).

진짜 Center를 in-process로 띄우고 진짜 `chk-admin` 명령으로 부른다.

거듭 보는 것 다섯.

1. **토큰만으로는 아무것도 바뀌지 않는다** — 봉투가 없으면 거부다.
2. **모르는 키·철회된 키의 서명은 거부**다 (V2).
3. **해시가 다르면 승인이 아니다** — 승인한 그 바이트여야 한다.
4. **마지막 Admin 키는 철회할 수 없다** — 잠겨서 아무도 서명 못 하게 되는 것을 막는다.
5. 개인키는 **암호문으로** 저장한다 (평문으로 두지 않는다).
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.admin import keys as keystore
from chaeksas.admin.cli import main as admin_main
from chaeksas.admin.client import Center, CenterProblem
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings
from chaeksas.contracts.hashing import content_hash_zip
from chaeksas.contracts.signing import sign

TOKEN = "t-admin"
PASS = "열쇠말"


@pytest.fixture(autouse=True)
def _passphrase(monkeypatch: Any, tmp_path: Path) -> None:
    """사람에게 묻지 않게 — 암호는 환경에서 (CI·시험용 길이다)."""
    monkeypatch.setenv(keystore.PASSPHRASE_ENV, PASS)
    monkeypatch.setenv(f"{keystore.ENV_PREFIX}DATA_DIR", str(tmp_path / "admin"))


@pytest.fixture
def center(tmp_path: Path) -> Any:
    settings = Settings(
        db_path=tmp_path / "center.sqlite3",
        package_dir=tmp_path / "packages",
        admin_token=TOKEN,
    )
    app = create_app(settings)
    return Center(base_url="http://center", token=TOKEN, client=TestClient(app))


def package_zip(package_id: str = "erp.order-entry", version: str = "2.1.0") -> bytes:
    """작은 패키지 하나 (C1). `content_hash`는 **자기 자신을 뺀** 내용의 해시다 (C2)."""
    import tempfile

    files = {"process/main.bpmn": "<definitions />"}
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": package_id,
        "version": version,
        "name": "주문 입력",
        "run_location": "pc",
        "entry": "process/main.bpmn",
        "process_id": "Proc_order",
        "requires": {},
        "human": {},
        "built": {"by": "studio", "at": "2026-10-05T09:00:00+09:00", "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }

    def made(body: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, text in files.items():
                archive.writestr(name, text)
            archive.writestr("manifest.json", body)
        return out.getvalue()

    staged = made(json.dumps(manifest, ensure_ascii=False))
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder) / "p.zip"
        tmp.write_bytes(staged)
        manifest["content_hash"] = content_hash_zip(tmp)
    return made(json.dumps(manifest, ensure_ascii=False))


def upload(center: Center, raw: bytes) -> dict[str, Any]:
    answer = center.client.post(
        "/api/v1/packages",
        files={"file": ("p.zip", raw, "application/zip")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert answer.status_code in (200, 201), answer.text
    return dict(answer.json())


def first_key(center: Center) -> Any:
    """Admin PC에 키를 만들고 Center에 부트스트랩한다 (C2 §부트스트랩)."""
    from chaeksas.center.api.signing import bootstrap_key

    made = keystore.create(label="첫 키")
    bootstrap_key(center.client.app.state.store, public_key=made.public_bytes(), label="첫 키")
    return made


# ─────────────────────────── 키 (ADM-01) ───────────────────────────


def test_a_new_key_is_kept_encrypted(tmp_path: Path) -> None:
    """**평문으로 두지 않는다** — 개인키는 암호문이다."""
    made = keystore.create(label="시험")
    raw = made.path.read_bytes()
    assert b"ENCRYPTED" in raw, "암호문이 아니다"
    assert made.public_path.is_file(), "공개키는 따로 적어 둔다 (부트스트랩에 쓴다)"
    assert len(made.public_bytes()) == 32


def test_a_wrong_passphrase_says_so(monkeypatch: Any) -> None:
    made = keystore.create()
    with pytest.raises(keystore.KeyError_, match="암호가 다를 수 있습니다"):
        keystore.load(made, passphrase="틀린말")


def test_an_empty_passphrase_is_refused(monkeypatch: Any) -> None:
    monkeypatch.setenv(keystore.PASSPHRASE_ENV, "")
    with pytest.raises(keystore.KeyError_, match="평문으로 두지 않습니다"):
        keystore.create()


def test_choosing_between_keys_is_asked_not_guessed() -> None:
    """**아무거나 쓰지 않는다** — 키가 여럿이면 고르라고 한다."""
    keystore.create(label="가")
    keystore.create(label="나")
    with pytest.raises(keystore.KeyError_, match="키가 여럿입니다"):
        keystore.find(None)


def test_the_first_key_only_goes_in_once(center: Center) -> None:
    """부트스트랩은 **키가 하나도 없을 때만** (C2)."""
    from chaeksas.center.api.signing import bootstrap_key
    from chaeksas.center.errors import ApiError

    first_key(center)
    another = keystore.create(label="둘째")
    with pytest.raises(ApiError, match="이미 있다"):
        bootstrap_key(center.client.app.state.store, public_key=another.public_bytes())


def test_a_second_key_needs_an_existing_signature(center: Center) -> None:
    """V8 — **자기 자신으로는 못 올린다.** 그러면 아무나 키를 넣을 수 있다."""
    first = first_key(center)
    second = keystore.create(label="둘째")

    payload = {
        "kind": "admin_key",
        "key_id": second.key_id,
        "public_key": base64.b64encode(second.public_bytes()).decode("ascii"),
        "label": "둘째",
    }
    self_signed = sign(payload, keystore.load(second, passphrase=PASS), signed_at="2026-10-05T09:00:00+09:00")
    with pytest.raises(CenterProblem) as caught:
        center.add_admin_key(self_signed)
    assert caught.value.code in ("unknown_key", "self_signed_key")

    good = sign(payload, keystore.load(first, passphrase=PASS), signed_at="2026-10-05T09:00:00+09:00")
    assert center.add_admin_key(good).key_id == second.key_id
    assert len(center.admin_keys()) == 2
    assert center.add_admin_key(good).key_id == second.key_id, "같은 봉투를 다시 올리면 멱등이다"


def test_the_last_key_cannot_be_revoked(center: Center) -> None:
    """**잠겨서 아무도 서명 못 하게 되는 것**을 막는다."""
    first = first_key(center)
    payload = {
        "kind": "admin_key_revoke",
        "key_id": first.key_id,
        "reason": "시험",
        "revoked_at": "2026-10-05T09:00:00+09:00",
    }
    envelope = sign(payload, keystore.load(first, passphrase=PASS), signed_at="2026-10-05T09:00:00+09:00")
    with pytest.raises(CenterProblem) as caught:
        center.revoke_admin_key(envelope)
    assert caught.value.code == "last_admin_key"


def test_a_revoked_key_cannot_sign_any_more(center: Center) -> None:
    first = first_key(center)
    second = keystore.create(label="둘째")
    center.add_admin_key(
        sign(
            {
                "kind": "admin_key",
                "key_id": second.key_id,
                "public_key": base64.b64encode(second.public_bytes()).decode("ascii"),
            },
            keystore.load(first, passphrase=PASS),
            signed_at="2026-10-05T09:00:00+09:00",
        )
    )
    center.revoke_admin_key(
        sign(
            {
                "kind": "admin_key_revoke",
                "key_id": second.key_id,
                "reason": "잃어버림",
                "revoked_at": "2026-10-05T10:00:00+09:00",
            },
            keystore.load(first, passphrase=PASS),
            signed_at="2026-10-05T10:00:00+09:00",
        )
    )
    info = upload(center, package_zip())
    bad = sign(
        {"kind": "package", "id": info["id"], "version": info["version"],
         "content_hash": info["content_hash"]},
        keystore.load(second, passphrase=PASS),
        signed_at="2026-10-05T11:00:00+09:00",
    )
    with pytest.raises(CenterProblem) as caught:
        center.approve(info["id"], info["version"], bad)
    assert caught.value.code == "revoked_key"


# ─────────────────────────── 패키지 승인 (ADM-02) ───────────────────────────


def test_a_token_alone_changes_nothing(center: Center) -> None:
    """**토큰만으로는 아무것도 바뀌지 않는다** (C2) — 봉투가 아니면 422다."""
    info = upload(center, package_zip())
    answer = center.client.put(
        f"/api/v1/packages/{info['id']}/{info['version']}/signature",
        json={"status": "approved"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert answer.status_code == 422
    assert center.package(info["id"], info["version"])["status"] == "candidate"


def test_an_unknown_key_is_refused(center: Center) -> None:
    """키를 넣지 않고 서명한 봉투 — **모르는 키는 거부**다 (V2)."""
    info = upload(center, package_zip())
    lonely = keystore.create(label="등록 안 한 키")
    envelope = sign(
        {"kind": "package", "id": info["id"], "version": info["version"],
         "content_hash": info["content_hash"]},
        keystore.load(lonely, passphrase=PASS),
        signed_at="2026-10-05T09:00:00+09:00",
    )
    with pytest.raises(CenterProblem) as caught:
        center.approve(info["id"], info["version"], envelope)
    assert caught.value.code == "unknown_key"


def test_a_different_hash_is_not_an_approval(center: Center) -> None:
    """**승인한 그 바이트가 아니면 승인이 아니다.**"""
    key = first_key(center)
    info = upload(center, package_zip())
    envelope = sign(
        {"kind": "package", "id": info["id"], "version": info["version"], "content_hash": "sha256:다른것"},
        keystore.load(key, passphrase=PASS),
        signed_at="2026-10-05T09:00:00+09:00",
    )
    with pytest.raises(CenterProblem) as caught:
        center.approve(info["id"], info["version"], envelope)
    assert caught.value.code == "hash_mismatch"


def test_a_tampered_envelope_is_refused(center: Center) -> None:
    """서명한 뒤 내용을 바꾸면 **서명이 맞지 않는다** (V3)."""
    key = first_key(center)
    info = upload(center, package_zip())
    envelope = sign(
        {"kind": "package", "id": info["id"], "version": info["version"],
         "content_hash": info["content_hash"]},
        keystore.load(key, passphrase=PASS),
        signed_at="2026-10-05T09:00:00+09:00",
    )
    raw: dict[str, Any] = envelope.to_json_dict()
    payload: dict[str, Any] = dict(raw["payload"])
    payload["version"] = "9.9.9"
    raw["payload"] = payload
    with pytest.raises(CenterProblem) as caught:
        center.call("PUT", f"/packages/{info['id']}/{info['version']}/signature", body=raw)
    assert caught.value.code == "bad_signature"


def test_the_signature_rides_in_the_zip_without_changing_the_hash(center: Center, tmp_path: Path) -> None:
    """내려줄 때 `SIGNATURE`를 넣는다 — **해시는 그대로다** (C2)."""
    key = first_key(center)
    raw = package_zip()
    info = upload(center, raw)
    center.approve(
        info["id"],
        info["version"],
        sign(
            {"kind": "package", "id": info["id"], "version": info["version"],
             "content_hash": info["content_hash"]},
            keystore.load(key, passphrase=PASS),
            signed_at="2026-10-05T09:00:00+09:00",
        ),
    )
    answer = center.client.get(
        f"/api/v1/packages/{info['id']}/{info['version']}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert answer.status_code == 200
    with zipfile.ZipFile(io.BytesIO(answer.content)) as found:
        assert "SIGNATURE" in found.namelist()
        envelope = json.loads(found.read("SIGNATURE"))
    assert envelope["payload"]["kind"] == "package"
    downloaded = tmp_path / "내려받은.zip"
    downloaded.write_bytes(answer.content)
    assert content_hash_zip(downloaded) == info["content_hash"], "해시가 바뀌면 안 된다"
    assert answer.headers["X-Content-Hash"] == info["content_hash"]


def test_a_revoked_package_cannot_be_approved_again(center: Center) -> None:
    """**철회된 것은 되살아나지 않는다.**"""
    key = first_key(center)
    info = upload(center, package_zip())
    ok = sign(
        {"kind": "package", "id": info["id"], "version": info["version"],
         "content_hash": info["content_hash"]},
        keystore.load(key, passphrase=PASS),
        signed_at="2026-10-05T09:00:00+09:00",
    )
    center.approve(info["id"], info["version"], ok)
    center.revoke_package(
        info["id"],
        info["version"],
        sign(
            {"kind": "package_revoke", "id": info["id"], "version": info["version"],
             "reason": "잘못 만든 것", "revoked_at": "2026-10-05T10:00:00+09:00"},
            keystore.load(key, passphrase=PASS),
            signed_at="2026-10-05T10:00:00+09:00",
        ),
    )
    assert center.package(info["id"], info["version"])["status"] == "revoked"
    with pytest.raises(CenterProblem) as caught:
        center.approve(info["id"], info["version"], ok)
    assert caught.value.code == "package_revoked"


# ─────────────────────────── 명령줄 (chk-admin) ───────────────────────────


def test_the_command_signs_and_uploads(center: Center, capsys: Any) -> None:
    """`chk-admin approve` — **해시를 보여 주고** 서명해 올린다."""
    first_key(center)
    info = upload(center, package_zip())
    code = admin_main(["-y", "approve", info["id"], info["version"]], center=center)
    assert code == 0
    printed = capsys.readouterr().out
    assert info["content_hash"] in printed, "무엇에 서명하는지 보여 준다"
    assert "승인했습니다" in printed
    assert center.package(info["id"], info["version"])["status"] == "approved"


def test_saying_no_changes_nothing(center: Center, monkeypatch: Any, capsys: Any) -> None:
    """**되돌릴 수 없는 일은 묻는다** — 기본은 「아니오」다 (U9)."""
    first_key(center)
    info = upload(center, package_zip())
    monkeypatch.setattr("builtins.input", lambda *_: "")
    assert admin_main(["approve", info["id"], info["version"]], center=center) == 1
    assert "취소했습니다" in capsys.readouterr().out
    assert center.package(info["id"], info["version"])["status"] == "candidate"


def test_pending_lists_what_waits(center: Center, capsys: Any) -> None:
    upload(center, package_zip())
    assert admin_main(["pending"], center=center) == 0
    assert "erp.order-entry@2.1.0" in capsys.readouterr().out


def test_a_problem_is_one_line_not_a_traceback(center: Center, capsys: Any) -> None:
    """**왜 안 되는지 한 줄로** — 추적을 쏟지 않는다."""
    assert admin_main(["-y", "approve", "없는것", "1.0.0"], center=center) == 2
    assert "오류:" in capsys.readouterr().err
