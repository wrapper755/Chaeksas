# S5 덧붙임 — 실제 확장 호스트로, 빌드 인자 없이 (Linux)

> 결론 ADR: [ADR-0024](../../../docs/decisions/0024-desktop-packaging-extensions.md) — 위 폴더의 [NOTES.md](../NOTES.md)(Windows 11, 크기·기동 시간·Qt 기여)가 본체이고, 이것은 **두 가지를 더 본 기록**이다.
>
> 1. 시험용 호스트가 아니라 **진짜 `chaeksas.core.extensions`**와 내장 확장 `ui-automation`으로 묶었다.
> 2. B의 세 인자를 손으로 적는 대신, `core`가 **PyInstaller 훅**을 딸려 보내 **인자 0개**로 되게 했다.
>
> 돌린 곳: Linux aarch64, PyInstaller 6.22.3, Python 3.12. **Windows 확인은 CI에 맡긴다.**

## 본 것 1: 셋이 따로따로 빠진다 (훅을 넣기 전)

| 설정 | entry_points | 확장 | `entry` 해석 |
| --- | --- | --- | --- |
| 아무 인자 없이 | **없음** | 없음 | `LookupError: 기여된 태스크 종류가 아니다: ui_task` |
| `--copy-metadata` | `['ui-automation']` | **없음** | 같음. `failures`에 「`extension.json`을 읽을 수 없다: No module named 'chaeksas.ext'」 |
| `+ --collect-data` | `['ui-automation']` | `ui-automation@0.1.0` | **`EntryError: 'ui_automation.client'은 … 밖이거나 없다`** |
| `+ --collect-submodules` | `['ui-automation']` | `ui-automation@0.1.0` | `UiTaskExecutor`·`UiTaskEditor`·`SelectorRegistration` ✓ |

(위 폴더 NOTES의 A·B와 같은 결론이다. 여기서는 **어느 인자가 어느 증상을 고치는지** 한 칸씩 갈라 봤다.)

읽은 것:

- 증상이 단계마다 다르고 **전부 호스트가 말해 준다.** `summarize()`의 `failed`·`disabled`에 사유가 남아서, "묶으니 조용히 안 됨"이 아니라 "무엇이 빠졌는지"가 보였다 (ADR-0018의 설계가 여기서 값을 했다).
- PEP 420 네임스페이스(`chaeksas.ext`)는 `--collect-data`가 패키지를 함께 끌고 와야 import조차 된다 (둘째 줄의 `No module named 'chaeksas.ext'`).

## 본 것 2: 훅 하나로 인자가 0개가 된다

`chaeksas.core`가 `pyinstaller40` 엔트리 포인트로 훅 폴더를 딸려 보내면, 묶는 쪽은 **아무 인자도 적지 않는다.**

```
[hook-chaeksas.core.extensions] 확장 1개 (ui-automation), hiddenimports 10개, datas 3개
[bare] entry_points=['ui-automation'] · 확장=['ui-automation@0.1.0'] · 태스크=['ui_task']
       · 수행기=UiTaskExecutor · 편집기=UiTaskEditor · 유틸=SelectorRegistration
```

- `--onedir`·`--onefile` 둘 다 통과했다 (`onefile`은 `sys._MEIPASS`로 풀린 뒤 `importlib.resources`가 그대로 읽는다). 어느 쪽을 쓸지는 위 폴더 NOTES의 크기·기동 측정으로 정했다 (onedir).
- 사전 점검(`preflight_checks()`)도 함께 떴다.
- 훅은 **확장 이름을 적지 않는다** — 그룹을 훑기 때문에 확장을 설치하면 그만큼 들어간다.
- probe 하나가 onedir 55 MB (pydantic·fastapi·cryptography 포함). Qt는 여기 없다.

## 본 것 3: 묶인 앱은 자기 자신을 자식으로 띄울 수 있다

ADR-0024가 고른 「로컬 런타임을 같은 실행 파일로」가 Linux에서도 되는지 봤다.

| | `sys.executable` | 자기 자신을 `--child`로 다시 실행 |
| --- | --- | --- |
| 소스로 돌릴 때 | venv의 `python3` | 안 됨 (python에 `--child`를 주면 usage 오류) |
| 묶은 뒤 | 묶인 실행 파일 | **됨** (`argv=['--child','--port','8899']`, 자식도 `frozen=True`) |

즉 **묶였는지에 따라 명령 모양이 다르다.** ADR-0024가 `command`를 `entry`로 바꾸고 호스트가 명령을 만들자고 한 이유가 이것이다 (C13 `bot_ui.local_runtimes` 참고).

## 어떻게 다시 돌리나

```
uv run --with pyinstaller python spikes/S5-extension-packaging/linux-core-hook/build.py
```

- `probe.py` — `load_host()`를 부르고 메타데이터·데이터 파일·클라이언트 모듈 세 단계를 따로 찍는다.
- `runtime_probe.py` — 자기 자신을 자식으로 띄워 본다.
- 처음의 **실패 표**를 다시 보려면 `packages/core/pyproject.toml`의 `[project.entry-points.pyinstaller40]`을 지우고 `uv sync --all-packages` 뒤에 돌린다 (훅이 늘 걸리기 때문이다).

## 남은 것

- **Windows.** 기제는 플랫폼을 가리지 않지만 경로·`.exe` 이름이 다르다. `build.py`를 Windows에서 그대로 돌릴 수 있게 써 뒀다.
- **Qt 화면 기여.** 위 폴더 NOTES가 시험용 확장(`ext_s5demo`)으로 봤고, 여기서는 PySide6가 없어 못 봤다.
- **확장 둘 이상.** 훅이 그룹을 훑는 것은 코드로 보이지만, 둘째 확장을 venv에 설치하면 `tests/test_extension_host.py`의 기대값이 흔들려 하지 않았다 (위 폴더 NOTES가 `ext_s5demo`로 봤다).
