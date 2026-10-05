"""서비스 앱의 모델 연결 — C11 §모델 연결, ADR-0034(서비스 앱의 모델 연결).

클라이언트는 `chaeksas.llm` 하나다 (엔진과 같은 것). 여기서 더하는 것은 서비스 앱의 몫뿐이다.

- **설정은 환경변수로만** 받는다 (`CHK_SVC_<APP>__LLM__*`). 키는 비밀이라 코드·파일에 두지 않는다.
- 연결되지 않았는데 모델이 필요한 작업이 불리면 **503 `llm_unavailable`** — 지어낸 답을 주지 않는다.
- 부르다 실패하면 C11 오류로 옮긴다: 잠깐 막힌 것은 `dependency_down`, 그 밖은 `llm_unavailable`.
- 관리 상태에 `llm` 의존 한 줄을 준다. **키 값·주소는 보이지 않는다.**

    llm = ServiceLlm.from_env("CHK_SVC_UI_AUTOMATION__")
    app = create_app(manifest, handlers, keys=store, llm=llm)

    def heal(request):
        reply = llm.ask([...])
        return OpResult({...}, usage=usage_of([reply]))
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from chaeksas.contracts.service_app import Dependency, Usage
from chaeksas.llm import DEFAULT_TIMEOUT_S, Llm, LlmError, OpenAiCompatibleLlm, Reply, ToolSpec
from chaeksas.service_kit.app import OpError

#: 관리 상태(`dependencies`)에 보이는 이름 (C11).
DEPENDENCY_NAME = "llm"
#: 모델이 없거나 설정이 틀렸다 — 다시 시도해도 풀리지 않는다 (C11 오류 표).
LLM_UNAVAILABLE = "llm_unavailable"
#: 잠깐 막혔다 — 다시 시도할 만하다 (C11 오류 표).
DEPENDENCY_DOWN = "dependency_down"


@dataclass(frozen=True)
class LlmSettings:
    """`CHK_SVC_<APP>__LLM__*`에서 읽은 것. **주소와 모델 이름이 둘 다 있어야** 연결이다."""

    base_url: str = ""
    model: str = ""
    api_key: str = ""
    timeout_s: float = DEFAULT_TIMEOUT_S

    @property
    def complete(self) -> bool:
        return bool(self.base_url and self.model)

    @property
    def partial(self) -> bool:
        """하나만 적었다 — 설정을 잊은 것과 구별해서 알린다."""
        return bool(self.base_url or self.model) and not self.complete

    @classmethod
    def from_env(cls, prefix: str, environ: Mapping[str, str] | None = None) -> LlmSettings:
        """`prefix`는 앱의 접두사 그대로다 (`CHK_SVC_UI_AUTOMATION__`).

        시간이 숫자가 아니면 **띄울 때 멈춘다** — 틀린 설정으로 조용히 기본값을 쓰지 않는다.
        """
        env = os.environ if environ is None else environ

        def get(name: str) -> str:
            return (env.get(f"{prefix}LLM__{name}") or "").strip()

        raw_timeout = get("TIMEOUT_S")
        try:
            timeout = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_S
        except ValueError as e:
            raise ValueError(f"{prefix}LLM__TIMEOUT_S가 숫자가 아니다: {raw_timeout!r}") from e
        if timeout <= 0:
            raise ValueError(f"{prefix}LLM__TIMEOUT_S는 0보다 커야 한다: {raw_timeout!r}")
        return cls(base_url=get("BASE_URL"), model=get("MODEL"), api_key=get("API_KEY"), timeout_s=timeout)


class ServiceLlm:
    """서비스 앱이 모델을 부르는 자리. 작업 함수는 이것의 `ask()`만 부른다.

    `client`를 직접 넣을 수 있다 (시험 — `RecordingLlm`). 없으면 연결되지 않은 것이다.
    """

    def __init__(self, client: Llm | None = None, *, model: str = "", partial: bool = False) -> None:
        self.client = client
        self.model = model
        self.partial = partial
        #: 마지막 호출 결과 — 관리 상태가 보인다. 부른 적이 없으면 `unknown`.
        self.last_status = "unknown"

    @classmethod
    def from_settings(cls, settings: LlmSettings) -> ServiceLlm:
        if not settings.complete:
            return cls(partial=settings.partial)
        client = OpenAiCompatibleLlm(
            base_url=settings.base_url,
            api_key=settings.api_key,
            model=settings.model,
            timeout_s=settings.timeout_s,
        )
        return cls(client, model=settings.model)

    @classmethod
    def from_env(cls, prefix: str, environ: Mapping[str, str] | None = None) -> ServiceLlm:
        return cls.from_settings(LlmSettings.from_env(prefix, environ))

    @property
    def configured(self) -> bool:
        return self.client is not None

    def ask(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[ToolSpec] = (),
        timeout_s: float | None = None,
    ) -> Reply:
        """한 번 묻는다. 실패는 **C11 오류(`OpError`)로** 올린다 — 작업 함수는 잡지 않아도 된다."""
        if self.client is None:
            raise OpError(
                LLM_UNAVAILABLE,
                "이 앱에 모델이 설정되지 않았다 (CHK_SVC_<APP>__LLM__BASE_URL·MODEL)",
                status=503,
            )
        try:
            reply = self.client.ask(messages, tools=tools, timeout_s=timeout_s)
        except LlmError as e:
            if e.retryable:
                self.last_status = "unreachable" if e.status is None else "degraded"
                raise OpError(DEPENDENCY_DOWN, f"모델이 잠깐 답하지 못했다: {e}", status=503) from e
            self.last_status = "degraded"
            raise OpError(LLM_UNAVAILABLE, f"모델 설정이 틀렸을 수 있다: {e}", status=503) from e
        self.last_status = "ok"
        return reply

    def dependency(self) -> Dependency:
        """관리 상태의 `llm` 한 줄 (C11). **키 값·주소는 넣지 않는다.**"""
        if self.client is None:
            note = (
                "설정이 덜 됐다 — 주소와 모델 이름이 둘 다 있어야 한다"
                if self.partial
                else "설정되지 않음 — 모델이 필요한 작업은 503 llm_unavailable"
            )
            return Dependency(name=DEPENDENCY_NAME, status="unknown", detail=note)
        detail = f"모델 {self.model}" if self.model else None
        return Dependency(name=DEPENDENCY_NAME, status=self.last_status, detail=detail)


def usage_of(replies: Sequence[Reply]) -> Usage | None:
    """한 작업에서 물은 것을 더해 C11 `usage`로. 물은 적이 없으면 `None`. **금액은 넣지 않는다.**"""
    if not replies:
        return None
    model = next((r.model for r in reversed(replies) if r.model), "")
    return Usage(
        model=model,
        input_tokens=sum(r.input_tokens for r in replies),
        output_tokens=sum(r.output_tokens for r in replies),
    )


__all__ = [
    "DEPENDENCY_DOWN",
    "DEPENDENCY_NAME",
    "LLM_UNAVAILABLE",
    "LlmSettings",
    "ServiceLlm",
    "usage_of",
]
