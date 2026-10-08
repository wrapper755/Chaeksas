# samples/ — 업무 예제가 부르는 모의 앱

> 상태: **구현됨** (M5 조각 13). 인수 시험이 쓰는 것은 M5 조각 14다.

제품이 아니다. `docs/08-business-examples/`의 예제 50개가 서비스 앱 **16개**를 부르고
(작업 **31개**), 그 앱이 하나도 없으면 M5 인수 시험을 돌릴 수 없다. 여기에 거짓 데이터로
답하는 앱을 둔다.

멤버는 하나다 — `samples/mock_apps` (import 이름 `chaeksas.mock_apps`). 앱 열여섯 개를
`pyproject.toml` 열여섯 개로 쪼개지 않는다.

**아무 멤버도 `samples/`를 의존하지 않는다** (`tests/test_import_direction.py`가 막는다).
쓰는 쪽은 `tests/`와 사람이 띄우는 `chk-mock-apps`뿐이다.

## 두 종류다

| | C11 앱 열넷 (`apps/`) | 외부 앱 둘 (`external/`) |
| --- | --- | --- |
| 무엇인가 | 사내 확장의 **서버 부분** | 우리 계약을 모르는 **남의 API** 흉내 |
| 뼈대 | `packages/service_kit` (C11) | 없다 — 평범한 FastAPI |
| 붙는 길 | `HttpServiceCaller` (C11) | **HTTP 어댑터** (C13 §4) |
| Center에 어떻게 아는가 | 운영자가 **주소를 등록**하면 Center가 `/manifest`를 읽는다 (C7) | Admin이 **서명한 정의**를 등록한다 (C13 E6) |
| 키 | 앱이 스스로 발급·검증 (ADR-0013) | 받아서 확인만 한다 |

외부 앱이 C11로 답하면 어댑터가 하는 일(템플릿 채우기·제한 JSONPath로 읽기·`error_when`)을
하나도 시험하지 못한다. 그래서 일부러 남의 API처럼 생겼다 — 낙타 표기(`bizNo`), 자기만의
봉투(`{"status": …, "result": …}`), 자기만의 경로. **조각 11·12가 만든 길을 실제로 밟는
유일한 자리다.**

## 띄우기

```bash
uv run chk-mock-apps list                 # 무엇이 있나, 기본 포트는 몇인가
uv run chk-mock-apps serve                # 전부 한 포트(8010)에, /<app_id> 밑에
uv run chk-mock-apps serve --app erp      # 하나만, 그 앱의 기본 포트에
```

`serve`를 앱 없이 부르면 **한 프로세스·한 포트**에 전부 붙는다. 서비스 앱 주소에 경로가
붙어도 되므로(`{base_url}/v1/ops/…`) Center 리소스 등록에 `http://127.0.0.1:8010/erp`를
그대로 넣을 수 있다. 앱 열여섯 개를 따로 띄우지 않아도 된다.

기본 포트는 `docs/04-setup.md` §6의 「다음 서비스 앱: 8010부터 10씩」을 따른다
(`catalog.port_of`가 유일한 자리다, ADR-0011). 옮기려면 `CHK_SVC_<앱 id>__PORT`.

### 키

```bash
CHK_MOCK_APPS__DEV_KEY=chk_svc_… uv run chk-mock-apps serve
```

이 하나로 **모든 모의 앱이 그 키를 받는다**. 앱마다 다르게 하려면 `CHK_SVC_<앱 id>__DEV_KEY`가
이긴다. 둘 다 없으면 앱이 띄울 때 하나 만들어 화면에 보여 준다 (개발용이다 — 비밀 저장소가
아니다). 부르는 쪽은 그 값을 키 참조 이름으로 넣는다 (`CHK_BOT_UI__SVC__<참조>` 또는 OS 비밀
저장소, BUI-10·STU-10).

`app_id`의 `-`는 환경변수에서 `_`가 된다 (`kb-search` → `CHK_SVC_KB_SEARCH__…`).

### 외부 확장 등록

정의는 **주소를 담아** 그대로 커밋할 수 없다 (포트가 띄울 때 정해진다). CLI가 그 자리에서 쓴다.

```bash
uv run chk-mock-apps definition ext-credit --base-url http://127.0.0.1:8150 -o ext-credit.json
```

그 파일을 `chk-admin sign-extension`으로 서명해 Center에 등록한다 (C13 E6 — **서명이 유일한
관문**이다). 모의 앱은 127.0.0.1에 뜨므로 정의가 `allow_private_network: true`를 켠다. 주소를
진짜 외부 호스트로 주면 그 칸은 저절로 꺼진다.

## 거짓 데이터는 **케이스가 정한다**

예제를 비틀지 않고 앱이 예제를 따라간다 (CLAUDE.md §3-6). 값마다 어느 케이스가 요구하는지
코드에 적어 두었다. 숫자를 고치려면 `docs/08-business-examples/cases/`를 먼저 본다.

`tests/test_mock_apps.py`가 **예제의 DMN을 실제로 돌려** 대조한다 — 눈으로 맞춘 숫자가 아니다.

| 케이스가 기대하는 것 | 앱의 거짓 데이터 |
| --- | --- |
| BX-06 위험수 1 | `ext-credit`: 마바테크만 `overdue: true` → `credit_grade`가 「위험」 |
| BX-08 이관건수 0 / 1 | `erp`: 연체 10·40·20일 → 시나리오 `이관1건`이 95일 한 건을 더한다 |
| BX-15 배송비 3000 | `erp`: P-100 무게 1.2kg → 10개면 12kg (`shipping_fee`의 20kg 선 아래) |
| BX-16 제안수 2 | `wms`: `qty < safety`인 것이 정확히 둘 |
| BX-23 메일 3통 | `lms`: 세 명, `남은일수` −2·3·14 → `training_nudge`의 세 갈래 |
| BX-24 잔여 11.5 / 3 | `hris`: 원장 `발생 − 사용 − 예정`. E002의 3이 BX-21 「잔여 부족」도 막는다 |
| BX-22 실패수 1 (ERP) | `erp`: **E009에만** 계속 503 → 재시도 2번 뒤 오류 경계 |
| BX-35 분석묶음 3개 | `ext-helpdesk`: 문의 120건 (50씩 나누면 3묶음) |
| FX-20 `{"score": 780}` | `ext-credit`: 123-45-67890 |

### 시나리오 — 입력이 같은데 답이 달라야 할 때

BX-08의 두 케이스는 입력이 둘 다 비어 있고, 케이스 설명이 「모의 서버에 95일 연체 1건 추가」라고
적어 두었다. 그래서 모의 앱에 제어 길이 하나 있다.

```bash
curl -X POST localhost:8010/erp/mock/v1/scenario -d '{"name":"이관1건"}'
```

**C11에는 이런 길이 없다.** 경로를 `/mock/`으로 떼어 둔 것이 그래서다 — 모의 앱만의 것이고
진짜 서비스 앱이 흉내 내서는 안 된다. **인증이 없으므로 이 앱들은 개발 PC·시험망에서만 띄운다**
(`serve`의 기본 바인드가 127.0.0.1인 것도 그 이유다).

## 두 가지는 모의가 아니다

- **`center-jobs`** — 진짜 Center의 `POST /jobs`(C5)를 부른다. BX-16이 메우려는 공백이
  「서버 BPM 프로세스가 PC BPM 프로세스에 일을 넘기는 요소가 없다」는 것이고
  ([ADR-0016](../docs/decisions/0016-server-first.md) §3), 그 자리를 **Center 연동용 키를 가진
  서비스 앱**으로 메우는 것이 예제의 설계다 (`docs/08-business-examples/scm.md`).
  `CHK_SVC_CENTER_JOBS__CENTER__BASE_URL`·`__CENTER__TOKEN`이 없으면 흉내 내지 않고 503이다.
- **`ui-automation`** — 진짜 내장 확장이라 여기 없다 (BX-36이 쓴다).

## 드러난 공백

- **C5의 작업 대상에 「그룹」이 없다.** 대상은 `bot_ui`(id 필수) 또는 `server_runner`뿐인데
  BX-16은 `group:구매-PC`로 적는다. 지금은 **`center-jobs` 앱이** 그룹을 PC로 푼다
  (`CHK_SVC_CENTER_JOBS__GROUPS`) — 계약을 늘리지 않고 앱 쪽에 두었다. 「어느 PC 묶음에
  던진다」가 운영에서 필요하다고 판단되면 C5에 올릴 거리다.
- **BX-35의 `나누기(VOC, 50)`가 성립하지 않는다.** `core.helpers`의 `나누기`는 수 나눗셈이고
  목록을 쪼개는 도우미가 없다. BX-35는 M5 묶음에 있으므로 조각 14 전에 정해야 한다
  (도우미를 더할지, 예제를 고칠지 — CLAUDE.md §5는 도우미를 더하면 ADR-0025의 표도 함께
  고치라고 한다).

## 파일

```
samples/mock_apps/src/chaeksas/mock_apps/
├─ c11.py          # MockApp·Op → service_kit 앱 하나 (+ /mock/v1/scenario)
├─ catalog.py      # 무엇이 있나, 기본 포트
├─ cli.py          # chk-mock-apps
├─ fixtures.py     # 앱 경계를 넘는 거짓 데이터 (사람·거래처)
├─ apps/           # C11 앱 하나 = 모듈 하나 (APP 하나를 내보낸다)
└─ external/
   ├─ apps.py        # 남의 API 흉내 둘 (service_kit을 쓰지 않는다)
   └─ definitions.py # 그 둘의 C13 어댑터 정의
```
