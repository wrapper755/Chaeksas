# ADR-0017. 웹 화면은 Next.js, 모든 화면은 하나의 디자인 시스템(토큰 하나)으로

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 (2026-10-01) — 라이브러리 버전은 M1에서 고정 · §4 저장소 구성은 ADR-0018이 보완(`extensions/`) |
| 날짜 | 2026-10-01 |
| 대체 | 없음 (프로토타입의 Streamlit 화면을 잇지 않는다) |
| 관련 | [07-style-guide](../07-style-guide.md), `design/tokens.json`, ADR-0004, ADR-0013, 화면 CON-*, SVC-*, UIA-*, STU-*, BUI-* |

## 배경

프로토타입은 빠르게 보기 위해 앱마다 화면을 따로 만들었고, 웹 화면(Center 대시보드, UI 자동화 서버 화면)은 Streamlit으로 만들었다. 학습·속도에는 좋았지만 제품으로는 한계가 드러났다.

- **Streamlit:** 상호작용마다 스크립트 전체가 다시 돈다. 상태 관리·표·폼·필터를 원하는 대로 다루기 어렵고, 로그인·권한·토큰 숨기기가 약하며, 모양을 세밀하게 맞출 수 없다.
- **앱마다 다른 모양:** 같은 "실행 중"이 앱마다 다른 색·말로 보였다. 데스크톱(Qt)과 웹의 색·글꼴이 따로 놀았다.

## 결정

### 1. 웹 화면(Center 콘솔, 서비스 앱 관리 콘솔)은 Next.js

| 항목 | 선택 |
| --- | --- |
| 프레임워크 | **Next.js** (App Router) + **TypeScript** |
| 런타임·패키지 | Node.js LTS, **pnpm** 워크스페이스 (`web/`) |
| UI 기반 | **Tailwind CSS** + **shadcn/ui**(Radix 기반, 코드를 저장소에 복사해 우리 토큰으로 맞춤) |
| 아이콘 | **Lucide** (웹 `lucide-react`, 데스크톱은 같은 SVG) |
| 데이터 | 서버 쪽에서 Center·서비스 앱 API 호출(아래 BFF), 화면 쪽 갱신은 TanStack Query, 표는 TanStack Table |
| 폼 | react-hook-form + zod |
| 계약 타입 | `packages/contracts`(Python)가 내보낸 JSON Schema(계약 원칙 5)에서 **TypeScript 타입을 생성**한다 (`web/packages/api-types`). 손으로 타입을 쓰지 않는다 |
| 테스트 | Vitest(단위), Playwright(화면 흐름, 프로토타입부터 쓰던 도구) |
| 배포 | `output: standalone` 컨테이너. 서버 `docker compose`에 함께 |

- **BFF(서버 쪽 중계):** 브라우저는 Center API·서비스 앱 API를 직접 부르지 않는다. Next.js 서버(Route Handler·Server Action)가 관리자 토큰을 들고 부른다. 토큰은 브라우저에 내려가지 않고, 로그인 상태는 암호화된 httpOnly 세션 쿠키로 둔다 (OIDC는 로드맵 "나중에").
- **포트는 그대로:** Center 콘솔 8501, UI 자동화 앱 관리 콘솔 8001, 다음 서비스 앱 콘솔 = API 포트 + 1 (ADR-0011).
- **서비스 앱 관리 콘솔:** `service_kit`(Python)은 화면 대신 **관리 API**(`/admin/v1/status`, `/admin/v1/keys`, `/admin/v1/usage`)를 제공하고, 화면은 `web/apps/svc-console` 한 벌이 그린다. 앱 고유 화면(UIA-01~03)은 같은 코드베이스의 모듈로 두고, 접속한 앱의 `app_id`에 맞는 메뉴만 켠다. 서비스 앱마다 같은 이미지를 설정만 바꿔 띄운다.

### 2. 데스크톱(Studio·Bot UI)은 PySide6 그대로, 같은 토큰

- Qt 화면은 그대로 PySide6 (ADR 변경 없음). 색·글꼴·간격은 웹과 **같은 토큰**에서 생성한 QSS·팔레트를 쓴다.
- Studio 캔버스(bpmn-js, QtWebEngine)는 웹과 같은 CSS 변수 파일을 주입받아 노드 상태 색이 콘솔과 같다.

### 3. 디자인 토큰 하나가 원본

- 원본: 저장소 루트 `design/tokens.json` (색 밝게/어둡게, 글꼴, 크기, 간격, 둥글기, 그림자, 움직임, 상태→색 대응표).
- 생성물 (M1, 생성기 `scripts/gen_tokens.py`):
  - 웹: `web/packages/ui/src/tokens.css` (CSS 변수) + Tailwind 테마
  - 데스크톱: `packages/qt/…/theme/tokens.py` + `theme.qss`
  - 미리보기: `design/preview.html`
- 코드에 색값을 직접 쓰지 않는다. CI가 생성물이 원본과 맞는지 검사한다.
- 규칙·구성요소·문구는 [07-style-guide.md](../07-style-guide.md).

### 4. 저장소 구성 (ADR-0004에 더함)

```
Chaeksas/
├─ design/                 # tokens.json(원본), preview.html(생성)
├─ web/                    # pnpm 워크스페이스
│  ├─ apps/center-console/ # Center 콘솔 (Next.js, 8501)
│  ├─ apps/svc-console/    # 서비스 앱 관리 콘솔 (Next.js, 앱마다 하나씩 띄움)
│  └─ packages/
│     ├─ ui/               # 공용 구성요소 + 토큰 CSS
│     ├─ api-types/        # 계약 JSON Schema에서 생성한 타입
│     └─ config/           # tsconfig·eslint 공용 설정
└─ (기존) packages/ apps/ services/ …
```

- `web/`은 Python 코드를 import하지 않는다. HTTP와 생성된 타입으로만 잇는다.
- `apps/center/`는 Center **API만** 가진다 (콘솔은 `web/apps/center-console`).

## 검토한 다른 안

| 안 | 장점 | 버린 이유 |
| --- | --- | --- |
| Streamlit 유지 | 빠름, Python 하나 | 위 배경의 한계. 제품 화면으로 키우기 어렵다 |
| Vite + React SPA를 FastAPI가 서빙 | Node 런타임이 서버에 필요 없음 | 토큰을 숨기려면 BFF를 따로 만들어야 하고, 라우팅·서버 렌더링을 직접 갖춰야 함 |
| Python 서버 렌더링 (Jinja + HTMX) | 도구가 하나 | 표·폼·필터 같은 복잡한 상호작용 구성요소가 부족 |
| NiceGUI / Reflex | Python으로 React급 화면 | 생태계가 작고, 모양을 세밀하게 맞추기 어려움 |

## 결과

- 쉬워지는 것: 웹 화면을 제품 수준(권한, 표, 폼, 접근성)으로 만든다. 웹·데스크톱이 같은 색·글꼴·상태 표기를 쓴다. 계약이 바뀌면 TypeScript 타입도 생성으로 따라온다.
- 어려워지는 것: 도구가 둘(uv + pnpm)이 되고 CI에 Node 작업이 생긴다. 개발 PC에 Node.js LTS·pnpm이 필요하다 (04-setup).
- 다시 볼 조건: 웹 화면이 콘솔 몇 개를 넘어 크게 늘지 않고 Node 운영이 부담이면, 정적 내보내기 + FastAPI BFF로 줄이는 안을 다시 본다.
