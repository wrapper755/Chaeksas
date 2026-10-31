# ADR-0077. UI 셀렉터 등록은 Bot UI 밖의 Tool UI에서 연다 — Worker는 빌려 쓰고, Bot UI와 함께 깐다

| 항목 | 값 |
| --- | --- |
| 상태 | 대체됨([ADR-0114](0114-remove-ui-automation.md)) — 원래 수락 (2026-10-20) |
| 구현 | `apps/tool_ui`(창·설정·한 세션 하나 — `QLocalServer`), 기여 지점 `tool_ui.tools`(`core.extensions.ExtensionHost.tools`), Bot UI 바로가기 `apps/bot_ui/tool_launch.py`, 묶기 진입 `packaging/botui_main.py`, 설치 바로가기 `packaging/installer/chaeksas.iss`(`ToolUiName`). 시험 `tests/test_tool_ui.py` |
| 날짜 | 2026-10-20 |
| 대체 | [ADR-0018](0018-extensions.md) 기여 지점 표의 `bot_ui.utilities` 한 줄과 「셀렉터 등록 = Bot UI 유틸리티」. [ADR-0012](0012-bot-ui.md)의 ③(이미 0018이 확장 기여로 바꾼 것)을 **어느 프로그램이 띄우나**까지 옮긴다 |
| 관련 | 계약 C13(`tool_ui.tools`·`scope: tool_ui`), C10(세션 하나·예약), ADR-0014 §4, ADR-0024(같은 실행 파일), ADR-0043(끈 확장), ADR-0068(설치 파일), ADR-0072(표시 테두리), ADR-0074(Studio가 Worker를 빌려 쓰는 길), 화면 `docs/06-screens/tool-ui.md`(TOL-01~05) |

## 배경

Bot UI는 **현장에서 Bot(BPM 프로세스)을 받아 돌리는 프로그램**이다 — 대기열·결재·배포·Center 연결이 그 일이다. 그런데 UI 셀렉터 등록(구 BUI-06~08)이 Bot UI의 「도구」 메뉴에 붙어 **Bot UI 프로세스 안에서** 돌았다.

- ADR-0018로 **코드**는 이미 확장의 것이다(Bot UI 코드에 셀렉터라는 말이 없다). 남은 결합은 **어느 프로그램이 그 창을 띄우나**다: 창은 Bot UI 메인 창이 쥐고, 등록 담당자 키는 Bot UI 설정(BUI-03 「확장별 설정」)에 있고, 밀린 등록 큐는 Bot UI 데이터 폴더에 있다.
- 쓰는 사람이 다르다 — 셀렉터 등록은 **화면 등록 담당자**의 일이고(00-vision) Bot UI는 **현장 PC 사용자**가 켜 둔다. 현장 운영자의 설정 창에 남의 업무 키 칸이 있었다.
- 셀렉터 등록은 BPM 프로세스가 UI 자동화를 쓰려고 **미리 갖춰 두는 도구 하나**다. 앞으로 확장이 더할 도구도 같은 자리에 온다 — Bot UI가 도구 상자가 되어 간다.

한편 **떼어 내는 데 새 조정이 필요 없다**는 것이 대조로 드러났다: Worker의 세션은 한 번에 하나이고(409 `worker_busy`), 실행 예약도 Worker가 쥐며(C10 `reserved_for`, ADR-0014 §4), Bot UI의 「셀렉터 등록 중」 표기도 **Worker가 말해 준 세션 주인**에서 읽는다. Studio는 이미 **Bot UI가 띄운 Worker를 빌려 쓴다**(`runtime.json`·토큰 파일, ADR-0074). 그래서 지금 정하는 것은 **프로그램의 경계**다.

## 선택지

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. 그대로 (Bot UI 유틸리티) | 바꿀 것이 없다 | Bot UI가 실행 프로그램이면서 도구 상자다. 등록 담당자 키가 현장 운영 설정에 섞인다. Bot UI를 다시 띄우면 등록 창도 닫힌다 |
| B. 셀렉터 전용 프로그램 (확장이 제 실행 파일을 가짐) | 이름이 분명하다 | 확장이 실행 파일을 갖는 길이 없다(ADR-0024는 앱 둘을 묶는다). 플랫폼이 그 확장을 알게 되거나 도구마다 프로그램이 하나씩 는다 |
| C. **일반 Tool UI** — 확장이 기여한 도구를 띄우는 플랫폼 프로그램, Worker는 빌려 쓰고 Bot UI와 함께 깐다 | Bot UI는 실행에 집중한다. 다음 도구도 같은 자리다. 조정은 이미 Worker에 있다 | 프로그램이 하나 는다(실행 파일은 그대로 — 아래 6). Bot UI가 꺼져 있으면 Worker를 쓰는 도구는 열리지 않는다 |
| D. C인데 Tool UI가 Worker를 직접 띄운다 | Bot UI 없이도 열린다 | Worker가 둘이 된다 — 포트·「세션 하나」·감시자가 둘로 갈린다(ADR-0014·0023) |
| E. Studio에 넣는다 | 프로그램이 늘지 않는다 | 현장 PC에는 Studio(598MB)가 없다. 등록은 **대상 화면이 있는 PC**에서 해야 한다 |

## 결정

**확장이 기여한 도구는 Bot UI가 아니라 Tool UI라는 따로 뜨는 프로그램이 띄운다. Tool UI는 로컬 런타임을 띄우지 않고 Bot UI가 띄운 것을 빌려 쓰며, Bot UI 설치에 함께 들어간다.** 첫 도구가 UI 셀렉터 등록(TOL-03~05)이다.

1. **Tool UI** (`tool_ui`, `apps/tool_ui`, `chaeksas.tool_ui`, 소스 실행 `chk-tool-ui`) — 창 있는 데스크톱 프로그램이고 **트레이가 없으며 항상 떠 있지 않다.** 창 하나에 도구마다 탭 하나다 (TOL-01). **Center에 등록하지 않고 Center를 부르지 않는다**(키가 없다). 한 로그인 세션에 **하나만** 뜬다 — 두 번째 실행은 떠 있는 창을 앞으로 부르고 열어 달라는 도구를 넘긴다.
2. **기여 지점은 `tool_ui.tools`** (C13) — `[{id, label, entry, needs_runtime?}]`. `entry`는 `extension_api.ToolUiTool`(`widget(ctx)`·`closed()` — 지금의 `BotUiUtility`와 같은 모양)이다. **`bot_ui.utilities`는 걷는다** — Bot UI도 Tool UI도 읽지 않는다. 쓰는 확장이 저장소 안 하나(UI 자동화)라 같은 변경에서 옮기고, 그 열쇠를 적은 확장이 있으면 호스트가 **경고 한 줄**을 남긴다(모르는 열쇠라고 조용히 사라지지 않게). `extension_api`는 **1.4**다 — `api: ">=1,<2"`인 확장을 끄지 않으려고 큰 판(2.0)으로 올리지 않는다.
3. **Worker는 빌려 쓴다** — Tool UI는 로컬 런타임을 **띄우지 않는다**(D를 고르지 않은 까닭). 자리는 **Studio와 같은 길**로 찾는다: Bot UI가 런타임 폴더에 남긴 `runtime.json`과 토큰 파일 → 예약 키 `runtime.<id>.*`. `needs_runtime`의 런타임이 떠 있지 않으면 **그 도구를 열지 않고 까닭과 길을 말한다**(「Worker 프로세스가 답하지 않습니다 — Bot UI를 켜고 Bot UI 「도구」에서 이 도구를 열면 Bot UI가 Worker 프로세스를 띄웁니다」 — 떠 있나는 `health`로만 본다). Worker가 다시 뜨면 토큰을 **부를 때마다** 다시 읽는다(지금 규칙 그대로).
   - **Bot UI 「도구」 메뉴는 바로가기로 남는다** — 기여의 `label`만 읽어 그리고, 누르면 `needs_runtime`을 **`Runtimes.ensure`로 띄운 뒤** Tool UI를 **따로** 띄운다(`<Bot UI 실행 파일> --tool-ui --open <확장>:<도구>`, 소스 실행은 `python -m chaeksas.tool_ui --open …`). **자식으로 감시하지 않는다** — Job Object에 넣지 않으므로 Bot UI를 다시 띄워도 도구 창은 남는다(Worker가 다시 뜨는 것은 위 규칙이 받는다).
   - **Bot 실행과의 차례는 그대로 Worker가 가른다** — 도구가 세션을 쥐고 있으면 Bot은 예약 409로 기다리고, Bot이 예약해 두었으면 도구가 409를 받아 「Bot 실행 중 — 끝나면 쓸 수 있습니다」라고 한다(ADR-0014 §4). 새 통로를 만들지 않는다.
4. **빌려 읽는 것과 제 것을 가른다.**
   - **빌려 읽는다(Bot UI 데이터 폴더, 쓰지 않는다):** 런타임 자리(`runtime.json`·토큰), **앱 주소 명부**(`core.app_directory.DirectoryCache` — 예약 키 `service.base_url`의 출처는 「Center 리소스 등록 > 정의」 그대로 하나다), **끈 확장 목록**(Bot UI 설정의 `disabled_extensions` — 이 PC에서 확장을 켜고 끄는 자리는 **BUI-11 하나**다. Tool UI에 켜기·끄기 창을 두지 않는다, ADR-0043).
   - **제 것:** 도구 설정과 비밀(C13 `configuration`의 새 `scope: tool_ui` — 비밀 칸은 OS 비밀 저장소 `chaeksas-tool-ui`), 예약 키 `storage.dir`(Tool UI 데이터 폴더의 `extensions/<id>` — 밀린 등록 큐가 여기로 온다). UI 자동화의 **등록 담당자 키(`registrar_key`)는 `scope: tool_ui`**가 된다 — Bot UI 설정 창(BUI-03)에서 빠진다.
   - Bot UI 데이터 위치 규칙은 **Tool UI가 따로 적는다**(앱끼리 import하지 않는다 — Studio와 같다). 어긋나면 시험이 잡는다(`tests/test_extension_wiring.py`의 결).
5. **Bot UI에서 걷는 것:** 유틸리티를 메인 창 탭으로 붙이는 길(BUI-02 [K]의 「메인 창 탭으로 열기」), 유틸리티 창을 메인 창이 쥐는 자리, BUI-03 「확장별 설정」의 등록 담당자 키 칸(그 칸의 `scope`가 바뀌어 저절로 빠진다). **남는 것:** 트레이·메뉴의 「도구」 바로가기, 상태 「셀렉터 등록 중」(Worker가 말해 준다 — 그대로다), BUI-09. 데스크톱 「표시」의 테두리 창(ADR-0072)은 **Tool UI가 띄운다** — 같은 Qt 코드다.
6. **묶기·설치:** 실행 파일을 늘리지 않는다 — **Bot UI 실행 파일이 `--tool-ui`로 Tool UI가 된다**(로컬 런타임을 `--local-runtime`으로 띄우는 것과 같은 길, ADR-0024 — 파이썬·Qt·DPI 선언을 함께 쓴다). 가르는 자리는 **묶기 진입 스크립트**(`packaging/botui_main.py`)라 앱끼리 import하지 않는다. 설치 파일(ADR-0068)이 시작 메뉴에 「Chaeksas Tool UI」 바로가기(`--tool-ui`)를 하나 더 만든다. 판은 Bot UI와 같다(ADR-0067). `--selftest`가 Tool UI의 도구 기여가 풀리는지도 본다.

## 결과

- **쉬워지는 것:** Bot UI는 Bot 실행·대기열·배포·Center 연결에 집중한다. 등록 담당자는 현장 운영 설정을 건드리지 않고 제 키를 제 창에 둔다. Bot UI를 다시 띄워도 등록 창이 닫히지 않는다. 확장이 도구를 더하면 Tool UI에 탭으로 온다(Bot UI 메뉴는 바로가기만 는다).
- **어려워지거나 포기하는 것:**
  - **Bot UI가 꺼져 있으면 Worker를 쓰는 도구는 열리지 않는다** — Worker 감시자를 하나로 지키는 값이다. 런타임이 필요 없는 도구는 그대로 열린다.
  - 작업 관리자에서 Tool UI도 Bot UI 이름으로 보인다 — 명령줄(`--tool-ui`)로 가른다(Worker와 같은 결).
  - **Bot UI 데이터 폴더의 밀린 등록 큐는 옮기지 않는다.** 큐는 창을 열 때마다 올리려 하므로 바꾸기 전에 셀렉터 등록 창을 한 번 열면 빈다. 현장에 깐 곳은 M6 리허설 PC 하나다.
  - 앱 하나(`apps/tool_ui`)와 화면 문서 하나(`tool-ui.md`)가 는다. 화면 ID BUI-06~08은 폐기하고 TOL-03~05로 옮긴다(번호는 재사용하지 않는다).
- **다시 볼 조건:**
  - Bot UI가 없는 PC(설계자 PC에 Studio만)에서 도구를 써야 할 때 — 그때 「Worker 감시자는 하나」를 지키며 띄우는 쪽을 정한다(예: Tool UI가 Bot UI에게 띄워 달라고 부르는 길).
  - Tool UI 도구가 Center를 불러야 할 때 — 키를 어디 둘지(Bot UI의 Center API 키를 빌리지 않는다, ADR-0013) 먼저 정한다.
  - 확장이 런타임 없이 Bot UI 화면 안에 있어야 하는 것을 기여할 때 — 그것은 도구가 아니라 `bot_ui.panels`(ADR-0042)다.
