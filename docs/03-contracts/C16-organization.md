# C16. Center API: 조직·업무 자리

| 항목 | 값 |
| --- | --- |
| 상태 | **합의** (2026-11-01) — 모델·판정이 코드로 있다: `packages/contracts/organization.py`(조직·`Place`·`place_violation`·`PlaceIdentity`), 다른 계약의 칸(C5 `PackageInfo`·`JobInfo`·`BotUiInfo`·계정 `company`·역할 `company_admin`, 등록 승인 `company`, C3 `RunInfo`, C12 `JobDispatch.place`, C14 값 출처)과 Center 저장소 22판(기본 회사·조직 표·가상 직원 → 직원). 서버 실행기는 `JobDispatch.place`를 값 출처로 푼다. **쓰는 쪽은 아직이다** — Center API·관문·목록 거르기·콘솔은 조각 2~4([ADR-0125](../decisions/0125-organization-and-work-placement.md) 「다음 순서」). 그때까지 Center는 칸을 채우지 않는다. **가상 직원 기능은 조각 1에서 없앴다**(아래 「없어진 것」) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | 콘솔(Center 관리자·회사 관리자)·연동용 키 ↔ Center (조직·업무 자리), Center → 서버 실행기 (작업의 자리) |
| 코드 위치 | `packages/contracts/organization.py`, Center `migrations.py` 22판 · (예정) `api/organization.py`·`api/packages.py`·`enrollments.py`·`accounts.py` |
| 관련 ADR | [0125](../decisions/0125-organization-and-work-placement.md), [0090](../decisions/0090-center-admin-accounts.md), [0092](../decisions/0092-keys-are-issued-and-delivered-by-center.md), [0093](../decisions/0093-studio-is-let-in-by-approval.md), [0099](../decisions/0099-input-value-source.md) |
| 관련 화면 | CON-13 조직, CON-02·CON-06 승인(자리 고르기), CON-03 승인 대기(회사 고르기), CON-14 관리자 계정(회사 관리자), CON-01 (회사·부서·직원 열) |

## 목적

Center 안에 **회사 > 부서 > 직원** 조직을 두고, Studio·PC 실행기를 회사에 묶으며, 올라온 BPM 프로세스를 승인할 때 **회사·부서·직원 중 한 자리**에 놓는다. 이것이 없으면 「누가 무슨 업무를 하나」를 볼 자리가 없고, 여러 회사가 한 Center를 쓸 때 서로의 것이 섞인다.

## 전송

- 방식: HTTP `/api/v1/companies…`·`/departments…`·`/staff…`·`/packages/{id}/place` (C5와 같은 공통 규칙).
- 인증: 회사 만들기·바꾸기는 **Center 관리자**. 부서·직원·업무 자리는 **Center 관리자 또는 그 회사의 회사 관리자**. 읽기는 관리자 계정(회사가 있으면 제 회사만)·읽기 토큰·연동용 키(전부 — > 미정, ADR-0125 §2).
- 멱등성: `POST`는 같은 id가 있으면 409 `exists`. `PUT`은 본문 전체로 바꾼다.
- 남의 회사 것: **404**다(있다는 것조차 알리지 않는다).

## 모델

### CompanyRequest / CompanyInfo

| 필드 | 타입 | 필수 | 뜻 | 추가된 schema |
| --- | --- | --- | --- | --- |
| `id` | str | ✓ | `^[a-z0-9][a-z0-9._-]{0,63}$`, Center 전체에서 하나 | 1 |
| `name` | str | ✓ | 화면 이름 (1~100자) | 1 |
| `state` | str | | `active`(기본) / `stopped` (열린 문자열). 멈춘 회사는 새 작업·배포·승인을 받지 않는다 | 1 |

CompanyInfo는 `created_at`·`updated_at`과 셈(`departments`·`staff`·`processes`·`bot_uis`·`studios`)을 더한다 — 읽을 때 센다.

### DepartmentRequest / DepartmentInfo

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `id` | str | ✓ | id 규칙, Center 전체에서 하나 |
| `company` | str | ✓ | 회사 id. 회사 관리자는 제 회사만 적을 수 있다(아니면 404) |
| `name` | str | ✓ | |
| `state` | str | | `active` / `stopped` |

한 단계다 — 부서 안의 부서는 없다. DepartmentInfo는 `staff`(셈)·`processes`(이 부서 자리 업무 수)를 더한다.

### StaffRequest / StaffInfo

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `id` | str | ✓ | id 규칙. 주체 이름은 `staff:<id>`(예약 앞머리) |
| `company` | str | ✓ | |
| `department` | str | | 그 회사의 부서. 비우면 회사에 바로 속한다 (다른 회사의 부서면 422 `place_outside_company`) |
| `name` | str | ✓ | 아무 글 — 사람 이름이어도, 「구매 자동 처리」여도 |
| `state` | str | | `active` / `stopped` |

StaffInfo는 하나 읽기에서 `work[]`(이 직원 자리 업무 — `{bpm_process_id, versions[], triggers[]}`, `versions`는 살아 있는 배포의 판, `triggers`는 그 판 매니페스트의 C1 `triggers`)와 `recent_runs[]`(최근 20개 — `{run_id, bpm_process_id, status, started_at, requested_by}`)를 더한다. 부서·회사 상세도 같은 모양으로 그 자리 업무와 최근 실행을 준다.

- 지우지 않고 멈춘다. `DELETE`는 가리키는 것(직원·업무 자리·작업)이 없을 때만 되고, 있으면 409 `in_use`다.

### Place (업무 자리)

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `scope` | str | `company` / `department` / `staff` |
| `department` | str | `scope: department`일 때 |
| `staff` | str | `scope: staff`일 때 |

회사는 적지 않는다 — **패키지의 회사**다. 부서·직원이 그 회사 밖이면 422 `place_outside_company`.

| 메서드·경로 | 인증 | 뜻 |
| --- | --- | --- |
| `GET /packages/{id}/place` | 읽기 | 지금 자리 (`null` = 자리 없음 — 회사 공통으로 읽는다) |
| `PUT /packages/{id}/place` | Center 관리자 / 그 회사의 회사 관리자 | 자리 바꾸기. **서명하지 않는다** — 다음 작업부터 새 자리다. `process_lib`이면 422 `place_not_for_lib` |

### 다른 계약에 더하는 칸

| 계약 | 자리 | 칸 | 뜻 |
| --- | --- | --- | --- |
| C5 | 승인 (`PUT /packages/{id}/{version}/signature` — 지금은 본문 없음) | 본문 `{place?}` | **그 BPM 프로세스에 자리가 아직 없으면 필수**(422 `place_required`), 있으면 비워 둔다(적으면 바꾼다). `process_lib`에는 적지 않는다 |
| C5 | `PackageInfo` | `company`, `place?` | `company` = 올린 Studio의 회사 |
| C5 | 배포 | — | PC 대상의 회사 ≠ 패키지의 회사이면 422 `company_mismatch` (`validate_deployment`) |
| C5 | `JobInfo` | `company`, `department?`, `staff?` | **만들 때의 자리**를 작업 행에 적는다 |
| C5 | 작업 지시·C12 메시지 시작 | — | 자리의 회사·부서·직원이 멈췄으면 409 `owner_stopped` |
| C5 | 등록 승인 (`POST /enrollments/{id}/approve`, CON-03 「승인 대기」 — Studio·PC 실행기) | 본문 `{company}` | **필수**. 회사 관리자는 제 회사만 |
| C5 | `BotUiInfo`·Studio 키 | `company` | 서버 실행기에는 없다(Center 공용) |
| C5 | 관리자 계정 | `role` 값 `company_admin`, `company?` | `company_admin`은 회사 필수, `viewer`는 선택, `admin`은 없음 |
| C5·C3 | 모든 목록 (`/packages`·`/deployments`·`/jobs`·`/runs`·`/approvals`·`/bot-uis`·`/studios`·조직) | `?company=` | 회사가 있는 계정은 **늘 그 회사로 걸린다**(쿼리가 이기지 않는다) |
| C3 | `RunInfo` | `company`, `department?`, `staff?` | Center가 읽을 때 그 실행의 작업에서 붙인다. `run_started`에는 칸이 없다 |
| C12 | `JobDispatch` | `place?` = `{company: {id, name}, department?: {id, name}, staff?: {id, name}}` | 서버 작업을 내려줄 때 붙인다. 저장하지 않는다 |
| C14·C1 | `inputs[].source` | `company.id`·`company.name`·`department.id`·`department.name`·`staff.id`·`staff.name` (모두 `string`) | Center가 넣는 값 출처. 부르는 쪽은 줄 수 없다(`input_not_from_caller`). 그 자리에 없는 것은 `None` |

### 없어진 것 (조각 1)

C5 §가상 직원 전부(`/virtual-workers`, `VirtualWorkerRequest`·`VirtualWorkerInfo`, `intake_*` 코드, 배포 때 B16 관문), `JobCreateRequest.virtual_worker`·`JobInfo.virtual_worker`·`?virtual_worker=`, C12 `JobDispatch.virtual_worker`, 값 출처 `virtual_worker.*`, 예약 앞머리 `vw:`. C14 **B16은 경고로 남는다**(Studio 실행 전 검사). Center 저장소 22판이 가상 직원을 같은 id의 직원으로 옮기고 표·칸을 지운다.

## 예시

`GET /api/v1/staff/buyer-kim` 응답:

```json
{
  "id": "buyer-kim",
  "company": "company1",
  "department": "purchasing",
  "name": "김구매",
  "state": "active",
  "created_at": "2026-11-01T09:00:00+09:00",
  "updated_at": "2026-11-01T09:00:00+09:00",
  "work": [
    {"bpm_process_id": "buy.request", "versions": ["1.0.0"],
     "triggers": [{"kind": "timer", "schedule": "0 8 * * 1-5"}]}
  ],
  "recent_runs": [
    {"run_id": "run_20261101_080000_a1b2c3", "bpm_process_id": "buy.request", "status": "success",
     "started_at": "2026-11-01T08:00:00+09:00", "requested_by": "timer:0 8 * * 1-5"}
  ]
}
```

## 오류

| 상태 코드 | 코드 | 언제 | 보내는 쪽이 할 일 |
| --- | --- | --- | --- |
| 404 | `not_found` | 없거나 남의 회사 것 | |
| 409 | `exists` | 같은 id로 만들기 | |
| 409 | `in_use` | 가리키는 것이 있는 조직을 지우기 | 멈춘다 |
| 409 | `owner_stopped` | 멈춘 회사·부서·직원 자리 업무의 작업 | 다시 켠다 |
| 422 | `place_required` | 자리 없는 BPM 프로세스를 자리 없이 승인 | 자리를 고른다 |
| 422 | `place_outside_company` | 다른 회사의 부서·직원 | |
| 422 | `place_not_for_lib` | 공유 BPM 프로세스에 자리 | |
| 422 | `company_mismatch` | 다른 회사 PC로 배포 | 그 회사의 PC를 고른다 |

## 호환 규칙

- 받는 쪽이 모르는 필드·`scope` 값을 받으면: 남긴다(README 원칙). 모르는 `scope`로는 자리를 바꾸지 않는다(422 `input_invalid`).
- 옮기기(ADR-0125 §7): 회사 `default`를 만들고 지금의 장비·패키지를 거기 둔다. 가상 직원은 같은 id의 직원이 되고, 접수 BPM 프로세스의 자리는 그 직원이다. 다른 BPM 프로세스는 자리 없음으로 남는다(회사 공통으로 읽는다).
- 이전 schema의 `virtual_worker` 칸: 없앴다 — 옛 쪽이 보내면 모르는 칸으로 무시된다(원칙 3).

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-11-01 | 1 | 초안 → 합의 (모델·판정·저장소 22판) | [0125](../decisions/0125-organization-and-work-placement.md) |
