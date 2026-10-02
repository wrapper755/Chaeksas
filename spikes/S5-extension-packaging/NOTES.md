# S5 확장 로딩 — 설치 파일로 묶은 Studio·Bot UI에서 엔트리 포인트 확장

결론 → [ADR-0024](../../docs/decisions/0024-desktop-packaging-extensions.md) (제안)

## 확인하려 한 것

ADR-0018: 확장은 엔트리 포인트 그룹 `chaeksas.extensions`로 찾고, 내장 확장은 설치 파일에 함께 들어간다. 그렇다면 PyInstaller로 묶은 Studio·Bot UI 안에서

1. 엔트리 포인트가 보이는가 (패키지 메타데이터 `*.dist-info`가 들어가야 한다)
2. 문자열 진입점(C13 `entry`)으로 동적 import하는 확장 모듈, PEP 420 네임스페이스 `chaeksas.*`가 빠지지 않는가
3. 확장의 Qt 화면, 패키지 데이터 파일(`extension.json`)이 들어가는가
4. 로컬 런타임(Worker 프로세스)을 묶인 앱에서 어떻게 띄우는가 — 묶인 앱에는 `python -m`이 없다
5. 크기·시작 시간, onedir과 onefile, Claude 앱 패키지 밖에서도 도는가 (S4의 가상화 교훈), DPI 선언 (ADR-0021)

## 환경

| 항목 | 값 |
| --- | --- |
| OS | Windows 11 Education 10.0.26200 |
| Python | 3.12, 스파이크 전용 `.venv` (워크스페이스와 따로) |
| 도구 | PyInstaller 6.22.3, pyinstaller-hooks-contrib 2026.8, PySide6 6.11.2 |

워크스페이스의 `extension_api`·`ui_automation`은 아직 비어 있어서, 같은 이름 규칙의 시험 패키지 둘을 만들었다.

| 폴더 | 배포 이름 | 뜻 |
| --- | --- | --- |
| `ext_s5demo/` | `chaeksas-ext-s5demo` (`chaeksas.ext.s5demo`) | 내장 확장 흉내. 엔트리 포인트 `chaeksas.extensions: s5demo`, 기여는 문자열 진입점 (Qt 유틸리티, 로컬 런타임), 데이터 파일 `extension.json` |
| `host/` | `chaeksas-s5host` (`chaeksas.s5host`) | Bot UI·Studio 흉내. **확장을 import하지 않고** 엔트리 포인트로만 찾는다. `--selftest`, `--local-runtime <확장>:<id>` |

## 파일

| 파일 | 하는 일 |
| --- | --- |
| `botui_main.py`, `studio_main.py` | PyInstaller 진입 스크립트 (Studio 쪽만 WebEngine을 import) |
| `build.py` | 변형 A~E를 묶고 각 실행 파일의 `--selftest`를 두 번(cold·warm) 돌림 → `out/summary.json` |
| `app.manifest` | PyInstaller 기본 매니페스트 + `dpiAwareness PerMonitorV2` |
| [`linux-core-hook/`](linux-core-hook/NOTES.md) | **덧붙임** — 시험용 호스트가 아니라 진짜 `chaeksas.core.extensions`와 내장 확장으로, B의 세 인자를 `core`가 주는 PyInstaller 훅으로 자동화해 **인자 0개**로 되게 한 기록 (Linux). ADR-0024가 이것을 쓴다 |

```bash
cd spikes/S5-extension-packaging
uv venv .venv --python 3.12
uv pip install --python .venv ./host ./ext_s5demo pyinstaller
.venv/Scripts/python.exe build.py          # A~E 전부 (약 8분)
```

## 본 것

### 변형별 결과

| 변형 | 내용 | 자체 점검 | 크기 | 실행(cold / warm) |
| --- | --- | --- | --- | --- |
| A | 그대로 묶기 | **실패: 엔트리 포인트가 빈 목록**(오류 없음), `chaeksas.ext` 모듈 없음 | 112MB | 1.6 / 0.5초 |
| B | 확장 옵션 자동 계산 | 전부 통과 | 113MB | 2.4 / 1.3초 |
| C | B + QtWebEngine (Studio) | 전부 통과 (웹 페이지 1.2초) | **551MB** | 6.1 / 4.1초 |
| D | B를 onefile로 | 전부 통과 | 44MB (압축) | 4.2 / **3.4초** |
| E | B + PerMonitorV2 매니페스트 | 전부 통과, 로컬 런타임이 per-monitor | 113MB | 2.6 / 1.3초 |

「실행」은 `--selftest` 전체(엔트리 포인트·확장 로드·Qt 화면·로컬 런타임 기동·종료)의 벽시계 시간이다. 로컬 런타임 기동은 0.7~1.0초.

### 발견

1. **그대로 묶으면 확장이 조용히 사라진다.** PyInstaller는 `*.dist-info`를 기본으로 넣지 않아 `entry_points()`가 **오류 없이 빈 목록**을 준다. 플랫폼은 「확장 없음」으로 정상처럼 뜬다. 확장 모듈은 문자열로만 import되니 정적 분석에도 안 걸린다.
2. **고치는 법은 확장마다 옵션 셋:** `--copy-metadata <배포 이름>` (엔트리 포인트), `--collect-submodules <패키지>` (동적 import되는 모듈), `--collect-data <패키지>` (`extension.json` 같은 데이터). `build.py`는 이것을 **엔트리 포인트 그룹을 읽어 자동 계산**한다 — 확장을 하나 더해도 빌드 설정을 손으로 고치지 않는다.
3. PEP 420 네임스페이스 `chaeksas`(여러 배포에 나뉜 `chaeksas.s5host`·`chaeksas.ext.s5demo`)는 묶인 앱에서도 하나로 합쳐졌다 (`_internal/chaeksas`).
4. **로컬 런타임은 같은 실행 파일을 인자만 바꿔 다시 띄운다** (`<exe> --local-runtime s5demo:worker --port <p>`). 묶인 앱에는 `python -m`이 없고, 런타임마다 실행 파일을 따로 묶으면 Qt·Python이 겹친다. 기동 0.7초.
5. **PyInstaller 기본 매니페스트에는 DPI 선언이 없다** → 같은 실행 파일로 뜬 Worker가 DPI 비인식(unaware)이었다. ADR-0021의 Per-Monitor v2는 `--manifest`로 넣어야 한다 (변형 E에서 per-monitor 확인). Qt 화면은 그대로 정상.
6. **onefile은 쓰지 않는다.** 실행할 때마다 `%TEMP%\_MEI…`에 풀어서 warm 시작이 onedir의 2.6배(3.4초 vs 1.3초)이고, 로컬 런타임을 띄울 때마다 또 푼다. 강제 종료 뒤 남은 `_MEI` 폴더·프로세스는 이번 시험에서는 없었다.
7. **Claude 앱 패키지 밖(작업 스케줄러)에서도 B·C 모두 통과.** 묶인 실행 파일은 자기 안의 Python만 쓰므로 S4의 가상화 문제가 없다.
8. 크기 내역:
   - Bot UI(E): `opengl32sw.dll` 20MB(소프트웨어 OpenGL — 가상 PC·원격 데스크톱용), Qt6Core·Gui·Widgets 각 6~10MB, `Qt6Quick.dll` 6MB(위젯 앱인데 훅이 넣음).
   - Studio(C): `Qt6WebEngineCore.dll` 194MB, **개발자 도구 리소스 `qtwebengine_devtools_resources*.pak` 83MB** (뺄 후보), `icudtl.dat` 10MB.
9. 빌드 시간: onedir 77초, WebEngine 포함 143초 (`--clean`).

### 하지 않은 것 (다음에)

- 설치 프로그램(Inno Setup·WiX/MSI 등), 코드 서명, SmartScreen·백신 오탐.
- 크기 줄이기 실제 시험 (devtools pak·Qt Quick 제외 뒤에도 도는지).
- Linux 묶음.
- 사내 확장(다른 저장소)을 `installer/extensions.toml`로 넣는 흐름 (ADR-0018 §5) — 옵션 계산 방식은 같다.
- Studio PC에 Bot UI도 설치할 때 두 묶음이 PySide6를 따로 갖는 것 (공유 여부).
