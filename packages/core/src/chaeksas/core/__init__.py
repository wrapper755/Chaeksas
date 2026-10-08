"""런타임 코어 — BPMN 실행, 확장 호스트, AI 태스크, 도구, 재생 기억

Studio·Bot UI(실행기)·서버 실행기가 함께 쓴다. **화면(Qt)과 서버 통신은 여기 없다**
(docs/01-architecture.md §2·§5).

지금 구현된 것:

| 무엇 | 모듈 |
| --- | --- |
| BPMN 실행 — 상태·수행기 규약, 노드 수행기, 한 걸음씩 돌리기 | `run_state`, `nodes`, `engine` |
| 식·스크립트·템플릿, 도우미 함수, 값 없는 식 검사 (ADR-0025, C14 B15) | `expr`, `helpers`, `expr_check` |
| AI 태스크 — 운전사 루프, 모델에 닿는 길(실체는 `chaeksas.llm`), 내장 도구 | `agent`, `llm`, `tools` |
| 재생 기억 — 자율 수행이 적고 결정 수행이 되밟는다 (ADR-0028) | `replay` |
| 바깥 세계 — 파일, 보내기, 서비스 앱 호출 | `files`, `senders`, `services` |
| 외부 앱 — HTTP 어댑터 해석기, 바깥 앱 한 벌 (C13 §4) | `http_adapter`, `app_directory` |
| 확장 호스트 — 확장을 찾아 기여 등록 (ADR-0018, C13) | `extensions` |
| 사전 점검 — Bot을 띄우기 전, **서버를 부르지 않고** 본다 (ADR-0013, C4 `Readiness`) | `preflight` |
| 서비스 앱 키 상태 — 설정 화면이 누를 때 앱에 묻는다 (C11, BUI-10·STU-10) | `key_check` |
| 실행 기록과 전송 — 파일이 원본이다 (C3) | `run_log`, `run_shipping` |
| 올라가는 결재 요청(ADR-0038), 내려가는 제어 파일(ADR-0031) | `requests`, `control` |
| 자식 프로세스 — Worker·실행기를 띄우고 끈다 (ADR-0023) | `processes` |

**엔진을 쓰는 쪽은 `chaeksas.core.engine` 하나만 본다** — `run_state`·`nodes`를 다시
내보낸다. 나머지도 모듈 경로로 바로 가져온다 (`from chaeksas.core import control`).
그래서 이 `__init__`의 `__all__`에는 확장 호스트 이름만 둔다.

아직 없는 것: 설정 로더 — 지금은 앱마다 따로 있다 (`docs/01-architecture.md` §2).
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
