"""HTTP 어댑터 해석기 — 외부 확장의 작업을 부른다 (C13 §4-2·§4-3).

외부 앱은 C11을 따르지 않는다. 확장 정의가 「이 작업은 이 주소로 이렇게 부르고 응답의 이
자리를 읽어라」를 적어 두고, 이 모듈이 그대로 수행한다. **정의는 서명으로 고정된다** (C2
`extension`) — 그래서 해석기는 정의를 믿고, 대신 **나가는 요청을 막는 데** 힘을 쓴다.

막는 것 일곱 (§4-3). 하나라도 빠지면 정의 하나가 Bot의 키를 엉뚱한 곳으로 보낼 수 있다.

1. 주소는 **리소스 등록의 `base_url`이 이긴다** (없으면 정의의 것). 환경별 주소의 출처는 하나다.
2. **https만.** `allow_private_network`이고 호스트가 사설 주소일 때만 http를 허용한다.
3. 호스트가 `allowed_hosts`에 **정확히** 있어야 한다 (와일드카드 없음).
4. **DNS를 한 번 풀고 그 IP로 접속한다** — 푼 뒤에 DNS가 바뀌어도 그 IP로 간다 (재바인딩
   방지). 사설망을 허용하지 않으면 루프백·사설·링크 로컬 IP를 거부한다 — 이 규칙이 같은 PC의
   Worker도 막는다.
5. **리다이렉트를 따라가지 않는다.** 3xx는 오류다 — 따라가면 1~4를 우회할 수 있다.
6. 응답은 **읽는 동안** `max_response_kb`를 넘으면 끊는다 (다 받아 놓고 재지 않는다).
7. 결과는 C3 `service_call`로 남는다 — **요청·응답 본문은 남기지 않는다** (원칙 6).

값을 끼우는 자리마다 **인코딩이 다르다** (§4-2): 경로는 조각 하나로, 쿼리는 값마다, 헤더는
제어 문자 거부, 본문은 **JSON 값으로** 넣는다 (문자열을 이어 붙이지 않는다).
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from chaeksas.contracts.extension import (
    FORBIDDEN_HEADERS,
    AdapterOperation,
    ExtensionManifest,
    HttpAdapter,
    is_restricted_jsonpath,
)
from chaeksas.core.services import OpCall, OpOutcome, ServiceCallError

#: 템플릿 자리 (§4-2). 중괄호 두 개 안에 **변수 이름 하나만** 온다.
_SLOT = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")

#: 제어 문자 — 헤더 값에 있으면 거부한다 (헤더 쪼개기 방지).
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

#: 응답을 읽는 덩어리 크기. 상한을 넘는 순간 끊는다.
_CHUNK = 8192


class AdapterError(ServiceCallError):
    """어댑터 호출이 막혔거나 실패했다. `code`가 왜인지 말한다."""


@dataclass(frozen=True)
class Resolved:
    """부를 준비가 된 요청 하나. 시험이 들여다볼 수 있게 따로 둔다."""

    method: str
    url: str
    host: str
    ip: str
    headers: dict[str, str]
    body: Any | None
    timeout_s: float


# ─────────────────────────── 템플릿 (§4-2) ───────────────────────────


def _value_of(var: str, call: OpCall, *, idempotency_key: str) -> Any:
    """템플릿 변수 하나의 값. **쓸 수 있는 것만** 준다 (그 밖은 정의 검사가 이미 막았다)."""
    if var == "run_id":
        return call.run_id
    if var == "node_id":
        return call.node_id
    if var == "idempotency_key":
        return idempotency_key
    if var.startswith("input."):
        name = var[len("input.") :]
        if name not in call.input:
            raise AdapterError(
                f"입력 「{name}」이 없다 (템플릿 {{{{{var}}}}})", code="input_invalid"
            )
        return call.input[name]
    # 정의 검사(E3)를 통과했으면 여기 오지 않는다 — 와도 **지어내지 않는다**.
    raise AdapterError(f"템플릿에 쓸 수 없는 변수다: {var}", code="adapter_invalid")


def _as_text(value: Any) -> str:
    """템플릿에 끼울 글자. 참·거짓은 JSON 표기로 (파이썬 `True`가 나가지 않게)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def fill_path(template: str, call: OpCall, *, idempotency_key: str) -> str:
    """경로. 값은 **경로 조각 하나로** 인코딩한다 — `/`·`..`·`@`·`?`·`#`도 인코딩된다 (§4-2)."""

    def swap(match: re.Match[str]) -> str:
        found = _as_text(_value_of(match.group(1), call, idempotency_key=idempotency_key))
        # `safe=""` — 슬래시까지 인코딩해 **경로를 벗어나지 못하게** 한다.
        return quote(found, safe="")

    return _SLOT.sub(swap, template)


def fill_query(template: str, call: OpCall, *, idempotency_key: str) -> str:
    """쿼리 값. 값마다 인코딩한다 (이름은 정의가 고정했다)."""

    def swap(match: re.Match[str]) -> str:
        return quote(
            _as_text(_value_of(match.group(1), call, idempotency_key=idempotency_key)), safe=""
        )

    return _SLOT.sub(swap, template)


def fill_header(name: str, template: str, call: OpCall, *, idempotency_key: str) -> str:
    """헤더 값. **제어 문자가 있으면 거부한다** — 헤더를 쪼개 다른 것을 끼울 수 있다 (§4-2)."""
    if name.lower() in FORBIDDEN_HEADERS:
        # 정의 검사가 막았어야 한다 — 여기까지 왔으면 돌려보낸다 (키가 새는 자리다).
        raise AdapterError(f"헤더 {name}은 템플릿으로 쓸 수 없다", code="adapter_invalid")

    def swap(match: re.Match[str]) -> str:
        return _as_text(_value_of(match.group(1), call, idempotency_key=idempotency_key))

    filled = _SLOT.sub(swap, template)
    if _CONTROL.search(filled):
        raise AdapterError(f"헤더 {name}의 값에 제어 문자가 있다", code="adapter_invalid")
    return filled


def fill_body(template: Any, call: OpCall, *, idempotency_key: str) -> Any:
    """본문. **값을 JSON 값으로 넣는다** — 글자를 이어 붙이지 않는다 (§4-2).

    글자 하나가 템플릿 자리 **하나뿐**이면 그 값을 **그대로**(수·참거짓·객체) 넣는다.
    섞여 있으면 글자로 잇는다 — 그것이 적은 사람의 뜻이다.
    """
    if isinstance(template, dict):
        return {
            key: fill_body(value, call, idempotency_key=idempotency_key)
            for key, value in template.items()
        }
    if isinstance(template, list):
        return [fill_body(one, call, idempotency_key=idempotency_key) for one in template]
    if not isinstance(template, str):
        return template

    whole = _SLOT.fullmatch(template.strip())
    if whole is not None:
        return _value_of(whole.group(1), call, idempotency_key=idempotency_key)

    def swap(match: re.Match[str]) -> str:
        return _as_text(_value_of(match.group(1), call, idempotency_key=idempotency_key))

    return _SLOT.sub(swap, template)


# ─────────────────────────── 제한 JSONPath (§4-2) ───────────────────────────


def read_path(body: Any, path: str) -> Any:
    """`$`, `.이름`, `[숫자]`만 걷는다. 없으면 `None` (오류가 아니다 — 선택 출력일 수 있다)."""
    if not is_restricted_jsonpath(path):
        raise AdapterError(f"제한 JSONPath가 아니다: {path}", code="adapter_invalid")
    found = body
    for step in re.findall(r"\.([^.\[\]]+)|\[(\d+)\]", path):
        name, index = step
        if name:
            if not isinstance(found, dict) or name not in found:
                return None
            found = found[name]
        else:
            if not isinstance(found, list):
                return None
            at = int(index)
            if at >= len(found):
                return None
            found = found[at]
    return found


# ─────────────────────────── 주소와 IP (§4-3) ───────────────────────────


def _is_private(ip: str) -> bool:
    """루프백·사설·링크 로컬인가 (§4-3 4번). 이 규칙이 같은 PC의 Worker도 막는다."""
    found = ipaddress.ip_address(ip)
    return bool(
        found.is_loopback or found.is_private or found.is_link_local or found.is_reserved
    )


def resolve(
    *,
    base_url: str,
    operation: AdapterOperation,
    adapter: HttpAdapter,
    call: OpCall,
    idempotency_key: str,
    resolver: Any = None,
) -> Resolved:
    """부를 요청을 짓고 **§4-3 1~4를 본다.** 막히면 `AdapterError`다 (요청을 내지 않는다)."""
    request = operation.request
    path = fill_path(request.path, call, idempotency_key=idempotency_key)
    if not path.startswith("/"):
        raise AdapterError(f"경로가 `/`로 시작하지 않는다: {request.path}", code="adapter_invalid")

    parts = urlsplit(base_url)
    host = parts.hostname
    if not host or parts.scheme not in ("http", "https"):
        raise AdapterError(f"주소가 http(s)가 아니다: {base_url}", code="adapter_invalid")

    # 3) 허용 호스트 — **정확히** 있어야 한다 (와일드카드 없음).
    if host not in adapter.allowed_hosts:
        raise AdapterError(
            f"허용 호스트 밖이다: {host} (허용 {sorted(adapter.allowed_hosts)})",
            code="host_not_allowed",
        )

    # 4) DNS를 한 번 풀고 그 IP를 본다.
    try:
        found = (resolver or _getaddrinfo)(host)
    except OSError as e:
        raise AdapterError(f"{host}의 주소를 풀지 못했다 ({type(e).__name__})", retryable=True) from e
    if not found:
        raise AdapterError(f"{host}의 주소를 풀지 못했다", retryable=True)
    ip = found[0]
    private = _is_private(ip)
    if private and not adapter.allow_private_network:
        raise AdapterError(
            f"사설·루프백 주소다: {host} → {ip} (정의가 `allow_private_network`를 켜야 한다)",
            code="host_not_allowed",
        )

    # 2) https만 — 사설망을 허용한 사설 주소만 http가 된다.
    if parts.scheme == "http" and not (adapter.allow_private_network and private):
        raise AdapterError(f"https만 쓴다: {base_url}", code="host_not_allowed")

    query = "&".join(
        f"{quote(name, safe='')}={fill_query(value, call, idempotency_key=idempotency_key)}"
        for name, value in (request.query or {}).items()
    )
    headers = {
        name: fill_header(name, value, call, idempotency_key=idempotency_key)
        for name, value in (request.headers or {}).items()
    }
    # **IP로 접속하고 Host는 원래 이름**이다 (DNS 고정). TLS SNI도 원래 이름으로 보낸다.
    netloc = f"[{ip}]" if ":" in ip else ip
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    url = urlunsplit((parts.scheme, netloc, path, query, ""))
    headers["Host"] = parts.netloc

    body = (
        fill_body(request.body, call, idempotency_key=idempotency_key)
        if request.body is not None
        else None
    )
    return Resolved(
        method=request.method.upper(),
        url=url,
        host=host,
        ip=ip,
        headers=headers,
        body=body,
        timeout_s=float(call.timeout_s or adapter.limits.timeout_s),
    )


def _getaddrinfo(host: str) -> list[str]:
    found = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    out: list[str] = []
    for one in found:
        address = str(one[4][0])
        if address not in out:
            out.append(address)
    return out


# ─────────────────────────── 부르기 (§4-3 5~7) ───────────────────────────


@dataclass
class AdapterCaller:
    """외부 확장의 작업을 부르는 `ServiceCaller` (C13 §4).

    `definitions`는 **봉투가 검증된** 정의들이다 (`{확장 id: ExtensionManifest}`) — 검증은
    실행하는 쪽이 받아올 때 한다 (C13 전송, E6). 여기서는 검증된 것만 받는다.

    `addresses`는 `core.services.Addresses`와 같다 — 주소와 키 값을 준다 (ADR-0013).
    """

    definitions: dict[str, ExtensionManifest]
    addresses: Any
    client: Any | None = None  # httpx.Client (시험이 끼운다)
    resolver: Any = None  # 호스트 → IP 목록 (시험이 끼운다)
    #: 이 어댑터가 부른 요청들 (시험·진단용). 값은 담지 않는다.
    seen: list[Resolved] = field(default_factory=list)

    def knows(self, app_id: str) -> bool:
        """그 id가 **어댑터로 부르는** 외부 확장인가. 아니면 C11 쪽이 부른다."""
        found = self.definitions.get(app_id)
        return found is not None and found.service is not None and found.service.adapter is not None

    def call(self, request: OpCall) -> OpOutcome:
        import httpx  # noqa: PLC0415 — 부를 때만 든다

        adapter, operation = self._pick(request)
        key = self._key(request, adapter)
        base = self.addresses.base_url(request.app_id) or (
            self.definitions[request.app_id].service.base_url  # type: ignore[union-attr]
            if self.definitions[request.app_id].service
            else None
        )
        if not base:
            raise AdapterError(f"주소를 모른다: {request.app_id} (리소스 등록·정의 확인)")

        idempotency_key = _idempotency_key(request)
        made = resolve(
            base_url=str(base),
            operation=operation,
            adapter=adapter,
            call=request,
            idempotency_key=idempotency_key,
            resolver=self.resolver,
        )
        self.seen.append(made)

        headers = dict(made.headers)
        if adapter.auth is not None:
            # **키는 정해진 자리에만** 넣는다 — 쿼리 인증은 없다 (주소·로그에 키가 남는다).
            if adapter.auth.type == "bearer":
                headers["Authorization"] = f"Bearer {key}"
            else:
                headers[adapter.auth.name or "X-API-Key"] = key
        if made.body is not None:
            headers.setdefault("Content-Type", "application/json")

        own = self.client is None
        client = self.client or httpx.Client(timeout=made.timeout_s, follow_redirects=False)
        started = time.monotonic()
        try:
            status, body = self._send(client, made, headers, adapter)
        except AdapterError:
            raise
        except httpx.HTTPError as e:
            # **결과를 모르는 실패**다 — 멱등이 아니면 다시 부르지 않는다 (§4-1).
            raise AdapterError(
                f"{request.app_id}에 닿지 못했다 ({type(e).__name__})",
                code="unreachable",
                retryable=bool(operation.idempotent),
            ) from e
        finally:
            if own:
                client.close()
        duration_ms = int((time.monotonic() - started) * 1000)

        if status >= 400:
            raise AdapterError(
                f"{request.app_id}.{operation.name}이 {status}를 돌려줬다",
                code="http_error",
                status=status,
                # **`retry_on`에 적힌 것만** 다시 부른다 (요청이 처리되지 않았다는 뜻이다).
                retryable=status in set(operation.retry_on or ()),
            )
        return self._outcome(request, operation, status=status, body=body, duration_ms=duration_ms)

    # ── 속 ──

    def _pick(self, request: OpCall) -> tuple[HttpAdapter, AdapterOperation]:
        definition = self.definitions.get(request.app_id)
        if definition is None or definition.service is None or definition.service.adapter is None:
            raise AdapterError(f"어댑터 정의가 없다: {request.app_id}", code="adapter_invalid")
        adapter = definition.service.adapter
        operation = next((one for one in adapter.operations if one.name == request.operation), None)
        if operation is None:
            raise AdapterError(
                f"{request.app_id}에 작업 {request.operation}이 없다", code="operation_unknown"
            )
        if request.mode not in operation.modes:
            # 외부 작업의 기본은 자율 수행이다 — 결정 수행은 정의가 **명시해야** 한다 (§4-1).
            raise AdapterError(
                f"{operation.name}은 {request.mode}를 지원하지 않는다 (지원 {operation.modes})",
                code="mode_unsupported",
            )
        return adapter, operation

    def _key(self, request: OpCall, adapter: HttpAdapter) -> str:
        if adapter.auth is None:
            return ""
        if request.key_ref is None:
            raise AdapterError(f"{request.app_id}: 키 참조가 없다 (B7)", code="key_missing")
        found = self.addresses.key(request.key_ref)
        if not found:
            raise AdapterError(
                f"키 참조 「{request.key_ref}」의 값이 이 PC에 없다", code="key_missing"
            )
        key = str(found)
        if not key.isascii():
            # **헤더는 ASCII다** (CLAUDE.md §5) — 그대로 보내면 보내는 쪽 라이브러리가
            # `UnicodeEncodeError`로 죽는다. 왜 안 되는지 분명히 말하고 멈춘다.
            raise AdapterError(
                f"키 참조 「{request.key_ref}」의 값에 ASCII 밖의 글자가 있다 "
                "(HTTP 헤더에 넣을 수 없다 — 키를 다시 발급하세요)",
                code="key_invalid",
            )
        return key

    def _send(
        self, client: Any, made: Resolved, headers: dict[str, str], adapter: HttpAdapter
    ) -> tuple[int, Any]:
        """한 번 왕복한다. **리다이렉트를 따라가지 않고**, 크기 상한을 읽는 동안 본다."""
        limit = int(adapter.limits.max_response_kb) * 1024
        with client.stream(
            made.method,
            made.url,
            headers=headers,
            json=made.body if made.body is not None else None,
            # TLS는 **원래 이름으로** 맞춘다 (IP로 접속하지만 인증서는 호스트 것이다).
            extensions={"sni_hostname": made.host},
            follow_redirects=False,
            timeout=made.timeout_s,
        ) as response:
            if 300 <= response.status_code < 400:
                # 따라가면 허용 호스트·사설망 검사를 우회할 수 있다 (§4-3 5번).
                raise AdapterError(
                    f"리다이렉트는 따라가지 않는다 ({response.status_code} → "
                    f"{response.headers.get('location', '?')})",
                    code="redirect_not_allowed",
                    status=response.status_code,
                )
            raw = bytearray()
            for chunk in response.iter_bytes(_CHUNK):
                raw += chunk
                if len(raw) > limit:
                    # **읽는 동안** 끊는다 — 다 받아 놓고 재지 않는다 (§4-3 6번).
                    raise AdapterError(
                        f"응답이 {adapter.limits.max_response_kb} KB를 넘는다",
                        code="response_too_large",
                        status=response.status_code,
                    )
            if not raw:
                return response.status_code, None
            try:
                return response.status_code, json.loads(bytes(raw))
            except ValueError as e:
                raise AdapterError(
                    f"응답이 JSON이 아니다 ({len(raw)} 바이트)", code="bad_response"
                ) from e

    def _outcome(
        self,
        request: OpCall,
        operation: AdapterOperation,
        *,
        status: int,
        body: Any,
        duration_ms: int,
    ) -> OpOutcome:
        """응답을 출력 변수로 옮긴다. `error_when`이 맞으면 **업무 실패**다 (§4-1)."""
        mapping = operation.response
        if mapping is None:
            return OpOutcome(output={}, status=status, mode_used=request.mode, duration_ms=duration_ms)

        found = mapping.error_when
        if found is not None and _matches(read_path(body, found.path), found):
            raise AdapterError(
                f"{request.app_id}.{operation.name}이 오류를 알렸다 ({found.path})",
                code="operation_failed",
                status=status,
            )
        return OpOutcome(
            output={name: read_path(body, path) for name, path in (mapping.output or {}).items()},
            status=status,
            mode_used=request.mode,
            duration_ms=duration_ms,
        )


def _matches(value: Any, found: Any) -> bool:
    """`error_when`이 맞는가 (§4-1 — `equals` / `not_equals` / `exists` 중 하나)."""
    if found.exists is not None:
        return (value is not None) == bool(found.exists)
    if found.equals is not None:
        return bool(value == found.equals)
    if found.not_equals is not None:
        return bool(value != found.not_equals)
    return False


def _idempotency_key(call: OpCall) -> str:
    """C11과 같은 멱등 키 — 같은 시도는 같은 글자다."""
    return f"{call.operation}:{call.run_id}:{call.node_id}:{call.node_instance}:{call.attempt}:{call.call_seq}"


@dataclass(frozen=True)
class RoutedCaller:
    """외부 확장은 어댑터로, 나머지는 C11로 보낸다.

    **엔진은 어느 쪽인지 모른다** — `chk:serviceCall`은 `app_id`만 적고, 이름 공간이 하나라
    (C13 「전송」) 그 id가 어느 길로 가는지는 여기서 갈린다.
    """

    adapter: AdapterCaller
    others: Any  # ServiceCaller (C11 `HttpServiceCaller`)

    def call(self, request: OpCall) -> OpOutcome:
        side = self.adapter if self.adapter.knows(request.app_id) else self.others
        found: OpOutcome = side.call(request)
        return found


__all__ = [
    "AdapterCaller",
    "AdapterError",
    "Resolved",
    "RoutedCaller",
    "fill_body",
    "fill_header",
    "fill_path",
    "fill_query",
    "read_path",
    "resolve",
]
