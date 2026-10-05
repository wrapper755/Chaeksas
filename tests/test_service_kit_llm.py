"""서비스 앱의 모델 연결 — C11 §모델 연결, ADR-0034.

설정은 환경변수로만, 없으면 503 `llm_unavailable`(지어낸 답을 주지 않는다), 실패는 C11 오류로,
관리 상태에는 `llm` 한 줄 — **키 값·주소는 보이지 않는다**.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.contracts.service_app import MODE_DETERMINISTIC, Operation, OpRequest, ServiceAppManifest
from chaeksas.llm import LlmError, OpenAiCompatibleLlm, RecordingLlm, Reply
from chaeksas.service_kit import (
    LLM_UNAVAILABLE,
    InMemoryKeyStore,
    LlmSettings,
    OpResult,
    ServiceLlm,
    create_app,
    issue,
    usage_of,
)

PREFIX = "CHK_SVC_DEMO__"
ADMIN = {"Authorization": "Bearer t-admin"}
NOW = "2026-10-05T09:00:00+00:00"
SECRET = "sk-" + "s" * 30


def env(**values: str) -> dict[str, str]:
    return {f"{PREFIX}LLM__{name}": value for name, value in values.items()}


# ─────────────────────────── 설정 ───────────────────────────


def test_settings_need_both_address_and_model() -> None:
    assert LlmSettings.from_env(PREFIX, env(BASE_URL="http://gw", MODEL="m")).complete
    assert not LlmSettings.from_env(PREFIX, {}).complete
    half = LlmSettings.from_env(PREFIX, env(BASE_URL="http://gw"))
    assert not half.complete and half.partial, "하나만 적은 것은 「잊은 것」과 따로 알린다"


def test_a_bad_timeout_stops_the_app_instead_of_using_the_default() -> None:
    with pytest.raises(ValueError, match="TIMEOUT_S"):
        LlmSettings.from_env(PREFIX, env(BASE_URL="http://gw", MODEL="m", TIMEOUT_S="두 분"))
    with pytest.raises(ValueError, match="TIMEOUT_S"):
        LlmSettings.from_env(PREFIX, env(BASE_URL="http://gw", MODEL="m", TIMEOUT_S="0"))


def test_settings_become_the_same_client_the_engine_uses() -> None:
    made = ServiceLlm.from_env(PREFIX, env(BASE_URL="http://gw", MODEL="m", API_KEY=SECRET, TIMEOUT_S="30"))
    assert isinstance(made.client, OpenAiCompatibleLlm)
    assert (made.client.base_url, made.client.model, made.client.timeout_s) == ("http://gw", "m", 30.0)


# ─────────────────────────── 부르기 ───────────────────────────


def manifest() -> ServiceAppManifest:
    return ServiceAppManifest(
        schema=1,
        app_id="demo",
        name="데모",
        version="0.1.0",
        category="system",
        console_url="http://localhost:8011",
        operations=[Operation(name="summarize", description="요약", modes=[MODE_DETERMINISTIC])],
    )


def app_with(llm: ServiceLlm) -> tuple[TestClient, str]:
    keys = InMemoryKeyStore()
    raw, record = issue("운영", created_at=NOW)
    keys.add(record)

    def summarize(request: OpRequest, _mode: str) -> OpResult:
        first = llm.ask([{"role": "user", "content": str(request.input.get("text"))}])
        second = llm.ask([{"role": "user", "content": first.text}])
        return OpResult({"summary": second.text}, usage=usage_of([first, second]))

    app = create_app(manifest(), {"summarize": summarize}, keys=keys, admin_token="t-admin", llm=llm, now=lambda: NOW)
    return TestClient(app), raw


def call(client: TestClient, raw: str, attempt: int = 1) -> Any:
    body = {
        "schema": 1,
        "mode": MODE_DETERMINISTIC,
        "run_id": "run_20261005_090000_a1b2c3",
        "node_id": "Task_Summarize",
        "node_instance": 1,
        "attempt": attempt,
        "caller": {"type": "bot_ui", "host": "pc_01", "bpm_process_id": "demo", "version": "1.0.0"},
        "input": {"text": "긴 글"},
    }
    return client.post("/v1/ops/summarize", json=body, headers={"Authorization": f"Bearer {raw}"})


def status_line(client: TestClient) -> dict[str, Any]:
    found = client.get("/admin/v1/status", headers=ADMIN).json()["dependencies"]
    return next(d for d in found if d["name"] == "llm")


def test_without_a_model_the_operation_is_503_llm_unavailable() -> None:
    """모델 없이 지어낸 답을 주지 않는다."""
    client, raw = app_with(ServiceLlm.from_env(PREFIX, {}))
    answer = call(client, raw)
    assert answer.status_code == 503
    assert answer.json()["code"] == LLM_UNAVAILABLE
    assert status_line(client)["status"] == "unknown"
    assert "설정되지 않음" in status_line(client)["detail"]


def test_usage_is_summed_over_the_questions_and_status_turns_ok() -> None:
    model = RecordingLlm(
        replies=[
            Reply(text="중간", model="m-1", input_tokens=10, output_tokens=3),
            Reply(text="요약", model="m-1", input_tokens=7, output_tokens=2),
        ]
    )
    client, raw = app_with(ServiceLlm(model, model="m-1"))
    assert status_line(client)["status"] == "unknown", "부른 적이 없으면 닿는지 모른다"
    body = call(client, raw).json()
    assert body["output"] == {"summary": "요약"}
    assert body["usage"] == {"model": "m-1", "input_tokens": 17, "output_tokens": 5}
    assert status_line(client) == {"name": "llm", "status": "ok", "detail": "모델 m-1"}


def test_a_brief_outage_is_dependency_down_and_shows_unreachable() -> None:
    client, raw = app_with(ServiceLlm(RecordingLlm(fails=LlmError("닿지 못함", retryable=True)), model="m"))
    answer = call(client, raw)
    assert (answer.status_code, answer.json()["code"]) == (503, "dependency_down"), "다시 시도할 만하다"
    assert status_line(client)["status"] == "unreachable"


def test_a_wrong_key_or_model_name_is_llm_unavailable() -> None:
    client, raw = app_with(ServiceLlm(RecordingLlm(fails=LlmError("모르는 모델", status=404)), model="m"))
    answer = call(client, raw)
    assert (answer.status_code, answer.json()["code"]) == (503, LLM_UNAVAILABLE), "다시 해도 안 풀린다"
    assert status_line(client)["status"] == "degraded"


def test_the_status_never_shows_the_key_or_the_address() -> None:
    llm = ServiceLlm.from_env(PREFIX, env(BASE_URL="http://gw.internal:9000", MODEL="m", API_KEY=SECRET))
    client, _ = app_with(llm)
    raw = client.get("/admin/v1/status", headers=ADMIN).text
    assert SECRET not in raw and "gw.internal" not in raw


def test_the_ui_automation_app_reports_its_model_line(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """UI 자동화 앱도 같은 자리를 쓴다 — 치유·목표로 계획이 붙을 곳이다."""
    from chaeksas.ext.ui_automation.service.app import ENV_PREFIX, create  # noqa: PLC0415

    monkeypatch.setenv(f"{ENV_PREFIX}LLM__BASE_URL", "http://gw")
    monkeypatch.setenv(f"{ENV_PREFIX}LLM__MODEL", "heal-model")
    with TestClient(create(db_path=tmp_path / "uia.sqlite3", admin_token="t-admin")) as client:
        assert status_line(client) == {"name": "llm", "status": "unknown", "detail": "모델 heal-model"}
