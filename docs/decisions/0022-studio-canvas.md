# ADR-0022. Studio 캔버스는 QtWebEngine 안의 bpmn-js 배포본, Python과는 QWebChannel로 잇는다

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 (2026-10-03) |
| 날짜 | 2026-10-02 |
| 관련 | 스파이크 `spikes/S3-studio-shell/`, 계약 C14(BPMN 확장), ADR-0017(디자인 토큰), `docs/06-screens/studio.md` STU-01 |

## 배경

Studio는 PySide6 데스크톱 앱이고 캔버스는 bpmn-js다 (`06-screens/studio.md`). 이 조합이 Windows에서 실제로 뜨는지, 우리 BPMN 파일(C14 `chk:` 확장, 한글 JSON 본문)을 망가뜨리지 않고 저장하는지 확인한 적이 없었다. Studio를 만들기 전에 캔버스를 싣는 방식과 Python ↔ JS 경계를 정해야 한다.

## 선택지

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. QWebEngineView + bpmn-js 배포본(UMD) 로컬 파일 + QWebChannel | S3에서 예제 50개 불러오기·저장 왕복이 의미상 50/50. 한글 IME 입력 정상. 번들러 없이 동작. 오프라인 | 설치 크기(PySide6 641MB, WebEngine이 대부분), 메모리 약 590MB. bpmn-js가 저장 모양을 바꾼다 |
| B. 같은 구성 + 우리 JS를 번들(웹 워크스페이스에서 빌드) | 속성 패널·미니맵·토큰 CSS 등 플러그인을 묶기 쉽다. 타입 검사 | 빌드 단계가 Studio에 생긴다 — 지금은 플러그인이 없어 필요 없다 |
| C. 네이티브 Qt로 BPMN 편집기를 직접 | 가볍다 | BPMN 편집기를 새로 만드는 일. 현실적이지 않다 |

## 결정

**A로 시작한다.** Studio 캔버스는 `QWebEngineView`가 로컬 `index.html`을 띄우고, 그 안에서 bpmn-js 배포본을 쓴다. 플러그인(속성 패널·미니맵)을 붙일 때 B로 옮긴다.

- **오프라인.** JS·CSS·글꼴은 모두 앱과 함께 배포하고, `LocalContentCanAccessRemoteUrls`를 끈다. CDN을 쓰지 않는다.
- **Python ↔ JS는 QWebChannel 하나.** Python이 `window.chk(요청 id, 함수 이름, 인자 JSON)`을 부르고, JS가 `bridge.result(요청 id, 결과 JSON)`으로 돌려준다 (`runJavaScript`는 Promise 결과를 못 받는다). 변경 알림은 `bridge.changed`.
- **`chk:` 요소는 moddle 설명을 준다.** 설명 없이도 보존되지만, 속성 패널이 타입으로 다루려면 필요하다. 설명은 C14 모델에서 생성한다 (손으로 쓰지 않는다).
- **BPMN 비교는 의미로 한다.** bpmn-js는 저장할 때 DI 순서를 바꾸고, 스키마 기본값 속성을 빼고, `exporter`를 바꾸고, 라벨 편집 시 `BPMNLabel`을 더한다. 시험·Center 검사·「저장 안 한 변경」 판단은 글자 비교를 쓰지 않는다.
- bpmn.io 워터마크는 라이선스상 가리지 않는다 — STU-01의 미니맵·도구 배치가 오른쪽 아래를 덮지 않게 한다.

> 미정: bpmn-js 배포본을 어디서 가져와 Studio 패키지에 넣을지 — `web/` pnpm 워크스페이스(ADR-0017)에서 버전을 고정해 빌드 산출물로 복사하는 안이 첫 후보. Studio 설치 파일에 QtWebEngine을 묶는 크기·방법은 S5에서.

## 결과

- 이 결정으로 쉬워지는 것: 표준 BPMN 편집기를 그대로 쓴다. 우리 확장 속성이 왕복에서 보존됨을 50개 예제로 확인했다. 웹 콘솔과 같은 JS 생태계(토큰 CSS)를 쓸 수 있다.
- 어려워지거나 포기하는 것: Studio 설치 크기가 크다(WebEngine). Studio에서 저장한 예제·BPMN은 git diff가 크게 나온다 — 생성물(`docs/08-business-examples/bpmn/`)은 Studio로 저장하지 않는다.
- 다시 볼 조건: 배율 125%·150%에서 캔버스 문제가 나오는 경우, 설치 크기가 배포에 걸림돌이 되는 경우(S5), 요소 수백 개 다이어그램에서 느린 경우.
