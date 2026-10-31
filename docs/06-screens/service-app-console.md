# 서비스 앱 관리 콘솔 화면 설계

**서비스 앱마다 자기 관리 콘솔(웹)을 가진다** ([ADR-0013](../decisions/0013-api-keys.md)). 서비스 앱은 Center에 **일꾼**으로 들어와 일감을 가져간다 ([C15](../03-contracts/C15-external-tasks.md), [ADR-0102](../decisions/0102-calling-outside-is-pull.md)) — **서비스 앱 API 키는 없다**(「누가 불러도 되나」는 Center가 배포로 가린다). 그래서 이 콘솔에 키 화면이 없다. 공통 화면(SVC)은 `packages/service_kit`이 제공하고, 앱 고유 화면은 그 앱을 서버 부분으로 가진 확장이 더한다 (아래 「앱 고유 화면」).

일꾼은 Center 일꾼 폴더의 파일로 들어온다 (ADR-0122) — 화면에서 들이는 단계는 없다. Center 리소스 목록(CON-07)에서 각 관리 콘솔로 링크를 건다.

> 구현: `service_kit`(Python)은 **관리 API**(`/admin/v1/status`·`usage`)를 제공하고, 화면은 Next.js 앱 `web/apps/svc-console` 한 벌이 그린다. 서비스 앱마다 같은 콘솔을 설정만 바꿔 띄우고(포트 = API + 1), 접속한 앱의 확장에 맞는 고유 화면만 켠다 ([ADR-0017](../decisions/0017-web-nextjs-design-system.md)).
공통 원칙·상태 표기는 [README.md](README.md) §2·§3.

## SVC-00 공통 틀

```
+----------------------------------------------------------------+
| [A] top bar (full width): mark app name  version | status [Refresh] |
+------------+---------------------------------------------------+
| [N] nav    | [B] page body                                      |
+----------------------------------------------------------------+
```

| 영역 | 내용 |
| --- | --- |
| [N] 탐색 | 위 막대 아래 왼쪽, 남색 틀(Center 콘솔과 같다, ADR-0119). 공통: 「상태」(SVC-01) / 「사용 기록」(SVC-03) · 그 아래 앱 고유 메뉴 (확장이 기여한 것이 있을 때만) |
| [A] 위 막대 | 화면 폭 전체, 남색 틀. **BPM 흐름 마크 + 앱 이름**(`/admin/v1/status`의 `name`, 못 읽으면 「서비스 앱」 — 한 벌로 여러 앱을 그리므로 이름은 글로 남긴다, [ADR-0118](../decisions/0118-no-product-name-on-screens.md)), 버전·주소, 상태(정상·저하), 「새로 고침」, 「나가기」 |

**로그인:** 관리자 토큰(앱 설정)으로 들어간다 (OIDC는 나중). 보기 전용 토큰은 없다. 연회색 바탕 위 흰 카드 하나에 마크·제목·칸이 든다(Center 콘솔 로그인과 같은 모양).

> SVC-02(API 키)는 없다 — 서비스 앱 키가 없어졌다 ([ADR-0102](../decisions/0102-calling-outside-is-pull.md)). 번호는 다시 쓰지 않는다.

## SVC-01 상태

| 섹션 | 내용 |
| --- | --- |
| 요약 | 앱 id, 구분(업무·시스템), 버전, 가동 시간, API 주소 |
| 「작업」 | 작업 이름 / 설명 / 지원 수행 모드(자율·결정) / 결정 수행 실패 시 폴백 정책 / 최근 24시간 호출 수 / 오류율 |
| 「의존」 | LLM 게이트웨이, DB 등 바깥 의존의 상태 (`DependencyProbe`가 앱마다 돌려준다) |
| 「Center 등록」 | Center 리소스 목록에 올라가 있는지, 마지막 보고 시각 |

## SVC-03 사용 기록

| 열 | 내용 |
| --- | --- |
| 시각 / 부른 쪽 / 작업 / 수행 모드 / 결과(성공·실패·거부) / 소요 / 실행 id(있으면) / LLM | 업무 값은 기록하지 않는다 (부른 쪽·작업·결과만) |

「부른 쪽」은 일감의 `caller`를 `<종류>:<호스트>`로 적은 것이다 (예: `bot_ui:bui_…`, `server_runner:srv_…`, `studio:…` — C11 `UsageRecord.key_name`에 담긴다).

「실행 id」는 **CON-01 실행 상세로 가는 링크**다 ([ADR-0075](../decisions/0075-service-console-links-to-center-console.md)) — Center 콘솔 주소는 이 콘솔의 설정 `BPM_SVC_CONSOLE__CENTER_CONSOLE_URL`(브라우저가 여는 주소)이 주고, **없으면 링크만 없다**. C3 `run_id` 모양(`run_…`·`test_…`)일 때만 잇는다.

> 제안: 필터(부른 쪽, 작업, 결과, 기간)와 「부른 쪽별 합계」 탭(호출 수·실패 수·LLM 사용량). 지금은 최근 100건 목록뿐이다.

## 앱 고유 화면

확장은 제 서버 부분의 관리 콘솔에 화면을 기여할 수 있다 (`console.pages`, [ADR-0042](../decisions/0042-extension-contributed-panels.md) §2) — 콘솔이 모노레포 확장 정의의 `console.pages`를 빌드 시점 레지스트리(생성물 `lib/console-pages.generated.ts`)로 읽고 접속한 앱의 `extension.id`(C11 `AdminStatus.extension`)로 고른다. 화면 모듈은 `lib/console-modules.ts`에 적힌 것만 열린다. 외부 확장(외부 앱)은 이 콘솔을 쓰지 않고 자기 콘솔 링크만 CON-07에 보인다.

> 상태: **레지스트리가 비어 있다** — 지금 깔린 확장에 `console.pages` 기여가 없어 앱 고유 메뉴가 없다. UI 자동화 앱의 UIA-01~03은 그 확장과 함께 없어졌다 ([ADR-0114](../decisions/0114-remove-ui-automation.md)). 번호는 다시 쓰지 않는다.
