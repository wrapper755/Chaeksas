"""모델에 닿는 자리 — [ADR-0027](../../../../docs/decisions/0027-llm-connection.md).

보내기(`core.senders`)·서비스 앱(`core.services`)과 **같은 모양**이다. 엔진은 무엇을 물을지만
만들고, 실제로 부르는 일은 실행하는 쪽이 끼우는 어댑터가 한다. 그래야 주소·키·모델 이름이
BPMN에 들어가지 않는다 (C14 기본 규칙 8).

**어댑터를 주지 않으면 부르지 않고 실패한다.** 조용히 넘어가면 AI가 안 돈 채로 업무가 흘러간다.

내장 구현은 **OpenAI 호환 `/v1/chat/completions`** 하나다 — vLLM·Ollama·Azure·사내 게이트웨이가
모두 같은 경로를 연다. 벤더 네이티브가 필요해지면 어댑터를 하나 더 둔다 (ADR-0027 §1).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

#: 한 번 물어볼 때 기다리는 기본 시간 (초).
DEFAULT_TIMEOUT_S = 120.0

#: 다시 물어볼 만한 상태 코드 (잠깐 막힌 것).
RETRYABLE_STATUS = (408, 409, 429, 500, 502, 503, 504)


class LlmError(RuntimeError):
    """모델을 부르지 못했다. `retryable`이면 잠시 뒤 다시 물어볼 만하다."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@dataclass(frozen=True)
class ToolSpec:
    """모델에게 알려 줄 도구 하나. 이름은 `chk:aiTask.tools`에 적힌 것이다."""

    name: str
    description: str = ""
    parameters: Mapping[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})

    def as_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.parameters),
            },
        }


@dataclass(frozen=True)
class ToolCall:
    """모델이 「이 도구를 불러라」고 한 것. `arguments`는 이미 JSON에서 푼 사전이다."""

    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class Reply:
    """모델의 답 한 번. `tool_calls`가 비면 `text`가 최종 답이다."""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class Llm(Protocol):
    """모델 어댑터. 한 번 물어본다. 실패는 `LlmError`로 올린다.

    `messages`는 OpenAI 호환 모양 그대로다 (`role`·`content`·`tool_calls`·`tool_call_id`).
    """

    def ask(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[ToolSpec] = (),
        timeout_s: float | None = None,
    ) -> Reply: ...


class NoLlm:
    """기본 — **부르지 않고 실패한다.** 실행하는 쪽이 어댑터를 끼워야 AI 태스크가 돈다."""

    def ask(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[ToolSpec] = (),
        timeout_s: float | None = None,
    ) -> Reply:
        raise LlmError("모델 어댑터가 없다 (실행하는 쪽이 끼워야 한다)")


@dataclass
class RecordingLlm:
    """시험용 — 정해 둔 답을 차례로 돌려주고, 무엇을 물었는지 담아 둔다.

    스파이크 S7의 스텁과 같은 꼴이다. 진짜 모델 없이 도구 루프·결과 검증·재생을 시험한다.
    """

    replies: list[Reply] = field(default_factory=list)
    asked: list[list[dict[str, Any]]] = field(default_factory=list)
    fails: LlmError | None = None

    def ask(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[ToolSpec] = (),
        timeout_s: float | None = None,
    ) -> Reply:
        if self.fails is not None:
            raise self.fails
        self.asked.append([dict(m) for m in messages])
        if not self.replies:
            raise LlmError("시험용 어댑터에 더 돌려줄 답이 없다")
        return self.replies.pop(0)


@dataclass
class OpenAiCompatibleLlm:
    """OpenAI 호환 `/v1/chat/completions` (ADR-0027).

    `base_url`·`api_key`·`model`은 **실행하는 쪽의 설정·비밀 저장소**에서 온다. BPM 프로세스는
    모른다. `client`를 넣으면 그것을 쓴다 (시험).
    """

    base_url: str
    api_key: str
    model: str
    timeout_s: float = DEFAULT_TIMEOUT_S
    #: 모델에 따라 이름이 다르다 (`temperature`를 안 받는 것도 있다). 그대로 실어 보낸다.
    extra: Mapping[str, Any] = field(default_factory=dict)
    client: Any | None = None  # httpx.Client

    def headers(self) -> dict[str, str]:
        """보낼 헤더. **키가 없으면 `Authorization`을 아예 빼고 보낸다.**

        `Bearer `(빈 값)는 **잘못된 헤더 값**이라 보내는 쪽 라이브러리가 요청 자체를 거부한다
        (`LocalProtocolError`). 키가 필요 없는 로컬 모델(Ollama·vLLM)이 그 자리다 — 인수
        시험에서 실제로 모든 AI 태스크가 여기서 막혔다. 키는 ASCII만 (CLAUDE.md §5).
        """
        found = {"Content-Type": "application/json"}
        if self.api_key:
            found["Authorization"] = f"Bearer {self.api_key}"
        return found

    def ask(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[ToolSpec] = (),
        timeout_s: float | None = None,
    ) -> Reply:
        import httpx  # noqa: PLC0415 — 부를 때만 든다

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(m) for m in messages],
            **dict(self.extra),
        }
        if tools:
            payload["tools"] = [t.as_openai() for t in tools]

        own = self.client is None
        client = self.client or httpx.Client(timeout=timeout_s or self.timeout_s)
        try:
            response = client.post(
                f"{self.base_url.rstrip('/')}/v1/chat/completions",
                json=payload,
                headers=self.headers(),
            )
        except httpx.HTTPError as e:
            raise LlmError(f"모델에 닿지 못했다 ({type(e).__name__})", retryable=True) from e
        finally:
            if own:
                client.close()

        if response.status_code >= 400:
            raise LlmError(
                _message(response),
                status=response.status_code,
                retryable=response.status_code in RETRYABLE_STATUS,
            )
        try:
            return parse_reply(response.json())
        except (ValueError, KeyError, IndexError) as e:
            raise LlmError(f"모델 응답이 OpenAI 호환 모양이 아니다: {e}") from e


def _message(response: Any) -> str:
    try:
        body = response.json()
        found = body.get("error") if isinstance(body, dict) else None
        if isinstance(found, dict) and found.get("message"):
            return str(found["message"])
    except ValueError:
        pass
    return f"모델이 {response.status_code}를 돌려줬다"


def parse_reply(body: Mapping[str, Any]) -> Reply:
    """OpenAI 호환 응답 하나를 `Reply`로. **인자 JSON은 여기서 푼다.**"""
    choice = body["choices"][0]
    message = choice.get("message") or {}
    calls = []
    for raw in message.get("tool_calls") or []:
        function = raw.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except ValueError as e:
            raise ValueError(f"도구 인자가 JSON이 아니다 ({function.get('name')}): {e}") from e
        if not isinstance(arguments, dict):
            raise ValueError(f"도구 인자가 사전이 아니다: {function.get('name')}")
        calls.append(ToolCall(id=raw.get("id") or "", name=function.get("name") or "", arguments=arguments))
    usage = body.get("usage") or {}
    return Reply(
        text=message.get("content") or "",
        tool_calls=tuple(calls),
        model=str(body.get("model") or ""),
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
    )


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "RETRYABLE_STATUS",
    "Llm",
    "LlmError",
    "NoLlm",
    "OpenAiCompatibleLlm",
    "RecordingLlm",
    "Reply",
    "ToolCall",
    "ToolSpec",
    "parse_reply",
]
