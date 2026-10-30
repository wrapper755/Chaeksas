"""배포 한 바퀴 — 관리자 배포 → Center 서명 → PC 실행기 설치 (C2·C4·C5, M5 조각 2).

**서명이 관문**이라는 것을 끝에서 끝까지 본다. 진짜 Center를 in-process로 띄우고, 관리자가
배포하면 **Center가 제 키로 서명하고**(ADR-0090), 진짜 PC 실행기 쪽 코드가 받아 설치한다.

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
from center_admin import AdminCenter as Center
from center_admin import CenterProblem
from fastapi.testclient import TestClient

from chaeksas.center import signer as center_signer
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings
from chaeksas.contracts.hashing import content_hash_zip
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
BOT_UI = "bui_a81c22d0"
AT = "2026-10-05T09:00:00+09:00"


@pytest.fixture
def center(tmp_path: Path, monkeypatch: Any) -> Any:
    settings = Settings(
        db_path=tmp_path / "center.sqlite3", package_dir=tmp_path / "packages", admin_token=TOKEN
    )
    made = Center(client=TestClient(create_app(settings)), token=TOKEN)
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


def approved(
    center: Center, *, package_id: str = "erp.order-entry", run_location: str = "pc"
) -> dict[str, Any]:
    """업로드 → 승인까지 (봉투는 Center가 짓는다)."""
    info = upload(center, package_zip(package_id, run_location=run_location))
    center.approve(info["id"], info["version"])
    return info


def deploy(
    center: Center, info: dict[str, Any], *, target: str = BOT_UI, target_type: str = "bot_ui", **extra: Any
) -> dict[str, Any]:
    """배포한다 — `deployment_id`는 Center가 짓는다. 돌려주는 것은 C5 `DeploymentInfo`다."""
    return dict(
        center.deploy(
            target={"type": target_type, "id": target},
            bpm_process_id=info["id"],
            version=info["version"],
            **extra,
        )
    )


def sealed(center: Center, info: dict[str, Any], *, deployment_id: str, **over: Any) -> Any:
    """Center 키로 서명한 `deployment` 봉투 — `create`를 **거치지 않고** 지은 것이다.

    옛 DB에 들어 있던 행을 꾸미거나, 같은 봉투를 계약에게 직접 물어 보려고 쓴다.
    """
    payload: dict[str, Any] = {
        "kind": "deployment",
        "deployment_id": deployment_id,
        "target": {"type": over.pop("target_type", "bot_ui"), "id": over.pop("target", BOT_UI)},
        "bpm_process_id": info["id"],
        "version": info["version"],
        "content_hash": over.pop("content_hash", info["content_hash"]),
        **over,
    }
    return center_signer.seal(center.client.app.state.store, payload)


def deployer(center: Center, tmp_path: Path, **extra: Any) -> Deployer:
    """PC 실행기 쪽 — 패키지는 **진짜 Center에서** 받는다."""

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
    info = upload(center, package_zip())
    with pytest.raises(CenterProblem) as caught:
        deploy(center, info)
    assert caught.value.code == "not_approved"


def test_a_deprecated_package_cannot_be_deployed_again(center: Center) -> None:
    """지원 종료가 **새 배포를 막는다** (C5) — 서명은 멀쩡한데도 거부다.

    막는 일에는 봉투가 없다 — 관리자 토큰으로 상태만 옮긴다.
    """
    info = approved(center)
    center.deprecate(info["id"], info["version"])
    with pytest.raises(CenterProblem) as caught:
        deploy(center, info)
    assert caught.value.code == "deprecated"


def test_a_deprecated_package_keeps_running_where_it_is_deployed(center: Center) -> None:
    """지원 종료는 **새 배포만** 막는다 — 이미 배포된 것은 그대로 돈다 (C5 §패키지, 09-gaps §3-22).

    고르는 자리가 모두 `approved` 하나로 걸러, 누르는 순간 봉투가 하트비트에서 사라지고 작업·
    위임·내려받기가 그 판을 「배포되지 않음」으로 봤다. 고르는 조건은 이제 `live_sql` 하나다.
    """
    from chaeksas.center.api import deployments as deployments_api

    store = center.client.app.state.store
    pc = approved(center)
    server = approved(center, package_id="erp.night-close", run_location="server")
    deploy(center, pc)
    runner = center.client.post(
        "/api/v1/center-keys", json={"name": "서버 1", "type": "server_runner"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    ).json()["key"]
    registered = center.client.post(
        "/api/v1/server-runner/register",
        json={"schema": 1, "machine_id": "7" * 64, "name": "서버 1", "os": "Linux",
              "versions": {"server_runner": "0.1.0", "core": "0.1.0"}, "max_concurrency": 2},
        headers={"Authorization": f"Bearer {runner}"},
    )
    assert registered.status_code < 400, registered.text
    deploy(center, server, target_type="server_runner", target=registered.json()["server_runner_id"])
    before = _envelopes(center)

    for info in (pc, server):
        center.deprecate(info["id"], info["version"])

    # 하트비트 봉투(C4)는 같은 것이 그대로 내려간다.
    assert _envelopes(center) == before and len(before) == 1
    # 작업 지시(C5 `/jobs`)가 판을 푼다 — `version`을 비워도 Center가 채운다.
    job = center.client.post(
        "/api/v1/jobs",
        json={"bpm_process_id": pc["id"], "target": {"type": "bot_ui", "id": BOT_UI}, "inputs": {}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert job.status_code == 201, job.text
    assert job.json()["version"] == pc["version"]
    assert deployments_api.server_versions(store, bpm_process_id=server["id"]) == [server["version"]]
    # PC 위임이 고르는 PC(C12)도 그대로다.
    assert deployments_api.targets_for(
        store, bpm_process_id=pc["id"], version=pc["version"], target_type="bot_ui"
    ) == [BOT_UI]
    assert deployments_api.versions_deployed_to(
        store, bpm_process_id=pc["id"], target_type="bot_ui"
    ) == [pc["version"]]
    # 내려받기도 된다 — 다시 설치해야 하는 PC가 있다.
    auth = {"Authorization": f"Bearer {center.client.app.state.bot_ui_key}"}
    assert center.client.get(f"/api/v1/packages/{pc['id']}/{pc['version']}", headers=auth).status_code == 200
    # 새 배포만 막힌다.
    with pytest.raises(CenterProblem) as caught:
        deploy(center, pc)
    assert caught.value.code == "deprecated"


def test_deploying_twice_makes_two_deployments(center: Center) -> None:
    """같은 배포를 두 번 누르면 **두 배포**다 — `deployment_id`를 Center가 새로 짓는다 (ADR-0090 §6).

    막을 일은 아니다 — 하나를 철회해도 다른 하나가 남아 그 PC에 그대로 간다.
    """
    info = approved(center)
    first = deploy(center, info)
    again = deploy(center, info)
    assert first["deployment_id"] != again["deployment_id"]
    assert all(one["deployment_id"].startswith("dep_") for one in (first, again))
    assert len(center.deployments()) == 2


def test_a_wildcard_pc_deployment_is_not_even_kept(center: Center) -> None:
    """**PC 배포에 전체(`*`) 대상은 없다** (ADR-0046) — 받아 두지도 않는다.

    받아 두면 Center가 모든 PC에 내려 주고 **모든 PC가 V6 `wrong_target`으로 거부해** CON-03이
    거짓 ⛔로 찬다. 그때 운영자가 뒤지는 것은 승인·해시·키인데 **막은 것은 대상**이다.
    """
    info = approved(center)
    with pytest.raises(CenterProblem) as caught:
        deploy(center, info, target="*")
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

    info = approved(center)
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
                json.dumps(
                    sealed(center, info, deployment_id="dep_old00001", target="*").to_json_dict(),
                    ensure_ascii=False,
                ),
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
    """**철회된 것은 영구히 철회 상태**다 (C2) — 다시 철회해도 그대로이고 더 내려가지 않는다."""
    info = approved(center)
    made = deploy(center, info)
    assert _envelopes(center)
    first = center.revoke_deployment(made["deployment_id"], reason="잘못")
    again = center.revoke_deployment(made["deployment_id"], reason="또")
    assert first["revoked_at"] and again["revoked_at"] == first["revoked_at"], "멱등이다"
    assert _envelopes(center) == [], "철회된 배포는 내려가지 않는다"
    assert center.deployments(active=True) == []


def test_a_pc_package_cannot_go_to_a_server_runner(center: Center) -> None:
    """`run_location`과 대상이 맞아야 한다 (C2 §배포 대상 규칙).

    코드는 **`wrong_target`(409) 하나**다 (ADR-0047) — 계약도 그 이름으로 말한다.
    `target_mismatch`는 작업 쪽(모르는 대상 종류)에만 남았다.
    """
    info = approved(center)
    with pytest.raises(CenterProblem) as caught:
        deploy(center, info, target_type="server_runner", target="*")
    assert (caught.value.status, caught.value.code) == (409, "wrong_target")


def test_a_server_deployment_is_taken_now_that_m7_is_open(center: Center) -> None:
    """**서버 실행기 배포를 이제 받는다** (M7 — 스위치를 켰다).

    켜기 전에는 422 `server_runner_not_available`이었다 (내려 줄 실행기가 없는 배포가 표에
    남으면 `GET /deployments`를 보는 운영자가 돌 것이라고 읽는다). 이제 실행기가 등록하고
    설치하고 **돌린다** — 관문은 서명·승인·대상뿐이다 (ADR-0047의 그 함수 하나).
    """
    info = approved(center, package_id="erp.night-close", run_location="server")
    assert deploy(center, info, target_type="server_runner", target="srv_1")
    listed = center.deployments(active=False)
    assert [one["target"]["type"] for one in listed] == ["server_runner"]


def test_an_unregistered_pc_cannot_be_deployed_to(center: Center) -> None:
    """**등록되지 않은 PC에는 배포하지 않는다** (ADR-0049) — 404 `target_not_found`.

    받아 두면 **아무에게도 가지 않는 배포**가 표에 남는다 — `envelopes_for`는 `target_id`로
    맞추고, CON-03에는 그 PC 줄이 없어 보여 줄 자리조차 없다. 「미리 배포해 두기」를 막는 것이
    아니다: `bot_ui_id`는 Center가 등록에서 만들어 등록 전에는 봉투에 적을 id가 없다.
    """
    info = approved(center)
    with pytest.raises(CenterProblem) as caught:
        deploy(center, info, target="bui_00000000")
    assert (caught.value.status, caught.value.code) == (404, "target_not_found")
    assert center.deployments(active=False) == [], "행조차 남지 않는다"

    # 등록된 PC에는 그대로 간다 — 막는 것은 **명부에 없는 id**뿐이다.
    deploy(center, info, target=BOT_UI)
    assert [one["target"]["id"] for one in center.deployments(active=True)] == [BOT_UI]


def test_a_wrong_target_is_answered_before_a_missing_one(center: Center) -> None:
    """**「대상이 틀렸다」가 「대상이 없다」를 이긴다** (ADR-0049).

    PC 배포의 `"*"`는 등록된 id가 아니지만, 운영자가 할 일은 「대상을 하나 적는다」다 (ADR-0046)
    — 404로 답하면 있지도 않은 「`*`라는 PC」를 찾는다.
    """
    info = approved(center)
    with pytest.raises(CenterProblem) as caught:
        deploy(center, info, target="*")
    assert (caught.value.status, caught.value.code) == (409, "wrong_target")


def test_center_refuses_exactly_what_the_contract_refuses(center: Center) -> None:
    """**관문이 하나다** (ADR-0047) — Center의 `(상태, 코드)`가 계약의 것과 **규칙마다** 같다.

    두 벌이던 때 대상 어긋남이 한쪽에서 `target_mismatch`(422), 다른 쪽에서 `wrong_target`(409)
    이었고 서버 배포 관문은 계약에만 있었다. 베낀 것이 아니라 **같은 함수**를 부르는지 보려고
    Center가 지을 것과 같은 봉투를 계약에게도 물어 본다.
    """
    from chaeksas.center.api import bot_ui as bot_ui_api
    from chaeksas.contracts.center_api import (
        DEPLOYMENT_REFUSAL_STATUS,
        PackageInfo,
        deployment_refusal,
        validate_deployment,
    )

    keys = center.admin_keys()
    pc = approved(center)
    server = approved(center, package_id="erp.night-close", run_location="server")
    other = upload(center, package_zip("erp.not-approved"))  # 승인하지 않는다
    old = approved(center, package_id="erp.old")
    center.deprecate(old["id"], old["version"])

    tried: tuple[tuple[dict[str, Any], dict[str, Any]], ...] = (
        (other, {}),
        (old, {}),
        (pc, {"target": "*"}),
        (pc, {"target_type": "server_runner", "target": "srv_1"}),
        (pc, {"target": "bui_00000000"}),
    )
    store = center.client.app.state.store
    seen = set()
    for info, over in tried:
        envelope = sealed(center, info, deployment_id="dep_00000001", **over)
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
        assert said is not None, f"계약이 거절하지 않았다: {info['id']} {over}"
        with pytest.raises(CenterProblem) as caught:
            deploy(center, info, **over)
        assert (caught.value.status, caught.value.code) == (said[0], said[1].code), (info["id"], over)
        seen.add(caught.value.code)
    # **규칙마다** 봤다는 것까지 — 하나로 뭉쳐도 통과하면 「맞물린다」를 증명하지 못한다.
    #
    # 둘이 빠진다. `server_runner_not_available` — **스위치를 켰으므로**(M7) HTTP 길로는 그 코드를
    # 낼 수 없다. 표에는 남아 있다 (끌 수 있는 값이면 상태도 있어야 한다 — `test_center_api.py`가
    # 끈 길을 본다). `hash_mismatch` — **해시는 Center가 패키지에서 채운다**(ADR-0090) — 요청에
    # 해시를 적을 칸이 없어 어긋날 수가 없다. 계약 쪽은 `test_contracts_center_api.py`가 본다.
    assert seen == set(DEPLOYMENT_REFUSAL_STATUS) - {"server_runner_not_available", "hash_mismatch"}

    assert center.deployments(active=False) == [], "거절한 것은 하나도 남지 않는다"

    # 거꾸로도 본다 — **서버 패키지를 서버 실행기에 배포하는 것은 이제 통과한다** (M7).
    made = deploy(center, server, target_type="server_runner", target="srv_1")
    assert [one["deployment_id"] for one in center.deployments(active=False)] == [made["deployment_id"]]


def test_the_listing_answers_in_the_contract_shape(center: Center) -> None:
    """`GET /deployments`는 C5 `DeploymentInfo`다 — **서명자·유효 기간은 봉투에서 읽는다**.

    CON-03 「배포」가 유효 기간을 그리려면 이것이 있어야 한다.
    """
    from chaeksas.contracts.center_api import DeploymentInfo

    info = approved(center)
    until = "2027-01-01T00:00:00+09:00"
    deploy(center, info, expires_at=until)

    found = DeploymentInfo.model_validate(center.deployments()[0])
    assert found.signed_by == center_signer.current_key_id(center.client.app.state.store), "Center 키"
    assert found.signed_at
    assert found.deployed_by, "누가 배포했는지는 계정·행위자 이름으로 남는다 (ADR-0090 §6)"
    assert found.expires_at == until and found.not_before is None
    assert found.revoked_at is None and found.last_result is None


def test_a_revoked_deployment_keeps_its_row_with_a_time(center: Center) -> None:
    """철회해도 **행은 남는다** — 「언제 철회됐나」가 콘솔에 보여야 한다 (C5)."""
    info = approved(center)
    made = deploy(center, info)
    center.revoke_deployment(made["deployment_id"], reason="잘못")
    assert center.deployments(active=True) == []
    [one] = center.deployments(active=False)
    assert one["revoked_at"]


def test_a_bot_ui_key_downloads_only_what_is_deployed_to_it(center: Center) -> None:
    """내려받기 관문 (C5 권한표) — **자기 배포분만**이다.

    배포를 철회하면 **그 자리에서 닫힌다** — 키는 그대로인데 받을 수 있는 것이 달라진다.
    """
    mine = approved(center)
    other = approved(center, package_id="erp.payment")

    auth = {"Authorization": f"Bearer {center.client.app.state.bot_ui_key}"}

    made = deploy(center, mine, target=BOT_UI)
    for info, expected in ((mine, 200), (other, 403)):
        answer = center.client.get(
            f"/api/v1/packages/{info['id']}/{info['version']}", headers=auth
        )
        assert answer.status_code == expected, (info["id"], answer.text)

    center.revoke_deployment(made["deployment_id"], reason="잘못")
    closed = center.client.get(f"/api/v1/packages/{mine['id']}/{mine['version']}", headers=auth)
    assert closed.status_code == 403


def test_a_bot_ui_key_gets_only_the_package_deployed_to_it(center: Center) -> None:
    """실행하는 쪽이 받는 것은 **자기에게 배포된 BPM 프로세스 패키지뿐**이다 (C5 권한표).

    쓰는 공유 BPM 프로세스도 따로 받지 않는다 — 그것은 패키지 안 `libs/`로 **복사해 넣은**
    것이다 (C1 §패키지 구성). 도구 묶음은 패키지로 오지 않는다 (ADR-0050).
    """
    lib = upload(center, lib_zip())
    info = upload(
        center,
        package_zip(requires={"libs": [f"{lib['id']}@{lib['version']}"]}),
    )
    center.approve(info["id"], info["version"])

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
    deploy(center, info, target=registered.json()["bot_ui_id"])
    assert center.client.get(
        f"/api/v1/packages/{info['id']}/{info['version']}", headers=auth
    ).status_code == 200
    # 「없다」와 「내 것이 아니다」는 같은 403이다 — 404로 가르면 그것이 곧 목록이 된다.
    assert center.client.get(
        f"/api/v1/packages/{lib['id']}/{lib['version']}", headers=auth
    ).status_code == 403


# ─────────────────────────── PC 실행기 설치 (C2 V1~V7) ───────────────────────────


def test_a_signed_deployment_installs(center: Center, tmp_path: Path) -> None:
    """한 바퀴 — Admin 서명 → Center → **설치**."""
    info = approved(center)
    deploy(center, info)

    found = deployer(center, tmp_path).apply(_envelopes(center))
    assert [one.result for one in found] == [APPLIED]
    bots = installed(tmp_path / "botui")
    assert [(one.id, one.version) for one in bots] == [("erp.order-entry", "2.1.0")]
    assert "승인됨" in bots[0].signature, "설치된 것에 봉투가 남는다 (BUI-04 「서명」)"


def test_installing_twice_does_nothing(center: Center, tmp_path: Path) -> None:
    info = approved(center)
    deploy(center, info)
    one = deployer(center, tmp_path)
    assert len(one.apply(_envelopes(center))) == 1
    assert one.apply(_envelopes(center)) == [], "이미 설치돼 있으면 조용히 지나간다"


def test_an_unsigned_package_is_refused(center: Center, tmp_path: Path) -> None:
    """**서명 없는 패키지는 설치하지 않는다** (V7) — 거부도 보고한다."""
    info = approved(center)
    deploy(center, info)

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
    info = approved(center)
    other_pc = "bui_b70d1104"
    register_pc(center, monkeypatch, other_pc, machine="7" * 64, name="현장 PC 2")

    deploy(center, info, target=other_pc)
    found = deployer(center, tmp_path).apply(_all_envelopes(center))
    assert [one.reason for one in found] == ["wrong_target"]
    assert installed(tmp_path / "botui") == []


def test_an_unknown_key_is_refused(center: Center, tmp_path: Path) -> None:
    """Admin 키를 모르면 **설치하지 않는다** (V2)."""
    info = approved(center)
    deploy(center, info)
    one = deployer(center, tmp_path)
    one.keys = []  # 아직 키를 못 받았다
    found = one.apply(_envelopes(center))
    assert [x.reason for x in found] == ["unknown_key"]


def test_a_scheduled_deployment_waits(center: Center, tmp_path: Path) -> None:
    """**예약은 거부가 아니다** (V5b) — 때가 되면 설치한다."""
    info = approved(center)
    later = (datetime.fromisoformat(AT) + timedelta(days=1)).isoformat()
    deploy(center, info, not_before=later)

    waiting = deployer(center, tmp_path)
    assert waiting.apply(_envelopes(center)) == [], "기다림은 보고하지 않는다"
    assert installed(tmp_path / "botui") == []

    ready = deployer(center, tmp_path)
    ready.clock = lambda: (datetime.fromisoformat(AT) + timedelta(days=2)).isoformat()
    assert [one.result for one in ready.apply(_envelopes(center))] == [APPLIED]


def test_an_expired_deployment_is_refused(center: Center, tmp_path: Path) -> None:
    info = approved(center)
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    with pytest.raises(CenterProblem) as caught:
        deploy(center, info, expires_at=past)
    assert caught.value.code == "expired", "Center도 만료를 본다 (V5a)"


def test_a_revoked_package_stops_coming_down(center: Center) -> None:
    """승인이 철회되면 **배포가 더 내려오지 않는다** (C2)."""
    info = approved(center)
    deploy(center, info)
    assert _envelopes(center)

    center.revoke_package(info["id"], info["version"], reason="결함")
    assert _envelopes(center) == []
    with pytest.raises(CenterProblem) as caught:
        center.approve(info["id"], info["version"])
    assert caught.value.status == 409, "철회된 승인은 되살아나지 않는다 (C2)"


def test_a_retired_signing_key_makes_the_field_refuse(center: Center, tmp_path: Path) -> None:
    """Center 키를 **버리면** 그 키가 서명한 배포를 현장이 거부한다 (C2 V2 `revoked_key`, ADR-0090 §5).

    사람이 Admin 키를 철회하던 자리다. 버리기 전에 바꿔야 한다 — 지금 서명하는 키는 버릴 수
    없다(잠기면 아무것도 서명하지 못한다).
    """
    store = center.client.app.state.store
    info = approved(center)
    deploy(center, info)
    old = center_signer.current_key_id(store)
    with pytest.raises(ValueError):
        center_signer.retire(store, old)

    center_signer.rotate(store)
    center_signer.retire(store, old)
    found = deployer(center, tmp_path).apply(_envelopes(center))
    assert [x.reason for x in found] == ["revoked_key"]
    assert installed(tmp_path / "botui") == []


def test_a_download_failure_is_not_a_refusal(center: Center, tmp_path: Path) -> None:
    """**닿지 못한 것은 거부가 아니다** — 다음 하트비트에 다시 받는다."""
    info = approved(center)
    deploy(center, info)

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
    info = approved(center)
    deploy(center, info)

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

    `install()`만 거친 폴더 — 표식을 남기기 전에 설치된 BPM 프로세스가 이 꼴이다. 배포로 온 것일
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
    info = approved(center)
    deploy(center, info)
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
    info = approved(center)
    deploy(center, info)
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


# ─────────────────────────── 하트비트가 나르는 것 ───────────────────────────


def _envelopes(center: Center) -> list[dict[str, Any]]:
    """이 PC 실행기에게 내려갈 배포 봉투 (C4) — Center가 고른 그대로."""
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

    PC 실행기가 받은 것을 그대로 `Deployer`에 넘겨 설치되는 것까지 본다.
    """
    from conftest import FakeCredentials

    from chaeksas.bot_ui.agent import Agent
    from chaeksas.bot_ui.settings import Settings as BotSettings
    from chaeksas.bot_ui.store import Store as BotStore
    from chaeksas.contracts.bot_ui import HeartbeatResponse

    info = approved(center)
    made = deploy(center, info)
    store = center.client.app.state.store
    row = store.row("SELECT envelope_json FROM deployments WHERE deployment_id = ?", (made["deployment_id"],))
    stored = json.loads(row["envelope_json"])

    # Center가 그 PC 실행기에게 줄 것 (하트비트 응답의 `deployments`).
    body = {
        "server_time": AT,
        "deployments": _envelopes(center),
        "admin_keys": [one.to_json_dict() for one in center.admin_keys()],
    }
    response = HeartbeatResponse.model_validate(body)
    assert response.deployments[0]["sig"] == stored["sig"], "봉투 바이트가 그대로다"

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


# ─────────────────────── 목록과 설치를 맞춘다 (C2 §검증 규칙, ADR-0113) ───────────────────────


def _installed_one(center: Center, tmp_path: Path, **extra: Any) -> tuple[Deployer, dict[str, Any], dict[str, Any]]:
    """배포 → 설치 → 맞추기 한 번. `(현장, 패키지, 배포)`."""
    info = approved(center)
    made = deploy(center, info, **extra)
    field = deployer(center, tmp_path)
    envelopes = _envelopes(center)
    assert [x.result for x in field.apply(envelopes)] == [APPLIED]
    assert field.reconcile(envelopes) == []
    return field, info, made


def _finding(field: Deployer, *, now: str | None = None) -> str | None:
    from chaeksas.core.deploy import deployment_finding

    [bot] = installed(field.data_dir)
    found = deployment_finding(bot, now=now or AT)
    return found.id if found is not None else None


def test_a_revoked_deployment_turns_the_install_off(center: Center, tmp_path: Path) -> None:
    """배포를 철회하면 **다음 하트비트에서** 「실행 불가」다 — 파일은 그대로다 (C2 §검증 규칙)."""
    from chaeksas.core.deploy import DEPLOYMENT_WITHDRAWN, read_standing

    field, _, made = _installed_one(center, tmp_path)
    assert _finding(field) is None
    [bot] = installed(field.data_dir)
    assert read_standing(bot.folder).deployment_ids == (made["deployment_id"],)  # type: ignore[union-attr]

    center.revoke_deployment(made["deployment_id"], reason="결함")
    gone = field.reconcile(_envelopes(center))
    assert [one.id for one in gone] == [bot.id]
    assert _finding(field) == DEPLOYMENT_WITHDRAWN
    assert installed(field.data_dir), "파일은 지우지 않는다"
    assert field.reconcile(_envelopes(center)) == [], "빠졌다고는 한 번만 말한다"


def test_a_revoked_approval_turns_the_install_off_too(center: Center, tmp_path: Path) -> None:
    from chaeksas.core.deploy import DEPLOYMENT_WITHDRAWN

    field, info, _ = _installed_one(center, tmp_path)
    center.revoke_package(info["id"], info["version"], reason="결함")
    field.reconcile(_envelopes(center))
    assert _finding(field) == DEPLOYMENT_WITHDRAWN


def test_a_retired_signing_key_turns_the_install_off(center: Center, tmp_path: Path) -> None:
    """서명 키를 버린 것도 같은 길이다 — 봉투가 목록에 있어도 V2로 덮지 못한다 (C2)."""
    from chaeksas.core.deploy import DEPLOYMENT_WITHDRAWN

    field, _, _ = _installed_one(center, tmp_path)
    store = center.client.app.state.store
    old = center_signer.current_key_id(store)
    center_signer.rotate(store)
    center_signer.retire(store, old)
    field.keys = center.admin_keys()
    field.reconcile(_envelopes(center))
    assert _finding(field) == DEPLOYMENT_WITHDRAWN


def test_a_deprecated_package_stays_on_in_the_field(center: Center, tmp_path: Path) -> None:
    """지원 종료는 현장을 끄지 않는다 — 봉투가 그대로 내려오기 때문이다 (C5, §3-22)."""
    field, info, _ = _installed_one(center, tmp_path)
    center.deprecate(info["id"], info["version"])
    assert field.reconcile(_envelopes(center)) == []
    assert _finding(field) is None


def test_deploying_the_same_version_again_turns_it_back_on(center: Center, tmp_path: Path) -> None:
    """철회된 배포가 되살아나는 것이 아니라 **새 배포가 덮는다**."""
    field, info, made = _installed_one(center, tmp_path)
    center.revoke_deployment(made["deployment_id"], reason="잘못")
    field.reconcile(_envelopes(center))
    deploy(center, info)
    field.reconcile(_envelopes(center))
    assert _finding(field) is None


def test_without_keys_nothing_is_reconciled(center: Center, tmp_path: Path) -> None:
    """서명을 볼 수 없으면 맞추지 않는다 — 맞추면 모든 설치가 빠진다."""
    field, _, _ = _installed_one(center, tmp_path)
    field.keys = []
    assert field.reconcile([]) == []
    assert _finding(field) is None


def test_the_field_sees_the_expiry_without_center(center: Center, tmp_path: Path) -> None:
    """기한은 표식으로 **현장이 혼자** 본다 — Center에 닿지 않아도 지나면 「실행 불가」다."""
    from chaeksas.core.deploy import DEPLOYMENT_EXPIRED

    ends = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    field, _, _ = _installed_one(center, tmp_path, expires_at=ends)
    assert _finding(field) is None
    later = (datetime.now(UTC) + timedelta(days=31)).isoformat()
    assert _finding(field, now=later) == DEPLOYMENT_EXPIRED


def test_a_manual_install_is_not_governed_by_the_list(tmp_path: Path) -> None:
    """「수동 설치」는 Center 목록이 들인 것이 아니다 (ADR-0113 §3)."""
    data = tmp_path / "botui"
    _manual(data, tmp_path)
    field = Deployer(data_dir=data, host_id=BOT_UI, keys=[object()], clock=lambda: AT)  # type: ignore[list-item]
    assert field.reconcile([]) == []
    assert _finding(field) is None


def test_the_pc_runner_refuses_a_withdrawn_bot_and_says_so(center: Center, tmp_path: Path) -> None:
    """한 바퀴 — 하트비트가 **답한** 빈 목록 → 알림 · `readiness` · BUI-04 「지금 실행...」 거절."""
    from conftest import FakeCredentials

    from chaeksas.bot_ui.agent import Agent
    from chaeksas.bot_ui.main_window import readiness_label
    from chaeksas.bot_ui.notices import DEPLOYMENT_WITHDRAWN as NOTICE
    from chaeksas.bot_ui.settings import Settings as BotSettings
    from chaeksas.bot_ui.settings import data_dir
    from chaeksas.bot_ui.store import Store as BotStore
    from chaeksas.contracts.bot_ui import HeartbeatResponse
    from chaeksas.core.deploy import DEPLOYMENT_WITHDRAWN

    info = approved(center)
    made = deploy(center, info)
    agent = Agent(
        settings=BotSettings(),
        store=BotStore.load(tmp_path / "state.json"),
        credentials=FakeCredentials("chk_ctr_test"),
    )
    agent.store.state.bot_ui_id = BOT_UI
    field = deployer(center, tmp_path)
    field.data_dir = data_dir()
    agent.deployer = lambda: field  # type: ignore[method-assign]
    keys = [one.to_json_dict() for one in center.admin_keys()]

    def beat() -> None:
        agent.apply_deployments(
            HeartbeatResponse.model_validate({"server_time": AT, "deployments": _envelopes(center), "admin_keys": keys})
        )

    beat()
    [ready] = agent.readiness()
    assert ready.ready

    center.revoke_deployment(made["deployment_id"], reason="결함")
    beat()
    [ready] = agent.readiness()
    assert not ready.ready and ready.blocked[0] == DEPLOYMENT_WITHDRAWN
    assert [n.kind for n in agent.notices.take()].count(NOTICE) == 1
    [bot] = installed(data_dir())
    assert readiness_label(agent.preflight(bot))[0] == "배포 철회"
    with pytest.raises(RuntimeError, match="철회"):
        agent.enqueue_manual(info["id"], version=info["version"])
    assert agent.queue == []
