# C16. Center API: 직원·요청

| 항목 | 값 |
| --- | --- |
| 상태 | **초안** (2026-11-01) — 글이 먼저 있다. 코드는 아직 가상 직원(C5 §가상 직원)이다. 구현하면 아래 「고칠 자리」가 각 계약으로 옮겨 가고 C5 §가상 직원이 없어진다 |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | 콘솔·연동용 키 ↔ Center (직원), 서버 실행기 → Center (요청 = 위임), Center → 서버 실행기 (작업의 직원) |
| 코드 위치 | (예정) `packages/contracts/staff.py`, Center `api/staff.py`·`api/delegations.py`·`api/timers.py` |
| 관련 ADR | [0125](../decisions/0125-staff-own-work-and-request-each-other.md), [0062](../decisions/0062-pc-delegation.md), [0080](../decisions/0080-approval-assignees.md), [0082](../decisions/0082-batch-start.md), [0099](../decisions/0099-input-value-source.md), [0110](../decisions/0110-center-keeps-the-schedule.md) |
| 관련 화면 | CON-13 직원, CON-01 (「직원」 열) |

## 목적

업무의 주체(**직원**)와 그 업무(BPM 프로세스)를 Center에 묶고, 직원이 같은 회사 직원의 업무를 **요청**(기다리기·맡기고 끝)할 수 있게 한다. 이것이 없으면 「누가 무슨 업무를 하나」를 볼 자리가 없고, 다른 주체의 업무를 부를 길이 패키지 id뿐이다.

## 전송

- 방식: HTTP `/api/v1/staff…`(C5와 같은 공통 규칙), 위임 요청 `POST /api/v1/server-runner/delegations`(C12)에 칸 둘, 작업·메시지(C5·C12)에 칸 하나.
- 인증: 직원 쓰기는 **관리자**(콘솔 세션·관리자 토큰). 읽기는 읽기·관리자 토큰·**연동용 키**(전부). 대리 답용 키·실행기 키는 읽지 못한다.
- 멱등성: `POST /staff`는 같은 id가 있으면 409 `staff_exists`. `PUT`은 본문 전체로 바꾼다. 위임은 지금 키 그대로(C12).
- 크기 한도: 한 직원의 `work[]`는 200개까지.

## 모델

### StaffRequest

| 필드 | 타입 | 필수 | 뜻 | 추가된 schema |
| --- | --- | --- | --- | --- |
| `id` | str | ✓ | `^[a-z0-9][a-z0-9._-]{0,63}$`. 주체 이름은 `staff:<id>`(예약 앞머리) | 1 |
| `name` | str | ✓ | 화면 이름 (1~100자, 아무 글) | 1 |
| `company` | str | ✓ | 회사 id — id와 같은 규칙. 회사 자원은 없고 같은 글자가 같은 회사다 | 1 |
| `state` | str | | `active`(기본) / `stopped` (열린 문자열). 멈추면 그 직원 앞으로 **새 작업이 생기지 않는다** | 1 |
| `work` | str[] | | 업무 = BPM 프로세스 id(패키지 id, `kind=bpm_process`). 판은 적지 않는다. 겹치는 것은 하나로. 없는 패키지는 422 `work_unknown` | 1 |

### StaffInfo

StaffRequest에 다음을 더한다. `recent_runs`·`requests`·`open_approvals`는 **하나 읽기에서만** 차고 목록에서는 빈 배열이다. 모두 읽을 때 센다(저장하지 않는다).

| 필드 | 뜻 |
| --- | --- |
| `created_at`, `updated_at` | |
| `work_detail[]` | 업무마다 `{bpm_process_id, versions[], triggers[]}` — `versions`는 지금 살아 있는 배포의 판, `triggers`는 그 판 매니페스트의 C1 `triggers`(`kind`·`schedule`/`message`)를 옮긴 것이고, 이 업무를 **부를 수 있는 업무가 있으면**(Center의 어떤 매니페스트 `requires.delegations`에 있으면) `{kind: "request"}`를 더한다 |
| `recent_runs[]` | 이 직원 작업의 최근 실행 20개 — `{run_id, bpm_process_id, status, started_at, requested_by}` (`status`는 C3 `RunInfo.status`) |
| `requests[]` | 최근 요청 40개 — `{direction: "received"\|"sent", job_id, other_staff?, bpm_process_id, mode, state, run_id?, requested_at}`. 받은 것은 `staff`가 이 직원이고 `requested_by = server_bot:`인 작업, 보낸 것은 이 직원 실행이 맡긴 작업이다 |
| `open_approvals[]` | 이 직원 실행의 열린 결재 — `{request_id, title, assignees, expires_at?}` (C6. 값은 싣지 않는다) |

### 다른 계약에 더하는 칸

| 계약 | 자리 | 칸 | 뜻 |
| --- | --- | --- | --- |
| C5 | `JobCreateRequest` | `staff?` | 누구의 일인가. 그 직원이 이 업무를 가져야 한다(422 `staff_mismatch`), 활성이어야 한다(409 `staff_stopped`). 비우면 그 업무를 가진 활성 직원이 정확히 하나일 때 그 직원, 아니면 없음 |
| C5 | `JobInfo` | `staff?` | 고른 id (작업 행에 남는다). 위임으로 만든 작업은 받는 직원 — 받는 직원이 없으면 맡긴 쪽 직원을 이어받는다 |
| C5 | `GET /jobs`·C3 `GET /runs` | `?staff=` | 그 직원의 작업·실행 |
| C3 | `RunInfo` | `staff?` | Center가 읽을 때 그 실행의 작업에서 붙인다. `run_started`에는 칸이 없다 |
| C12 | `MessageRequest` (메시지 시작) | `staff?` | 작업과 같은 규칙 |
| C12 | 위임 요청 | `staff?`, `mode?` | 아래 §요청 |
| C12 | `JobDispatch` | `staff?` = `{id, name, company}` | 서버 작업을 내려줄 때 붙인다. 저장하지 않는다 |
| C14 | `chk:call.delegate` | `staff?`(식), `mode?` | 아래 §요청. `mode: handoff`이면 `chk:call.output`이 비어야 한다 (B14 오류) |
| C14·C1 | `inputs[].source` | `staff.id` (`string`)·`staff.name` (`string`)·`staff.company` (`string`) | Center가 넣는 값 출처. 부르는 쪽은 줄 수 없다(`input_not_from_caller`) |

### 없어지는 것

C5 §가상 직원 전부(`/virtual-workers`, `VirtualWorkerRequest`·`VirtualWorkerInfo`, `intake_*` 코드, 배포 때 B16 관문), C5 `JobCreateRequest.virtual_worker`·`JobInfo.virtual_worker`·`?virtual_worker=`, C12 `JobDispatch.virtual_worker`, C14·C1 값 출처 `virtual_worker.id`·`.name`·`.supervisors`, 예약 앞머리 `vw:`. C14 **B16은 경고로 남는다**(Studio 실행 전 검사).

## 요청 (위임을 넓힌다)

C14 그림:

```json
{"delegate": {"bpm_process_id": "buy.request", "staff": "구매담당", "mode": "handoff"},
 "input": {"품목": "품목", "요청자": "내직원ID"}}
```

C12 위임 요청에 더하는 칸:

| 필드 | 뜻 |
| --- | --- |
| `staff?` | 받는 직원 id — 실행기가 그림의 `staff` 식을 값으로 풀어 보낸다. 비우면 Center가 고른다 |
| `mode?` | `wait`(기본) / `handoff` |

**관문** (Center가 위임 요청을 받을 때, 지금 검사 — 배포·`requires.delegations` 승인 — 다음에):

R = 요청한 실행의 직원(그 실행 작업의 `staff`, 없을 수 있다), T = 받는 직원.

| 경우 | 결과 |
| --- | --- |
| `staff`를 적었고 그 직원이 없거나 그 업무를 갖지 않았다 | 422 `staff_mismatch` |
| T가 멈췄다 | 409 `staff_stopped` |
| R이 없거나 R.company ≠ T.company | 403 `company_mismatch` |
| `staff`를 비웠다 — 그 업무를 가진 활성 직원 중 R과 같은 회사인 것이 하나 | 그 직원 |
| 〃 — 둘 이상 | 422 `staff_ambiguous` |
| 〃 — 하나도 없고, 그 업무를 아무 직원도 갖지 않았다 | 직원 없이 지금 위임 그대로 (작업의 `staff`는 R을 이어받는다) |
| 〃 — 하나도 없고, 다른 회사 직원만 가졌다 | 403 `company_mismatch` |

실행기는 어느 거절이든 지금 위임 거부와 같이 **업무 실패**(`DELEGATION_FAILED`)로 올린다.

**`mode: handoff`**

- 응답(`{job_id, …}`)을 받으면 그 노드는 끝난다 — `waiting[]`에 올라가지 않고 스냅샷에 위임 기다림이 없다.
- Center는 handoff 작업의 결과 `outputs`를 담지 않고 `delegations[]`로 내려보내지 않는다(위임 표에 `mode`를 적어 가른다).
- 요청한 실행이 취소돼도 `…/delegations/{job_id}/cancel`을 부르지 않는다.
- 멱등 키·`requested_by`·`parent_run_id`는 `wait`와 같다.

## 일정 (C5 §일정에 더한다)

타이머 시작이 있는 업무를 **활성 직원이 가지면** 차례마다 **직원마다** 작업 하나(`staff`가 찬)를 만든다 — 서버는 (BPM 프로세스, 판, 직원), PC는 (배포된 PC, 직원)마다. 아무 직원도 갖지 않으면 지금 그대로 직원 없이 한 번, 가진 직원이 모두 멈췄으면 만들지 않는다. 차례를 잡는 기본 키와 멱등 키에 직원 id가 들어간다(직원 없음은 빈 글).

## 예시

`GET /api/v1/staff/buyer-kim` 응답:

```json
{
  "id": "buyer-kim",
  "name": "김구매",
  "company": "company1",
  "state": "active",
  "work": ["buy.request"],
  "created_at": "2026-11-01T09:00:00+09:00",
  "updated_at": "2026-11-01T09:00:00+09:00",
  "work_detail": [
    {"bpm_process_id": "buy.request", "versions": ["1.0.0"], "triggers": [{"kind": "request"}]}
  ],
  "recent_runs": [
    {"run_id": "run_20261101_100000_a1b2c3", "bpm_process_id": "buy.request", "status": "success",
     "started_at": "2026-11-01T10:00:00+09:00", "requested_by": "server_bot:run_20261101_095900_d4e5f6"}
  ],
  "requests": [
    {"direction": "received", "job_id": "job_1a2b3c4d", "other_staff": "fin-lee", "bpm_process_id": "buy.request",
     "mode": "handoff", "state": "finished", "run_id": "run_20261101_100000_a1b2c3",
     "requested_at": "2026-11-01T09:59:58+09:00"}
  ],
  "open_approvals": []
}
```

## 오류

| 상태 코드 | 코드 | 언제 | 보내는 쪽이 할 일 |
| --- | --- | --- | --- |
| 403 | `company_mismatch` | 요청한 직원과 받는 직원의 회사가 다르다(또는 요청한 실행에 직원이 없다) | 그림의 받는 직원·업무 묶음을 고친다 |
| 404 | `staff_not_found` | 없는 직원 읽기·바꾸기 | |
| 409 | `staff_exists` | 같은 id로 등록 | |
| 409 | `staff_stopped` | 멈춘 직원 앞으로 작업·요청 | 그 직원을 다시 켠다 |
| 422 | `staff_mismatch` | 그 직원이 그 업무를 갖지 않았다(없는 id도) | |
| 422 | `staff_ambiguous` | 받는 직원을 비웠는데 고를 수 있는 직원이 둘 이상 | 그림의 `staff` 식으로 고른다 |
| 422 | `work_unknown` | `work[]`에 Center에 없는 BPM 프로세스 | 패키지를 먼저 올린다 |

## 호환 규칙

- 받는 쪽이 모르는 필드를 받으면: 남긴다(README 원칙). `mode`의 모르는 값은 위임 요청 422 `input_invalid`다 — 기다릴지를 짐작하지 않는다.
- 이전 schema를 보내는 쪽(가상 직원 칸 `virtual_worker`)은: 구현하는 판에서 없앤다(ADR-0125 §6 — 옛 이름을 함께 읽지 않는다).

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-11-01 | 1 | 초안 | [0125](../decisions/0125-staff-own-work-and-request-each-other.md) |
