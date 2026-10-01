# Chaeksas

BPMN으로 업무 프로세스를 그리고, 각 단계의 실제 일(웹·데스크톱 화면 조작, 문서 처리, 판단, 서버 API 호출)은 AI 에이전트·Worker·서비스 앱이 수행하는 업무 자동화 플랫폼.

> **현재 상태: 문서 단계 (코드 없음).** 구현은 [docs/05-roadmap.md](docs/05-roadmap.md)의 M1부터 시작한다.
> 이 저장소는 프로토타입 4개를 **참고만 하여 새로 만든다.** 프로토타입 코드는 수정하지 않는다 ([ADR-0001](docs/decisions/0001-new-repo-prototypes-as-reference.md)).

## 처음 보는 사람이 읽는 순서

| 순서 | 문서 | 알게 되는 것 |
| --- | --- | --- |
| 1 | [docs/00-vision.md](docs/00-vision.md) | 무엇을 만들고, 무엇을 만들지 않는가 |
| 2 | [docs/02-glossary.md](docs/02-glossary.md) | 용어 하나에 뜻 하나 (Bot, Worker, 프로세스, 서비스 앱…) |
| 3 | [docs/01-architecture.md](docs/01-architecture.md) | 구성요소, 어디서 도는가, 누가 누구를 부르는가 |
| 4 | [docs/06-screens/](docs/06-screens/README.md) | 화면 설계 (Studio, Bot, Worker, Center 콘솔, Admin) |
| 5 | [docs/decisions/](docs/decisions/README.md) | 지금까지 내린 결정과 그 이유 |
| 6 | [docs/03-contracts/](docs/03-contracts/README.md) | 구성요소 사이의 약속 (API·이벤트·패키지) |
| 7 | [docs/04-setup.md](docs/04-setup.md) | Windows·Linux에서 개발 환경 만들기, 포트 |
| 8 | [docs/05-roadmap.md](docs/05-roadmap.md) | 단계와 완료 기준 |
| 참고 | [docs/reference/](docs/reference/README.md) | 프로토타입 4개의 지도와 배운 점 |

## 실행 환경 한눈에

| 구성요소 | 주 환경 | 선택 환경 |
| --- | --- | --- |
| 서버 (Center, 서비스 앱) | Linux | Windows |
| 클라이언트 (Studio, Bot, Worker) | Windows | Linux |

근거: [ADR-0003](docs/decisions/0003-target-platforms.md)

## 작업 방식 요약

**실험 → 결정 → 명세 → 구현.** 모르는 것은 `spikes/`에서 마음껏 실험하되, 실험이 끝나면 ADR 한 장을 남긴다. 구성요소 사이의 약속은 `docs/03-contracts/`에, 화면은 `docs/06-screens/`에 코드보다 먼저 쓴다. 자세한 규칙은 [CLAUDE.md](CLAUDE.md)와 [ADR-0002](docs/decisions/0002-docs-first-and-adr.md).
