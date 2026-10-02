# ADR-0020. Windows 데스크톱 조작은 `uiautomation` 라이브러리로 한다

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 (2026-10-03) |
| 날짜 | 2026-10-02 |
| 관련 | 스파이크 `spikes/S1-windows-uia/`, 계약 C8(로케이터)·C10, ADR-0003(클라이언트는 Windows 주), `docs/01-architecture.md` §6 |

## 배경

Worker 프로세스는 Windows 데스크톱 앱을 UIA로 조작한다 (`01-architecture.md` §6). 프로토타입에는 Windows 백엔드가 코드로만 있었고 실기 검증이 없었다 (ADR-0003). 후보는 `pywinauto`(backend="uia")와 `uiautomation` 두 가지였다.
M4의 「Windows 앱 한 개 조작」 전에, C8 데스크톱 로케이터(`automation_id`, `control_name`)를 무엇으로 구현할지 정해야 한다.

## 선택지

S1에서 Win11 메모장과 엑셀에 같은 시나리오를 돌렸다 (자세히: `spikes/S1-windows-uia/NOTES.md`).

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. `uiautomation` 2.0.x (Apache-2.0) | 이름 조건이 UIA `Name`과 그대로 맞는다 (C8 `control_name`과 같은 뜻). 키 입력이 `{Ctrl}` 같은 중괄호만 문법이라 업무 값(괄호·기호·한글)이 그대로 들어간다. 의존이 comtypes 하나. 시나리오 33/33, 셀 찾기 82ms | 관리자 한 명 위주. 타입 힌트가 없다. 전역 설정(검색 시간 등)이 모듈 전역이다. Win32 전용 기능(창 메시지 등)은 없다 |
| B. `pywinauto` 0.6.x (BSD-3) | 널리 쓰이고 자료가 많다. win32 backend도 있어 오래된 앱에 대안이 있다 | `title` 조건이 `Name`이 아니라 `rich_text`(입력칸·셀은 **내용**)와 비교돼 메모장 편집기·엑셀 셀을 이름으로 못 찾는다. `type_keys`가 `( ) + ^ % { } ~`를 먹는다. 우회 시 셀 찾기 494ms. pywin32 의존. Python 3.12에서 SyntaxWarning. 시나리오 31/34 |
| C. comtypes로 UIA를 직접 | 의존 최소, 완전한 통제 | 트리 탐색·패턴 감싸기·대기 로직을 전부 새로 써야 한다 |

## 결정

**A. Windows 데스크톱 백엔드는 `uiautomation`으로 만든다.** 라이브러리는 OS별 백엔드 구현 안에만 두고, 바깥에는 C8 로케이터로만 말한다 (`01-architecture.md` §5 — OS 전용 기능은 인터페이스 뒤에).

- C8 `automation_id` → UIA `AutomationId`, `control_name` → UIA `Name` (정확 일치, `exact=false`면 부분 일치).
- 쓰기는 **포커스 → 키 입력**을 기본으로 한다. 엑셀 셀의 ValuePattern.SetValue는 값이 바뀐 것처럼 보이지만 수식이 재계산되지 않아 쓰지 않는다. 엑셀 셀은 이름 상자로 이동한 뒤 입력하고, 이름(`B4`)으로 찾아 읽는다 (그리드는 화면에 보이는 영역만 노출).
- 단축키·입력 전에 대상 컨트롤에 포커스를 준다. 메뉴를 닫은 뒤 포커스가 메뉴 막대에 남는 경우를 봤다.
- 라이브러리가 기본으로 현재 폴더에 쓰는 `@AutomationLog.txt`는 끄거나 `platformdirs` 로그 위치로 돌린다.
- 백엔드는 **자기가 만든 탭·문서·창에만** 입력하고 저장 없이 닫는다. Win11 메모장은 사용자의 이전 탭을 복원하고 엑셀은 문서 복구 창과 함께 뜬다 — 「방금 띄운 앱이니 비어 있다」고 가정하지 않는다.

> 제안: C8 데스크톱 로케이터 전략에 `class_name`(+ 컨트롤 종류)을 더한다. 메모장 편집기처럼 `AutomationId`가 없는 컨트롤은 지금 `control_name`(「텍스트 편집기」, 언어마다 다름)으로만 잡힌다. 계약을 고치는 일은 이 ADR이 수락된 뒤 C8 문서부터.

> 미정: 엑셀 대량 읽기·쓰기는 UIA 대신 COM 또는 파일(openpyxl)로 할지 — 별도 스파이크.

## 결과

- 이 결정으로 쉬워지는 것: C8 `control_name`이 레지스트리에 적힌 이름 그대로 동작한다. 업무 값 입력에 이스케이프 규칙이 필요 없다. 의존이 가볍다.
- 어려워지거나 포기하는 것: pywinauto의 win32 backend(오래된 비UIA 앱용 대안)를 쓰지 않는다. 타입 힌트가 없어 백엔드 모듈은 mypy에서 `ignore_missing_imports`가 필요하다. 라이브러리가 멈추면 C(직접 구현)로 갈 수 있게 감싸는 층을 얇게 둔다.
- 다시 볼 조건: 사내 앱(MFC·WinForms·Java Swing)에서 UIA로 잡히지 않는 컨트롤이 나오는 경우, `uiautomation`이 새 Python 버전을 따라오지 못하는 경우, 배율·다중 모니터(S2)나 잠금 화면(S4)에서 이 라이브러리 고유의 문제가 나오는 경우.
