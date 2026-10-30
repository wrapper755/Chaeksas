# ADR-0108. Windows CI는 PR마다 돌리지 않고 주 1회와 수동 실행으로 돌린다

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 |
| 날짜 | 2026-10-30 |
| 관련 | [ADR-0104](0104-windows-ci-runs-the-client-side.md)(Windows CI는 클라이언트 쪽만), `.github/workflows/ci.yml`, `.github/workflows/desktop.yml`, `tests/ci_scope.py`·`tests/test_ci_scope.py` |

## 배경

ADR-0104로 서버 시험을 뺀 뒤에도 Windows 테스트 잡이 PR마다 가장 길다(#205에서 13분, Linux 10분).
PR 하나가 끝나는 시각을 Windows가 정한다.

그런데 Windows에서만 드러나던 결함은 대부분 **Linux에서 잡는 자리**가 생겼다 — 인코딩은
`tests/test_generators_on_windows_encoding.py`, Windows 전용 API의 타입은 Linux 잡의
`mypy --platform win32`. 요즘 PR(STU-04 편집기 #197~#205)은 Windows에서만 깨질 거리가 거의 없었고
실제로 Windows만 빨갛게 된 적이 없다. 남는 것은 Windows에서만 도는 시험(UIA 데스크톱·Windows 글꼴
동작)과 느린 러너에서만 드러나는 타이밍이다 — 매 PR이 아니라 정기적으로 보면 되는 것들이다.

## 선택지

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. 그대로 PR마다 | 깨진 곳을 그 PR에서 안다 | PR마다 13분을 기다린다 |
| B. 바뀐 경로로 거른다 | 서버만 만진 PR은 빠르다 | 요즘 PR은 거의 다 클라이언트를 만져 결국 돈다 |
| C. 주 1회 + 수동 실행 | PR이 Linux 시간에 끝난다 | 깨진 것을 최대 한 주 늦게 안다 |

## 결정

**C.** `ci.yml`은 PR에서 **Linux만** 돌고, 주 1회(월요일 00:00 UTC = 09:00 KST, main)와
`workflow_dispatch`에서 **Windows + Linux**를 돈다. 테스트·웹 두 잡이 같은 규칙이다
(`matrix.os`가 `github.event_name`으로 고른다 — `tests/test_ci_scope.py`가 지킨다).

- `mypy --platform win32`는 Linux 잡에 남아 PR마다 Windows 분기를 본다.
- 프로세스 관리(`core.processes`)·인코딩·경로·패키징·UIA처럼 **OS를 타는 것을 만진 PR**은 그 브랜치에서
  손으로 한 번 돌린다(`gh workflow run CI --ref <브랜치>`).
- 데스크톱 산출물(`desktop.yml`, `v*` 태그)은 그대로다 — 내기 전에 Windows 묶음을 늘 본다.
- CLAUDE.md의 Windows 통과 셈은 **주간 실행이나 수동 실행이 말해 준 값**으로 적는다.

## 결과

- 쉬워지는 것: PR이 Linux 잡 시간(약 10분)에 끝난다. 러너 사용량이 줄어든다.
- 포기하는 것: Windows에서만 깨지는 것을 머지 뒤에, 최대 한 주 늦게 알 수 있다. 그때는 그 주의
  머지들을 거슬러 찾아야 한다.
- 다시 볼 조건: 주간 실행이 두 번 연달아 Windows에서만 빨갛게 되거나, 현장 PC 배포(M8)가 잦아져
  Windows 회귀의 값이 커지면 A나 B로 돌아간다.
