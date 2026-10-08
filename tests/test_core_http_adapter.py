"""HTTP 어댑터 해석기 — 외부 확장을 부른다 (C13 §4-2·§4-3, M5 조각 11).

**진짜 HTTP 서버**를 127.0.0.1에 띄워 부른다. 사설 주소라 정의가 `allow_private_network`를
켜야 하는데, 그것이 바로 §4-3 4번이 지키는 규칙이다.

거듭 보는 것 일곱.

1. **값은 자리마다 다르게 인코딩된다** — 경로는 조각 하나로(`/`·`..`도), 본문은 JSON 값으로.
2. **허용 호스트 밖·사설 주소·http는 막힌다** (정의가 켜지 않으면).
3. **DNS를 한 번 풀고 그 IP로 간다** — 푼 뒤 바뀌어도 그 IP다.
4. **리다이렉트를 따라가지 않는다** — 따라가면 1~3을 우회한다.
5. **크기 상한은 읽는 동안** 본다.
6. **`retry_on`에 적힌 것만** 다시 부른다. 결과를 모르는 실패는 **멱등일 때만**.
7. **금지 헤더·제어 문자는 거부한다.**
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from chaeksas.contracts.extension import ExtensionManifest
from chaeksas.core.http_adapter import (
    AdapterCaller,
    AdapterError,
    fill_body,
    fill_path,
    read_path,
    resolve,
)
from chaeksas.core.services import OpCall

APP = "ext-ocr"


# ─────────────────────────── 거리 ───────────────────────────


def definition(**over: Any) -> ExtensionManifest:
    """C13 §예시의 외부 확장. `allow_private_network`는 시험이 127.0.0.1을 부르려고 켠다."""
    adapter: dict[str, Any] = {
        "allowed_hosts": ["127.0.0.1"],
        "allow_private_network": True,
        "auth": {"type": "bearer"},
        "limits": {"timeout_s": 5, "max_response_kb": 16},
        "operations": [
            {
                "name": "read_invoice",
                "modes": ["autonomous", "deterministic"],
                "idempotent": False,
                "retry_on": [429, 503],
                "request": {
                    "method": "POST",
                    "path": "/v2/invoice/{{input.doc_id}}",
                    "query": {"ref": "{{run_id}}"},
                    "headers": {"X-Idem": "{{idempotency_key}}"},
                    "body": {"amount": "{{input.amount}}", "note": "건 {{input.doc_id}}"},
                },
                "response": {
                    "output": {"biz_no": "$.result.bizNo", "total": "$.result.total"},
                    "error_when": {"path": "$.status", "not_equals": "ok"},
                },
            }
        ],
    }
    adapter.update(over.pop("adapter", {}))
    base: dict[str, Any] = {
        "schema": 2,
        "id": APP,
        "version": "1.0.0",
        "name": "외부 OCR",
        "publisher": "예시 업체",
        "tier": "external",
        "requires_keys": [{"purpose": "run", "extra_scopes": []}],
        "contributes": {},
    }
    # `service`는 **칸만 골라** 덮을 수 있다 — 통째로 덮으면 어댑터 블록을 잃는다.
    service: dict[str, Any] = {
        "protocol": "http-adapter",
        "base_url": "https://127.0.0.1",
        "adapter": adapter,
    }
    service.update(over.pop("service", {}))
    base["service"] = service
    base.update(over)
    return ExtensionManifest.model_validate(base)


class Addresses:
    """주소와 키 값을 주는 쪽 (ADR-0013 — 키는 여기서만 나온다)."""

    def __init__(self, base: str | None = None, key: str | None = "ocr-secret-1") -> None:
        self._base = base
        self._key = key

    def base_url(self, app_id: str) -> str | None:
        return self._base

    def key(self, key_ref: str) -> str | None:
        return self._key


def op_call(**over: Any) -> OpCall:
    base: dict[str, Any] = {
        "app_id": APP,
        "operation": "read_invoice",
        "mode": "deterministic",
        "input": {"doc_id": "INV-1", "amount": 1100000},
        "run_id": "run_20261008_090000_a1b2c3",
        "node_id": "Task_ocr",
        "key_ref": "ocr-key",
        "bpm_process_id": "finance.invoice",
        "version": "1.0.0",
    }
    base.update(over)
    return OpCall(**base)


class Echo(BaseHTTPRequestHandler):
    """부른 것을 그대로 돌려주는 서버. 시험이 `plan`으로 응답을 바꾼다."""

    plan: dict[str, Any] = {}

    def _answer(self) -> None:
        plan = type(self).plan
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        type(self).seen = {  # type: ignore[attr-defined]
            "path": self.path,
            "headers": dict(self.headers),
            "body": json.loads(raw) if raw else None,
        }
        status = int(plan.get("status", 200))
        if plan.get("location"):
            self.send_response(status)
            self.send_header("Location", str(plan["location"]))
            self.end_headers()
            return
        body = plan.get("body", {"status": "ok", "result": {"bizNo": "123-45-67890", "total": 1100000}})
        if plan.get("huge"):
            payload = json.dumps({"filler": "x" * plan["huge"]}).encode()
        elif plan.get("not_json"):
            payload = "<html>아니다</html>".encode()
        else:
            payload = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _answer
    do_POST = _answer

    def log_message(self, *args: Any) -> None:  # 조용히
        return


@pytest.fixture
def server() -> Iterator[tuple[int, type[Echo]]]:
    Echo.plan = {}
    made = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
    thread = threading.Thread(target=made.serve_forever, daemon=True)
    thread.start()
    yield made.server_address[1], Echo
    made.shutdown()
    made.server_close()
    thread.join(timeout=5)


def caller(port: int, *, found: ExtensionManifest | None = None, key: str | None = "ocr-secret-1") -> AdapterCaller:
    return AdapterCaller(
        definitions={APP: found or definition()},
        addresses=Addresses(f"http://127.0.0.1:{port}", key),
    )


# ─────────────────────────── 템플릿 (§4-2) ───────────────────────────


def test_path_values_are_encoded_as_one_segment() -> None:
    """**경로를 벗어나지 못한다** — `/`·`..`까지 인코딩한다 (§4-2)."""
    made = fill_path("/v2/invoice/{{input.doc_id}}", op_call(input={"doc_id": "../../admin"}), idempotency_key="k")
    assert made == "/v2/invoice/..%2F..%2Fadmin"
    # 요점은 **조각 수가 늘지 않는다**는 것이다 — 값에 `/`가 있어도 경로를 벗어나지 못한다.
    assert made.count("/") == "/v2/invoice/x".count("/")


def test_path_values_encode_query_and_fragment_too() -> None:
    made = fill_path("/a/{{input.doc_id}}", op_call(input={"doc_id": "x?y#z&w"}), idempotency_key="k")
    assert made == "/a/x%3Fy%23z%26w"


def test_body_puts_values_as_json_values() -> None:
    """**글자를 이어 붙이지 않는다** — 자리 하나면 그 값 그대로 (수·참거짓·객체)."""
    made = fill_body(
        {"amount": "{{input.amount}}", "flag": "{{input.flag}}", "note": "건 {{input.doc_id}}"},
        op_call(input={"amount": 1100000, "flag": True, "doc_id": "INV-1"}),
        idempotency_key="k",
    )
    assert made == {"amount": 1100000, "flag": True, "note": "건 INV-1"}
    assert isinstance(made["amount"], int), "수가 글자로 바뀌지 않는다"


def test_a_missing_input_is_refused() -> None:
    with pytest.raises(AdapterError) as caught:
        fill_path("/a/{{input.없는것}}", op_call(), idempotency_key="k")
    assert caught.value.code == "input_invalid"


def test_restricted_jsonpath_reads_and_misses_quietly() -> None:
    body = {"result": {"bizNo": "1", "rows": [{"v": 7}]}}
    assert read_path(body, "$.result.bizNo") == "1"
    assert read_path(body, "$.result.rows[0].v") == 7
    assert read_path(body, "$.result.missing") is None, "없는 자리는 None (선택 출력일 수 있다)"
    with pytest.raises(AdapterError):
        read_path(body, "$.result[*].v")
    # 계약의 제한 JSONPath는 **ASCII 식별자만** 받는다 — 한글 열쇠는 적을 수 없다.
    with pytest.raises(AdapterError):
        read_path(body, "$.결과")


# ─────────────────────────── 나가기 전 검사 (§4-3 1~4) ───────────────────────────


def _resolve(**over: Any) -> Any:
    found = over.pop("definition", definition())
    adapter = found.service.adapter
    return resolve(
        base_url=over.pop("base_url", "https://127.0.0.1"),
        operation=adapter.operations[0],
        adapter=adapter,
        call=over.pop("call", op_call()),
        idempotency_key="k",
        resolver=over.pop("resolver", lambda host: ["127.0.0.1"]),
    )


def test_a_host_outside_allowed_hosts_is_refused() -> None:
    with pytest.raises(AdapterError) as caught:
        _resolve(base_url="https://evil.example.com")
    assert caught.value.code == "host_not_allowed"


def test_a_private_address_needs_the_flag() -> None:
    """**사설·루프백은 정의가 켜야만** 간다 — 이 규칙이 같은 PC의 Worker도 막는다."""
    closed = definition(
        adapter={"allow_private_network": False, "allowed_hosts": ["inside.example.com"]}
    )
    with pytest.raises(AdapterError) as caught:
        _resolve(definition=closed, base_url="https://inside.example.com", resolver=lambda h: ["10.0.0.5"])
    assert caught.value.code == "host_not_allowed"
    assert "10.0.0.5" in str(caught.value)


def test_plain_http_is_refused_on_a_public_host() -> None:
    public = definition(adapter={"allow_private_network": False, "allowed_hosts": ["ocr.example.com"]})
    with pytest.raises(AdapterError) as caught:
        _resolve(definition=public, base_url="http://ocr.example.com", resolver=lambda h: ["93.184.216.34"])
    assert caught.value.code == "host_not_allowed"


def test_the_request_goes_to_the_resolved_ip_with_the_original_host() -> None:
    """**DNS를 한 번 풀고 그 IP로** 간다 — Host 헤더는 원래 이름이다 (재바인딩 방지)."""
    made = _resolve(resolver=lambda host: ["127.0.0.1", "127.0.0.2"])
    assert made.ip == "127.0.0.1"
    assert made.url.startswith("https://127.0.0.1/"), made.url
    assert made.headers["Host"] == "127.0.0.1"
    assert made.host == "127.0.0.1", "SNI에 쓸 원래 이름"


def test_an_unresolvable_host_is_retryable() -> None:
    def broken(host: str) -> list[str]:
        raise OSError("안 풀린다")

    with pytest.raises(AdapterError) as caught:
        _resolve(resolver=broken)
    assert caught.value.retryable is True


def test_a_forbidden_header_template_is_refused() -> None:
    bad = definition(
        adapter={
            "operations": [
                {
                    "name": "read_invoice",
                    "modes": ["deterministic"],
                    "request": {
                        "method": "GET",
                        "path": "/a",
                        "headers": {"Authorization": "{{input.doc_id}}"},
                    },
                }
            ]
        }
    )
    with pytest.raises(AdapterError) as caught:
        _resolve(definition=bad)
    assert caught.value.code == "adapter_invalid"


def test_control_characters_in_a_header_are_refused() -> None:
    """헤더를 쪼개 다른 것을 끼우지 못하게 (§4-2)."""
    bad = definition(
        adapter={
            "operations": [
                {
                    "name": "read_invoice",
                    "modes": ["deterministic"],
                    "request": {"method": "GET", "path": "/a", "headers": {"X-Ref": "{{input.doc_id}}"}},
                }
            ]
        }
    )
    with pytest.raises(AdapterError) as caught:
        _resolve(definition=bad, call=op_call(input={"doc_id": "a\r\nX-Evil: 1"}))
    assert caught.value.code == "adapter_invalid"


# ─────────────────────────── 진짜로 부르기 (§4-3 5~7) ───────────────────────────


def test_a_call_goes_out_and_maps_the_output(server: tuple[int, type[Echo]]) -> None:
    """한 바퀴 — 템플릿 → 요청 → 출력 매핑."""
    port, echo = server
    found = caller(port).call(op_call())
    assert found.output == {"biz_no": "123-45-67890", "total": 1100000}
    assert found.status == 200 and found.mode_used == "deterministic"

    seen = echo.seen  # type: ignore[attr-defined]
    assert seen["path"] == "/v2/invoice/INV-1?ref=run_20261008_090000_a1b2c3"
    assert seen["body"] == {"amount": 1100000, "note": "건 INV-1"}
    assert seen["headers"]["Authorization"] == "Bearer ocr-secret-1", "키는 정해진 자리에만"
    assert "read_invoice:run_20261008_090000_a1b2c3" in seen["headers"]["X-Idem"]


def test_the_key_never_rides_the_query(server: tuple[int, type[Echo]]) -> None:
    """**쿼리 인증은 없다** (§4-1) — 주소·로그에 키가 남지 않는다."""
    port, echo = server
    caller(port).call(op_call())
    assert "ocr-secret-1" not in echo.seen["path"]  # type: ignore[attr-defined]


def test_a_header_auth_goes_where_the_definition_says(server: tuple[int, type[Echo]]) -> None:
    port, echo = server
    found = definition(
        adapter={"auth": {"type": "header", "name": "X-API-Key"}}
    )
    caller(port, found=found).call(op_call())
    seen = echo.seen  # type: ignore[attr-defined]
    assert seen["headers"]["X-API-Key"] == "ocr-secret-1" and "Authorization" not in seen["headers"]


def test_a_missing_key_is_refused(server: tuple[int, type[Echo]]) -> None:
    port, _echo = server
    with pytest.raises(AdapterError) as caught:
        caller(port, key=None).call(op_call())
    assert caught.value.code == "key_missing"


def test_a_non_ascii_key_is_refused_clearly(server: tuple[int, type[Echo]]) -> None:
    """**헤더는 ASCII다** (CLAUDE.md §5) — 그대로 보내면 라이브러리가 죽는다. 먼저 막는다."""
    port, _echo = server
    with pytest.raises(AdapterError) as caught:
        caller(port, key="한글키").call(op_call())
    assert caught.value.code == "key_invalid"


def test_a_redirect_is_not_followed(server: tuple[int, type[Echo]]) -> None:
    """따라가면 허용 호스트·사설망 검사를 우회할 수 있다 (§4-3 5번)."""
    port, echo = server
    echo.plan = {"status": 302, "location": "https://evil.example.com/steal"}
    with pytest.raises(AdapterError) as caught:
        caller(port).call(op_call())
    assert caught.value.code == "redirect_not_allowed"
    assert "evil.example.com" in str(caught.value), "어디로 보내려 했는지 말한다"


def test_a_response_over_the_limit_is_cut(server: tuple[int, type[Echo]]) -> None:
    """**읽는 동안** 끊는다 — 다 받아 놓고 재지 않는다 (§4-3 6번)."""
    port, echo = server
    echo.plan = {"huge": 32 * 1024}  # 상한은 16 KB
    with pytest.raises(AdapterError) as caught:
        caller(port).call(op_call())
    assert caught.value.code == "response_too_large"


def test_error_when_makes_it_a_business_failure(server: tuple[int, type[Echo]]) -> None:
    port, echo = server
    echo.plan = {"body": {"status": "failed", "result": {}}}
    with pytest.raises(AdapterError) as caught:
        caller(port).call(op_call())
    assert caught.value.code == "operation_failed"
    assert caught.value.retryable is False, "업무 실패는 다시 불러도 같다"


def test_only_retry_on_codes_are_retryable(server: tuple[int, type[Echo]]) -> None:
    """**요청이 처리되지 않았다는 뜻의 코드만** 다시 부른다 (§4-1)."""
    port, echo = server
    echo.plan = {"status": 503}
    with pytest.raises(AdapterError) as caught:
        caller(port).call(op_call())
    assert caught.value.status == 503 and caught.value.retryable is True

    echo.plan = {"status": 400}
    with pytest.raises(AdapterError) as caught:
        caller(port).call(op_call())
    assert caught.value.status == 400 and caught.value.retryable is False


def test_a_result_unknown_failure_is_retried_only_when_idempotent() -> None:
    """**멱등이 아니면 다시 부르지 않는다** — 저쪽이 이미 처리했을 수 있다 (§4-1)."""
    import httpx

    class Dead:
        def stream(self, *args: Any, **kwargs: Any) -> Any:
            raise httpx.ConnectError("끊겼다")

        def close(self) -> None:
            return

    once = AdapterCaller(
        definitions={APP: definition()},
        addresses=Addresses("http://127.0.0.1:9", "ocr-secret-1"),
        client=Dead(),
        resolver=lambda host: ["127.0.0.1"],
    )
    with pytest.raises(AdapterError) as caught:
        once.call(op_call())
    assert caught.value.code == "unreachable" and caught.value.retryable is False

    safe = definition(
        adapter={
            "operations": [
                {
                    "name": "read_invoice",
                    "modes": ["deterministic"],
                    "idempotent": True,
                    "request": {"method": "GET", "path": "/a"},
                }
            ]
        }
    )
    again = AdapterCaller(
        definitions={APP: safe},
        addresses=Addresses("http://127.0.0.1:9", "ocr-secret-1"),
        client=Dead(),
        resolver=lambda host: ["127.0.0.1"],
    )
    with pytest.raises(AdapterError) as caught:
        again.call(op_call())
    assert caught.value.retryable is True


def test_a_mode_the_definition_did_not_allow_is_refused(server: tuple[int, type[Echo]]) -> None:
    """외부 작업의 기본은 자율 수행이다 — 결정 수행은 **명시해야** 한다 (§4-1)."""
    port, _echo = server
    only_auto = definition(
        adapter={
            "operations": [
                {
                    "name": "read_invoice",
                    "modes": ["autonomous"],
                    "request": {"method": "GET", "path": "/a"},
                }
            ]
        }
    )
    with pytest.raises(AdapterError) as caught:
        caller(port, found=only_auto).call(op_call(mode="deterministic"))
    assert caught.value.code == "mode_unsupported"


def test_an_unknown_operation_is_refused(server: tuple[int, type[Echo]]) -> None:
    port, _echo = server
    with pytest.raises(AdapterError) as caught:
        caller(port).call(op_call(operation="없는작업"))
    assert caught.value.code == "operation_unknown"


def test_a_non_json_response_is_refused(server: tuple[int, type[Echo]]) -> None:
    port, echo = server
    echo.plan = {"not_json": True}
    with pytest.raises(AdapterError) as caught:
        caller(port).call(op_call())
    assert caught.value.code == "bad_response"


def test_the_registered_address_beats_the_definition(server: tuple[int, type[Echo]]) -> None:
    """§4-3 1번 — **리소스 등록의 `base_url`이 먼저**다 (운영자가 주소를 옮길 수 있어야 한다)."""
    port, echo = server
    # 정의에는 닿지 못하는 주소가 적혀 있다. 등록된 주소로 가야 한다.
    found = definition(service={"base_url": "https://ocr.example.com"})
    made = AdapterCaller(
        definitions={APP: found},
        addresses=Addresses(f"http://127.0.0.1:{port}", "ocr-secret-1"),
    )
    assert made.call(op_call()).status == 200
    assert echo.seen["path"].startswith("/v2/invoice/INV-1")  # type: ignore[attr-defined]


def test_no_address_at_all_is_refused() -> None:
    """등록도 없고 정의에도 없으면 **부르지 않는다** (어디로 보낼지 모른다)."""
    found = definition(service={"base_url": None})
    made = AdapterCaller(definitions={APP: found}, addresses=Addresses(None, "ocr-secret-1"))
    with pytest.raises(AdapterError) as caught:
        made.call(op_call())
    assert "주소를 모른다" in str(caught.value)


def test_knows_tells_c11_from_adapter() -> None:
    """부르는 쪽이 **어느 길로 갈지** 고른다 — C11 앱은 이 어댑터가 모른다."""
    one = AdapterCaller(definitions={APP: definition()}, addresses=Addresses())
    assert one.knows(APP) is True
    assert one.knows("ui-automation") is False


def test_the_event_data_carries_no_business_values(server: tuple[int, type[Echo]]) -> None:
    """C3 `service_call`에 **업무 값이 담기지 않는다** (원칙 6)."""
    port, _echo = server
    call = op_call()
    found = caller(port).call(call)
    data = found.event_data(call)
    assert data["app_id"] == APP and data["operation"] == "read_invoice"
    assert data["key_ref"] == "ocr-key"
    body = json.dumps(data, ensure_ascii=False)
    assert "123-45-67890" not in body and "INV-1" not in body
