# ADR-0119. 웹 콘솔의 모양을 NowView에 맞춘다 — 남보라 강조색·남색 틀·Geist

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 |
| 날짜 | 2026-10-31 |
| 관련 | [07-style-guide](../07-style-guide.md) §2-1·§2-3·§4-1, `design/tokens.json`, 화면 CON-00·SVC-00, [ADR-0017](0017-web-nextjs-design-system.md), [ADR-0118](0118-no-product-name-on-screens.md) |

## 배경

Center 콘솔은 바깥 시연 앱 NowView와 나란히 보인다 — NowView가 회사 업무 시스템이고 Center가 그 일을 하는 가상 직원·BPM
프로세스의 자리다. 둘의 모양이 달라(파란 강조색·흰 틀 ↔ 남보라 강조색·남색 틀) 한 시연 안에서 다른 제품처럼 보였다.
사용자가 스타일을 통일하려 하고 있으니 NowView에 맞춰 달라고 했다.

## 선택지

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. **색·틀·글꼴 모두** NowView 값으로 | 나란히 두면 한 제품처럼 보인다 | 글꼴 파일이 하나 는다. 데스크톱은 같은 토큰이라 색이 함께 바뀐다 |
| B. 색·틀만 | 글꼴을 들이지 않는다 | 영문·숫자 모양이 다르다 |
| C. 색만 | 바뀌는 것이 가장 적다 | 틀(남색 위 막대·탐색)이 달라 여전히 다른 제품으로 보인다 |

## 결정

**A — 색·틀·글꼴을 NowView에 맞추고, 토큰 원본 하나를 고치므로 데스크톱(Studio·PC 실행기·Tool UI)의 색도 함께 바뀐다.**

- 값은 NowView `app/globals.css`의 oklch를 sRGB로 옮긴 것이다 — `primary` = `--brand`(남보라 278°), `primary.subtle` =
  `--brand-soft`, `bg.canvas` = `--background`(연회색), `bg.surface` = `--card`(흰색), 글자·선은 무채색. 상태 색 일곱은
  그대로다(상태 표기는 우리 것이다).
- **남색 틀은 새 토큰 `chrome.*`**이다(NowView의 `--ink` + `.chrome-ink`). 틀 안에서는 `.chrome`이 `bg.surface`·`text.*`·
  `border.*`를 틀 색으로 바꿔 끼워 Button 같은 구성요소를 고치지 않고 쓴다 — NowView가 쓰는 방법과 같다.
- 틀은 화면 폭 전체의 위 막대(48) + 그 아래 왼쪽 탐색(224)이고 둘 다 고정이다. 고른 탐색 줄은 `primary` 바탕이다.
- 글꼴은 **Geist(라틴) → Pretendard(한글)**이다. Geist는 OFL이고 라틴 부분 집합 가변 woff2 하나를 자체 호스팅한다(외부 CDN
  금지 그대로). 데스크톱은 Geist를 등록하지 않아 지금처럼 Pretendard로 그린다. 고정폭은 JetBrains Mono 그대로다.

## 결과

- 쉬워지는 것: NowView와 Center 콘솔을 오가도 한 제품처럼 보인다. 틀 색을 바꿀 때 `chrome.*` 다섯만 고친다.
- 어려워지거나 포기하는 것: NowView가 색을 바꾸면 따라가는 것은 사람의 일이다(두 저장소가 토큰을 나누지 않는다).
  데스크톱은 같은 남보라가 되지만 틀(남색)은 웹에만 있다.
- 다시 볼 조건: NowView가 디자인 토큰을 따로 낼 때(같은 원본을 읽게 한다), 데스크톱에도 남색 틀을 원할 때, 현장 PC에서
  Geist가 한글과 섞여 어색하다는 말이 나올 때.
