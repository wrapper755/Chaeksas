"""배포 한 바퀴 — Admin 서명 → Center → Bot UI 설치 (C2·C4·C5, M5 조각 2).

**서명이 유일한 관문**이라는 것을 끝에서 끝까지 본다. 진짜 Center를 in-process로 띄우고,
진짜 `chk-admin`으로 서명하고, 진짜 Bot UI 쪽 코드가 받아 설치한다.

거듭 보는 것 다섯.

1. **서명 없는 패키지는 설치하지 않는다** (V7 `unsigned_package`) — 거부도 보고한다.
2. **남의 배포는 받지 않는다** (V6) — `target`이 나여야 한다.
3. **예약 배포는 기다린다** (V5b) — 거부가 아니다.
4. **철회하면 더 내려오지 않는다** — 승인 철회도 같다.
5. **승인되지 않은 패키지는 배포할 수 없다** — 승인이 먼저다.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.admin import keys as keystore
from chaeksas.admin.cli import main as admin_main
from chaeksas.admin.client import Center, CenterProblem
from chaeksas.center.api.signing import bootstrap_key
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings
from chaeksas.contracts.hashing import content_hash_zip
from chaeksas.contracts.signing import sign
from chaeksas.core.deploy import APPLIED, REJECTED, Deployer, read_signature
from chaeksas.core.packages import (
    CENTER,
    INSTALL_SOURCE_NAME,
    MANUAL,
    SIGNATURE_NAME,
    SOURCE_UNKNOWN,
    install,
    installed,
    write_source,
)

TOKEN = "t-admin"
PASS = "열쇠말"
BOT_UI = "bui_a81c22d0"
AT = "2026-10-05T09:00:00+09:00"


@pytest.fixture(autouse=True)
def _admin_home(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv(keystore.PASSPHRASE_ENV, PASS)
    monkeypatch.setenv(f"{keystore.ENV_PREFIX}DATA_DIR", str(tmp_path / "admin"))


@pytest.fixture
def center(tmp_path: Path, monkeypatch: Any) -> Any:
    settings = Settings(
        db_path=tmp_path / "center.sqlite3", package_dir=tmp_path / "packages", admin_token=TOKEN
    )
    made = Center(base_url="http://center", token=TOKEN, client=TestClient(create_app(settings)))
    # 그 PC의 키는 내려받기 관문을 보는 시험이 쓴다 (C5 권한표).
    made.client.app.state.bot_ui_key = register_pc(made, monkeypatch, BOT_UI, machine="9" * 64)
    return made


def register_pc(
    center: Center, monkeypatch: Any, bot_ui_id: str, *, machine: str, name: str = "현장 PC 1"
) -> str:
    """등록된 PC 하나 — **배포 대상은 등록되어 있어야 한다** (ADR-0049). 그 PC의 키를 준다.

    `bot_ui_id`는 Center가 등록에서 만들어(`api.bot_ui.new_bot_ui_id`) 시험이 미리 알 수 없다.
    그래서 **만드는 자리만 고정하고** 등록은 진짜 길로 한다 — 키를 발급받아 `POST
    /bot-ui/register`를 부른다. 고정하지 않으면 봉투에 적을 id를 아래 모든 시험에 실어
    날라야 한다.
    """
    from chaeksas.center.api import bot_ui as bot_ui_api

    # **이번 등록에만** 고정한다 — 뒤에 다른 PC가 등록하면 진짜 길로 제 id를 받는다
    # (하나로 고정해 두면 둘째 PC가 같은 id로 들어온다).
    original = bot_ui_api.new_bot_ui_id
    pinned = [bot_ui_id]
    monkeypatch.setattr(
        bot_ui_api, "new_bot_ui_id", lambda: pinned.pop() if pinned else original()
    )
    created = center.client.post(
        "/api/v1/center-keys",
        json={"name": name, "type": "bot_ui"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert created.status_code == 201, created.text
    registered = center.client.post(
        "/api/v1/bot-ui/register",
        json={
            "schema": 1,
            "machine_id": machine,
            "name": name,
            "os": "windows-11-23H2",
            "versions": {"bot_ui": "0.1.0", "core": "0.1.0"},
        },
        headers={"Authorization": f"Bearer {created.json()['key']}"},
    )
    assert registered.status_code < 400, registered.text
    assert registered.json()["bot_ui_id"] == bot_ui_id
    return str(created.json()["key"])


def package_zip(
    package_id: str = "erp.order-entry",
    version: str = "2.1.0",
    *,
    requires: dict[str, Any] | None = None,
    run_location: str = "pc",
) -> bytes:
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": package_id,
        "version": version,
        "name": "주문 입력",
        "run_location": run_location,
        "entry": "process/main.bpmn",
        "process_id": "Proc_order",
        "requires": requires or {},
        "human": {},
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }
    return _zipped(manifest, {"process/main.bpmn": "<definitions />"})


def lib_zip(package_id: str = "shared.approval", version: str = "1.1.0") -> bytes:
    """공유 BPM 프로세스 패키지 하나 (C1 `kind=process_lib`)."""
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "process_lib",
        "id": package_id,
        "version": version,
        "name": "공통 결재",
        "requires": {},
        "human": {},
        "provides": {"processes": [{"process_id": "Proc_approval", "file": "process/approval.bpmn"}]},
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }
    return _zipped(manifest, {"process/approval.bpmn": "<definitions />"})


def _zipped(manifest: dict[str, Any], files: dict[str, str]) -> bytes:
    """`content_hash`는 **자기 자신을 뺀** 내용의 해시다 (C2) — 두 번 만들어 채운다."""
    import tempfile

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


def admin_key(center: Center) -> Any:
    made = keystore.create(label="첫 키")
    bootstrap_key(center.client.app.state.store, public_key=made.public_bytes(), label="첫 키")
    return made


def approved(
    center: Center, key: Any, *, package_id: str = "erp.order-entry", run_location: str = "pc"
) -> dict[str, Any]:
    """업로드 → 승인까지."""
    info = upload(center, package_zip(package_id, run_location=run_location))
    center.approve(
        info["id"],
        info["version"],
        sign(
            {"kind": "package", "id": info["id"], "version": info["version"],
             "content_hash": info["content_hash"]},
            keystore.load(key, passphrase=PASS),
            signed_at=AT,
        ),
    )
    return info


def deployment(
    key: Any, info: dict[str, Any], *, target: str = BOT_UI, **extra: Any
) -> Any:
    payload: dict[str, Any] = {
        "kind": "deployment",
        "deployment_id": extra.pop("deployment_id", "dep_3f9a1c07"),
        "target": {"type": extra.pop("target_type", "bot_ui"), "id": target},
        "bpm_process_id": info["id"],
        "version": info["version"],
        "content_hash": extra.pop("content_hash", info["content_hash"]),
        "not_before": extra.pop("not_before", None),
        "expires_at": extra.pop("expires_at", None),
    }
    return sign(payload, keystore.load(key, passphrase=PASS), signed_at=AT)


def deployer(center: Center, tmp_path: Path, **extra: Any) -> Deployer:
    """Bot UI 쪽 — 패키지는 **진짜 Center에서** 받는다."""

    def fetch(package_id: str, version: str) -> Path:
        answer = center.client.get(
            f"/api/v1/packages/{package_id}/{version}", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        assert answer.status_code == 200, answer.text
        target = tmp_path / "downloads" / f"{package_id}-{version}.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(answer.content)
        return target

    return Deployer(
        data_dir=tmp_path / "botui",
        host_id=BOT_UI,
        keys=center.admin_keys(),
        fetch=fetch,
        clock=lambda: AT,
        **extra,
    )


# ─────────────────────────── Center (C5) ───────────────────────────


def test_an_unapproved_package_cannot_be_deployed(center: Center) -> None:
    """**승인이 먼저다** — 서명 없는 것을 배포하면 받는 쪽이 어차피 거부한다."""
    key = admin_key(center)
    info = upload(center, package_zip())
    with pytest.raises(CenterProblem) as caught:
        center.deploy(deployment(key, info))
    assert caught.value.code == "not_approved"


def test_a_deprecated_package_cannot_be_deployed_again(center: Center) -> None:
    """지원 종료가 **새 배포를 막는다** (C5) — 서명은 멀쩡한데도 거부다.

    막는 일에는 봉투가 없다 — 관리자 토큰으로 상태만 옮긴다.
    """
    key = admin_key(center)
    info = approved(center, key)
    center.deprecate(info["id"], info["version"])
    with pytest.raises(CenterProblem) as caught:
        center.deploy(deployment(key, info))
    assert caught.value.code == "deprecated"


def test_the_same_envelope_twice_is_idempotent(center: Center) -> None:
    key = admin_key(center)
    info = approved(center, key)
    envelope = deployment(key, info)
    first = center.deploy(envelope)
    again = center.deploy(envelope)
    assert first == again
    assert len(center.deployments()) == 1


def test_a_different_body_on_the_same_id_conflicts(center: Center) -> None:
    key = admin_key(center)
    info = approved(center, key)
    center.deploy(deployment(key, info))
    with pytest.raises(CenterProblem) as caught:
        center.deploy(deployment(key, info, expires_at="2027-01-01T00:00:00+09:00"))
    assert caught.value.code == "deployment_conflict"


def test_a_wildcard_pc_deployment_is_not_even_kept(center: Center) -> None:
    """**PC 배포에 전체(`*`) 대상은 없다** (ADR-0046) — 받아 두지도 않는다.

    받아 두면 Center가 모든 PC에 내려 주고 **모든 PC가 V6 `wrong_target`으로 거부해** CON-03이
    거짓 ⛔로 찬다. 그때 운영자가 뒤지는 것은 승인·해시·키인데 **막은 것은 대상**이다.
    """
    key = admin_key(center)
    info = approved(center, key)
    with pytest.raises(CenterProblem) as caught:
        center.deploy(deployment(key, info, target="*"))
    assert caught.value.code == "wrong_target"
    assert center.deployments() == [], "행조차 남지 않는다"


def test_a_wildcard_row_already_in_the_database_still_goes_nowhere(
    center: Center, tmp_path: Path
) -> None:
    """**관문이 둘이다** — 옛 DB에 `*` PC 배포 행이 있어도 내려가지 않는다 (ADR-0046).

    `create`가 막기 전에 들어간 행이 있을 수 있다. 고르는 네 자리가 **같은 `_target_sql`**을
    쓰므로 하나만 새 보다가 어긋나는 일이 없다 — 여기서 그 셋을 함께 본다.
    """
    from chaeksas.center.api.deployments import downloadable_by, envelopes_for, versions_for

    key = admin_key(center)
    info = approved(center, key)
    store = center.client.app.state.store
    # `create`를 거치지 않고 **손으로** 넣는다 (옛 DB에 들어 있던 꼴).
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO deployments (deployment_id, target_type, target_id, bpm_process_id,"
            " version, content_hash, envelope_json, revoked_json, at) VALUES"
            " (?, 'bot_ui', '*', ?, ?, ?, ?, NULL, ?)",
            (
                "dep_old00001",
                info["id"],
                info["version"],
                info["content_hash"],
                json.dumps(deployment(key, info, target="*").to_json_dict(), ensure_ascii=False),
                AT,
            ),
        )

    assert envelopes_for(store, target_type="bot_ui", target_id=BOT_UI) == [], "내려가지 않는다"
    assert versions_for(
        store, target_type="bot_ui", target_id=BOT_UI, bpm_process_id=info["id"]
    ) == [], "작업을 만들 수도 없다"
    assert downloadable_by(store, target_type="bot_ui", target_id=BOT_UI) == set(), "받을 수도 없다"
    assert [one.target["id"] for one in listing_of(center, BOT_UI)] == [], "CON-03에도 안 보인다"


def test_the_server_runner_still_matches_everything_with_a_wildcard(center: Center) -> None:
    """**`*`는 서버 실행기 배포에 그대로 있다** (C2 §배포 대상 규칙·V6).

    서버 배포는 M7이라 `create`로는 만들 수 없다 — 그래서 고르는 조건 자체를 본다. 이것이
    깨지면 ADR-0046이 지우려던 것보다 많이 지운 것이다.
    """
    from chaeksas.center.api.deployments import WILDCARD_TARGETS, _target_sql

    assert WILDCARD_TARGETS == {"server_runner"}
    where, args = _target_sql("server_runner", "srv_1")
    assert where.count("?") == len(args) == 3
    assert args[-1] == "*"
    where, args = _target_sql("bot_ui", BOT_UI)
    assert where.count("?") == len(args) == 2
    assert "*" not in args


def listing_of(center: Center, target_id: str) -> list[Any]:
    """`GET /deployments?target_id=` — CON-03의 「배포」가 읽는 것."""
    from chaeksas.center.api.deployments import listing

    return listing(center.client.app.state.store, target_id=target_id)


def test_a_revoked_deployment_never_comes_back(center: Center) -> None:
    """**철회된 것은 영구히 철회 상태**다 (C2)."""
    key = admin_key(center)
    info = approved(center, key)
    envelope = deployment(key, info)
    center.deploy(envelope)
    center.revoke_deployment(
        sign(
            {"kind": "revoke", "deployment_id": "dep_3f9a1c07", "reason": "잘못", "revoked_at": AT},
            keystore.load(key, passphrase=PASS),
            signed_at=AT,
        )
    )
    with pytest.raises(CenterProblem) as caught:
        center.deploy(envelope)
    assert caught.value.code == "deployment_revoked"
    assert center.deployments(active=True) == []


def test_a_pc_package_cannot_go_to_a_server_runner(center: Center) -> None:
    """`run_location`과 대상이 맞아야 한다 (C2 §배포 대상 규칙).

    코드는 **`wrong_target`(409) 하나**다 (ADR-0047) — 계약도 그 이름으로 말한다.
    `target_mismatch`는 작업 쪽(모르는 대상 종류)에만 남았다.
    """
    key = admin_key(center)
    info = approved(center, key)
    with pytest.raises(CenterProblem) as caught:
        center.deploy(deployment(key, info, target_type="server_runner", target="*"))
    assert (caught.value.status, caught.value.code) == (409, "wrong_target")


def test_a_server_deployment_is_taken_now_that_m7_is_open(center: Center) -> None:
    """**서버 실행기 배포를 이제 받는다** (M7 — 스위치를 켰다).

    켜기 전에는 422 `server_runner_not_available`이었다 (내려 줄 실행기가 없는 배포가 표에
    남으면 `GET /deployments`를 보는 운영자가 돌 것이라고 읽는다). 이제 실행기가 등록하고
    설치하고 **돌린다** — 관문은 서명·승인·대상뿐이다 (ADR-0047의 그 함수 하나).
    """
    key = admin_key(center)
    info = approved(center, key, package_id="erp.night-close", run_location="server")
    assert center.deploy(deployment(key, info, target_type="server_runner", target="srv_1"))
    listed = center.deployments(active=False)
    assert [one["target"]["type"] for one in listed] == ["server_runner"]


def test_an_unregistered_pc_cannot_be_deployed_to(center: Center) -> None:
    """**등록되지 않은 PC에는 배포하지 않는다** (ADR-0049) — 404 `target_not_found`.

    받아 두면 **아무에게도 가지 않는 배포**가 표에 남는다 — `envelopes_for`는 `target_id`로
    맞추고, CON-03에는 그 PC 줄이 없어 보여 줄 자리조차 없다. 「미리 배포해 두기」를 막는 것이
    아니다: `bot_ui_id`는 Center가 등록에서 만들어 등록 전에는 봉투에 적을 id가 없다.
    """
    key = admin_key(center)
    info = approved(center, key)
    with pytest.raises(CenterProblem) as caught:
        center.deploy(deployment(key, info, target="bui_00000000"))
    assert (caught.value.status, caught.value.code) == (404, "target_not_found")
    assert center.deployments(active=False) == [], "행조차 남지 않는다"

    # 등록된 PC에는 그대로 간다 — 막는 것은 **명부에 없는 id**뿐이다.
    center.deploy(deployment(key, info, target=BOT_UI))
    assert [one["target"]["id"] for one in center.deployments(active=True)] == [BOT_UI]


def test_a_wrong_target_is_answered_before_a_missing_one(center: Center) -> None:
    """**「대상이 틀렸다」가 「대상이 없다」를 이긴다** (ADR-0049).

    PC 배포의 `"*"`는 등록된 id가 아니지만, 운영자가 할 일은 「대상을 하나 적는다」다 (ADR-0046)
    — 404로 답하면 있지도 않은 「`*`라는 PC」를 찾는다.
    """
    key = admin_key(center)
    info = approved(center, key)
    with pytest.raises(CenterProblem) as caught:
        center.deploy(deployment(key, info, target="*"))
    assert (caught.value.status, caught.value.code) == (409, "wrong_target")


def test_center_refuses_exactly_what_the_contract_refuses(center: Center) -> None:
    """**관문이 하나다** (ADR-0047) — Center의 `(상태, 코드)`가 계약의 것과 **규칙마다** 같다.

    두 벌이던 때 대상 어긋남이 한쪽에서 `target_mismatch`(422), 다른 쪽에서 `wrong_target`(409)
    이었고 서버 배포 관문은 계약에만 있었다. 베낀 것이 아니라 **같은 함수**를 부르는지 보려고
    같은 봉투를 계약에게도 물어 본다.
    """
    from chaeksas.center.api import bot_ui as bot_ui_api
    from chaeksas.contracts.center_api import (
        DEPLOYMENT_REFUSAL_STATUS,
        PackageInfo,
        deployment_refusal,
        validate_deployment,
    )

    key = admin_key(center)
    keys = center.admin_keys()
    pc = approved(center, key)
    server = approved(center, key, package_id="erp.night-close", run_location="server")
    other = upload(center, package_zip("erp.not-approved"))  # 승인하지 않는다
    old = approved(center, key, package_id="erp.old")
    center.deprecate(old["id"], old["version"])

    tried = (
        (other, deployment(key, other, deployment_id="dep_00000001")),
        (old, deployment(key, old, deployment_id="dep_00000002")),
        (pc, deployment(key, pc, target="*", deployment_id="dep_00000003")),
        (pc, deployment(key, pc, target_type="server_runner", target="srv_1",
                        deployment_id="dep_00000004")),
        (pc, deployment(key, pc, content_hash="sha256:" + "99" * 32,
                        deployment_id="dep_00000005")),
        (pc, deployment(key, pc, target="bui_00000000", deployment_id="dep_00000007")),
    )
    store = center.client.app.state.store
    seen = set()
    for info, envelope in tried:
        # 대상이 등록됐나는 **Center가 읽어 계약에 넘긴다** (ADR-0049) — 여기서도 같은 길로
        # 묻는다. SQL을 베껴 두면 「같은 함수를 부르는가」가 아니라 베낀 것을 보게 된다.
        target = envelope.payload["target"]
        said = deployment_refusal(
            validate_deployment(
                envelope,
                package=PackageInfo.model_validate(center.package(info["id"], info["version"])),
                keys=keys,
                now=AT,
                target_registered=(
                    bot_ui_api.exists(store, str(target.get("id") or ""))
                    if target.get("type") == "bot_ui"
                    else None
                ),
            )
        )
        assert said is not None, f"계약이 거절하지 않았다: {envelope.payload['deployment_id']}"
        with pytest.raises(CenterProblem) as caught:
            center.deploy(envelope)
        assert (caught.value.status, caught.value.code) == (said[0], said[1].code), (
            envelope.payload["deployment_id"]
        )
        seen.add(caught.value.code)
    # **규칙마다** 봤다는 것까지 — 하나로 뭉쳐도 통과하면 「맞물린다」를 증명하지 못한다.
    #
    # `server_runner_not_available`만 빠진다 — **스위치를 켰으므로**(M7) HTTP 길로는 그 코드를
    # 낼 수 없다. 표에는 남아 있다 (끌 수 있는 값이면 상태도 있어야 한다 — `test_center_api.py`가
    # 끈 길을 본다).
    assert seen == set(DEPLOYMENT_REFUSAL_STATUS) - {"server_runner_not_available"}

    assert center.deployments(active=False) == [], "거절한 것은 하나도 남지 않는다"

    # 거꾸로도 본다 — **서버 패키지를 서버 실행기에 배포하는 것은 이제 통과한다** (M7).
    assert center.deploy(
        deployment(key, server, target_type="server_runner", target="srv_1",
                   deployment_id="dep_00000006")
    )
    assert [one["deployment_id"] for one in center.deployments(active=False)] == ["dep_00000006"]


def test_the_listing_answers_in_the_contract_shape(center: Center) -> None:
    """`GET /deployments`는 C5 `DeploymentInfo`다 — **서명자·유효 기간은 봉투에서 읽는다**.

    CON-03 「배포」가 유효 기간을 그리려면 이것이 있어야 한다.
    """
    from chaeksas.contracts.center_api import DeploymentInfo

    key = admin_key(center)
    info = approved(center, key)
    until = "2027-01-01T00:00:00+09:00"
    center.deploy(deployment(key, info, expires_at=until))

    found = DeploymentInfo.model_validate(center.deployments()[0])
    assert found.signed_by == key.key_id, "서명한 Admin 키"
    assert found.signed_at == AT
    assert found.expires_at == until and found.not_before is None
    assert found.revoked_at is None and found.last_result is None


def test_a_revoked_deployment_keeps_its_row_with_a_time(center: Center) -> None:
    """철회해도 **행은 남는다** — 「언제 철회됐나」가 콘솔에 보여야 한다 (C5)."""
    key = admin_key(center)
    info = approved(center, key)
    center.deploy(deployment(key, info))
    center.revoke_deployment(
        sign(
            {"kind": "revoke", "deployment_id": "dep_3f9a1c07", "reason": "잘못", "revoked_at": AT},
            keystore.load(key, passphrase=PASS),
            signed_at=AT,
        )
    )
    assert center.deployments(active=True) == []
    [one] = center.deployments(active=False)
    assert one["revoked_at"] == AT


def test_a_bot_ui_key_downloads_only_what_is_deployed_to_it(center: Center) -> None:
    """내려받기 관문 (C5 권한표) — **자기 배포분만**이다.

    배포를 철회하면 **그 자리에서 닫힌다** — 키는 그대로인데 받을 수 있는 것이 달라진다.
    """
    key = admin_key(center)
    mine = approved(center, key)
    other = approved(center, key, package_id="erp.payment")

    auth = {"Authorization": f"Bearer {center.client.app.state.bot_ui_key}"}

    center.deploy(deployment(key, mine, target=BOT_UI))
    for info, expected in ((mine, 200), (other, 403)):
        answer = center.client.get(
            f"/api/v1/packages/{info['id']}/{info['version']}", headers=auth
        )
        assert answer.status_code == expected, (info["id"], answer.text)

    center.revoke_deployment(
        sign(
            {"kind": "revoke", "deployment_id": "dep_3f9a1c07", "reason": "잘못", "revoked_at": AT},
            keystore.load(key, passphrase=PASS),
            signed_at=AT,
        )
    )
    closed = center.client.get(f"/api/v1/packages/{mine['id']}/{mine['version']}", headers=auth)
    assert closed.status_code == 403


def test_a_bot_ui_key_gets_only_the_package_deployed_to_it(center: Center) -> None:
    """실행하는 쪽이 받는 것은 **자기에게 배포된 BPM 프로세스 패키지뿐**이다 (C5 권한표).

    쓰는 공유 BPM 프로세스도 따로 받지 않는다 — 그것은 패키지 안 `libs/`로 **복사해 넣은**
    것이다 (C1 §패키지 구성). 도구 묶음은 패키지로 오지 않는다 (ADR-0050).
    """
    key = admin_key(center)
    lib = upload(center, lib_zip())
    info = upload(
        center,
        package_zip(requires={"libs": [f"{lib['id']}@{lib['version']}"]}),
    )
    center.approve(
        info["id"],
        info["version"],
        sign(
            {"kind": "package", "id": info["id"], "version": info["version"],
             "content_hash": info["content_hash"]},
            keystore.load(key, passphrase=PASS),
            signed_at=AT,
        ),
    )

    created = center.client.post(
        "/api/v1/center-keys",
        json={"name": "현장 PC 2", "type": "bot_ui"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    auth = {"Authorization": f"Bearer {created.json()['key']}"}
    registered = center.client.post(
        "/api/v1/bot-ui/register",
        json={
            "schema": 1,
            "machine_id": "8" * 64,
            "name": "현장 PC 2",
            "os": "windows-11-23H2",
            "versions": {"bot_ui": "0.1.0", "core": "0.1.0"},
        },
        headers=auth,
    )
    center.deploy(deployment(key, info, target=registered.json()["bot_ui_id"]))
    assert center.client.get(
        f"/api/v1/packages/{info['id']}/{info['version']}", headers=auth
    ).status_code == 200
    # 「없다」와 「내 것이 아니다」는 같은 403이다 — 404로 가르면 그것이 곧 목록이 된다.
    assert center.client.get(
        f"/api/v1/packages/{lib['id']}/{lib['version']}", headers=auth
    ).status_code == 403


# ─────────────────────────── Bot UI 설치 (C2 V1~V7) ───────────────────────────


def test_a_signed_deployment_installs(center: Center, tmp_path: Path) -> None:
    """한 바퀴 — Admin 서명 → Center → **설치**."""
    key = admin_key(center)
    info = approved(center, key)
    center.deploy(deployment(key, info))

    found = deployer(center, tmp_path).apply(_envelopes(center))
    assert [one.result for one in found] == [APPLIED]
    bots = installed(tmp_path / "botui")
    assert [(one.id, one.version) for one in bots] == [("erp.order-entry", "2.1.0")]
    assert "승인됨" in bots[0].signature, "설치된 것에 봉투가 남는다 (BUI-04 「서명」)"


def test_installing_twice_does_nothing(center: Center, tmp_path: Path) -> None:
    key = admin_key(center)
    info = approved(center, key)
    center.deploy(deployment(key, info))
    one = deployer(center, tmp_path)
    assert len(one.apply(_envelopes(center))) == 1
    assert one.apply(_envelopes(center)) == [], "이미 설치돼 있으면 조용히 지나간다"


def test_an_unsigned_package_is_refused(center: Center, tmp_path: Path) -> None:
    """**서명 없는 패키지는 설치하지 않는다** (V7) — 거부도 보고한다."""
    key = admin_key(center)
    info = approved(center, key)
    envelope = deployment(key, info)
    center.deploy(envelope)

    def bare(package_id: str, version: str) -> Path:
        """승인 봉투를 뺀 zip — Center를 거치지 않고 온 것처럼."""
        target = tmp_path / "bare.zip"
        target.write_bytes(package_zip(package_id))
        assert read_signature(target) is None
        return target

    one = deployer(center, tmp_path)
    one.fetch = bare
    found = one.apply(_envelopes(center))
    assert [x.result for x in found] == [REJECTED]
    assert found[0].reason == "unsigned_package"
    assert installed(tmp_path / "botui") == []


def test_someone_elses_deployment_is_refused(
    center: Center, tmp_path: Path, monkeypatch: Any
) -> None:
    """**남의 배포는 받지 않는다** (V6) — 대상이 나여야 한다.

    남의 것도 **등록된 PC**다 (ADR-0049) — 등록되지 않은 id로는 배포 자체가 404라서, 이 시험이
    보려는 「설치하는 쪽이 대상을 본다」를 Center가 먼저 가로챈다.
    """
    key = admin_key(center)
    info = approved(center, key)
    other_pc = "bui_b70d1104"
    register_pc(center, monkeypatch, other_pc, machine="7" * 64, name="현장 PC 2")

    center.deploy(deployment(key, info, target=other_pc))
    found = deployer(center, tmp_path).apply(_all_envelopes(center))
    assert [one.reason for one in found] == ["wrong_target"]
    assert installed(tmp_path / "botui") == []


def test_an_unknown_key_is_refused(center: Center, tmp_path: Path) -> None:
    """Admin 키를 모르면 **설치하지 않는다** (V2)."""
    key = admin_key(center)
    info = approved(center, key)
    center.deploy(deployment(key, info))
    one = deployer(center, tmp_path)
    one.keys = []  # 아직 키를 못 받았다
    found = one.apply(_envelopes(center))
    assert [x.reason for x in found] == ["unknown_key"]


def test_a_scheduled_deployment_waits(center: Center, tmp_path: Path) -> None:
    """**예약은 거부가 아니다** (V5b) — 때가 되면 설치한다."""
    key = admin_key(center)
    info = approved(center, key)
    later = (datetime.fromisoformat(AT) + timedelta(days=1)).isoformat()
    center.deploy(deployment(key, info, not_before=later))

    waiting = deployer(center, tmp_path)
    assert waiting.apply(_envelopes(center)) == [], "기다림은 보고하지 않는다"
    assert installed(tmp_path / "botui") == []

    ready = deployer(center, tmp_path)
    ready.clock = lambda: (datetime.fromisoformat(AT) + timedelta(days=2)).isoformat()
    assert [one.result for one in ready.apply(_envelopes(center))] == [APPLIED]


def test_an_expired_deployment_is_refused(center: Center, tmp_path: Path) -> None:
    key = admin_key(center)
    info = approved(center, key)
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    with pytest.raises(CenterProblem) as caught:
        center.deploy(deployment(key, info, expires_at=past))
    assert caught.value.code == "expired", "Center도 만료를 본다 (V5a)"


def test_a_revoked_package_stops_coming_down(center: Center) -> None:
    """승인이 철회되면 **배포가 더 내려오지 않는다** (C2)."""
    key = admin_key(center)
    info = approved(center, key)
    center.deploy(deployment(key, info))
    assert _envelopes(center)

    center.revoke_package(
        info["id"],
        info["version"],
        sign(
            {"kind": "package_revoke", "id": info["id"], "version": info["version"],
             "reason": "결함", "revoked_at": AT},
            keystore.load(key, passphrase=PASS),
            signed_at=AT,
        ),
    )
    assert _envelopes(center) == []


def test_a_download_failure_is_not_a_refusal(center: Center, tmp_path: Path) -> None:
    """**닿지 못한 것은 거부가 아니다** — 다음 하트비트에 다시 받는다."""
    key = admin_key(center)
    info = approved(center, key)
    center.deploy(deployment(key, info))

    def broken(package_id: str, version: str) -> Path:
        raise RuntimeError("닿지 못했다")

    one = deployer(center, tmp_path)
    one.fetch = broken
    assert one.apply(_envelopes(center)) == [], "기다림이다 (거부로 보고하지 않는다)"


# ─────────────────────────── BUI-04 「출처」 ───────────────────────────
#
# 표식은 **설치하는 쪽이** 남긴다 (`write_source`) — 푸는 것만으로는 배포로 온 것인지
# 사람이 고른 파일인지 알 수 없다. 그래서 표식이 없으면 「알 수 없음」이다.


def _manual(data_dir: Path, tmp_path: Path, name: str = "manual.zip") -> Any:
    """BUI-04 「패키지 파일에서 설치...」가 하는 그대로 — 설치하고 **그 자리가** 적는다."""
    package = tmp_path / name
    package.write_bytes(package_zip())
    bot = install(data_dir, package)
    write_source(bot.folder, MANUAL)
    return bot


def test_a_deployed_bot_says_it_came_from_center(center: Center, tmp_path: Path) -> None:
    """배포로 설치된 것은 「Center 배포」다 — 표식이 봉투 옆에 남는다 (BUI-04)."""
    key = admin_key(center)
    info = approved(center, key)
    center.deploy(deployment(key, info))

    assert [one.result for one in deployer(center, tmp_path).apply(_envelopes(center))] == [APPLIED]
    [bot] = installed(tmp_path / "botui")
    assert bot.source == "Center 배포"
    assert (bot.folder / INSTALL_SOURCE_NAME).is_file(), "표식은 봉투 옆에 있다"
    assert (bot.folder / SIGNATURE_NAME).is_file(), "봉투는 그대로 남는다"
    assert json.loads((bot.folder / INSTALL_SOURCE_NAME).read_text(encoding="utf-8")) == {
        "source": CENTER
    }


def test_a_manually_installed_bot_says_so(tmp_path: Path) -> None:
    """사람이 고른 파일은 「수동 설치」다."""
    data_dir = tmp_path / "botui"
    _manual(data_dir, tmp_path)
    [bot] = installed(data_dir)
    assert bot.source == "수동 설치"


def test_an_unmarked_folder_is_not_called_a_manual_install(tmp_path: Path) -> None:
    """**모르는 것은 「수동 설치」라고 하지 않는다** (`bots.py`의 원칙).

    `install()`만 거친 폴더 — 표식을 남기기 전에 설치된 Bot이 이 꼴이다. 배포로 온 것일
    수도 있으므로 둘 중 하나로 단정하지 않는다.
    """
    data_dir = tmp_path / "botui"
    package = tmp_path / "bare.zip"
    package.write_bytes(package_zip())
    bot = install(data_dir, package)

    assert not (bot.folder / INSTALL_SOURCE_NAME).exists(), "`install()`은 적지 않는다"
    assert bot.source == SOURCE_UNKNOWN == "알 수 없음"
    assert installed(data_dir)[0].source == SOURCE_UNKNOWN, "목록에서도 같다"


@pytest.mark.parametrize(
    "raw",
    ["", "{", "[]", "null", '{"source": ""}', '{"source": "somewhere"}', '"center"'],
    ids=["빈 파일", "깨진 JSON", "목록", "null", "빈 값", "모르는 값", "글자"],
)
def test_a_marker_it_cannot_read_is_unknown_too(tmp_path: Path, raw: str) -> None:
    """읽지 못하는 표식으로 **단정하지 않는다** — 「서명」 칸과 같은 태도다."""
    data_dir = tmp_path / "botui"
    package = tmp_path / "bare.zip"
    package.write_bytes(package_zip())
    bot = install(data_dir, package)
    (bot.folder / INSTALL_SOURCE_NAME).write_text(raw, encoding="utf-8")
    assert bot.source == SOURCE_UNKNOWN


def test_installing_over_a_deployed_bot_rewrites_the_mark(center: Center, tmp_path: Path) -> None:
    """같은 판을 사람이 다시 넣으면 「수동 설치」다 — **폴더에 있는 것은 그 파일이다**."""
    key = admin_key(center)
    info = approved(center, key)
    center.deploy(deployment(key, info))
    data_dir = tmp_path / "botui"
    deployer(center, tmp_path).apply(_envelopes(center))
    assert installed(data_dir)[0].source == "Center 배포"

    _manual(data_dir, tmp_path)  # 같은 id·버전 → 덮어쓴다 (`install`이 먼저 비운다)
    [bot] = installed(data_dir)
    assert bot.source == "수동 설치", "표식도 덮어써야 한다 (옛 표식이 남으면 거짓이 된다)"


def test_a_skipped_deployment_leaves_the_mark_alone(center: Center, tmp_path: Path) -> None:
    """이미 그 판이 있으면 배포는 **조용히 지나간다** — 표식도 그대로다.

    사람이 넣은 파일이 그 폴더에 있는 것이니 「수동 설치」가 맞다 (설치하지 않았으므로).
    """
    key = admin_key(center)
    info = approved(center, key)
    center.deploy(deployment(key, info))
    data_dir = tmp_path / "botui"
    _manual(data_dir, tmp_path)

    assert deployer(center, tmp_path).apply(_envelopes(center)) == [], "이미 그 판이 있다"
    assert installed(data_dir)[0].source == "수동 설치"


def test_the_mark_does_not_make_the_bot_unreadable(tmp_path: Path) -> None:
    """표식은 패키지 안이 아니라 **푼 폴더**에 있다 — 해시·매니페스트를 건드리지 않는다."""
    data_dir = tmp_path / "botui"
    package = tmp_path / "one.zip"
    package.write_bytes(package_zip())
    bot = install(data_dir, package)
    before = bot.content_hash
    write_source(bot.folder, MANUAL)

    [again] = installed(data_dir)
    assert again.id == bot.id and again.version == bot.version
    assert content_hash_zip(package) == before, "zip은 그대로다"


# ─────────────────────────── 명령줄 ───────────────────────────


def test_the_command_signs_and_deploys(center: Center, capsys: Any) -> None:
    key = admin_key(center)
    info = approved(center, key)
    code = admin_main(["-y", "deploy", info["id"], info["version"], "--bot-ui", BOT_UI], center=center)
    assert code == 0
    printed = capsys.readouterr().out
    assert info["content_hash"] in printed and "배포했습니다" in printed
    assert len(center.deployments()) == 1


def test_the_command_refuses_an_unapproved_package(center: Center, capsys: Any) -> None:
    admin_key(center)
    info = upload(center, package_zip())
    assert admin_main(["-y", "deploy", info["id"], info["version"], "--bot-ui", BOT_UI], center=center) == 2
    assert "승인되지 않은" in capsys.readouterr().out


def test_the_command_lists_and_revokes(center: Center, capsys: Any) -> None:
    key = admin_key(center)
    info = approved(center, key)
    center.deploy(deployment(key, info))
    assert admin_main(["deployments"], center=center) == 0
    assert "dep_3f9a1c07" in capsys.readouterr().out

    assert admin_main(["-y", "revoke-deploy", "dep_3f9a1c07"], center=center) == 0
    assert "철회했습니다" in capsys.readouterr().out
    assert center.deployments(active=True) == []


# ─────────────────────────── 하트비트가 나르는 것 ───────────────────────────


def _envelopes(center: Center) -> list[dict[str, Any]]:
    """이 Bot UI에게 내려갈 배포 봉투 (C4) — Center가 고른 그대로."""
    from chaeksas.center.api.deployments import envelopes_for

    return envelopes_for(center.client.app.state.store, target_type="bot_ui", target_id=BOT_UI)


def _all_envelopes(center: Center) -> list[dict[str, Any]]:
    """남의 것까지 — V6을 보려고 일부러 넘긴다."""
    from chaeksas.center.api.deployments import listing

    store = center.client.app.state.store
    out = []
    for one in listing(store):
        row = store.row(
            "SELECT envelope_json FROM deployments WHERE deployment_id = ?", (one.deployment_id,)
        )
        out.append(json.loads(row["envelope_json"]))
    return out


# ─────────────────────────── 하트비트 한 줄 (C4) ───────────────────────────


def test_the_heartbeat_carries_the_envelope_and_keys(center: Center, tmp_path: Path) -> None:
    """**저장된 JSON 그대로** 내려온다 — 다시 직렬화하면 서명이 깨진다 (C4).

    Bot UI가 받은 것을 그대로 `Deployer`에 넘겨 설치되는 것까지 본다.
    """
    from conftest import FakeCredentials

    from chaeksas.bot_ui.agent import Agent
    from chaeksas.bot_ui.settings import Settings as BotSettings
    from chaeksas.bot_ui.store import Store as BotStore
    from chaeksas.contracts.bot_ui import HeartbeatResponse

    key = admin_key(center)
    info = approved(center, key)
    envelope = deployment(key, info)
    center.deploy(envelope)

    # Center가 그 Bot UI에게 줄 것 (하트비트 응답의 `deployments`).
    body = {
        "server_time": AT,
        "deployments": _envelopes(center),
        "admin_keys": [one.to_json_dict() for one in center.admin_keys()],
    }
    response = HeartbeatResponse.model_validate(body)
    assert response.deployments[0]["sig"] == envelope.sig, "봉투 바이트가 그대로다"

    agent = Agent(
        settings=BotSettings(),
        store=BotStore.load(tmp_path / "state.json"),
        credentials=FakeCredentials("chk_ctr_test"),
    )
    agent.store.state.bot_ui_id = BOT_UI
    one = deployer(center, tmp_path)
    agent.deployer = lambda: one  # type: ignore[method-assign]
    agent.apply_deployments(response)

    assert [x.result for x in agent.store.state.pending_deployments] == [APPLIED]
    assert len(agent.store.state.admin_keys) == 1, "키는 바뀔 때만 오고, 없으면 들고 있던 것을 쓴다"
    assert installed(tmp_path / "botui"), "설치됐다"


def test_the_results_ride_the_next_heartbeat(center: Center, tmp_path: Path) -> None:
    """**거부도 보고한다** — 보내고 나면 지운다 (C4 `deployment_results`)."""
    from conftest import FakeCredentials

    from chaeksas.bot_ui.agent import Agent
    from chaeksas.bot_ui.settings import Settings as BotSettings
    from chaeksas.bot_ui.store import Store as BotStore
    from chaeksas.contracts.bot_ui import DeploymentResult

    agent = Agent(
        settings=BotSettings(),
        store=BotStore.load(tmp_path / "state.json"),
        credentials=FakeCredentials("chk_ctr_test"),
    )
    made = DeploymentResult(
        deployment_id="dep_3f9a1c07",
        bpm_process_id="erp.order-entry",
        version="2.1.0",
        result=REJECTED,
        at=AT,
        reason="unsigned_package",
    )
    agent.store.remember_deployments([made])
    request = agent.heartbeat_request()
    assert [one.reason for one in request.deployment_results] == ["unsigned_package"]

    agent.store.deployments_sent(request.deployment_results)
    assert agent.store.state.pending_deployments == [], "보낸 것은 지운다"
