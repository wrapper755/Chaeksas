# ADR-0029. bpmn-js 배포본은 `web/` 워크스페이스에서 버전을 고정해 **복사하고, 복사본을 커밋한다**

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 |
| 날짜 | 2026-10-04 |
| 관련 | [ADR-0022](0022-studio-canvas.md) §미정, [ADR-0017](0017-web-nextjs-design-system.md)(`web/` pnpm 워크스페이스), [ADR-0024](0024-desktop-packaging-extensions.md)(PyInstaller), 스파이크 [S3](../../spikes/S3-studio-shell/NOTES.md), M3 조각 3e |

## 배경

ADR-0022는 Studio 캔버스를 「QtWebEngine 안의 bpmn-js 배포본」으로 정하면서 **「배포본을 어디서 가져와 Studio 패키지에 넣을지」를 미정으로** 남겼다. 조각 3e에서 Studio를 만들기 시작하므로 지금 정한다.

까다로운 점은 도구가 둘이라는 것이다. 파이썬 쪽은 uv 워크스페이스이고 CI 작업에 Node가 **없다**. 웹 쪽은 pnpm 워크스페이스이고 Node가 있다. bpmn-js는 npm 패키지다.

## 선택지

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. 파이썬 빌드·시험 때 `npm install`을 돌린다 | 저장소에 남의 코드가 없다 | **파이썬 CI 작업에 Node를 들여야** 한다. 오프라인 빌드가 안 된다. Windows 설치 파일 만들 때마다 네트워크가 필요하다 |
| B. 배포본을 손으로 내려받아 커밋 | 간단하다 | 버전이 어디에 적혀 있는지 알 수 없다. 올릴 때 사람이 기억해야 한다 |
| **C. `web/`에 패키지 하나를 두어 버전을 고정하고, `build`가 배포본을 Studio 안으로 복사한다. 복사본을 커밋하고 CI(웹 작업)가 `--check`로 최신 여부를 본다** | 버전이 `package.json`·`pnpm-lock.yaml` 한 곳에 있다. 파이썬 쪽은 Node 없이 돈다 (오프라인·PyInstaller 그대로). 저장소의 **다른 생성물과 똑같은 규칙**이다 | 저장소에 ~1 MB의 생성물이 는다 |

## 결정

**C.**

1. `web/packages/bpmn-canvas`가 **bpmn-js 버전을 고정**한다 (`pnpm-lock.yaml`에 함께 잠긴다). `pnpm --filter @chaeksas/bpmn-canvas build`가 배포본(JS·CSS·글꼴)을 `apps/studio/src/chaeksas/studio/web/vendor/`로 복사하고, `--check`는 쓰지 않고 검사만 한다.
2. **복사본은 커밋한다.** 이 저장소는 이미 생성물을 커밋한다 — 계약 JSON Schema, 디자인 토큰 CSS, `api-types`, 업무 예제, 포함 글꼴. **CI가 `--check`로 최신 여부를 보는 것**이 그 규칙의 짝이고, 여기도 같다 (웹 작업이 본다 — 거기에 Node가 있다).
3. **`chk-moddle.js`는 손으로 쓰지 않는다** — C14 모델(`contracts.bpmn_ext.ELEMENT_MODELS`)에서 `scripts/gen_moddle.py`가 만든다 (ADR-0022의 「설명은 C14 모델에서 생성한다」). 이것도 커밋하고 `--check`가 파이썬 작업에서 본다. `chk:*` 요소를 하나 더하면 생성기를 다시 돌리지 않는 한 CI가 깨진다.
4. **우리가 쓴 것과 받아 온 것을 폴더로 가른다.** `web/vendor/`는 생성물(건드리지 않는다), 그 바깥의 `index.html`은 우리가 쓴다. `vendor/`에는 어느 판을 받았는지 적은 `VERSION.txt`를 함께 둔다.
5. **오프라인을 지킨다** (ADR-0022). CDN을 쓰지 않고, WebEngine의 `LocalContentCanAccessRemoteUrls`를 끈다.

## 결과

- **쉬워지는 것:** 파이썬 쪽(시험·`uv sync`·PyInstaller)이 Node 없이 돈다. bpmn-js를 올리는 일이 `package.json` 한 줄 + `pnpm build` + 커밋이다. 업무 PC가 인터넷에 못 나가도 Studio가 뜬다.
- **포기하는 것:** 저장소에 남의 배포본 ~1 MB가 들어온다. `git diff`에서 그 파일은 사람이 읽을 것이 아니다.
- **우리가 지는 것:** 버전을 올릴 때 **두 곳이 함께 움직여야 한다** (`package.json`과 복사본). `--check`가 그것을 지킨다.
- **다시 볼 조건:** ① 속성 패널·미니맵 같은 플러그인을 붙여 번들러가 필요해지면 (ADR-0022의 안 B로 가고, 그때도 산출물을 복사·커밋하는 이 규칙은 그대로다), ② 배포본이 10 MB를 넘으면 (그때는 설치 파일을 만들 때만 받는 쪽을 다시 본다).
