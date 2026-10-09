# Admin 화면 설계

Admin은 서명 키를 가지고 패키지 승인·배포·철회에 서명한다. 서명은 토큰이 새도 배포를 못 하게 하는 마지막 관문이라, 서버(콘솔)에서 하지 않고 관리자 PC에서 한다.

**첫 릴리스는 명령줄만** (프로토타입과 같음). 데스크톱 창은 로드맵 "나중에"에 있다. 아래는 명령 설계와, 나중에 창을 만들 때의 화면 초안이다.

## 명령 (첫 릴리스)

| 명령 (가안) | 하는 일 | 확인 문구 |
| --- | --- | --- |
| `chk-admin keys new` | 서명 키 생성 (암호문으로 보호, OS 사용자 폴더에 저장) | 키 id 출력 |
| `chk-admin keys register --signed-by <기존 키>` | 새 공개키를 **기존 Admin 키의 서명**으로 Center에 등록 (C2 `admin_key`) | 「<키 id>를 <기존 키 id>의 서명으로 추가합니다」 |
| (서버에서) `chk-center admin-keys bootstrap <public.pem>` | Admin 키가 하나도 없을 때만 첫 키를 넣는다. 서버 셸에서 실행 | |
| `chk-admin keys list` / `revoke <key_id>` | 목록 / 철회 (C2 `admin_key_revoke` 서명) | 철회는 「이 키로 서명한 승인·배포가 모두 무효가 됩니다. 계속할까요?」. 마지막 키는 철회할 수 없다 |
| `chk-admin pending` | 승인 대기(후보) 패키지 목록: id, 버전, 종류, 올린 이, 사전 점검 요약, 필요한 리소스 누락 | |
| `chk-admin approve <id> <버전>` | 패키지 승인 서명 → Center에 올림 | 해시·사전 점검 요약을 보이고 「승인할까요?」 |
| `chk-admin deploy <id> <버전> --bot-ui <Bot UI> [--from --until]` | PC 배포 서명 → Center에 올림 | 대상 Bot UI·유효 기간 확인 |
| `chk-admin deploy <id> <버전> --server [--max-concurrency 5] [--from --until]` | 서버 배포 서명 (실행 위치가 「서버」인 BPM 프로세스만, M7) | 동시 실행 상한·유효 기간 확인 |
| `chk-admin deployments [--bot-ui <이름>] [--bpm-process <id>]` | 활성 배포 목록 (배포 id, 대상, Bot, 버전, 유효 기간). CON-03 「배포」의 배포 id와 같다 | |
| `chk-admin revoke-deploy <배포 id>` | 배포 철회 서명 | |
| `chk-admin revoke-package <id> <버전>` | 패키지 승인 철회 서명 (C2 `package_revoke`) — 그 패키지의 배포가 모두 무효 | 「배포 N개가 무효가 됩니다」 |
| `chk-admin sign-extension <정의 파일> [--out]` | 외부 확장 정의 승인 서명 (C2 `extension`) → 봉투 파일. 운영자가 CON-07에 함께 올린다. **E1·E3을 먼저 로컬에서 돌려** 문제가 있으면 서명하지 않는다 | 해시·허용 호스트·사설망 허용·작업별 수행 모드를 보이고 「서명할까요?」 |
| `chk-admin revoke-extension <id> <버전> [--out]` | 외부 확장 승인 철회 서명 → 봉투 파일. 운영자가 CON-07 상세의 「등록 해제」에 올린다 | 「이 정의를 쓰는 Bot이 실행 불가가 됩니다. 계속할까요?」 |
| `chk-admin deprecate <id> <버전>` | 지원 종료 표시 (서명 없음, 새 배포만 막음). **묻고 기본은 「아니오」**다 — `-y`로 넘긴다 | **돈다** |
| `chk-admin job new <id> --bot-ui <Bot UI> [--version] [--input 이름=값] [--inputs <JSON>] [--until] [--note] [--idempotency-key]` | 작업 만들기 (콘솔 CON-05와 같은 일). **서명이 없다** — 이미 배포된 것을 돌릴 뿐이라 토큰 권한이 관문이다 (C5 권한표) | 대상 Bot UI·입력 개수·만료를 보이고 「작업을 보낼까요?」 |
| `chk-admin job list [--state] [--bot-ui] [--bpm-process]` / `show <작업 id>` | 작업 목록 / 하나 (실행 상태 포함) | |
| `chk-admin job cancel <작업 id>` | 작업 취소. **시작된 것은 멈추지 않는다** (C5) — 「취소를 요청했습니다」로 끝나면 현장의 답을 기다리는 중이다 | 「작업 <id>를 취소할까요?」 |

명령 이름 접두사 `chk-`는 환경변수 접두사(`CHK_`)와 맞춘 가안이다.

## 서버 쪽 명령 (서버 셸에서)

| 명령 (가안) | 하는 일 |
| --- | --- |
| `chk-center admin-keys bootstrap <public.pem>` | Admin 키가 하나도 없을 때만 첫 키를 넣는다 (C2) |
| `chk-runner keys set <참조 이름>` / `list` / `remove <참조 이름>` | 서버 실행기의 서비스 앱 키 값 (서버 Bot의 키 참조, ADR-0015). 값은 서버 OS 비밀 저장소. `list`는 앞자리만 |
| `chk-runner status` | 서버 실행기 상태·용량·실행 중·기다리는 실행 (CON-12와 같은 내용) |

## 창 초안 (나중)

| ID | 화면 | 내용 |
| --- | --- | --- |
| ADM-01 | 키 관리 | 키 목록(id, 만든 날, 등록 여부, 철회 여부), 「새 키」, 「Center에 등록」, 「철회」 |
| ADM-02 | 승인 대기 | CON-02·CON-06과 같은 열 + 사전 점검·리소스 누락. 「승인 서명」 |
| ADM-03 | 배포 | Bot UI 고르기(CON-03 정보), 패키지·버전, 유효 기간 → 「배포 서명」. 활성 배포 목록 + 「철회 서명」 |
