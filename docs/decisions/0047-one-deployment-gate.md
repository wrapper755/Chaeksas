# ADR-0047. 배포 관문은 하나다 — Center가 계약의 검사기를 부른다

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 |
| 날짜 | 2026-10-12 |
| 관련 | C2 §오류·V6, C5 §배포·§오류, [ADR-0013](0013-api-keys.md), [ADR-0016](0016-server-first.md), [ADR-0046](0046-no-wildcard-pc-deployment.md) |

## 배경

`POST /deployments`가 무엇을 받아들이나가 **두 곳에 적혀 있었다.**

1. 계약 `contracts.center_api.validate_deployment()` — C5 문서가 공개 API로 적어 두고
   (`docs/03-contracts/README.md`), `tests/test_center_api.py`가 규칙마다 시험한다.
   **그런데 제품 코드에서 아무도 부르지 않았다.**
2. Center `center/api/deployments.py`의 `create()` — 같은 검사를 **직접 다시** 적었다
   (서명·승인 상태·지원 종료·해시·대상 종류, ADR-0046의 PC `"*"`까지).

두 벌은 **이미 갈라져 있었다.**

- 대상이 어긋날 때 계약은 `target_mismatch`, Center는 409 `wrong_target`이었다. C5의 오류 표는
  **두 코드를 각각 다른 행**(422와 409)에 적어 두어 어긋남이 「적혀 있는데 뜻이 없는」 꼴이었다.
- 계약의 `server_runner_not_available`(M7 전 서버 배포)은 **Center에 없었다.** 문서는 두 곳
  (C5 §배포·상태 줄)에 422라고 적었는데, 실제로 막는 것은 작업 지시(`POST /jobs`)뿐이었다.
  `run_location=server` 패키지의 서버 배포는 **받아들여져 표에 남았다** — 내려 줄 서버 실행기가
  없는 배포를 운영자가 `GET /deployments`에서 보고 「돌 것」으로 읽는다.
- `run_location` → 대상 종류 표도 두 벌이었다 (계약 `TARGET_TYPE_FOR_RUN_LOCATION`,
  Center `TARGET_FOR`).

ADR-0046이 PC `"*"` 규칙을 **양쪽에 각각** 더하면서 이 중복이 드러났다. 한 규칙을 더할 때
두 곳을 고쳐야 하고, 코드가 둘이면 어느 것이 참인지 **문서만 보고는 알 수 없다**.

## 선택지

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. **Center가 `validate_deployment()`를 부른다** — 코드는 규칙마다 하나로 정하고 상태는 계약의 표가 준다 | 규칙 본문이 하나다. 계약이 원본이라는 결대로다 (CLAUDE.md §3). 문서의 표와 코드가 **같은 자리에서** 나온다. 공개 API가 쓰이는 함수가 된다 | 문서에 적힌 코드 하나(`target_mismatch`)가 배포 쪽에서 사라진다 — 이 ADR이 필요한 까닭 |
| B. 두 벌을 **그대로 두고** 「서로 같나」를 보는 시험을 더한다 | 가장 작다. 당장의 어긋남을 잡는다 | 중복을 **영구히 만든다.** 규칙을 더할 때 세 곳(계약·Center·시험)을 고친다. 시험이 말할 수 있는 것은 「같다」뿐이고 **어느 쪽이 참인지는 못 말한다** |
| C. `validate_deployment()`를 **지운다** — 아무도 안 부르니 | 죽은 코드가 사라진다 | C5·README가 공개 API로 적었고 시험이 규칙을 지키고 있다. 지우면 규칙이 **Center 안쪽에만** 남아 Admin이 서명 전에 볼 수 없다 (`chk-admin sign-extension`은 **서명 전에 E1·E3를 돌리는** 반대 선례다) |

## 결정

**A.** 규칙 본문은 `validate_deployment()` 하나이고 **Center가 그것을 부른다.**

- **코드는 규칙마다 하나다.** 대상이 틀린 것은 — `target.type` ↔ `run_location` 어긋남이든
  PC 배포의 `"*"`든 — **`wrong_target`**이다. C2 V6이 같은 조건에 쓰는 이름이고, 둘 다 받아
  두면 **모든 PC가 V6으로 거부할** 봉투라 운영자가 할 일도 하나다(대상을 제대로 적는다).
  `target_mismatch`는 **작업 지시 쪽 코드로만** 남는다 (「모르는 대상 종류」, 422) — 뜻이
  다른 두 규칙이 같은 이름을 쓰던 것도 함께 없어진다.
- **코드 → HTTP 상태는 계약의 `DEPLOYMENT_REFUSAL_STATUS` 한 표다.** 고르는 것은
  `deployment_refusal()`이고 **앞의 위반이 이긴다** — 서명·시간(C2 `V…`)은 403, 배포 규칙은
  409(상태 충돌), `server_runner_not_available`은 422(아직 없는 기능)다. 부르는 쪽이 상태를
  따로 고르면 문서의 표와 또 갈라지므로 `cancel_outcome()`처럼 계약이 쥔다.
- **Center도 서버 배포를 막는다** (422). M7 스위치는 `SERVER_RUNNER_AVAILABLE` **한 자리**이고
  배포와 작업 지시가 같은 값을 본다 — 두 곳에 적어 두면 한쪽만 켜져 「작업은 만들어지는데
  배포가 없다」가 된다.
- **Center에 남는 것은 저장소를 봐야 하는 것뿐이다**: 패키지가 있나(404), 같은
  `deployment_id`의 충돌·철회(409), 배포를 막는 리소스 누락과 C1 R8(422, C7). 계약이 「여기서
  하지 않는 것」으로 적어 둔 그 목록이다.
- `TARGET_FOR`(Center)는 지운다 — 표는 계약의 `TARGET_TYPE_FOR_RUN_LOCATION` 하나다.

**봉투는 패키지를 찾기 전에 본다.** `create()`는 `verify`·`verify_time`을 **먼저** 부른다 —
없는 패키지의 404로 봉투의 진위가 새지 않게 (서명되지 않은 요청이 「그 패키지가 있나」를
묻는 길이 되면 안 된다). `validate_deployment()`가 그 검사를 다시 하지만 **같은 계약 함수**라
답이 갈릴 수 없다. 순서를 당긴 것이고 규칙을 베낀 것이 아니다.

**B의 시험은 버리지 않고 함께 둔다.** `tests/test_m5_deploy.py`의
`test_center_refuses_exactly_what_the_contract_refuses`가 같은 봉투를 계약에게도 물어
`(상태, 코드)`가 **규칙마다** 같은지 본다 — 부르는 길이 하나라는 것을 시험이 지킨다(누가
다시 손으로 적으면 깨진다). `tests/test_center_api.py`는 **표가 규칙을 다 덮는지**까지 본다.

## 왜 코드 이름을 `wrong_target`으로 골랐나

`target_mismatch`가 아니라 `wrong_target`이다 — 「새 이름을 고른 것」이 아니라 **셋 가운데
둘이 이미 쓰던 이름**이기 때문이다.

1. C2 V6(실행하는 쪽이 「이 배포가 나에게 온 것인가」를 볼 때)의 코드가 `wrong_target`이다.
   같은 조건을 Center와 현장이 **다른 이름으로** 부를 까닭이 없다.
2. Center가 처음부터 그렇게 답했고 CON-03의 「⛔ 거부」 사유, C4 `deployment_results`,
   `tests/test_m5_deploy.py`가 모두 그 이름을 쓴다.
3. `target_mismatch`는 작업 지시에서 **다른 뜻**으로 살아 있다(모르는 대상 종류). 배포가 그
   이름을 쓰면 C5 오류 표의 「422는 모두 작업 지시 쪽이다」가 거짓이 된다.

## 함께 고친 것

- `docs/03-contracts/C5-packages-deployments-jobs.md` — 「배포할 때 Center가 검사하는 것」을
  **검사·코드·상태 표**로 바꾸고 `validate_deployment()`가 원본이라고 적는다. 오류 표에서
  배포 쪽 `target_mismatch`를 걷고 `server_runner_not_available`에 **배포도 포함된다**고 적는다.
- `docs/03-contracts/C2-signing-envelope.md` — 422 행에 남아 있던 `not_approved`·
  `hash_mismatch`·`target_mismatch`를 **409 `wrong_target`** 쪽으로 옮긴다. C5는 2026-10-09에
  409로 고쳤고 이 표만 낡아 있었다.
- `docs/09-gaps.md` §3-9 — 「대상이 존재한다」(C5 §배포)는 **어느 쪽도 보지 않는다**는 것을 적는다.
  이 ADR의 범위가 아니다(등록되지 않은 PC에 미리 배포해 두는 것이 뜻 있는 일인지 **먼저
  정해야 한다** — 작업 지시는 404로 막는다).

## 결과

- **쉬워지는 것:** 배포 규칙을 더하거나 바꿀 때 고치는 자리가 **계약 하나**다 (ADR-0046은 두
  곳을 고쳐야 했다). 문서의 오류 표가 코드의 표와 같은 자리에서 나온다. Admin·Studio가
  **서명·업로드 전에** 같은 함수로 미리 볼 수 있다 (`sign-extension`과 같은 결).
- **어려워지거나 포기하는 것:** 배포 쪽 `target_mismatch`가 사라진다 — 바깥 시스템이 그 코드를
  보고 있었다면 `wrong_target`으로 고쳐야 한다(schema는 올리지 않는다. 상태·사유는 열린
  문자열이고 C5 §호환 규칙이 「모르는 값은 그대로 보인다」다). 서버 배포를 미리 넣어 두고 M7을
  기다리는 길이 막힌다 — 그것이 애초에 문서가 적은 바다.
- **다시 볼 조건:** ① **M7에서 서버 실행기를 켤 때** — `SERVER_RUNNER_AVAILABLE`을 설정으로
  빼야 하나(그러면 계약이 설정을 읽게 된다 — 아마 부르는 쪽이 인자로 주는 쪽이 맞다).
  ② 배포 규칙이 **저장소를 봐야 하는 것**으로 늘면 — 계약이 상태를 보지 않는다는 선이 흔들린다.
  그때는 `validate_deployment()`에 「이미 읽어 온 사실」을 인자로 더하고(지금 `package`가 그렇다)
  읽는 것은 Center에 남긴다. ③ 봉투 위반의 상태가 C2의 400인지 Center의 403인지 — **이
  어긋남은 여기서 손대지 않았다**(배포만의 일이 아니라 모든 봉투 경로의 일이다).
