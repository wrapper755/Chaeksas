# ADR-0019. 패키지 이름은 `chaeksas.*` 네임스페이스, 폴더 이름은 문서 그대로

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 (2026-10-01) |
| 날짜 | 2026-10-01 |
| 관련 | ADR-0004(워크스페이스), ADR-0005(Python 3.12), ADR-0018(확장), `docs/01-architecture.md` §5·§8 |

## 배경

`01-architecture.md` §8이 폴더 이름(`packages/contracts`, `packages/core`, …)은 정했지만 **import 이름**은 정하지 않았다. M1 뼈대를 만들려면 지금 정해야 한다 — 앞으로 모든 import 줄과 모든 엔트리 포인트 문자열에 박히고, 나중에 바꾸면 전부 고쳐야 한다.
`core`·`qt`·`contracts`는 PyPI에 같은 이름이 이미 있는 흔한 단어다. 플랫폼은 확장을 엔트리 포인트 `chaeksas.extensions`로 찾으므로(ADR-0018), 이름 공간이 이미 `chaeksas`로 잡혀 있다.

## 선택지

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. `chaeksas.*` 네임스페이스 — `from chaeksas.core import ...` | 흔한 이름 충돌 없음. 엔트리 포인트·환경변수(`CHK_`)와 결이 같음. 저장소 밖에서 읽어도 출처가 보임 | 경로가 한 단계 길다. `src/chaeksas/`에 `__init__.py`를 두면 안 된다는 함정 |
| B. 평면 이름 — `from core import ...` | 문서의 의존 그림과 글자가 같다. 짧다 | `core`·`qt` 설치 시 PyPI 패키지와 섞일 위험. 어느 프로젝트 것인지 알 수 없음 |

## 결정

**A. `chaeksas.*` PEP 420 네임스페이스 패키지.** 폴더 이름은 `01-architecture.md` §8 그대로 두고, import 경로만 `chaeksas`를 앞에 붙인다.

| 폴더 | 배포 이름 | import |
| --- | --- | --- |
| `packages/contracts` | `chaeksas-contracts` | `chaeksas.contracts` |
| `packages/extension_api` | `chaeksas-extension-api` | `chaeksas.extension_api` |
| `packages/core` | `chaeksas-core` | `chaeksas.core` |
| `packages/qt` | `chaeksas-qt` | `chaeksas.qt` |
| `packages/service_kit` | `chaeksas-service-kit` | `chaeksas.service_kit` |
| `apps/<이름>` | `chaeksas-<이름>` | `chaeksas.<이름>` |
| `extensions/<id>` | `chaeksas-ext-<id>` | `chaeksas.ext.<id>` |

- 구조는 src 레이아웃이다: `<멤버>/src/chaeksas/<이름>/`. 빌드 백엔드는 hatchling, `packages = ["src/chaeksas"]`.
- **`src/chaeksas/__init__.py`와 `src/chaeksas/ext/__init__.py`를 만들지 않는다.** 만들면 그 멤버 하나만 보이고 나머지 import가 깨진다. `tests/test_workspace.py::test_chaeksas_is_namespace_package`가 막는다.
- 확장은 `chaeksas.ext.<id>` 밑에 `contracts`·`service`·`worker`·`client` 하위 패키지를 둔다 (C13 기여 지점과 1:1). 엔트리 포인트 값은 `chaeksas.ext.<id>:EXTENSION`.
- 워크스페이스 의존은 버전을 달지 않고 `[tool.uv.sources]`의 `workspace = true`로만 잇는다 (`03-contracts/README.md` 원칙 2의 "태그 없이 워크스페이스 의존").

## 결과

- 쉬워지는 것: 이름 충돌 걱정 없이 패키지를 더할 수 있다. 확장은 `chaeksas.ext.*` 한 자리에 모인다.
- 어려워지는 것: 네임스페이스에 `__init__.py`를 넣으면 조용히 깨진다 — 테스트로 막았다.
- 다시 볼 조건: 패키지를 PyPI에 올리게 되면 배포 이름 선점 여부를 확인한다 (지금은 사내 배포뿐).
