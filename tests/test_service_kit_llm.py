"""서비스 앱의 모델 연결 — C11 §모델 연결, ADR-0034.

| 보는 것 | 왜 |
| --- | --- |
| 설정은 환경변수로만, 주소·모델 둘 다 있어야 한다 | 반쯤 적은 것을 「잊은 것」과 가른다 |
| 모델이 없으면 일감이 `llm_unavailable`로 실패한다 | 지어낸 답을 주지 않는다 |
| 잠깐 막힌 것은 `dependency_down`(다시 해 볼 만함), 틀린 키·모델은 아니다 | C15 `retryable`이 재시도를 가른다 |
| 쓴 양은 더해서 `complete`에 실린다 | C3 `llm_usage`와 같은 이름 |
| 관리 상태에 `llm` 한 줄 — **키 값·주소는 보이지 않는다** | SVC-01 |
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.contracts.external_task import LockedTask
from chaeksas.contracts.service_app import MODE_DETERMINISTIC, Operation, OpRequest, ServiceAppManifest
from chaeksas.llm import LlmError, OpenAiCompatibleLlm, RecordingLlm, Reply
from chaeksas.service_kit import (
    LLM_UNAVAILABLE,
    LlmSettings,
    OpResult,
    Outcome,
    ServiceLlm,
    create_app,
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


def app_with(llm: ServiceLlm) -> TestClient:
    def summarize(request: OpRequest, _mode: str) -> OpResult:
        first = llm.ask([{"role": "user", "content": str(request.input.get("text"))}])
        second = llm.ask([{"role": "user", "content": first.text}])
        return OpResult({"summary": second.text}, usage=usage_of([first, second]))

    app = create_app(manifest(), {"summarize": summarize}, admin_token="t-admin", llm=llm, now=lambda: NOW)
    return TestClient(app)


def call(client: TestClient, attempt: int = 1) -> Outcome:
    """일꾼이 하는 그대로 — `app.state.ops`에 일감 하나를 준다 (C15)."""
    task = LockedTask.model_validate(
        {
            "task_id": f"et_{attempt}",
            "topic": "demo",
            "operation": "summarize",
            "mode": MODE_DETERMINISTIC,
            "origin": "run",
            "idempotency": {"run_id": "run_20261005_090000_a1b2c3", "node_id": "Task_Summarize",
                            "node_instance": 1, "attempt": attempt},
            "caller": {"type": "bot_ui", "host": "pc_01", "bpm_process_id": "demo", "version": "1.0.0"},
            "input": {"text": "긴 글"},
            "lock_until": "2026-10-05T09:10:00+00:00",
            "deadline": "2026-10-05T09:10:00+00:00",
        }
    )
    found: Outcome = client.app.state.ops.execute(task)  # type: ignore[attr-defined]
    return found


def status_line(client: TestClient) -> dict[str, Any]:
    found = client.get("/admin/v1/status", headers=ADMIN).json()["dependencies"]
    return next(d for d in found if d["name"] == "llm")


def test_without_a_model_the_task_fails_llm_unavailable() -> None:
    """모델 없이 지어낸 답을 주지 않는다."""
    client = app_with(ServiceLlm.from_env(PREFIX, {}))
    answer = call(client)
    assert not answer.ok
    assert (answer.code, answer.retryable) == (LLM_UNAVAILABLE, False)
    usage = client.get("/admin/v1/usage", headers=ADMIN).json()["items"]
    assert [one["status"] for one in usage] == [503], "사용 기록에는 503으로 센다 (SVC-01 오류율)"
    assert status_line(client)["status"] == "unknown"
    assert "설정되지 않음" in status_line(client)["detail"]


def test_usage_is_summed_over_the_questions_and_status_turns_ok() -> None:
    model = RecordingLlm(
        replies=[
            Reply(text="중간", model="m-1", input_tokens=10, output_tokens=3),
            Reply(text="요약", model="m-1", input_tokens=7, output_tokens=2),
        ]
    )
    client = app_with(ServiceLlm(model, model="m-1"))
    assert status_line(client)["status"] == "unknown", "부른 적이 없으면 닿는지 모른다"
    body = call(client).complete_body()
    assert body["output"] == {"summary": "요약"}
    assert body["usage"] == {"model": "m-1", "input_tokens": 17, "output_tokens": 5}
    assert status_line(client) == {"name": "llm", "status": "ok", "detail": "모델 m-1"}


def test_a_brief_outage_is_dependency_down_and_shows_unreachable() -> None:
    client = app_with(ServiceLlm(RecordingLlm(fails=LlmError("닿지 못함", retryable=True)), model="m"))
    answer = call(client)
    assert (answer.code, answer.retryable) == ("dependency_down", True), "다시 시도할 만하다"
    assert status_line(client)["status"] == "unreachable"


def test_a_wrong_key_or_model_name_is_llm_unavailable() -> None:
    client = app_with(ServiceLlm(RecordingLlm(fails=LlmError("모르는 모델", status=404)), model="m"))
    answer = call(client)
    assert (answer.code, answer.retryable) == (LLM_UNAVAILABLE, False), "다시 해도 안 풀린다"
    assert status_line(client)["status"] == "degraded"


def test_the_status_never_shows_the_key_or_the_address() -> None:
    llm = ServiceLlm.from_env(PREFIX, env(BASE_URL="http://gw.internal:9000", MODEL="m", API_KEY=SECRET))
    client = app_with(llm)
    raw = client.get("/admin/v1/status", headers=ADMIN).text
    assert SECRET not in raw and "gw.internal" not in raw
