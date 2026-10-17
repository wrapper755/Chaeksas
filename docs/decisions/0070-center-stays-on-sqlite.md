# ADR-0070. Center 저장소는 SQLite로 남는다 — PostgreSQL은 길만 열어 두고, 옮길 때를 적어 둔다

| 항목 | 값 |
| --- | --- |
| 상태 | 제안 |
| 날짜 | 2026-10-17 |
| 관련 | [ADR-0065](0065-center-schema-migrations.md)(옮기기 수단 — §4 「PostgreSQL은 막지 않는다, 옮길지는 아직이다」를 여기서 정한다), [ADR-0066](0066-migration-guards.md)(지킴 질의), [ADR-0040](0040-registry-storage-sqlite.md)(UI 자동화 앱 SQLite), [ADR-0054](0054-server-run-state-and-concurrency.md)(서버 실행기 저장소), 로드맵 M8-B, `docs/01-architecture.md` §7(「SQLite로 시작, PostgreSQL 호환」) |

> 초안이다. 아래 「결정」은 **추천**이고, 정할 것 셋(가~다)마다 고른 까닭과 버린 길을 적었다.

## 배경

01-architecture §7은 Center DB를 「SQLite로 시작, PostgreSQL 호환」이라고 적었고, ADR-0065는 옮기기
수단을 세우며 **전환 여부를 따로 정한다**고 미뤄 두었다. 로드맵 M8-B에 남은 것이 이 결정 하나다.

지금 모습 (main `c60d5be`):

- `sqlite3`(표준 라이브러리)만 쓴다. **SQLite를 아는 파일은 다섯**이다 — `storage.py`(연결·WAL·
  기준선)·`migrations.py`(`BEGIN IMMEDIATE`)·`repair.py`·`__main__.py`(`chk-center hosts`)·`settings.py`.
  **API 모듈은 `sqlite3`를 import하지 않는다** — 모두 `Store.tx()`·`rows()`·`row()`를 거친다.
- SQL은 이식할 수 있는 모양으로 적어 왔다 — `ON CONFLICT … DO UPDATE/NOTHING`(둘 다 받는다)이 세 곳,
  SQLite 전용 함수(`GROUP_CONCAT`·`INSERT OR`·`AUTOINCREMENT`·`rowid`·`datetime()`)는 **없다**. 다른 것은
  자리표시(`?` ↔ `%s` — `?`가 든 줄이 203곳)·`PRAGMA` 셋·`BEGIN IMMEDIATE`·JSON 칸(`TEXT`에 넣고 파이썬이 읽는다)이다.
- 표 18개, 연결 **하나**를 스레드가 함께 쓴다. **Center는 하나만 뜬다** (`deploy/compose.yaml`). 패키지
  zip은 DB가 아니라 **디스크**(`package_dir`)에 있다.
- 쓰는 양은 하트비트(PC마다 30초에 한 번)·실행 기록 배치·결재다. 현장 PC 수십 대면 초당 몇 건이다.

## 선택지

### 가. 지금 PostgreSQL로 옮기는가

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. **SQLite로 남는다** — PostgreSQL은 길만 열어 두고, 옮길 조건을 적는다 | 바뀌는 것이 없다. `compose up` 한 번에 서버가 서는 것(M2 완료 기준)이 그대로다. 의존이 늘지 않는다 | 「여러 대의 Center」·DB 쪽 백업 도구는 쓸 수 없다. 옮길 때가 오면 그때 일이 몰린다 |
| B. PostgreSQL로 옮긴다 (SQLite를 버린다) | 쓰기 동시성·온라인 백업·복제를 DB가 준다. 회사 DBA가 아는 도구다 | 서버 구성에 DB 컨테이너·비밀·백업이 하나 더 는다. Center 시험이 모두 PostgreSQL을 띄워야 한다(지금은 메모리·임시 파일 SQLite라 따로 세울 것이 없다). **지금 겪는 문제가 없다** |
| C. 둘 다 받는다 (설정으로 고른다) | 작은 곳은 SQLite, 큰 곳은 PostgreSQL | 시험·CI가 두 벌이다(Windows CI가 이미 7~9분). 한쪽에서만 깨지는 흠이 생긴다. 쓰는 곳이 하나뿐인데 두 길을 지킨다 |

### 나. 옮기기 수단(ADR-0065)이 둘을 함께 받는가

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. **받을 수 있게 쓴다 — 돌리지는 않는다.** SQL은 이식할 모양으로만 적고, 그것을 **시험이 지킨다** | 옮길 때 SQL을 다시 쓰지 않는다. 지금 드는 값은 시험 하나다 | 진짜 PostgreSQL에서 돌려 보지 않았으니 「옮겨진다」는 어림이다 |
| B. 지금 PostgreSQL에서도 단계를 돌려 본다 (CI에 서비스 하나) | 어림이 아니다 | 가-B·C의 값을 반쯤 미리 낸다 |
| C. 지키지 않는다 — 옮길 때 고친다 | 할 일이 없다 | SQLite 전용 문법이 조용히 쌓인다(지금은 사람이 주석으로 막고 있다 — `migrations.py`의 `GROUP_CONCAT` 주석) |

### 다. Center 밖의 SQLite 둘

서버 실행기 `state.sqlite3`(기다리는 실행의 스냅샷, ADR-0054)·UI 자동화 앱 레지스트리(ADR-0040).

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. **그대로 SQLite다 — 이 결정 밖이다** | 둘 다 **그 프로세스 하나의 것**이다. 서버 실행기는 실행기마다 제 상태를 들고(나눠 쓰지 않는다), 레지스트리는 앱 하나가 쓴다 | Center를 옮겨도 서버에 SQLite 파일이 남는다(백업 대상이 셋) |
| B. Center와 함께 옮긴다 | 서버 DB가 하나다 | 서버 실행기가 Center DB에 닿으면 C12 경계를 넘는다(실행기는 HTTP로만 Center를 안다). 레지스트리는 다른 앱이다 |

## 결정

**가-A · 나-A · 다-A를 추천한다.** Center는 SQLite로 남고, PostgreSQL로 옮길 길은 **시험으로 지켜**
열어 둔다. 옮길 때는 아래 「옮길 조건」 가운데 하나가 실제로 생겼을 때다.

### 1. 옮길 조건 — 이것이 생기면 옮긴다

- **Center를 둘 이상 띄워야 한다**(고가용성). 이때는 DB만으로 안 된다 — **패키지 zip이 디스크에 있다.**
  공유 파일 저장소(또는 DB·객체 저장소로 옮기기)를 함께 정해야 하므로 그 결정과 한 덩이다.
- **쓰기 잠금 기다림이 실제로 보인다** — `database is locked`·하트비트 응답 지연. 연결 하나·WAL로
  초당 수백 건까지는 SQLite가 버틴다고 보고 있고, 수가 아니라 **관측**으로 정한다.
- **회사가 DB를 요구한다** — 백업·감사·접근 통제를 DBA 도구로 해야 할 때.

옮길 때는 **가-B(버린다)**로 간다 — C(둘 다)는 쓰는 곳이 하나인 동안 값을 두 번 낸다.

### 2. 이식성은 시험이 지킨다

> 제안: `tests/test_center_sql_portable.py` — Center 패키지의 SQL 글(파이썬 문자열)에서 SQLite에만 있는
> 것을 찾아 막는다: `INSERT OR`·`REPLACE INTO`·`AUTOINCREMENT`·`rowid`·`GROUP_CONCAT`·`datetime(`·
> `julianday`·`strftime`·`IIF(`. **허용하는 자리는 `storage.py`·`migrations.py`·`repair.py`·`__main__.py`
> 넷**이다(연결·`PRAGMA`·`BEGIN IMMEDIATE`가 사는 곳). 그리고 **API 모듈이 `sqlite3`를 import하지 않는
> 것**도 본다 — 지금 그런 것을 굳힌다.

옮길 때 바뀌는 자리는 그래서 **넷과 자리표시**로 줄어든다: 연결(`psycopg`)·`BEGIN IMMEDIATE` →
`BEGIN` + `LOCK TABLE schema_migrations`·`_use_wal` 없애기, 그리고
`?` → `%s`(`Store`가 한 자리에서 바꿀 수 있다). 판 표·단계·지킴 질의(ADR-0065·0066)는 **그대로** 간다.

### 3. SQLite로 남는 동안 운영에 적을 것

> 제안: `docs/04-setup.md`에 **백업**을 적는다 — WAL에서는 파일 복사가 안전하지 않다(`-wal`에 커밋이
> 남아 있다). `sqlite3 center.sqlite3 ".backup <파일>"`(돌던 중에도 된다)과 패키지 폴더를 함께 백업한다.
> 판 번호가 같은 Center로만 되살린다(DB 판이 높으면 뜨지 않는다, ADR-0065 §2).

### 4. Center 밖의 둘은 그대로다

서버 실행기·UI 자동화 앱의 SQLite는 그 프로세스의 것이고 이 결정이 건드리지 않는다. 옮기기 수단
(ADR-0065)도 아직 그 둘 밖이다 — 빚이 생기면 그때 **공유 자리를 정한다**(ADR-0065 「다시 볼 조건」).

## 결과

- 쉬워지는 것: 서버 구성이 그대로 `compose up` 한 번이다. 시험이 빠르다. 옮길 때 고칠 자리가 미리
  좁혀져 있다(넷과 자리표시).
- 어려워지거나 포기하는 것: 여러 대의 Center는 아직 없다. 백업은 운영자가 `.backup`으로 한다.
  「PostgreSQL에서 돈다」는 진짜로 돌려 본 것이 아니라 시험이 지키는 어림이다.
- 다시 볼 조건: 위 「옮길 조건」 셋. 그리고 **실행 기록(`run_events`)에 보관 기한이 없다** — 표가 끝없이
  커진다. 크기가 문제가 되면 먼저 보관 기한을 정하고(계약 C3·C5의 일이다), 그래도 모자라면 옮긴다 —
  크기만으로 DB를 바꾸지 않는다.
