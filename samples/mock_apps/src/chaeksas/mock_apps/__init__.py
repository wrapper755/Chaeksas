"""업무 예제가 부르는 모의 앱 — 개발·시험용. **제품에 들어가지 않는다.**

`docs/08-business-examples/`의 예제 50개가 서비스 앱 열여섯 개를 부른다 (작업 31개).
그 앱이 하나도 없으면 M5 인수 시험을 돌릴 수 없어서, 여기에 거짓 데이터로 답하는 앱을 둔다.

- **C11 앱 열넷** (`apps/`) — 사내 확장의 서버 부분. `service_kit`으로 만든다.
- **외부 앱 둘** (`external/`) — 우리 계약을 모르는 남의 API 흉내. HTTP 어댑터로 붙는다 (C13 §4).

거짓 데이터의 값은 **예제 케이스가 정한다** — 케이스의 `expected`가 맞으려면 그 숫자여야
한다. 예제를 비틀지 않고 앱이 예제를 따라간다 (CLAUDE.md §3-6). 자세히: `samples/README.md`.
"""

from chaeksas.mock_apps.c11 import Built, MockApp, Op, Scenario, build

__all__ = ["Built", "MockApp", "Op", "Scenario", "build"]
