# S3 Studio 셸 — PySide6 + QtWebEngine + bpmn-js

결론 → [ADR-0022](../../docs/decisions/0022-studio-canvas.md) (제안)

## 확인하려 한 것

PySide6 + QtWebEngine 안의 bpmn-js가 Windows에서 뜨고, BPMN을 불러오고 저장할 수 있는가. 특히 C14의 `chk:` 확장 요소(한글 JSON 본문)가 bpmn-js를 거쳐도 보존되는가 (C14: 「표준 BPMN 도구(bpmn-js)로 열고 그릴 수 있어야 한다」). 한글 라벨 입력, 오프라인 동작, 시작 시간·메모리·설치 크기.

## 환경

| 항목 | 값 |
| --- | --- |
| OS | Windows 11 Education 10.0.26200, 한국어, 1920×1080 100% |
| Python | 3.12 (uv 관리), PEP 723 인라인 의존 `pyside6>=6.8` |
| bpmn-js | 18.31.0, npm으로 `web/node_modules`에 받아 배포본(`dist/bpmn-modeler.production.min.js`)을 번들러 없이 그대로 읽는다 |
| 시험 재료 | 업무 예제 BPMN 50개 (`docs/08-business-examples/bpmn/`) — `chk:` 요소 13종, 모두 한글 |

## 파일

| 파일 | 하는 일 |
| --- | --- |
| `web/index.html` | bpmn-js 모델러 + QWebChannel. Python이 부르는 함수 `importXML`·`saveXML`·`setLabel`·`stats` |
| `web/chk-moddle.js` | `chk:` 요소 13종을 bpmn-moddle에 알려 주는 설명 (`?moddle=1`일 때만 씀) |
| `web/package.json` | bpmn-js 버전 고정 (`node_modules/`는 커밋하지 않는다) |
| `shell.py` | `auto`: 예제 전부 불러오기→저장→원본과 비교, `outputs/report.json`. 인자 없으면 직접 써 보는 창 (파일 → 예제 열기·저장, 저장은 `outputs/edited-*.bpmn`) |

```bash
cd spikes/S3-studio-shell/web && npm install
uv run spikes/S3-studio-shell/shell.py auto
uv run spikes/S3-studio-shell/shell.py
```

## 본 것

### 결과

| 항목 | 값 |
| --- | --- |
| 불러오기 | 50/50, 경고 0 (moddle 설명 없이 / 있이 둘 다) |
| 저장 후 원본과 **의미상** 같음 | 50/50 (두 모드 모두) |
| 불러오기 시간 | 평균 23~29ms, 최대 175ms |
| 프로세스 시작 → 첫 페이지 준비 | 3.3~4.8초 (첫 실행·캐시 없음이 4.8초). Qt import 0.7~1.0초, 페이지 준비 0.8~1.3초 |
| 메모리 (예제 100번 불러온 뒤 작업 집합) | Python 프로세스 307MB + QtWebEngineProcess 282MB |
| 설치 크기 | PySide6 641MB (그중 `Qt6WebEngineCore.dll` 195MB, `resources/` 102MB). 내려받기 essentials 73MB + addons 160MB |
| JS 콘솔 오류 | 없음 |
| 한글 라벨 (API) | `modeling.updateLabel`로 넣은 「한글 라벨 ✓ 편집」이 저장 XML에 그대로 |
| 한글 IME 직접 입력 | 사용자가 직접 확인: 태스크 더블클릭 → 한글 입력 → 저장·다시 열어 확인 정상, 제목의 「 *」 표시도 정상 |
| Ctrl+S | 캔버스(Chromium)에 포커스가 있어도 Qt 메뉴 단축키로 간다 (UIA로 재현) |

### 발견

1. **`chk:` 확장 요소는 moddle 설명 없이도 보존된다.** bpmn-moddle이 모르는 요소를 일반 요소로 읽고 그대로 쓴다. 본문 JSON(한글·줄바꿈)도 같다. moddle 설명을 주면 JS에서 `chk:` 요소를 타입으로 다룰 수 있다 (속성 패널을 만들 때 필요).
2. **bpmn-js는 저장할 때 모양을 바꾼다 (의미는 같다).**
   - 다이어그램(DI) 요소 순서를 자기 순서로 다시 쓴다 — 50개 중 19개가 글자 단위로는 달랐던 원인.
   - BPMN 스키마 기본값과 같은 속성을 뺀다 (`isSequential="false"` 등).
   - `exporter`·`exporterVersion`을 자기 이름으로 바꾼다.
   - 라벨을 편집하면 그 요소의 DI에 `BPMNLabel`(위치)을 더한다.
   → 예제처럼 **생성물 BPMN을 Studio로 열어 저장하면 git diff가 커진다.** 비교는 글자가 아니라 의미로 해야 한다 (`shell.py`의 `normalize`: id 있는 자식은 id 순, 경로점처럼 id 없는 자식은 순서 유지, 기본값 속성 제거). 일부러 본문·경로점·이름을 바꾼 음성 시험에서 셋 다 잡았다.
3. **오프라인으로 돈다.** 모든 자원(JS·CSS·BPMN 아이콘 글꼴)이 로컬 파일이고 `LocalContentCanAccessRemoteUrls=False`로 바깥을 막았다. `qwebchannel.js`는 `qrc:///qtwebchannel/qwebchannel.js`로 `file://` 페이지에서 읽혔다.
4. **`file://` 페이지에서 `fetch()`로 로컬 JSON을 읽지 못할 수 있다** — moddle 설명을 `<script>`(`chk-moddle.js`)로 바꿔 피했다.
5. **Python ↔ JS:** `runJavaScript`는 Promise 결과를 못 받는다. 요청 id를 붙여 JS가 `bridge.result(id, JSON)`으로 돌려주는 방식이 잘 됐다.
6. `QWebEngineView.grab()`은 마지막으로 그려진 화면을 줘서, 방금 바꾼 내용이 안 보일 수 있다 (스크린샷이 앞 화면이었다). 캔버스 이미지가 필요하면 bpmn-js `saveSVG`를 쓴다.
7. JS 콘솔을 받으려면 `QWebEnginePage`를 상속해 `javaScriptConsoleMessage`를 덮어야 한다 (인스턴스 속성으로 바꾸면 안 불린다).
8. **bpmn-js 라이선스:** bpmn.io 워터마크(오른쪽 아래 「BPMN.iO」)를 없애거나 가리면 안 된다. 미니맵·속성 패널 배치(STU-01)를 그릴 때 겹치지 않게 해야 한다.

### 하지 않은 것 (다음에)

- 배율 125%·150%에서의 캔버스 (글자 흐림·좌표). S2는 Worker만 봤다.
- PyInstaller 등으로 묶었을 때 QtWebEngine 자원·크기 (S5).
- 속성 패널(`bpmn-js-properties-panel`), 미니맵, 디자인 토큰 CSS 주입 (ADR-0017).
- 큰 다이어그램(요소 수백 개) 성능 — 예제는 최대 수십 개.
