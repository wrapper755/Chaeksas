# ADR-0126. 운영자·사용자에게 닿는 이름은 `BPM`으로 쓴다 — `CHK`·`chk`를 걷는다

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 (2026-11-01) |
| 날짜 | 2026-11-01 |
| 관련 | [ADR-0019](0019-package-names.md)(파이썬 이름 `chaeksas.*` — 그대로), [ADR-0118](0118-no-product-name-on-screens.md)(화면에 제품 이름 없음), [ADR-0025](0025-expression-language.md)(식 언어 이름), [ADR-0081](0081-answering-on-behalf.md)·[ADR-0123](0123-folder-keys.md)(헤더·토큰), 계약 C4·C5·C7·C12·C14 |

## 배경

저장소 이름은 Chaeksas이지만 운영자와 사용자에게 이것은 **BPM 시스템**이다. 그런데 그들이 손으로 치거나 보는 이름에 프로젝트 약자 `chk`가 남아 있었다. 설정 환경변수(`CHK_CENTER__PORT`), 셸 명령(`chk-center`), 연동하는 쪽이 싣는 HTTP 헤더(`X-CHK-Actor`), 키 앞머리(`chk_ctr_…`), BPMN 파일을 열면 보이는 확장 요소(`chk:aiTask`)가 그렇다. 화면에서는 이미 제품 이름을 걷었다(ADR-0118).

## 선택지

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| **A. 닿는 이름을 모두 `BPM`으로, 옛 이름은 읽지 않는다** | 이름이 한 벌이다. 출시 전이라 지금이 가장 싸다 | 이미 돌던 설정·키·연동이 한 번 깨진다 |
| B. 새 이름 + 한동안 옛 이름도 읽는다 | 바꾸는 동안 깨지지 않는다 | 이름이 두 벌인 기간이 생기고, 걷는 조각이 한 번 더 든다 |
| C. 그대로 둔다 | 할 일이 없다 | 운영자가 모르는 약자를 계속 친다 |

## 결정

**A — 운영자·사용자에게 닿는 이름은 `BPM`으로 쓰고, 옛 이름은 읽지 않는다.**

| 갈래 | 전 | 후 |
| --- | --- | --- |
| 환경변수 접두사 | `CHK_` (`CHK_CENTER__PORT`, `CHK_SVC_<앱>__…`) | `BPM_` (`BPM_CENTER__PORT`, `BPM_SVC_<앱>__…`) |
| 명령 | `chk-center`·`chk-server-runner`·`chk-bot-ui`·`chk-bot-runner`·`chk-studio`·`chk-adapter-consumer`·`chk-mock-apps` | `bpm-center`·`bpm-server-runner`·`bpm-bot-ui`·`bpm-bot-runner`·`bpm-studio`·`bpm-adapter-consumer`·`bpm-mock-apps` |
| HTTP 헤더 | `X-CHK-Actor`·`X-CHK-On-Behalf-Of`·`X-CHK-Join-Token`·`X-CHK-Local-Token`·`X-CHK-Local-Admin` | `X-BPM-Actor`·`X-BPM-On-Behalf-Of`·`X-BPM-Join-Token`·`X-BPM-Local-Token`·`X-BPM-Local-Admin` |
| 토큰 앞머리 | Center API 키 `chk_ctr_`, 세션 `chk_ses_` | `bpm_ctr_`, `bpm_ses_` |
| BPMN 확장 요소 접두어 | `chk:` (`chk:aiTask`, `xmlns:chk`) | `bpm:` (`bpm:aiTask`, `xmlns:bpm`) |
| 식 언어 이름 | `chk-expr` | `bpm-expr` |
| 웹·캔버스 CSS 변수·마커 | `--chk-*`, `chk-running` 등 | `--bpm-*`, `bpm-running` 등 |

- **BPMN 네임스페이스 URI는 그대로다** (`urn:chaeksas:bpmn:1`). 읽는 쪽(`contracts.bpmn_ext`)은 접두어가 아니라 URI로 요소를 찾으므로, 접두어만 바꾸면 옛 그림도 그대로 읽힌다. 새로 쓰는 그림은 `bpm:`로 나간다(Studio의 moddle 설명 `prefix`). URI는 화면·설정에 나오지 않는 식별자라 프로젝트 이름이 남아도 된다. 일부러 옛 접두어를 읽는 코드를 둔 것이 아니라 XML 규칙이 그렇다.
- **그대로 두는 것**: 파이썬 패키지 이름 `chaeksas.*`(ADR-0019 — 개발자의 것), 저장소·설치 파일 스크립트 이름, 코드 안의 식별자(`chk` 변수·`ChkButton` 같은 Qt 클래스·캔버스 통신의 `chk` 칸·`chkTheme` 같은 JS 함수). 사람이 치거나 보는 이름이 아니다.
- **지나간 ADR(0001~0125)은 고치지 않는다** — 이 표가 옛 이름을 새 이름으로 읽는 열쇠다. 지금 규칙을 적는 문서(CLAUDE.md·`docs/0*`·계약·화면·용어집·예제 생성물)는 새 이름으로 바꿨다.
- **옛 이름은 받지 않는다.** `CHK_…` 환경변수는 이제 아무 설정도 채우지 않고 `X-CHK-…` 헤더는 무시된다. **토큰은 예외다** — Center는 앞머리가 아니라 해시를 맞추므로 이미 발급된 `chk_ctr_` 키·일꾼 폴더의 토큰은 그대로 통한다. 새로 짓는 것만 `bpm_ctr_`이다(일부러 옛 것을 받는 코드가 아니라 원래 그렇다).

## 결과

- 이 결정으로 쉬워지는 것: 운영자가 치는 이름(`bpm-center`, `BPM_CENTER__…`)과 보는 이름이 「BPM 시스템」과 맞는다. 이름이 한 벌이다.
- 어려워지거나 포기하는 것 — **한 번 손봐야 하는 자리**:
  - 운영 중인 Center·서버 실행기의 `.env`·compose 환경(원격 Center 포함)의 `CHK_` → `BPM_`. 반영할 때 함께 고친다.
  - 셸 스크립트·서비스 단위·compose의 명령 이름 `chk-…` → `bpm-…`.
  - 연동하는 쪽(NowView 일꾼)의 헤더 `X-BPM-…`·토큰 앞머리·그림의 `bpm:`.
  - 이미 서명된 패키지는 접두어가 `chk:`여도 URI가 같아 읽힌다. 다시 낼 필요는 없다.
- 다시 볼 조건: 제품 이름이 정해져 「BPM」 말고 다른 이름을 바깥에 써야 하면, 이 표의 「후」 열만 다시 정한다.
