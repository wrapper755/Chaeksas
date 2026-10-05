"""모델에 닿는 자리 — 실체는 `chaeksas.llm`이다 (ADR-0034).

서비스 앱도 같은 클라이언트를 쓰도록 맨 아래 패키지로 내렸다. 엔진과 실행하는 쪽(Studio·Bot UI·
서버 실행기)은 지금처럼 `chaeksas.core.llm`에서 가져와도 된다 — 같은 것을 다시 내보낸다.
"""

from __future__ import annotations

from chaeksas.llm import (
    DEFAULT_TIMEOUT_S,
    RETRYABLE_STATUS,
    Llm,
    LlmError,
    NoLlm,
    OpenAiCompatibleLlm,
    RecordingLlm,
    Reply,
    ToolCall,
    ToolSpec,
    parse_reply,
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
