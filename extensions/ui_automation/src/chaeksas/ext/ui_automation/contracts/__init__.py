"""이 확장이 소유하는 계약 — C8 계획·치유·보고, C9 화면 레지스트리, C10 Worker 로컬 API

**JSON Schema로 내보낼 모델은 `SCHEMA_MODELS`에 적는다** (계약 README 원칙 5). 플랫폼 생성기
(`scripts/gen_schemas.py`)가 설치된 확장마다 이 표를 읽어 **그 확장의 `schemas/`**에 쓰고, 웹
콘솔의 타입 생성기가 거기서 타입을 만든다 — **확장 이름이 생성기에 나오지 않는다** (ADR-0018).

콘솔 화면(UIA-01~03)이 읽는 모양만 여기 있다. 나머지 계약(C8·C9 작업·C10)은 파이썬끼리만
오가므로 스키마를 만들지 않는다 — 쓰는 쪽이 없는 생성물은 두지 않는다.
"""

from chaeksas.ext.ui_automation.contracts.console import ConsoleOverview

#: 파일 이름 → 모델. 이름 앞에 계약 번호를 붙여 문서에서 찾기 쉽게 한다.
SCHEMA_MODELS = {
    "c9-console-overview": ConsoleOverview,
}

__all__ = ["SCHEMA_MODELS"]
