"""서버 실행기가 **확장을 꽂는다** (C13, ADR-0064 — 09-gaps §3-14).

여기서 보는 것은 **무엇이 서버로 새지 않는가**다:

- 로컬 런타임은 **띄우지 않는다** — 예약 키 `runtime.<id>.*`가 없다. 런타임은 PC 실행기의
  것이고(C13 칸 이름이 그렇다) 그 예약은 「PC에 하나」를 전제한 배타 잠금이다 (ADR-0014 §4).
- `run_locations`에 `server`를 적지 않은 태스크 종류는 **수행기를 내지 않고**, 그런 BPM 프로세스는
  **시작 전에** `not_ready`로 막힌다 (전에는 실행 중에 `node_kind_unsupported`로 죽었다).
- 설정은 **환경변수뿐**이고(서버에는 설정 파일이 없다) 비밀은 설정에 섞이지 않는다 (ADR-0013).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from chaeksas.core.extensions import ExtensionHost
from chaeksas.core.packages import bots_dir
from chaeksas.core.preflight import TASK_TYPES_WRONG_LOCATION
from chaeksas.extension_api import HOST_SERVER_RUNNER
from chaeksas.server_runner import agent as agent_mod
from chaeksas.server_runner import extensions as ext_mod
from chaeksas.server_runner.center_client import CenterClient
from chaeksas.server_runner.credentials import Credentials, extension_config_env
from chaeksas.server_runner.settings import Settings

#: 서버에서 돌 수 있다고 적은 종류 하나와 PC 전용 하나 — 둘을 한 확장이 기여한다.
DEFINITION: dict[str, Any] = {
    "schema": 2,
    "id": "doc-ocr",
    "version": "1.0.0",
    "name": "문서 인식",
    "publisher": "사내",
    "tier": "internal",
    "api": ">=1,<2",
    "service": {"protocol": "chk-c11", "base_url": "https://ocr.example.com"},
    "contributes": {
        "task_types": [
            {"id": "ocr_task", "label": "문서 인식", "executor": {"entry": "x:Y"}, "run_locations": ["pc"]},
            {"id": "sum_task", "label": "요약", "executor": {"entry": "x:Y"}, "run_locations": ["server"]},
        ],
        "bot_ui.local_runtimes": [
            {
                "id": "worker",
                "label": "Worker",
                "entry": "doc_ocr.worker:serve",
                "default_port": 8899,
                "health": "/v1/health",
                "token_dir": True,
                "start": "on_demand",
            }
        ],
        "configuration": [
            {"key": "quality", "label": "품질", "scope": "server_runner"},
            {"key": "ocr_key", "label": "키", "scope": "server_runner", "secret": True},
            {"key": "theme", "label": "테마", "scope": "bot_ui"},
        ],
    },
}

#: 매니페스트의 나머지 필수 칸 — 확장 점검은 이것들을 보지 않는다.
BOT: dict[str, Any] = {
    "schema": 1,
    "id": "ocr.intake",
    "version": "1.0.0",
    "name": "문서 접수",
    "kind": "bpm_process",
    "run_location": "server",
    "entry": "main.bpmn",
    "content_hash": "sha256:" + "0" * 64,
    "human": {"approval_center": False, "approval_field": False, "confirmation": False},
    "built": {"by": "studio", "at": "2026-10-16T00:00:00+09:00", "core": "0.1.0", "spec_version": 1},
}


def host_with(definition: dict[str, Any] | None = None) -> ExtensionHost:
    """실행 위치를 쥔 호스트 — `ext_mod.load()`가 짓는 것과 같은 꼴이다."""
    found = ExtensionHost(run_location="server")
    found.add_installed(
        json.dumps(definition or DEFINITION).encode("utf-8"),
        origin="test",
        root="chaeksas.ext.ui_automation",
    )
    return found


def install(data_path: Path, *, task_type: str) -> None:
    """그 종류를 요구하는 BPM 프로세스 하나를 **손으로 설치한다**.

    Center를 거치지 않는다 — C1 R2가 업로드에서 이미 막는 꼴이라 **그 길로는 만들 수 없다**.
    현장에서 이것이 생기는 길은 **확장 선언이 승인 뒤에 바뀌는 것**이다 (ADR-0064 §1).
    """
    folder = bots_dir(data_path) / BOT["id"] / BOT["version"]
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {
        **BOT,
        "requires": {
            "task_types": [{"id": task_type, "extension": "doc-ocr"}],
            "extensions": [{"id": "doc-ocr", "version": ">=1,<2"}],
        },
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def runner(tmp_path: Path) -> agent_mod.Agent:
    settings = Settings(center_url="http://center", data_path=tmp_path / "runner")
    found = agent_mod.Agent(
        settings=settings,
        client=CenterClient(base_url="http://center", api_key="k"),
        host=host_with(),
    )
    return found


# ─────────────────────── 로컬 런타임이 서버로 새지 않는다 ───────────────────────


def test_the_server_gets_no_runtime_keys(runner: agent_mod.Agent) -> None:
    """**예약 키를 일부러 비운다** (ADR-0064) — 「띄우지 않았는데 자리가 있다」가 되면 수행기가
    없는 런타임을 두드린다. 확장이 런타임을 선언해도 서버에서는 채우지 않는다.
    """
    ctx = runner.extensions().context("doc-ocr")

    assert ctx.setting("runtime.worker.port") is None
    assert ctx.setting("runtime.worker.token_dir") is None
    assert ctx.host == HOST_SERVER_RUNNER


def test_only_the_task_types_that_declare_the_server_get_an_executor(runner: agent_mod.Agent) -> None:
    """PC 전용 종류는 서버에서 **없는 것**이다 — 엔진은 설치 오류로 올린다."""
    tasks = runner.extensions()

    assert tasks.executor("ocr_task") is None
    assert [c.value.id for c in tasks.host.task_types()] == ["sum_task"]


# ─────────────────────── 시작 전에 막는다 (C12 `readiness`) ───────────────────────


def test_a_pc_only_task_type_blocks_before_the_run_starts(runner: agent_mod.Agent) -> None:
    """**이것이 §3-14의 공백이었다** — 전에는 배포·시작까지 가서 실행 중에 죽었다."""
    install(runner.settings.data_path, task_type="ocr_task")

    found = runner.readiness()
    assert [one.bpm_process_id for one in found] == ["ocr.intake"]
    assert found[0].ready is False
    assert found[0].blocked == [TASK_TYPES_WRONG_LOCATION]


def test_a_server_task_type_is_ready(runner: agent_mod.Agent) -> None:
    """**적어 둔 것은 돈다** — 거짓 차단이 거짓 통과보다 나쁘다."""
    install(runner.settings.data_path, task_type="sum_task")

    found = runner.readiness()
    assert found[0].ready is True and found[0].blocked == []


def test_readiness_and_the_run_share_one_host(runner: agent_mod.Agent) -> None:
    """점검이 다른 호스트를 보면 「점검은 통과했는데 실행이 안 된다」가 된다."""
    install(runner.settings.data_path, task_type="sum_task")
    runner.readiness()
    bot = runner.installed_bots()[0]

    # 실행은 그 BPM 프로세스에 묶인 창구를 받지만(ADR-0094 §8) **호스트는 점검과 같은 하나**다.
    assert runner.run_env(bot).extensions.host is runner.extensions().host  # type: ignore[attr-defined]
    assert runner.extensions().host is runner.extension_host()


# ─────────────────────── 설정·비밀 (ADR-0064 §2, ADR-0013) ───────────────────────


def test_configuration_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """서버에는 설정 파일이 없다 — 이름 규칙은 **PC 실행기의 것과 같다**."""
    host = host_with()
    monkeypatch.setenv(extension_config_env("doc-ocr", "quality"), "high")

    values = ext_mod.settings_for(host, "doc-ocr")
    assert values.get("quality") == "high"


def test_a_secret_field_does_not_come_through_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """**비밀은 설정에 섞이지 않는다** (ADR-0013) — 그것을 푸는 것은 `Secrets`다."""
    host = host_with()
    monkeypatch.setenv(extension_config_env("doc-ocr", "ocr_key"), "chk_svc_secret")

    values = ext_mod.settings_for(host, "doc-ocr")
    assert values.get("ocr_key") is None

    secrets = ext_mod.RunnerSecrets(credentials=Credentials(), extension_id="doc-ocr")
    assert secrets.resolve("ocr_key") == "chk_svc_secret"


def test_a_field_of_another_scope_is_not_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """`scope: bot_ui` 칸은 서버의 것이 아니다 — 있는 척하지 않는다."""
    monkeypatch.setenv(extension_config_env("doc-ocr", "theme"), "dark")
    assert ext_mod.settings_for(host_with(), "doc-ocr").get("theme") is None


def test_the_call_token_is_this_runners_own_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """확장이 외부 작업을 올릴 토큰(`call_token`)은 **이 실행기의 Center API 키**다 (C15) — 다른 비밀은
    그 확장의 비밀 칸이다."""
    monkeypatch.setenv("CHK_SERVER_RUNNER__CENTER_API_KEY", "chk_ctr_runner")
    monkeypatch.setenv(extension_config_env("doc-ocr", "ocr_key"), "from-ext")

    secrets = ext_mod.RunnerSecrets(credentials=Credentials(), extension_id="doc-ocr")
    assert secrets.resolve("call_token") == "chk_ctr_runner"
    assert secrets.resolve("ocr_key") == "from-ext"


def test_extensions_are_told_the_center_address() -> None:
    """C13 `center.url` — 확장 클라이언트가 외부 작업을 올리는 곳. 서버 부분의 주소는 주지 않는다."""
    found = ext_mod.settings_for(host_with(), "doc-ocr", center_url="http://center:8800")
    assert found.get("center.url") == "http://center:8800"
    assert found.get("service.base_url") is None


def test_nothing_is_turned_off_on_the_server() -> None:
    """끄는 자리는 사람이 누르는 화면이고(ADR-0043) 서버에는 그 화면이 없다."""
    assert ext_mod.load().off == frozenset()
    assert ext_mod.load().run_location == "server"
