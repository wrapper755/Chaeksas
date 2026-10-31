# ADR-0120. Center 콘솔 로그인의 머리는 INNONOW 로고와 문구다 — 탭 제목도 INNONOW

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 |
| 날짜 | 2026-10-31 |
| 관련 | 화면 CON-00 (로그인), [ADR-0118](0118-no-product-name-on-screens.md), [ADR-0119](0119-match-nowview-style.md) |

## 배경

ADR-0118로 「Chaeksas」(저장소 이름)를 화면에서 걷었고 로그인 화면에는 BPM 흐름 마크만 남았다. 사용자는 로그인 화면 위에
**INNONOW**(innonow.co.kr — NowView가 그 「Management Reference Model 파일럿」이다)의 대표 로고와 문구를 두고, 탭 제목도
「Center 콘솔」이 아니라 InnoNow 누리집과 비슷한 뜻으로 하기를 원했다. 문구는 그대로 쓰지 않아도 되고 로그인 공간에 맞게.

## 결정

- 로그인 화면 맨 위에 **화면 폭 전체의 띠**로 머리를 둔다(카드 폭이 아니다) — INNONOW 로고(InnoNow 저장소 `web/public/images/logo-innonow-{navy,ivory}.png` 그대로,
  `web/apps/center-console/public/brand/`), 제목 「AI와 함께, 경영을 실행합니다.」, 영문 한 줄 「Management Transformation
  in Action.」. 누리집의 「AI 시대, 경영은 진화해야 합니다. / Management Transformation Starts Here.」를 **실행하는 자리**
  쪽으로 옮긴 말이다. 어두운 테마면 밝은(ivory) 로고를 쓴다.
- 카드 맨 위의 BPM 흐름 마크는 그대로 둔다 — 띠는 브랜드, 카드는 Center다.
- 띠 아래에는 **배경 그림**을 깐다 — BPMN 흐름(원·태스크·마름모)과 AI를 떠올리는 신경망, 남색~남보라, 가운데가 밝아 흰 카드가 읽힌다. 사용자 요청으로 Gemini 이미지 모델(`gemini-3.1-flash-image`)로 만들었고 webp 한 장(약 24KB)이다. 사진이 아니라 토큰 색을 따르지 않는다 — 어두운 테마에서도 같은 그림이다.
- 브라우저 탭 제목은 모든 화면에서 「INNONOW — Management Transformation Center」다(누리집 「INNONOW — AI 시대의
  Management Transformation」과 같은 결). 위 막대 마크의 툴팁은 「첫 화면」이다.
- ADR-0118의 「화면에 제품 이름을 쓰지 않는다」는 저장소 이름(Chaeksas) 이야기라 그대로다 — INNONOW는 이 콘솔을 쓰는 쪽의 브랜드다.
- 서비스 앱 관리 콘솔은 그대로다(앱마다 이름이 있다).

## 결과

- 쉬워지는 것: NowView·누리집·Center 콘솔이 같은 브랜드로 이어 보인다.
- 포기하는 것: 로고가 PNG라 토큰 색을 따르지 않는다 — InnoNow가 로고를 바꾸면 손으로 다시 가져온다.
- 다시 볼 조건: INNONOW가 아닌 곳에 Center를 설치할 때(로고·문구를 설정으로 빼야 한다), InnoNow가 SVG 로고를 낼 때.
