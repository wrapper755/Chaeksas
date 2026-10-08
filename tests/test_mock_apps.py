"""모의 서비스 앱·모의 외부 앱 (`samples/mock_apps`, M5 조각 13).

거듭 보는 것 다섯.

1. **예제가 부르는 것을 다 갖췄나** — 목록을 손으로 적지 않고 **예제 BPMN에서 읽어** 대조한다.
   예제가 새 앱을 부르기 시작하면 여기서 바로 드러난다.
2. **C11을 지키나** — 키 없이는 안 되고, `/manifest`는 비밀 없이 열리고, 관리 API는 토큰이
   없으면 503이다 (빈 토큰으로 열리지 않는다).
3. **거짓 데이터가 케이스의 기대값과 맞물리나** — 숫자를 눈으로 맞추지 않고 **예제의 DMN을
   실제로 돌려** 본다. 케이스가 바뀌면 깨져야 한다.
4. **외부 앱은 C11이 아니다** — 정의가 C13 검사(E1·E3)를 지나고, **진짜 어댑터**가 그 정의로
   모의 앱을 불러 우리 말로 옮긴다. 조각 11·12가 만든 길을 실제로 밟는 자리다.
5. **업무 값을 되돌려주지 않는다** (원칙 6) — 메일 본문·답변 글·파일 경로는 응답에 없다.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from chaeksas.contracts.dmn import Decision, read_decisions
from chaeksas.contracts.extension import ExtensionManifest, validate
from chaeksas.contracts.service_app import OpRequest, ServiceAppManifest
from chaeksas.core.http_adapter import AdapterCaller, AdapterError
from chaeksas.core.services import OpCall
from chaeksas.mock_apps import catalog
from chaeksas.mock_apps.c11 import SCENARIO_PATH, MockApp, build
from chaeksas.mock_apps.external import apps as external_apps
from chaeksas.mock_apps.external import definitions

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples"
BPMN = EXAMPLES / "bpmn"

RUN_ID = "run_20261008_090000_a1b2c3"


# ─────────────────────────── 예제에서 읽는다 ───────────────────────────


def called_by_examples() -> dict[str, set[str]]:
    """예제가 실제로 부르는 `{app_id: {작업, …}}` — BPMN의 `chk:serviceCall`에서 읽는다."""
    found: dict[str, set[str]] = {}
    for path in sorted(BPMN.glob("*.bpmn")):
        text = path.read_text(encoding="utf-8")
        for body in re.findall(r"<chk:serviceCall>(.*?)</chk:serviceCall>", text, re.S):
            call = json.loads(body)
            found.setdefault(str(call["app_id"]), set()).add(str(call["operation"]))
    return found


def decision(name: str) -> Decision:
    """예제의 DMN 하나 — 모의 데이터를 그 결정에 **진짜로** 먹여 본다."""
    return read_decisions((BPMN / f"{name}.dmn").read_text(encoding="utf-8"))[name]


@pytest.fixture(scope="module")
def examples() -> dict[str, set[str]]:
    return called_by_examples()


def test_every_app_the_examples_call_has_a_mock(examples: dict[str, set[str]]) -> None:
    """예제가 부르는 앱이 모두 있고, **쓰지 않는 앱을 들고 있지도 않다.**

    UI 자동화(`ui-automation`)는 모의가 아니라 진짜 내장 확장이라 여기 없다.
    """
    assert set(examples) == set(catalog.ids())


def test_every_operation_the_examples_call_exists(examples: dict[str, set[str]]) -> None:
    """작업 이름까지 맞는가. 모의가 **더 많이** 가진 것도 알려 준다 (죽은 작업이 쌓이지 않게)."""
    have = catalog.operations()
    missing = {app: sorted(ops - set(have.get(app, ()))) for app, ops in examples.items()}
    assert not any(missing.values()), f"모의에 없는 작업: { {k: v for k, v in missing.items() if v} }"
    extra = {app: sorted(set(ops) - examples.get(app, set())) for app, ops in have.items()}
    assert not any(extra.values()), f"예제가 부르지 않는 작업: { {k: v for k, v in extra.items() if v} }"


def test_the_example_count_matches_the_handoff_tally(examples: dict[str, set[str]]) -> None:
    """앱 16개·작업 31개 — 이 수가 바뀌면 조각의 범위가 바뀐 것이다."""
    assert len(examples) == 16
    assert sum(len(ops) for ops in examples.values()) == 31


# ─────────────────────────── C11 (뼈대가 주는 것) ───────────────────────────


def client_for(mock: MockApp, **over: Any) -> tuple[TestClient, str]:
    made = build(mock, **over)
    return TestClient(made.app), made.key


def call(client: TestClient, key: str, operation: str, payload: dict[str, Any], **over: Any) -> httpx.Response:
    body: dict[str, Any] = {
        "schema": 1,
        "mode": "deterministic",
        "run_id": RUN_ID,
        "node_id": "Task_1",
        "node_instance": 1,
        "attempt": 1,
        "caller": {"type": "bot_ui", "host": "PC-1"},
        "input": payload,
    }
    body.update(over)
    found: httpx.Response = client.post(f"/v1/ops/{operation}", json=body, headers={"Authorization": f"Bearer {key}"})
    return found


def output(client: TestClient, key: str, operation: str, payload: dict[str, Any], **over: Any) -> dict[str, Any]:
    response = call(client, key, operation, payload, **over)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["output"]
    return found


@pytest.mark.parametrize("mock", catalog.C11_APPS, ids=lambda m: m.app_id)
def test_c11_manifest_is_valid(mock: MockApp) -> None:
    """manifest가 C11 모양이고, **확장을 알린다** — 사내 확장의 정의는 Center에 없으므로
    이 칸이 C7 「확장」 목록의 출처다 (조각 10)."""
    client, _ = client_for(mock)
    found = ServiceAppManifest.model_validate(client.get("/manifest").json())
    assert found.app_id == mock.app_id
    assert found.extension is not None and found.extension.id == mock.app_id
    assert [one.name for one in found.operations] == [one.name for one in mock.ops]
    # 두 모드를 다 받는다 — Bot은 결정 수행, Studio 시험 실행은 자율 수행이다.
    assert all(set(one.modes) == {"deterministic", "autonomous"} for one in found.operations)


@pytest.mark.parametrize("mock", catalog.C11_APPS, ids=lambda m: m.app_id)
def test_healthz_and_manifest_need_no_key(mock: MockApp) -> None:
    """Center가 주소만으로 읽는 두 길 (C7 — 읽지 못하면 등록하지 않는다)."""
    client, _ = client_for(mock)
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/manifest").status_code == 200


@pytest.mark.parametrize("mock", catalog.C11_APPS, ids=lambda m: m.app_id)
def test_an_operation_needs_a_key(mock: MockApp) -> None:
    client, _ = client_for(mock)
    response = client.post(f"/v1/ops/{mock.ops[0].name}", json={})
    assert response.status_code == 401
    assert response.json()["code"] == "key_missing"


def test_the_admin_api_is_closed_without_a_token() -> None:
    """빈 토큰으로 열리지 않는다 (C11). 주면 열린다."""
    closed, _ = client_for(catalog.C11_APPS[0])
    assert closed.get("/admin/v1/status").status_code == 503
    open_one, _ = client_for(catalog.C11_APPS[0], admin_token="t-admin")
    found = open_one.get("/admin/v1/status", headers={"Authorization": "Bearer t-admin"})
    assert found.status_code == 200, found.text
    assert found.json()["app_id"] == catalog.C11_APPS[0].app_id


def test_a_shared_dev_key_covers_every_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """앱 열여섯 개에 키를 하나씩 심는 것은 개발에서 쓸 수 없다 (`CHK_MOCK_APPS__DEV_KEY`)."""
    monkeypatch.setenv("CHK_MOCK_APPS__DEV_KEY", "chk_svc_devdevdev")
    for mock in catalog.C11_APPS:
        made = build(mock)
        assert made.key == "chk_svc_devdevdev", mock.app_id
        # 받은 키는 띄울 때 되읊지 않는다 (사람이 이미 안다).
        assert made.key_from_env is True, mock.app_id


def test_a_generated_key_is_shown_because_nobody_knows_it_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHK_MOCK_APPS__DEV_KEY", raising=False)
    monkeypatch.delenv("CHK_SVC_WMS__DEV_KEY", raising=False)
    made = build(catalog.c11("wms") or catalog.C11_APPS[0])
    assert made.key.startswith("chk_svc_")
    assert made.key_from_env is False


def test_the_same_call_twice_is_replayed_not_redone() -> None:
    """멱등은 뼈대가 준다 — 두 번째는 `replayed`다 (C11)."""
    client, key = client_for(catalog.c11("ticketing") or catalog.C11_APPS[0])
    payload = {"queue": "장비", "priority": "높음", "title": "요약", "body": "본문"}
    first = call(client, key, "create_ticket", payload).json()
    again = call(client, key, "create_ticket", payload).json()
    assert again["replayed"] is True
    assert again["output"]["id"] == first["output"]["id"]


# ─────────────────────────── 시나리오 제어 (모의만의 길) ───────────────────────────


def test_the_scenario_can_be_switched_and_unknown_names_are_refused() -> None:
    """BX-08은 입력이 같은 케이스 둘이 **다른 답**을 기대한다 (「평소」·「95일 1건 추가」)."""
    client, _ = client_for(catalog.c11("erp") or catalog.C11_APPS[0])
    assert client.get(SCENARIO_PATH).json()["name"] == "기본"
    assert client.post(SCENARIO_PATH, json={"name": "이관1건"}).status_code == 200
    assert client.get(SCENARIO_PATH).json()["name"] == "이관1건"
    refused = client.post(SCENARIO_PATH, json={"name": "없는것"})
    assert refused.status_code == 422
    assert client.get(SCENARIO_PATH).json()["name"] == "이관1건"


def test_apps_without_scenarios_only_know_the_default() -> None:
    client, _ = client_for(catalog.c11("wms") or catalog.C11_APPS[0])
    assert client.get(SCENARIO_PATH).json()["allowed"] == ["기본"]


# ─────────────────── 거짓 데이터가 케이스와 맞물리나 (DMN을 돌린다) ───────────────────


def test_bx08_overdue_data_lands_on_the_stages_the_case_expects() -> None:
    """BX-08: 「평소」는 이관건수 0, 「이관 1건」은 1. **DMN을 진짜로 돌려** 센다."""
    stage = decision("dunning_stage")
    client, key = client_for(catalog.c11("erp") or catalog.C11_APPS[0])

    def stages() -> list[str]:
        items = output(client, key, "list_overdue_receivables", {"기준일": "2026-10-08"})["items"]
        return [stage.decide({"연체일수": one["연체일수"], "금액": one["금액"]})["단계"] for one in items]

    평소 = stages()
    assert 평소 == ["1차", "2차", "1차"], 평소
    assert 평소.count("이관검토") == 0

    client.post(SCENARIO_PATH, json={"name": "이관1건"})
    # 멱등 키가 같으면 앞의 답이 되돌아온다 — 노드 인스턴스를 올려 다시 묻는다.
    items = output(client, key, "list_overdue_receivables", {"기준일": "2026-10-08"}, node_instance=2)["items"]
    이관 = [stage.decide({"연체일수": one["연체일수"], "금액": one["금액"]})["단계"] for one in items]
    assert 이관.count("이관검토") == 1, 이관


def test_bx24_ledgers_give_the_balances_the_cases_expect() -> None:
    """BX-24: E001 → 11.5, E002 → 3. `잔여 = 발생 - 사용 - 예정`이 BPM 프로세스의 식이다.

    E002의 3이 BX-21 「잔여 부족」(20일 신청)을 막는 숫자이기도 하다.
    """
    client, key = client_for(catalog.c11("hris") or catalog.C11_APPS[0])
    # `node_instance`를 올려 묻는다 — 멱등 키가 같은데 입력이 다르면 409다 (C11, 그게 맞다).
    for i, (emp_id, wanted) in enumerate((("E001", 11.5), ("E002", 3)), start=1):
        ledger = output(client, key, "get_leave_ledger", {"emp_id": emp_id}, node_instance=i)["ledger"]
        assert ledger["발생"] - ledger["사용"] - ledger["예정"] == wanted, emp_id


def test_an_unknown_employee_is_bad_input_not_a_crash() -> None:
    client, key = client_for(catalog.c11("hris") or catalog.C11_APPS[0])
    response = call(client, key, "get_leave_ledger", {"emp_id": "E999"})
    assert response.status_code == 422
    assert response.json()["code"] == "input_invalid"


def test_bx16_stock_has_exactly_two_items_below_safety() -> None:
    """BX-16 「부족 2품목」 — BPM 프로세스의 식이 `qty < safety`를 센다."""
    client, key = client_for(catalog.c11("wms") or catalog.C11_APPS[0])
    items = output(client, key, "list_stock", {})["items"]
    short = [one for one in items if one["qty"] < one["safety"]]
    assert len(short) == 2, items


def test_bx23_has_three_people_and_each_lands_on_a_different_nudge() -> None:
    """BX-23 「3명」 — 메일 세 통. `남은일수`가 DMN의 세 갈래를 한 번에 지난다."""
    nudge = decision("training_nudge")
    client, key = client_for(catalog.c11("lms") or catalog.C11_APPS[0])
    items = output(client, key, "list_incomplete", {})["items"]
    assert len(items) == 3
    stages = [nudge.decide({"남은일수": one["남은일수"]})["단계"] for one in items]
    assert sorted(stages) == ["본인안내", "인사팀보고", "팀장참조"], stages
    # 마감일과 남은일수가 어긋나면 AI 태스크가 서로 다른 말을 쓴다.
    assert all(one["마감일"] for one in items)


def test_bx15_prices_make_the_shipping_fee_the_case_expects() -> None:
    """BX-15 「할인 없음」: P-100 10개 → 배송비 3000.

    DMN `shipping_fee`는 20kg를 넘기면 6000이다 — 단가표의 무게가 그 선을 넘으면 기대값이 깨진다.
    """
    fee = decision("shipping_fee")
    client, key = client_for(catalog.c11("erp") or catalog.C11_APPS[0])
    품목 = [{"코드": "P-100", "수량": 10}]
    prices = output(client, key, "get_prices", {"codes": 품목})["prices"]
    단가 = {one["코드"]: one for one in prices}
    무게 = round(sum(x["수량"] * 단가[x["코드"]]["무게"] for x in 품목), 2)
    assert fee.decide({"등급": "일반", "지역": "수도권", "무게": 무게})["fee"] == 3000


def test_an_unknown_item_code_is_bad_input() -> None:
    client, key = client_for(catalog.c11("erp") or catalog.C11_APPS[0])
    response = call(client, key, "get_prices", {"codes": [{"코드": "P-없음", "수량": 1}]})
    assert response.status_code == 422


def test_bx22_erp_keeps_failing_for_one_employee_only() -> None:
    """BX-22 「ERP 실패」 — 모의 ERP가 E009에만 503을 돌려준다 (재시도해도 같다).

    503이라 BPM 프로세스의 `retry.on`이 두 번 다시 부르고, 다 떨어지면 오류 경계가 받는다.
    """
    client, key = client_for(catalog.c11("erp") or catalog.C11_APPS[0])
    assert output(client, key, "disable_user", {"emp_id": "E008"})["result"]["회수됨"] is True
    # 재시도는 `attempt`만 올라간다 (C11) — 멱등 자리가 비워져 같은 요청이 다시 돈다.
    for attempt in (1, 2, 3):
        broken = call(client, key, "disable_user", {"emp_id": "E009"}, node_instance=2, attempt=attempt)
        assert broken.status_code == 503, broken.text
        assert broken.json()["code"] == "dependency_down"


def test_bx22_directory_recovers_even_for_the_broken_employee() -> None:
    """실패수 1·실패=[{시스템: ERP}]가 되려면 메일·VPN은 **되어야** 한다."""
    client, key = client_for(catalog.c11("directory") or catalog.C11_APPS[0])
    assert output(client, key, "disable_mail", {"emp_id": "E009"})["result"]["회수됨"] is True
    assert output(client, key, "disable_vpn", {"emp_id": "E009"})["result"]["회수됨"] is True


def test_bx10_acme_is_not_on_the_sanctions_list() -> None:
    """BX-10 「해외 대액」의 반려는 **통장 사본이 없어서**다 (케이스 설명).

    제재로도 반려가 되게 해 두면 무엇이 반려를 만들었는지 시험이 구별하지 못한다.
    """
    client, key = client_for(catalog.c11("compliance") or catalog.C11_APPS[0])
    assert output(client, key, "screen_sanctions", {"name": "Acme Trading"})["hits"] == []
    hit = output(client, key, "screen_sanctions", {"name": "제재상사"}, node_instance=2)["hits"]
    assert len(hit) == 1


def test_bx36_upsert_counts_what_it_was_given() -> None:
    """BX-36 「5건 묶음」이 `{"count": 5}`를 기대한다."""
    client, key = client_for(catalog.c11("crm") or catalog.C11_APPS[0])
    customers = [{"이름": f"고객{i}"} for i in range(5)]
    assert output(client, key, "upsert_customers", {"customers": customers})["result"]["count"] == 5


def test_bx32_search_finds_something_for_the_case_body() -> None:
    """BX-32 「배송 문의」가 `근거부족: false`를 기대한다 — 근거가 비면 안 된다."""
    client, key = client_for(catalog.c11("kb-search") or catalog.C11_APPS[0])
    hits = output(client, key, "search", {"query": "주문한 지 5일 지났어요", "top_k": 5})["hits"]
    assert hits, "근거가 비었다"
    assert len(hits) <= 5


def test_search_does_not_make_things_up_when_nothing_matches() -> None:
    client, key = client_for(catalog.c11("kb-search") or catalog.C11_APPS[0])
    assert output(client, key, "search", {"query": "양자컴퓨터 임대 문의", "top_k": 5})["hits"] == []


def test_bx34_logs_come_back_for_the_service_in_the_case() -> None:
    client, key = client_for(catalog.c11("observability") or catalog.C11_APPS[0])
    assert output(client, key, "recent_logs", {"service": "payment-api", "minutes": 15})["lines"]


def test_fx18_head_is_200_for_the_case_url() -> None:
    """FX-18 「5개」가 정상 5를 기대한다."""
    client, key = client_for(catalog.c11("web-reader") or catalog.C11_APPS[0])
    assert output(client, key, "head", {"url": "https://example.com"})["status"] == 200


def test_the_web_reader_refuses_things_that_are_not_urls() -> None:
    client, key = client_for(catalog.c11("web-reader") or catalog.C11_APPS[0])
    assert call(client, key, "head", {"url": "회의실 예약 어떻게 해요?"}).status_code == 422


def test_the_web_reader_says_it_did_not_really_read() -> None:
    """모의가 읽은 척하면 「요약이 왜 이상한가」를 쫓게 된다."""
    client, key = client_for(catalog.c11("web-reader") or catalog.C11_APPS[0])
    summary = output(client, key, "summarize_url", {"url": "https://example.com/a"})["summary"]
    assert "실제로 가져오지 않" in summary


def test_center_jobs_says_so_when_it_has_no_center(monkeypatch: pytest.MonkeyPatch) -> None:
    """BX-16의 작업 지시는 **진짜 Center**로 간다 — 없으면 흉내 내지 않고 503이다."""
    monkeypatch.delenv("CHK_SVC_CENTER_JOBS__CENTER__BASE_URL", raising=False)
    monkeypatch.delenv("CHK_SVC_CENTER_JOBS__CENTER__TOKEN", raising=False)
    client, key = client_for(catalog.c11("center-jobs") or catalog.C11_APPS[0])
    response = call(
        client, key, "create_job", {"bpm_process": "bx17_erp_po_entry", "target": "group:구매-PC", "inputs": {}}
    )
    assert response.status_code == 503
    assert response.json()["code"] == "dependency_down"


def test_center_jobs_refuses_a_group_it_cannot_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """그룹은 Center에 없다 — 어느 PC인지 **이 앱이** 안다 (`GROUPS`)."""
    monkeypatch.setenv("CHK_SVC_CENTER_JOBS__CENTER__BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("CHK_SVC_CENTER_JOBS__CENTER__TOKEN", "t-int")
    monkeypatch.setenv("CHK_SVC_CENTER_JOBS__GROUPS", json.dumps({"다른-PC": "bot-1"}))
    client, key = client_for(catalog.c11("center-jobs") or catalog.C11_APPS[0])
    response = call(
        client, key, "create_job", {"bpm_process": "bx17_erp_po_entry", "target": "group:구매-PC", "inputs": {}}
    )
    assert response.status_code == 422
    assert "구매-PC" in response.json()["message"]


# ─────────────────────────── 업무 값을 되돌려주지 않는다 (원칙 6) ───────────────────────────


def test_mail_and_reply_bodies_do_not_come_back() -> None:
    """보낸 것·첨부한 것의 **내용**은 응답에 없다. 건수·번호만 돌려준다."""
    erp, erp_key = client_for(catalog.c11("erp") or catalog.C11_APPS[0])
    mails = [{"받는사람": "a@example.com", "제목": "독촉", "본문": "비밀스러운 금액 이야기"}]
    found = output(erp, erp_key, "send_customer_mail", {"메일": mails})
    assert found["result"] == {"보낸건수": 1, "실패": []}
    assert "비밀스러운" not in json.dumps(found, ensure_ascii=False)

    crm, crm_key = client_for(catalog.c11("crm") or catalog.C11_APPS[0])
    attached = output(crm, crm_key, "attach_document", {"request_id": "Q-01", "file": "견적/가나상사.md"})
    assert "가나상사" not in json.dumps(attached, ensure_ascii=False)


# ─────────────────────────── 외부 앱 (C13 §4) ───────────────────────────


def parsed(app_id: str, base_url: str) -> ExtensionManifest:
    return ExtensionManifest.model_validate(definitions.BUILDERS[app_id](base_url))


@pytest.mark.parametrize("app_id", sorted(definitions.BUILDERS))
def test_an_external_definition_passes_the_c13_checks(app_id: str) -> None:
    """E1(코드 기여 없음)·E3(어댑터 선언) — `chk-admin sign-extension`이 먼저 돌리는 것들이다."""
    found = parsed(app_id, "http://127.0.0.1:8150")
    assert validate(found, from_center=True) == []
    assert found.is_external
    assert not found.can_contribute_code
    assert found.adapter is not None


@pytest.mark.parametrize("app_id", sorted(definitions.BUILDERS))
def test_an_external_definition_only_opens_the_private_network_for_localhost(app_id: str) -> None:
    """127.0.0.1을 부르려면 열어야 하지만, 진짜 외부 주소에는 그 칸이 없어야 한다 (§4-3 4번)."""
    local = parsed(app_id, "http://127.0.0.1:8150").adapter
    public = parsed(app_id, "https://api.example.com").adapter
    assert local is not None and public is not None
    assert local.allow_private_network is True
    assert public.allow_private_network is False
    assert public.allowed_hosts == ["api.example.com"]


@pytest.mark.parametrize("app_id", sorted(definitions.BUILDERS))
def test_an_external_operation_accepts_both_modes(app_id: str) -> None:
    """외부 작업의 기본은 자율 수행이다 — 결정 수행은 **정의가 명시해야** Bot이 부를 수 있다."""
    adapter = parsed(app_id, "http://127.0.0.1:8150").adapter
    assert adapter is not None
    assert all(set(one.modes) == {"deterministic", "autonomous"} for one in adapter.operations)


class Addresses:
    """주소와 키 값을 주는 쪽 (ADR-0013 — 키는 여기서만 나온다)."""

    def __init__(self, base: str, key: str = "ext-secret-1") -> None:
        self._base = base
        self._key = key

    def base_url(self, app_id: str) -> str | None:
        return self._base

    def key(self, key_ref: str) -> str | None:
        return self._key


@pytest.fixture(scope="module")
def external() -> Iterator[dict[str, str]]:
    """모의 외부 앱 둘을 **진짜 소켓에** 띄운다 (`{app_id: base_url}`).

    ASGI로 끼우지 않는 것은 어댑터가 호스트를 IP로 풀어 그 IP로 접속하기 때문이다 (§4-3 3번).
    """
    made: dict[str, str] = {}
    servers = []
    for app_id, build_app in external_apps.BUILDERS.items():
        config = uvicorn.Config(build_app(), host="127.0.0.1", port=0, log_level="warning")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 20
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started, f"{app_id}이 뜨지 않았다"
        made[app_id] = f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
        servers.append((server, thread))
    yield made
    for server, thread in servers:
        server.should_exit = True
        thread.join(timeout=10)


def adapter_caller(app_id: str, base: str, *, key: str = "ext-secret-1") -> AdapterCaller:
    """진짜 어댑터 + 진짜 소켓에 떠 있는 모의 외부 앱.

    여기서 보는 것은 **정의가 그 앱과 맞물리는가**다 (템플릿·제한 JSONPath·`error_when`).
    어댑터의 네트워크 규칙(DNS 재바인딩·사설망·리다이렉트)은 `test_core_http_adapter.py`가 본다.
    """
    return AdapterCaller(
        definitions={app_id: parsed(app_id, base)},
        addresses=Addresses(base, key),
        resolver=lambda host: ["127.0.0.1"],
    )


def ext_op_call(app_id: str, operation: str, payload: dict[str, Any], **over: Any) -> OpCall:
    body: dict[str, Any] = {
        "app_id": app_id,
        "operation": operation,
        "mode": "deterministic",
        "input": payload,
        "run_id": RUN_ID,
        "node_id": "Task_1",
        "node_instance": 1,
        "attempt": 1,
        "key_ref": "finance-credit",
    }
    body.update(over)
    return OpCall(**body)


def ext_call(app_id: str, base: str, operation: str, payload: dict[str, Any], **over: Any) -> Any:
    return adapter_caller(app_id, base).call(ext_op_call(app_id, operation, payload, **over))


def test_fx20_the_adapter_brings_back_the_result_the_case_expects(external: dict[str, str]) -> None:
    """FX-20 「모의 서버」가 `결과 = {"score": 780}`를 기대한다.

    낙타 표기(`bizNo`)·자기 봉투(`{"status": …, "result": …}`)를 **정의가** 우리 말로 옮긴다.
    """
    found = ext_call("ext-credit", external["ext-credit"], "lookup", {"biz_no": "123-45-67890"})
    assert found.output["result"]["score"] == 780


def test_bx06_credit_grades_give_exactly_one_risky_vendor(external: dict[str, str]) -> None:
    """BX-06 「소량 3곳」이 위험수 1을 기대한다. **DMN을 진짜로 돌려** 센다."""
    grade = decision("credit_grade")
    거래처목록 = ["123-45-67890", "234-56-78901", "345-67-89012"]
    등급 = []
    for i, biz_no in enumerate(거래처목록, start=1):
        found = ext_call("ext-credit", external["ext-credit"], "lookup", {"biz_no": biz_no}, node_instance=i)
        result = found.output["result"]
        등급.append(grade.decide({"score": result["score"], "overdue": result["overdue"]})["grade"])
    assert 등급.count("위험") == 1, 등급


def test_an_unknown_vendor_is_a_business_failure_through_error_when(external: dict[str, str]) -> None:
    """모의 앱은 200에 `status: "not_found"`로 답한다 — `error_when`이 그것을 실패로 바꾼다."""
    with pytest.raises(AdapterError) as caught:
        ext_call("ext-credit", external["ext-credit"], "lookup", {"biz_no": "000-00-00000"})
    assert caught.value.code == "operation_failed", caught.value


def test_the_app_refuses_a_call_whose_key_the_adapter_could_not_resolve(external: dict[str, str]) -> None:
    """키는 참조 이름으로 와서 어댑터가 헤더에 싣는다 (ADR-0013). 풀리지 않으면 거기서 멈춘다."""
    caller = adapter_caller("ext-credit", external["ext-credit"], key="")
    with pytest.raises(AdapterError) as caught:
        caller.call(ext_op_call("ext-credit", "lookup", {"biz_no": "123-45-67890"}))
    assert caught.value.code == "key_missing", caught.value


def test_bx35_export_gives_enough_tickets_for_three_batches(external: dict[str, str]) -> None:
    """BX-35 「소량 120건」이 분석묶음 3개를 기대한다 (50씩 나누면 3묶음)."""
    found = ext_call("ext-helpdesk", external["ext-helpdesk"], "export_tickets", {"since": "2026-10-01"})
    items = found.output["items"]
    assert len(items) == external_apps.TICKET_COUNT == 120
    assert math.ceil(len(items) / 50) == 3


def test_bx32_posting_a_reply_comes_back_without_the_reply_text(external: dict[str, str]) -> None:
    """BX-32: 답변은 등록되지만 **글은 되돌아오지 않는다** (원칙 6)."""
    found = ext_call(
        "ext-helpdesk", external["ext-helpdesk"], "post_reply", {"ticket_id": "T-1001", "body": "안녕하세요 고객님"}
    )
    assert found.output["result"]["ok"] is True
    assert "안녕하세요" not in json.dumps(found.output, ensure_ascii=False)


def test_posting_a_reply_is_not_idempotent() -> None:
    """답변은 다시 보내면 두 번 달린다 — 그래서 BX-32가 **사람에게 확인**을 묻는다."""
    adapter = parsed("ext-helpdesk", "http://127.0.0.1:8150").adapter
    assert adapter is not None
    by_name = {one.name: one for one in adapter.operations}
    assert by_name["post_reply"].idempotent is False
    assert by_name["post_reply"].retry_on == []
    assert by_name["export_tickets"].idempotent is True


# ─────────────────────────── CLI ───────────────────────────


def test_the_cli_lists_every_app(capsys: pytest.CaptureFixture[str]) -> None:
    from chaeksas.mock_apps.cli import main  # noqa: PLC0415

    assert main(["list"]) == 0
    printed = capsys.readouterr().out
    for app_id in catalog.ids():
        assert app_id in printed


def test_the_cli_writes_a_definition_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """정의는 주소를 담아 커밋할 수 없다 — CLI가 그 자리에서 쓴다 (C13 E6으로 서명해 등록)."""
    from chaeksas.mock_apps.cli import main  # noqa: PLC0415

    out = tmp_path / "ext-credit.json"
    assert main(["definition", "ext-credit", "--base-url", "http://127.0.0.1:8150", "-o", str(out)]) == 0
    found = json.loads(out.read_text(encoding="utf-8"))
    assert found["id"] == "ext-credit"
    assert validate(ExtensionManifest.model_validate(found), from_center=True) == []
    capsys.readouterr()


def test_the_cli_refuses_an_app_that_is_not_external(capsys: pytest.CaptureFixture[str]) -> None:
    from chaeksas.mock_apps.cli import main  # noqa: PLC0415

    assert main(["definition", "erp", "--base-url", "http://127.0.0.1:8010"]) == 2
    capsys.readouterr()


@pytest.mark.parametrize("encoding", ["cp949", "cp1252", "ascii"])
def test_the_cli_survives_a_non_utf8_stdout(encoding: str) -> None:
    """한글을 찍는 도구는 stdout도 UTF-8로 고정한다 (CLAUDE.md §5).

    Windows 콘솔의 기본 코드페이지에서는 `print("종류")` 한 줄이 `UnicodeEncodeError`로 죽는다.
    `tests/test_generators_on_windows_encoding.py`와 같은 수법으로 Linux에서도 막는다.
    """
    root = Path(__file__).resolve().parent.parent
    found = subprocess.run(
        [sys.executable, "-m", "chaeksas.mock_apps.cli", "list"],
        capture_output=True,
        text=True,
        cwd=root,
        env=dict(os.environ, PYTHONIOENCODING=encoding),
        check=False,
    )
    assert found.returncode == 0, f"stdout 인코딩 {encoding}에서 깨졌다:\n{found.stdout}{found.stderr}"


def test_default_ports_follow_the_setup_table() -> None:
    """`docs/04-setup.md` §6 — 「다음 서비스 앱: 8010부터 10씩」. 코드에 흩어 적지 않는다."""
    order = catalog.ids()
    assert catalog.port_of(order[0]) == 8010
    assert catalog.port_of(order[1]) == 8020
    assert len({catalog.port_of(one) for one in order}) == len(order)


def test_a_port_can_be_moved_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHK_SVC_KB_SEARCH__PORT", "9999")
    assert catalog.port_of("kb-search") == 9999


def iter_app_modules() -> Iterator[MockApp]:
    yield from catalog.C11_APPS


@pytest.mark.parametrize("mock", catalog.C11_APPS, ids=lambda m: m.app_id)
def test_every_mock_app_says_which_examples_use_it(mock: MockApp) -> None:
    """「이 앱이 왜 있나」가 코드 안에 있어야 한다 — 숫자를 고칠 때 케이스를 찾아갈 수 있게."""
    assert mock.used_by, mock.app_id
    assert mock.doc, mock.app_id


def test_handlers_take_the_request_and_the_scenario() -> None:
    """작업 함수의 규약 하나 — 요청과 시나리오만 받는다 (상태를 들고 있지 않는다)."""
    mock = catalog.c11("wms")
    assert mock is not None
    found = mock.op("list_stock")
    assert found is not None
    request = OpRequest.model_validate(
        {
            "schema": 1,
            "mode": "deterministic",
            "run_id": RUN_ID,
            "node_id": "Task_1",
            "node_instance": 1,
            "attempt": 1,
            "caller": {"type": "studio"},
            "input": {},
        }
    )
    from chaeksas.mock_apps.c11 import Scenario  # noqa: PLC0415

    assert found.answer(request, Scenario())["items"]
