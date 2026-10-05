"""런타임 코어 — BPMN 실행, 확장 호스트, AI 태스크, 도구, 재생 기억, 설정 로더

Studio·Bot UI(실행기)·서버 실행기가 함께 쓴다. **화면(Qt)과 서버 통신은 여기 없다**
(docs/01-architecture.md §2·§5).

지금 구현된 것:

| 무엇 | 모듈 |
| --- | --- |
| 확장 호스트 — 확장을 찾아 기여 등록 (ADR-0018, C13) | `extensions` |

아직 없는 것: BPMN 실행, AI 태스크, 도구, 재생 기억, 설정 로더, HTTP 어댑터 해석기
(`docs/05-roadmap.md` M3·M5).
"""

from chaeksas.core.extensions import (
    Contribution,
    ExtensionHost,
    HostTasks,
    LoadedExtension,
    LoadFailure,
    load_host,
    summarize,
)

__all__ = [
    "Contribution",
    "ExtensionHost",
    "HostTasks",
    "LoadFailure",
    "LoadedExtension",
    "load_host",
    "summarize",
]
