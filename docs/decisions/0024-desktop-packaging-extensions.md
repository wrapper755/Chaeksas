# ADR-0024. Studio·Bot UI는 PyInstaller onedir로 묶고, 확장 옵션은 엔트리 포인트에서 계산하며, 로컬 런타임은 같은 실행 파일로 띄운다

| 항목 | 값 |
| --- | --- |
| 상태 | 제안 |
| 날짜 | 2026-10-02 |
| 관련 | 스파이크 `spikes/S5-extension-packaging/`(Windows)·`.../linux-core-hook/`(Linux, 확장 호스트와 훅), ADR-0018(확장), ADR-0019(이름 공간), ADR-0021(DPI), ADR-0022(Studio 캔버스), ADR-0023(자동 시작), 계약 C13 |
| 구현 | 훅: `packages/core/src/chaeksas/core/__pyinstaller/` (배선 검사 `tests/test_extension_host.py`) |

## 배경

ADR-0018은 확장을 엔트리 포인트 그룹 `chaeksas.extensions`로 찾고, 내장·사내 확장의 클라이언트 코드는 **우리가 빌드한 설치 파일에 든 것만** 돌리기로 했다. 설치 파일로 묶은 앱에서도 엔트리 포인트·동적 import·데이터 파일이 살아 있는지, 로컬 런타임(Worker 프로세스)을 어떻게 띄우는지는 확인하지 않았다.
ADR-0023은 자동 시작 대상이 설치된 실행 파일이어야 한다고 했다 (개발용 가상환경은 사용자 프로필 밖 Python에 기댄다).

## 선택지

S5에서 시험 호스트·확장을 PyInstaller 6.22로 다섯 가지로 묶어 자체 점검했다 (자세히: `spikes/S5-extension-packaging/NOTES.md`).

| 선택지 | 결과 |
| --- | --- |
| A. 그대로 묶기 | 엔트리 포인트가 **오류 없이 빈 목록**, 확장 모듈 없음 — 확장이 조용히 사라진다 |
| B. 확장마다 `--copy-metadata`·`--collect-submodules`·`--collect-data` | 전부 통과. Bot UI 113MB, warm 1.3초 |
| C. B를 onefile로 | 통과. 44MB지만 실행마다 압축 풀기로 warm 3.4초, 로컬 런타임 띄울 때마다 또 푼다 |

로컬 런타임:

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| 같은 실행 파일 + `--local-runtime <확장>:<id>` | 묶음 하나, 기동 0.7초, 매니페스트·DPI 선언을 공유 | Bot UI와 Worker가 같은 실행 파일 이름으로 보인다 (작업 관리자) |
| 런타임마다 실행 파일 따로 | 이름이 분명 | Python·Qt가 겹친다. 확장마다 빌드 대상이 늘어난다 |

B의 세 인자를 **손으로 적는 대신 훅으로 자동화**할 수 있는지는 뒤에 Linux에서 실제 확장 호스트(`chaeksas.core.extensions`)로 확인했다 (`spikes/S5-extension-packaging/linux-core-hook/`). 인자 0개로 A가 B와 같은 결과가 되고, 셋 중 무엇이 빠졌을 때 증상이 어떻게 다른지도 거기 적혀 있다. 아래 결정은 그것을 쓴다.

## 결정

**Studio와 Bot UI는 PyInstaller onedir로 묶는다.** 설치 프로그램이 그 폴더를 설치한다. onefile은 쓰지 않는다.

- **확장 옵션은 `core`가 주는 PyInstaller 훅이 넣는다.** `chaeksas.core`가 `__pyinstaller/` 폴더에 훅을 담고 `pyinstaller40` 엔트리 포인트(`hook-dirs`)로 알린다. 훅이 설치된 `chaeksas.extensions` 엔트리 포인트를 훑어 확장마다 `copy_metadata`(dist-info)·`collect_data_files`(`extension.json`)·`collect_submodules`(클라이언트 모듈)를 넣는다. **묶는 명령에는 확장 인자를 적지 않는다** — 빌드가 확장 이름을 알 필요가 없다 (ADR-0018: 플랫폼은 특정 확장을 모른다).
  - 넣을 확장 목록은 그대로 ADR-0018 §5의 포함 목록(`installer/extensions.toml`)이다. 빌드는 그 목록을 **설치하는 것까지만** 하고, 묶는 일은 훅에 맡긴다.
  - 셋 중 하나만 빠져도 증상이 다르다: 메타데이터가 없으면 엔트리 포인트가 빈 목록(확장이 조용히 사라진다), 데이터가 없으면 「`extension.json`을 읽을 수 없다」, 서브모듈이 없으면 확장은 켜지는데 `entry` 해석에서 터진다. 셋을 한곳에 모아 둔 이유다.
  - 훅 파일은 평범한 모듈이 아니라서(이름에 점, 전역 변수로 결과를 돌려준다) ruff·mypy 검사에서 뺀다.
- **빌드 검사:** 묶은 실행 파일을 `--selftest`로 실행해 기대한 확장이 모두 로드되는지(엔트리 포인트·모듈·데이터·Qt 기여·로컬 런타임 기동) 확인하고, 하나라도 빠지면 빌드를 실패시킨다. 빠진 확장은 실행 중에 오류를 내지 않기 때문이다.
- **로컬 런타임은 같은 실행 파일로 띄운다:** `<Bot UI 실행 파일> --local-runtime <확장 id>:<런타임 id> --port <p> --token-dir <폴더>`. 개발 환경에서는 같은 인자로 `python -m chaeksas.bot_ui`를 쓴다. ADR-0023의 Job Object로 감싼다.
  > 제안: C13 `bot_ui.local_runtimes`의 `command`(예 `["chk-worker"]`)를 내장·사내 확장에서는 `entry`(런타임 진입점 문자열)로 바꾸고, 호스트가 위 명령을 만든다. 계약 변경은 C13 문서를 먼저 고친 뒤.
- **매니페스트:** PyInstaller 기본 매니페스트에 `dpiAwareness PerMonitorV2, PerMonitor`(+ `dpiAware true/pm`)를 더해 `--manifest`로 넣는다. 기본 매니페스트에는 DPI 선언이 없어 같은 실행 파일로 뜬 Worker가 DPI 비인식이 된다 (ADR-0021). `longPathAware`는 유지.
- **Studio와 Bot UI는 따로 묶는다.** QtWebEngine은 Studio에만 넣는다 (Studio 551MB 중 WebEngine 194MB, 개발자 도구 리소스 83MB). Bot UI(113MB)는 모든 현장 PC에 깔리므로 작게 둔다.

> 미정: 설치 프로그램 종류(Inno Setup, WiX/MSI). MSIX는 S4에서 본 파일·레지스트리 가상화(다른 프로세스·작업 스케줄러가 보지 못함) 때문에 Bot UI에는 맞지 않아 보인다. 코드 서명·백신 오탐, 크기 줄이기(devtools pak, Qt Quick 제외)는 M1 뒤 설치 파일 작업에서 확인한다.

## 결과

- 이 결정으로 쉬워지는 것: 확장을 더해도 빌드 설정을 손으로 고치지 않는다 — 묶는 명령에 확장 인자가 아예 없다. 확장이 빠지면 빌드에서 잡히고(`--selftest`), 실행 중에도 호스트가 사유를 남긴다(ADR-0018). Worker가 Bot UI와 같은 Python·DPI 선언·서명을 쓴다. 설치된 실행 파일은 어디서 실행돼도(작업 스케줄러 포함) 스스로 돈다.
- 어려워지거나 포기하는 것: 설치 크기가 크다 (Studio 약 550MB). onefile의 「파일 하나」 배포는 포기한다. 작업 관리자에서 Worker가 Bot UI와 같은 이름으로 보인다 (명령줄로 구별). 묶기 도구가 PyInstaller로 고정된다 — 다른 도구로 가면 같은 일을 하는 훅을 새로 써야 한다.
- 다시 볼 조건: PyInstaller가 Python 3.12·PySide6 새 버전을 따라오지 못하는 경우, 백신 오탐이 현장에서 문제가 되는 경우(그때 Nuitka 등 검토), 사내 확장이 늘어 설치 파일 재빌드가 병목이 되는 경우(ADR-0018 §5 「나중」), 훅이 보는 「빌드 환경에 설치되어 있어야 한다」가 걸림돌이 되는 경우.
