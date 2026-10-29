# ADR-0104. Windows CI는 클라이언트 쪽 시험만 돌린다 — 서버 시험은 Linux에서

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 |
| 날짜 | 2026-10-29 |
| 관련 | [ADR-0102](0102-calling-outside-is-pull.md)(바깥 호출은 모두 Pull), [ADR-0016](0016-server-first.md), `.github/workflows/ci.yml`, `tests/ci_scope.py`, `docs/04-setup.md` §7 |

## 배경

CI는 처음부터 「Windows 클라이언트 + Linux 서버 조합」을 보려고 **모든 시험을 두 OS에서** 돌렸다.
Windows 잡이 20분, Linux가 10분이다 — PR마다 치르는 값의 대부분이 Windows다.

ADR-0102 뒤로 경계가 분명해졌다. BPM 프로세스가 바깥을 부르는 길은 **토픽에 일감을 올리고 결과를
기다리는 것**뿐이고, 그 너머(Center·서버 실행기·일꾼·서비스 앱)는 **Linux에서만 도는 서버**다.
OS에 기대는 코드는 화면을 만지는 쪽 — Worker·Bot UI·Studio·Tool UI와 그것들이 돌리는 엔진 — 에 남는다.
그런데 Windows 잡은 Center 저장소 옮기기·서버 실행기 동시 실행·M7 서버 예제 묶음·모의 앱까지 돌리고 있었다.

## 선택지

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. 지금대로 둘 다 전부 | 어느 OS에서 무엇이 깨질지 걱정이 없다 | Windows 잡이 서버 시험에 시간을 쓴다 — 서버는 Windows에서 돌지 않는다 |
| B. **서버 시험을 표시하고 Windows는 그것을 뺀다** | Windows 잡이 클라이언트 몫만 본다. Linux는 그대로 전부 | 표시를 지켜야 한다 (잘못 붙이면 클라이언트 시험이 Windows에서 빠진다) |
| C. Windows는 클라이언트 경로 목록만 고른다 | 무엇을 도는지가 목록에 바로 보인다 | 새 시험 파일이 **기본으로 Windows에서 빠진다** — 잊으면 조용히 덜 본다 |

## 결정

**B.** 서버 시험 파일을 `tests/ci_scope.py`의 `SERVER_SIDE` **한 자리**에 적고, `tests/conftest.py`가
그 파일의 시험에 `server` 표시를 붙인다. CI의 Windows 잡은 `pytest -m "not server"`, Linux는 전부다.

- **기본은 양쪽이다.** 새 시험 파일은 적지 않으면 Windows에서도 돈다 — 빠뜨리면 더 보는 쪽으로 틀린다(C를 고르지 않은 까닭).
- **서버**는 Center·서버 실행기·`service_kit`(서비스 앱 일꾼)·어댑터 일꾼·모의 앱·M7 서버 예제 묶음·UI 자동화 앱의
  레지스트리·관리 콘솔 읽기다.
- **엔진(`core`)은 서버가 아니다** — PC Bot은 Bot UI의 실행기 자식 프로세스로 **Windows에서 엔진을 돌린다**.
  부르는 쪽(`core.services.CenterServiceCaller`·C15 왕복)도 PC에서 돌므로 양쪽이다.
- **PC 쪽 코드가 걸린 시험은 서버로 적지 않는다** — 서버 실행기 위임 시험은 PC를 진짜 자식 프로세스(`bot_ui.runner`)로
  돌리고, UI 자동화 앱 시험은 Worker의 부르는 쪽(`worker.plans`)을 함께 본다. 그래서 둘은 양쪽이다.
  `tests/test_ci_scope.py`가 서버 파일이 Bot UI·Tool UI·Qt·Worker·UI 자동화 클라이언트를 import하지 않는지 본다.
- ruff·mypy(`--platform win32` 포함)·생성물 검사는 두 OS에서 그대로 돈다.

## 결과

- 쉬워지는 것: Windows 잡이 서버 시험 755개(정한 날 전체 3891개 중 — 무거운 M7 묶음·모의 앱 포함)를 건너뛴다. 「Windows에서 깨졌다」가 곧 클라이언트의 일이 된다.
- 포기하는 것: **Center·서버 실행기를 Windows에서 띄우는 길은 시험이 지켜 주지 않는다**(서버는 Linux 주 — ADR-0016·CLAUDE.md §1).
  CLAUDE.md의 Windows 셈은 「서버 시험을 뺀 수」로 뜻이 바뀐다.
- 다시 볼 조건: 서버를 Windows에 올리는 요구가 생기면(사내 Windows 서버), 또는 서버로 적은 파일에서 Windows 전용 흠이 드러나면.
