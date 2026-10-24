"""서버 실행기가 배포를 받아 설치하고 준비 상태를 보고한다 (C2 V1~V7, C12, M7 조각 3).

**한 줄로 본다**: 관리자가 배포 → 진짜 Center가 서명(ADR-0090) → 실행기의 `agent.tick()`이 받아
설치 → 다음 하트비트에 `deployment_results`·`readiness`가 올라간다.

`core.deploy`·`core.packages`는 Bot UI와 **같은 코드**다(`tests/test_m5_deploy.py`가 PC 쪽을
본다). 그러므로 여기서 보는 것은 **서버 쪽에서만 다른 것**이다.

| 다른 것 | 왜 |
| --- | --- |
| `host_kind = "server_runner"` | `"*"` 대상 배포를 받는다 (ADR-0046 — PC에는 전체 대상이 없다) |
| 공개키가 없으면 설치하지 않는다 | 서명을 볼 수 없는데 설치하면 관문이 없는 것과 같다 |
| 배치 결정을 **들고 있다** | 한 주기만 올라가는 값이라 못 올리면 사유가 영영 안 남는다 |
| 준비 상태는 **서버를 부르지 않는다** | 하트비트마다 돈다 (ADR-0013) |
"""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import center_admin
import pytest
from fastapi.testclient import TestClient

from chaeksas.center import signer as center_signer
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.hashing import MANIFEST_NAME, content_hash_zip
from chaeksas.contracts.signing import sign
from chaeksas.core.packages import CENTER, INSTALL_SOURCE_NAME, SOURCE_LABELS, installed
from chaeksas.server_runner import agent as agent_mod
from chaeksas.server_runner.center_client import CenterClient
from chaeksas.server_runner.credentials import Credentials
from chaeksas.server_runner.settings import Settings

ADMIN = {"Authorization": "Bearer t-admin"}
READ = {"Authorization": "Bearer t-read"}
AT = "2026-10-13T09:00:00+09:00"
BOT = "finance.invoice-issue"


@pytest.fixture(autouse=True)
def _server_runner_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """서버 대상 배포를 **이 시험에서만** 받게 한다.

    `SERVER_RUNNER_AVAILABLE`은 `validate_deployment`의 **기본 인자**로 굳어 있어(정의할 때
    평가된다) 상수를 패치해도 닿지 않는다 — 그래서 부르는 자리를 감싼다. 제품의 스위치는
    그대로 꺼져 있고, 켜는 것은 실행이 붙는 조각의 일이다 (ADR-0016·0047).
    """
    from chaeksas.center.api import deployments as deployments_api
    from chaeksas.contracts.center_api import validate_deployment

    def allowed(*args: Any, **kwargs: Any) -> Any:
        return validate_deployment(*args, **{**kwargs, "server_runner_available": True})

    monkeypatch.setattr(deployments_api, "validate_deployment", allowed)


@pytest.fixture
def store() -> Iterator[Store]:
    found = Store(Path(":memory:"))
    yield found
    found.close()


@pytest.fixture
def center(store: Store, tmp_path: Path) -> Iterator[TestClient]:
    settings = CenterSettings(
        admin_token="t-admin", read_token="t-read", package_dir=tmp_path / "pkg"
    )
    with TestClient(create_app(settings, store=store)) as found:
        yield found


@pytest.fixture
def key(center: TestClient) -> str:
    response = center.post(
        "/api/v1/center-keys", json={"name": "서버 1", "type": "server_runner"}, headers=ADMIN
    )
    assert response.status_code == 201, response.text
    return str(response.json()["key"])


@pytest.fixture
def runner(tmp_path: Path, key: str, center: TestClient) -> agent_mod.Agent:
    settings = Settings(center_url="http://center", name="서버 1", data_path=tmp_path / "runner")
    settings.data_path.mkdir(parents=True, exist_ok=True)
    return agent_mod.Agent(
        settings=settings,
        client=CenterClient(base_url="http://center", api_key=key, client=center),
    )


# ─────────────────────────── 거리 ───────────────────────────


def package_zip(*, package_id: str = BOT, version: str = "1.0.0", requires: Any = None) -> bytes:
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": package_id,
        "version": version,
        "name": "청구서 발행",
        "run_location": "server",
        "entry": "process/main.bpmn",
        "process_id": "Proc_invoice",
        "requires": requires or {},
        "human": {},
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        # `_zipped`가 **실제 해시로** 채운다 (C2 — Center가 R6으로 대조한다).
        "content_hash": "sha256:" + "0" * 64,
    }
    return _zipped(manifest, {"process/main.bpmn": "<definitions/>"})


def _zipped(manifest: dict[str, Any], files: dict[str, str]) -> bytes:
    """`content_hash`는 **자기 자신을 뺀** 내용의 해시다 (C2) — 두 번 만들어 채운다.

    Center가 R6으로 대조하므로 자리만 채운 값으로는 업로드가 422다.
    """

    def made(body: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, text in files.items():
                archive.writestr(name, text)
            archive.writestr(MANIFEST_NAME, body)
        return out.getvalue()

    with tempfile.TemporaryDirectory() as folder:
        staged = Path(folder) / "p.zip"
        staged.write_bytes(made(json.dumps(manifest, ensure_ascii=False)))
        manifest["content_hash"] = content_hash_zip(staged)
    return made(json.dumps(manifest, ensure_ascii=False))


def approved(center: TestClient, **extra: Any) -> dict[str, Any]:
    """업로드 → 승인까지 (C2 — 봉투는 Center가 짓는다)."""
    response = center.post(
        "/api/v1/packages",
        files={"file": ("p.zip", package_zip(**extra), "application/zip")},
        headers=ADMIN,
    )
    assert response.status_code in (200, 201), response.text
    info = dict(response.json())
    center_admin.approve(center, info["id"], info["version"])
    return info


def deploy(center: TestClient, info: dict[str, Any], *, target: str, **extra: Any) -> Any:
    """서버 실행기에 배포한다 (C5 — Center가 봉투를 지어 서명한다). 응답을 그대로 돌려준다."""
    return center_admin.deploy(
        center,
        target={"type": "server_runner", "id": target},
        bpm_process_id=info["id"],
        version=info["version"],
        expect=None,
        **extra,
    )


def deployed(
    center: TestClient,
    store: Store,
    runner: agent_mod.Agent,
    *,
    target: str | None = None,
    **extra: Any,
) -> Any:
    """등록 → 승인 → 배포까지 세워 둔다. 돌려주는 것은 배포 응답이다."""
    runner.tick()  # 등록 — `server_runner_id`를 받는다
    info = approved(center)
    return deploy(center, info, target=target or runner.server_runner_id, **extra)


# ─────────────────────────── 한 줄 ───────────────────────────


def test_a_signed_deployment_is_installed(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """서명 → Center → 실행기 설치 → 다음 하트비트에 `applied`가 올라간다."""
    response = deployed(center, store, runner)
    assert response.status_code in (200, 201), response.text

    # 첫 하트비트: 공개키와 배포 봉투를 함께 받아 설치한다.
    assert runner.tick() is True
    bots = installed(runner.settings.data_path)
    assert [(b.id, b.version) for b in bots] == [(BOT, "1.0.0")]
    # **배포로 온 것은 배포가 적는다** (「출처」 표식) — 푸는 것만으로는 알 수 없다.
    assert (bots[0].folder / INSTALL_SOURCE_NAME).is_file()
    assert bots[0].source == SOURCE_LABELS[CENTER]

    # 배치 결정은 **다음** 하트비트에 올라간다 (설치한 주기에는 이미 본문을 보냈다).
    assert [r.result for r in runner.pending_results] == ["applied"]
    assert runner.tick() is True
    assert runner.pending_results == [], "올렸으면 비운다"

    listed = center.get("/api/v1/server-runners", headers=READ).json()[0]
    # **Center가 쌓아 둔다** — 한 주기만 올라오는 값이라 흘려보내면 사유가 영영 안 남는다.
    assert [r["result"] for r in listed["deployment_results"]] == ["applied"]
    assert [r["bpm_process_id"] for r in listed["readiness"]] == [BOT]
    assert listed["readiness"][0]["ready"] is True


def test_a_wildcard_deployment_reaches_the_runner(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """**`"*"` 대상은 서버 실행기만 쓴다** (ADR-0046) — PC에는 전체 대상이 없다."""
    response = deployed(center, store, runner, target="*")
    assert response.status_code in (200, 201), response.text

    runner.tick()
    assert [b.id for b in installed(runner.settings.data_path)] == [BOT]


# ─────────────────────────── 동시 실행 상한 (C2 `max_concurrency`) ───────────────────────────


def test_a_server_deployment_carries_its_concurrency_limit(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """서버 배포는 **동시 실행 상한**을 싣는다 — 실행기 전체(`"*"`)에도 하나에도 (C2·C12 §3)."""
    response = deployed(center, store, runner, target="*", max_concurrency=3)
    assert response.status_code in (200, 201), response.text

    listed = center.get("/api/v1/deployments", headers=ADMIN).json()
    assert [(one["target"], one.get("max_concurrency")) for one in listed] == [
        ({"type": "server_runner", "id": "*"}, 3)
    ]
    runner.tick()
    assert [b.id for b in installed(runner.settings.data_path)] == [BOT], "실행기가 받아 설치한다"


def test_a_limit_left_out_is_the_default(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    response = deployed(center, store, runner)
    assert response.status_code in (200, 201), response.text
    listed = center.get("/api/v1/deployments", headers=ADMIN).json()
    assert [one["target"]["id"] for one in listed] == [runner.server_runner_id]
    assert listed[0].get("max_concurrency") is None, "적지 않으면 기본이다 (계약의 값을 베끼지 않는다)"


def test_someone_elses_deployment_is_refused(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """남의 배포는 받지 않는다 (C2 V6). Center가 안 내려 주므로 **설치할 거리조차 없다**."""
    deployed(center, store, runner, target="srv_deadbeef")

    runner.tick()
    assert installed(runner.settings.data_path) == []


def test_nothing_is_installed_without_admin_keys(runner: agent_mod.Agent) -> None:
    """공개키가 없으면 **서명을 볼 수 없다** — 설치하지 않고 다음 주기를 기다린다.

    거부로 보고하면 멀쩡한 배포가 영원히 닫힌다 (하트비트가 `admin_keys`를 준다).
    """
    envelope = {"schema": 1, "kind": "deployment", "payload": {"deployment_id": "dep_1"}, "sig": "QUJD"}
    assert runner.admin_keys == []
    assert runner.install_deployments([envelope]) == []
    assert runner.pending_results == []
    assert installed(runner.settings.data_path) == []


def test_an_unsigned_package_is_refused_with_a_reason(
    center: TestClient, runner: agent_mod.Agent, store: Store, tmp_path: Path
) -> None:
    """**서명 없는 패키지는 설치하지 않는다** (C2 V7) — 거부도 사유와 함께 보고한다.

    Center는 승인되지 않은 패키지의 배포를 애초에 막으므로(C2), 여기서는 **내려받는 자리를
    바꿔 끼워** 실행기 자신의 V7만 본다. 서버에서는 이 검사를 끌 길을 두지 않았다.
    """
    runner.tick()
    runner.admin_keys = _public_keys(store)

    unsigned = tmp_path / "unsigned.zip"
    unsigned.write_bytes(package_zip())
    runner.fetch_package = lambda package_id, version: unsigned  # type: ignore[method-assign]

    envelope = sign(
        {
            "kind": "deployment",
            "deployment_id": "dep_3f9a1c07",
            "target": {"type": "server_runner", "id": runner.server_runner_id},
            "bpm_process_id": BOT,
            "version": "1.0.0",
            "content_hash": content_hash_zip(unsigned),
        },
        center_signer.active(store),  # 믿는 키로 서명했다 — 막는 것은 V7 하나다
        signed_at=now_iso(),
    )
    found = runner.install_deployments([envelope.to_json_dict()])
    assert [one.result for one in found] == ["rejected"]
    assert found[0].reason == "unsigned_package"
    assert installed(runner.settings.data_path) == []


def test_a_scheduled_deployment_waits(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """예약 배포는 **기다림이고 거부가 아니다** (C2 V5b) — 보고하지 않는다."""
    later = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    response = deployed(center, store, runner, not_before=later)
    assert response.status_code in (200, 201), response.text

    runner.tick()
    assert installed(runner.settings.data_path) == []
    assert runner.pending_results == [], "기다림은 보고하지 않는다"


def test_installing_twice_is_quiet(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """같은 판이 이미 깔려 있으면 **조용히 지나간다** — 주기마다 다시 보고하지 않는다."""
    deployed(center, store, runner)
    runner.tick()
    assert [r.result for r in runner.pending_results] == ["applied"]

    runner.tick()  # 올리고 비운다
    runner.tick()  # 같은 배포가 또 내려온다
    assert runner.pending_results == []


def _public_keys(store: Store) -> list[Any]:
    from chaeksas.center.api import signing as signing_api

    return list(signing_api.admin_keys(store))


# ─────────────────────────── 준비 상태 (C12 `readiness`) ───────────────────────────


def test_readiness_names_the_missing_key_ref(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """키 참조가 이 서버에 없으면 **그 이름을 올린다** (C12 — CON-12가 보인다)."""
    runner.tick()
    info = approved(
        center, requires={"service_apps": [{"app_id": "erp", "operations": ["issue"], "key_ref": "erp-key"}]}
    )
    deploy(center, info, target=runner.server_runner_id)
    runner.tick()

    found = runner.readiness()
    assert [r.bpm_process_id for r in found] == [BOT]
    assert found[0].ready is False
    assert found[0].missing_key_refs == ["erp-key"]


def test_readiness_sees_the_key_once_it_is_there(
    center: TestClient,
    store: Store,
    runner: agent_mod.Agent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """키를 주면 **다음에 묻는 쪽이 「준비됨」을 본다** — 캐시가 그것을 막으면 안 된다."""
    runner.tick()
    info = approved(
        center, requires={"service_apps": [{"app_id": "erp", "operations": ["issue"], "key_ref": "erp-key"}]}
    )
    deploy(center, info, target=runner.server_runner_id)
    runner.tick()
    assert runner.readiness()[0].ready is False

    monkeypatch.setenv("CHK_SERVER_RUNNER__SVC__ERP_KEY", "secret")
    runner.credentials = Credentials()
    runner._readiness.clear()  # noqa: SLF001 — 설치·키가 바뀌면 비우는 그 자리다
    assert runner.readiness()[0].ready is True


def test_readiness_is_empty_without_installs(runner: agent_mod.Agent) -> None:
    assert runner.readiness() == []


def test_readiness_does_not_call_out(runner: agent_mod.Agent, monkeypatch: pytest.MonkeyPatch) -> None:
    """사전 점검은 **서버를 부르지 않는다** (ADR-0013 — 하트비트마다 돈다)."""
    import httpx

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("사전 점검이 밖으로 나갔다")

    monkeypatch.setattr(httpx.Client, "request", refuse)
    monkeypatch.setattr(httpx.Client, "send", refuse)
    assert runner.readiness() == []
