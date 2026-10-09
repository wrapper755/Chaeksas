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
from chaeksas.bot_ui.bots import (
    CENTER,
    INSTALL_SOURCE_NAME,
    MANUAL,
    SIGNATURE_NAME,
    SOURCE_UNKNOWN,
    install,
    installed,
    write_source,
)
from chaeksas.bot_ui.deploy import APPLIED, REJECTED, Deployer, read_signature
from chaeksas.center.api.signing import bootstrap_key
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings
from chaeksas.contracts.hashing import content_hash_zip
from chaeksas.contracts.signing import sign

TOKEN = "t-admin"
PASS = "열쇠말"
BOT_UI = "bui_a81c22d0"
AT = "2026-10-05T09:00:00+09:00"


@pytest.fixture(autouse=True)
def _admin_home(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv(keystore.PASSPHRASE_ENV, PASS)
    monkeypatch.setenv(f"{keystore.ENV_PREFIX}DATA_DIR", str(tmp_path / "admin"))


@pytest.fixture
def center(tmp_path: Path) -> Any:
    settings = Settings(
        db_path=tmp_path / "center.sqlite3", package_dir=tmp_path / "packages", admin_token=TOKEN
    )
    return Center(base_url="http://center", token=TOKEN, client=TestClient(create_app(settings)))


def package_zip(package_id: str = "erp.order-entry", version: str = "2.1.0") -> bytes:
    import tempfile

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
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }

    def made(body: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("process/main.bpmn", "<definitions />")
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


def approved(center: Center, key: Any, *, package_id: str = "erp.order-entry") -> dict[str, Any]:
    """업로드 → 승인까지."""
    info = upload(center, package_zip(package_id))
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
        bot_ui_id=BOT_UI,
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
    """`run_location`과 대상이 맞아야 한다 (C2 §배포 대상 규칙)."""
    key = admin_key(center)
    info = approved(center, key)
    with pytest.raises(CenterProblem) as caught:
        center.deploy(deployment(key, info, target_type="server_runner", target="*"))
    assert caught.value.code == "wrong_target"


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


def test_someone_elses_deployment_is_refused(center: Center, tmp_path: Path) -> None:
    key = admin_key(center)
    info = approved(center, key)
    center.deploy(deployment(key, info, target="bui_다른곳"))
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
