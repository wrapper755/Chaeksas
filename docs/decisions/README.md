# 결정 기록 (ADR)

결정 하나당 파일 하나. 형식은 [template.md](template.md).

- 번호는 순서대로 붙이고 재사용하지 않는다.
- 수락된 ADR은 고치지 않는다. 뒤집을 때는 새 ADR을 쓰고 옛 것의 상태를 `대체됨(ADR-XXXX)`으로 바꾼다.
- 스파이크가 끝나면 결론이 "안 된다"여도 ADR을 쓴다.
- "제안" 상태를 "수락"으로 바꿀 때는 이 표와 해당 파일의 상태 칸을 함께 고친다.

| # | 결정 | 상태 |
| --- | --- | --- |
| [0001](0001-new-repo-prototypes-as-reference.md) | 새 저장소로 다시 만들고 프로토타입 4개는 참고용으로 동결한다 | 수락 |
| [0002](0002-docs-first-and-adr.md) | 문서를 먼저 쓰고, 문서는 저장소 안 Markdown으로 둔다 | 수락 |
| [0003](0003-target-platforms.md) | 서버는 Linux 주, 클라이언트는 Windows 주 | 수락 |
| [0004](0004-monorepo-uv-workspace.md) | 저장소 하나, uv 워크스페이스 | 수락 |
| [0005](0005-python-version.md) | Python 3.12로 통일 | 수락 |
| [0006](0006-single-contracts-package.md) | 계약은 패키지 하나, 스키마 버전 정수 | 수락 |
| [0007](0007-client-initiated-communication.md) | 통신은 항상 현장 PC → 서버 | 수락 |
| [0008](0008-map-driver-hands-boundary.md) | 역할 경계: BPMN = 지도, AI = 운전사, 실행, 손 | 수락 · 역할 이름 일부 대체됨(0012) |
| [0009](0009-worker-deployment-form.md) | Worker는 미리 떠 있는 트레이 앱 | 대체됨(0012) |
| [0010](0010-service-apps.md) | 서버 앱은 "서비스 앱"으로 통일 (자율/결정 수행 모드) | 수락 · 인증 부분 대체됨(0013) |
| [0011](0011-config-ports-env.md) | 포트는 기본값 + 설정 변경, 환경변수 접두사는 CHK_ | 수락 |
| [0012](0012-bot-ui.md) | 현장 PC의 프로그램은 Bot UI 하나: Bot(BPM 프로세스) 실행, Worker 실행 관리, UI 셀렉터 등록 | 수락 · 실행기 동시 실행 제안은 대체됨(0014) · ③ 셀렉터 등록은 Tool UI로(0077) |
| [0013](0013-api-keys.md) | Center 키는 Bot UI에 등록, 서비스 앱 키는 각 앱 관리 콘솔 발급, BPM 프로세스 단위 키 참조 | 수락 (키 지정 위치 안 C 확정) |
| [0014](0014-one-bot-per-pc.md) | PC 한 대에서 실행 중인 Bot은 하나, 나머지는 Bot UI 대기열, 결재 대기 중에도 끝까지 | 수락 (결재 대기 중에도 끝까지 자리를 쥔다) |
| [0015](0015-run-location.md) | BPM 프로세스의 실행 위치: PC(Bot UI, 하나씩) 또는 서버(Center 관리 서버 실행기, 동시 실행) | 수락 · 기본값은 대체됨(0016) |
| [0016](0016-server-first.md) | 서버 우선: 업무 대부분은 서버 BPM 프로세스(기본값 서버), PC Bot은 사람·화면이 필요할 때만. 서버 Bot 이름·상한 10/5·M7 확정 | 수락 (PC 위임은 제안) |
| [0017](0017-web-nextjs-design-system.md) | 웹 화면은 Next.js(BFF), 모든 화면은 디자인 토큰 하나(`design/tokens.json`)와 스타일 가이드를 따른다. Streamlit 폐기 | 수락 (버전은 M1에서 고정) |
| [0018](0018-extensions.md) | 확장(Extension): BPM 프로세스의 공통 기능은 확장으로 붙인다. 내장·사내·외부 등급, 기여 지점, 외부 앱은 HTTP 어댑터, UI 자동화는 첫 내장 확장 | 수락 (사내 확장 코드 배포·어댑터 세부는 제안) · `bot_ui.utilities`는 대체됨(0077) |
| [0019](0019-package-names.md) | 패키지 이름은 `chaeksas.*` PEP 420 네임스페이스, 폴더 이름은 문서 그대로. 확장은 `chaeksas.ext.<id>` | 수락 |
| [0020](0020-windows-desktop-backend.md) | Windows 데스크톱 조작은 `uiautomation` 라이브러리로 한다 (S1) | 수락 |
| [0021](0021-worker-dpi-capture.md) | Worker 프로세스는 시작하자마자 Per-Monitor v2 DPI 인식을 선언하고, 캡처는 `mss`로 한다 (S2) | 수락 (다중 모니터 미확인) |
| [0022](0022-studio-canvas.md) | Studio 캔버스는 QtWebEngine 안의 bpmn-js 배포본, Python과는 QWebChannel로 잇는다 (S3) | 수락 |
| [0023](0023-bot-ui-process-supervision.md) | Bot 실행은 Bot UI의 자식 프로세스(실행기)로 확정, 자식마다 Job Object, 자동 시작은 작업 스케줄러 (S4) | 수락 (Linux 미확인) |
| [0024](0024-desktop-packaging-extensions.md) | Studio·Bot UI는 PyInstaller onedir, 확장 옵션은 엔트리 포인트에서 계산, 로컬 런타임은 같은 실행 파일로 (S5) | 수락 (설치 프로그램 미정) |
| [0025](0025-expression-language.md) | 식 `chk-expr`는 직접 만든 AST 검사기로 돌리고, 템플릿은 `{변수}`만 둔다 (S6) | 수락 |
| [0026](0026-file-paths-and-file-list-task.md) | 파일은 실행 폴더(출력·읽기 허용)로 묶고, 파일 목록은 식이 아니라 태스크로 둔다 | 수락 |
| [0027](0027-llm-connection.md) | AI 태스크는 OpenAI 호환 HTTP를 **우리 루프로** 직접 부른다 (S7) | 수락 |
| [0028](0028-replay-memory.md) | 재생 명세는 패키지 안에 넣고, 도구 인자는 `{변수}` 템플릿으로 적는다 | 수락 |
| [0029](0029-bpmn-js-vendoring.md) | bpmn-js 배포본은 `web/`에서 버전을 고정해 복사하고, 복사본을 커밋한다 (ADR-0022의 미정 해소) | 수락 |
| [0030](0030-ai-task-tools.md) | AI 태스크의 도구는 `core`가 가진 내장 넷으로 시작하고, PDF는 `pypdf`를 쓴다 (S8) | 수락 |
| [0031](0031-runner-control-file.md) | Bot UI와 실행기는 파일 한 벌로 주고받는다 — 올라오는 것은 실행 기록, 내려가는 것은 제어 파일 (ADR-0023의 stdin을 바꿈) | 수락 |
| [0032](0032-writable-dirs.md) | 쓰기 허용 폴더를 둔다 (출력 폴더 밖에 쓰는 유일한 길) | 수락 |
| [0033](0033-desktop-app-and-window.md) | 데스크톱 화면은 앱 이름과 창 조건으로 찾고, Worker는 계획을 먼저 받아 백엔드를 고른다 | 제안 |
| [0034](0034-service-app-model-connection.md) | 서비스 앱의 모델 연결 — 모델 클라이언트를 맨 아래 패키지(`chaeksas.llm`)로 내리고, 주소·키는 서비스 앱 설정이 갖는다 | 수락 |
| [0035](0035-ui-goal-planning.md) | UI 태스크의 목표로 계획 — 모델은 값의 이름만 보고, 앱이 계획을 거르고, 수행기가 값을 채운다 | 수락 |
| [0036](0036-screen-read-values.md) | 화면에서 읽은 값의 모양 — 표는 머리글을 열쇠로 하는 줄 목록, 수 모양 글은 수 | 수락 |
| [0037](0037-desktop-ai-task-environment.md) | 데스크톱 AI 태스크의 눈과 손 — 확장이 「AI 환경」을 기여하고, 도구는 Worker 세션 위에서 돈다 | 수락 |
| [0038](0038-approval-request-channel.md) | 결재 요청은 요청 파일로 올라오고 Bot UI가 Center로 올린다 (ADR-0031의 「올라오는 길은 하나」에 예외) | 수락 · 현장 결재도 본문을 쓴다(0078) |
| [0039](0039-optional-variables-and-b11.md) | 한 가지에서만 생기는 값은 공통 경로에서 초기값을 두고, B11은 경고로 남긴다 (거짓 양성을 줄인다) | 수락 |
| [0040](0040-registry-storage-sqlite.md) | UI 자동화 레지스트리는 SQLite 한 파일에 둔다 (그래프 저장소를 두지 않는다 — 문서에 남아 있던 Neo4j 전제를 걷었다) | 수락 |
| [0041](0041-extension-run-events.md) | 확장은 `TaskOutcome.events[]`로 실행 기록에 남기고, 줄을 쓰는 것은 엔진이다 (원칙 6을 거르는 자리를 하나로) | 수락 |
| [0042](0042-extension-contributed-panels.md) | 확장이 플랫폼 화면에 칸을 기여한다 — 데스크톱은 위젯(`bot_ui.panels`), 웹 콘솔은 화면(`console.pages`), 선언으로 되는 자리는 선언만 | 수락 |
| [0043](0043-turned-off-extensions.md) | 사람이 끈 확장은 앱마다 제 설정에 두고(Studio ↔ Bot UI 따로) 「흠이 있다」와 다르게 적는다 — 꺼지면 기여를 하나도 내지 않는다 | 수락 |
| [0044](0044-canvas-drag-and-drop.md) | 캔버스 드롭은 내부 렌더 위젯에서 가로채고, 자리만 캔버스에 넘긴다 (만드는 길은 「캔버스에 추가」와 하나다) | 수락 |
| [0045](0045-contributed-resource-children.md) | 기여 자원의 둘째 단계를 선언으로 걷지 않는다 — 요소는 그 확장의 편집기에 둔다 (C13에 자식 선언을 더하지 않는다) | 수락 |
| [0046](0046-no-wildcard-pc-deployment.md) | PC 배포에 전체(`*`) 대상을 두지 않는다 — 봉투 하나는 PC 하나를 가리킨다 (`*`는 서버 실행기만, CON-02가 PC 수를 센다) | 수락 |
| [0047](0047-one-deployment-gate.md) | 배포 관문은 하나다 — Center가 계약의 `validate_deployment()`를 부르고, 코드마다 상태는 계약의 표가 준다 (배포 쪽 `target_mismatch`는 `wrong_target`으로) | 수락 |
| [0048](0048-installing-shared-packages.md) | 받은 공유 BPM 프로세스는 작업 폴더의 `libs/`에 푼다 (패키지와 같은 자리 — 실행기가 이미 읽는다). 툴팩 설치는 「받은 코드를 돌려도 되나」라 따로 정한다 | 수락 |
| [0049](0049-deployment-target-must-exist.md) | 배포 대상은 등록된 PC여야 한다 — 404 `target_not_found`. 등록 전에는 적을 `bot_ui_id`가 없어 「미리 배포해 두기」는 길이 아니었다 (읽는 것은 Center, 판정은 계약) | 수락 |
| [0050](0050-no-toolpack-kind.md) | 툴팩이라는 패키지 갈래를 두지 않는다 — 도구는 확장이 기여하고, 코드는 설치 파일로만 온다 (`provides.tools`·`requires.toolpacks`·`requires.secrets`도 함께 빠진다) | 수락 |
| [0051](0051-shared-process-conveniences.md) | STU-03의 공유 BPM 프로세스 뿌리는 Center 목록이고 설치 여부를 줄에 덧붙인다 — 부르기·보기·복사는 설치된 판에서만, 읽기 전용은 뷰어 한 벌을 더 실어 지킨다 | 수락 |
| [0052](0052-service-app-key-notices.md) | 서비스 앱 키의 「거부」는 실행 기록에서 읽고(묻지 않는다), 「만료 임박」만 쓰는 키에 하루 한 번 묻는다 — 사전 점검은 그대로 서버를 부르지 않는다 | 수락 |
| [0053](0053-no-watch-mode-in-studio.md) | Studio에 감시 모드를 두지 않는다 — 일정(cron)을 읽는 자리는 현장 하나이고, 트리거가 깨우는 그림은 시험 케이스의 `messages`로 본다 | 수락 |
| [0054](0054-server-run-state-and-concurrency.md) | 서버 실행기는 기다리는 실행의 `Run`을 JSON 한 덩이로 SQLite에 담고(그림·기록·바깥 세계·도우미는 다시 꽂는다), 도는 실행은 한 프로세스 안에서 실행마다 스레드 하나로 돈다 (s10) | 수락 |
| [0055](0055-m6-field-scenario-is-scenario-3.md) | M6의 현장 기준은 시나리오 3(BX-04) 하나다 — 서버 Bot인 1·2·4는 M7 인수 시험이 덮는다 | 수락 |
| [0056](0056-bounded-seen-maps.md) | 멱등 기억(`seen_jobs`·메시지)은 ack가 Center에 닿은 뒤 두 주기에 잊는다 — 닿지 않은 ack는 버리지 않고(업무가 두 번 일어난다), 작업과 메시지가 한 자리를 쓴다 | 수락 |
| [0057](0057-shared-seen-map.md) | Bot UI도 같은 멱등 기억을 쓴다 — 자리는 `core.seen` 하나이고, 파일에는 **ack만** 남긴다 (「닿지 않았다」는 `pending_acks`가 이미 말해 준다) | 수락 |
| [0058](0058-absorbed-messages-travel-with-the-snapshot.md) | 빨아들인 메시지(`message_id`)는 스냅샷과 한 트랜잭션에 담는다 — 재시작을 건너 두 번 들어가지 않고, 따로 담아 갈라져 잃지도 않는다 (ADR-0056이 남긴 자리) | 수락 |
| [0059](0059-sending-mail-and-webhooks.md) | 보내기는 플랫폼이 한다 — `core.senders`의 SMTP·HTTP 구현에 실행하는 쪽이 설정을 준다. 웹훅 관문은 어댑터와 같은 함수이고 **허용 호스트는 운영자가 적는다**(기본은 닫힘) | 수락 |
| [0060](0060-pinning-external-definitions.md) | 외부 확장 정의는 **그림에 고정한다**(`chk:process.extensions[].definition_hash` — 모델·내보내기가 이미 받는다). 고정하지 않은 것은 **막지 않고 경고한다** — 겹으로 막는 것을 내보내기의 관문으로 올리면 뒷문이 기본값이 된다 | 수락 |
| [0061](0061-waking-runs-whose-timer-is-due.md) | 시각이 된 타이머는 **하트비트가 쓸어서** 깨운다 — 메모리의 일꾼만 보고(재시작은 이미 전부 되살린다) **자리가 있을 때만**. 기한은 「그 시각 이후」다 | 수락 |
| [0062](0062-pc-delegation.md) | PC 위임은 **배포된 PC Bot**을 Center 작업으로 부르는 것이다 (`chk:call.delegate`) — ADR-0016 §3의 「패키지 안의 PC 정의」는 **돌릴 길이 없었다**(공유 BPM 프로세스에는 진입이 없다). 결과 값만 Center를 지나가고 ack와 함께 지운다 | 수락 |
| [0063](0063-stopping-a-running-server-run.md) | **도는 서버 실행은 작업 취소로 멈춘다** — C5 취소 표의 `accepted` 줄을 **대상 종류로** 갈라 서버는 202, **PC는 그대로 거절**이다(화면을 만지는 중일 수 있다). 실행을 가리키는 새 경로를 두지 않았다 — 서버 실행은 작업으로만 시작되므로 작업이 유일한 손잡이다 | 수락 |
| [0064](0064-extension-tasks-on-the-server.md) | **서버 실행기는 로컬 런타임을 띄우지 않는다** — 확장만 꽂고, `run_locations`에 `server`를 적은 태스크 종류만 거기서 돈다(그 선언이 「런타임도 화면도 필요 없다」는 약속이다). 예약은 「PC에 하나」를 전제한 배타 잠금이라 동시 실행과 맞지 않는다. 계약은 늘지 않았다 | 수락 |
| [0065](0065-center-schema-migrations.md) | **Center 저장소는 판 번호와 앞으로만 가는 단계로 옮긴다** — 오늘의 `SCHEMA`가 1판이고 **얼었다**(바꿀 것은 단계로). 단계 하나는 그 판의 기록과 함께 **트랜잭션 하나**이고, DB 판이 코드보다 높으면 **뜨지 않는다**. 의존을 늘리지 않고(Alembic·SQLAlchemy 없이) SQL 문 목록이라 PostgreSQL 길을 닫지 않는다 | 수락 |
| [0066](0066-migration-guards.md) | **데이터가 단계의 전제를 어기면 막고 사람에게 넘긴다** — 단계는 지킴 질의(`guard`, 아무 줄도 없어야 하는 SELECT)를 가질 수 있고 걸리면 문을 하나도 돌리지 않는다. 고치는 도구(`chk-center hosts`)는 **옮기기를 돌리지 않고** DB를 연다. 3판이 키 묶기 UNIQUE를 건다 — 겹친 옛 행은 **은퇴**시킬 뿐 지우지 않는다 | 수락 |
| [0067](0067-build-stamp.md) | **산출물의 판은 빌드가 찍고 앱은 그것을 읽어 올린다** — 태그면 태그, 아니면 `<core 판>+g<커밋>`(고치다 만 것은 `.dirty`). 실행 파일 옆 `chaeksas-build.json` 하나에 찍고 `core.build_info`가 읽는다. C4 `versions.build`가 있으면 묶은 것, 없으면 체크아웃이다. 빌드가 **되읽어** 찍은 판과 다르면 실패한다 | 수락 |
| [0068](0068-installer-inno-setup-per-user.md) | **설치 프로그램은 Inno Setup이고 사용자별로 깐다** — 관리자 권한을 묻지 않고 `%LOCALAPPDATA%\Programs\Chaeksas\<앱>`에, Studio·Bot UI 둘. 덮어쓸 때 옛 `_internal`을 먼저 지우고, 자동 시작은 앱이 걸고 제거할 때 지운다. **서명 없이** 시작한다(SmartScreen 경고). CI가 설치 → 검사 → 제거까지 해 본다 | 수락 |
| [0069](0069-upgrading-by-reinstall.md) | **Studio·Bot UI의 판은 사람이 설치 파일로 다시 깔아 올린다** — Center는 판을 보여 줄 뿐 프로그램을 내려 주지 않는다(서명 봉투도 두지 않는다). 언제 깔지(도는 Bot·대기열이 빈 때 — CON-03 「비활성화」로 만든다)와 실패 때 옛 설치 파일로 되돌리기는 사람이 정한다. 자동으로 내려 주게 되면 Admin 서명 봉투가 관문이다 | 수락 |
| [0070](0070-center-stays-on-sqlite.md) | **Center 저장소는 SQLite로 남는다** — PostgreSQL은 길만 열어 두고(SQL 이식성을 시험이 지킨다) 옮길 조건 셋(Center 여러 대·쓰기 잠금 관측·회사 요구)을 적는다. 옮길 때는 SQLite를 버린다(둘 다 받지 않는다). 서버 실행기·UI 자동화 앱의 SQLite는 그대로다 | 수락 |
| [0071](0071-splitting-a-task-into-a-pc-bot.md) | **「PC BPM 프로세스로 나누기」는 노드 하나를 새 PC Bot으로 옮기고 그 자리에 위임 호출을 둔다** — 바꾸기는 bpmn-js `replaceElement`라 흐름·경계가 남고 실행 취소가 한 걸음이다. 그림은 둘 다 캔버스가 짓고(파이썬은 XML을 만지지 않는다) 입력·출력은 아는 이름만 미리 채워 사람이 확인한다(짝은 같은 이름). PC 쪽을 다 지은 뒤 서버 쪽을 바꾼다. 오류 경계·케이스는 지어 넣지 않고 말한다 | 수락 |
| [0072](0072-desktop-pick-without-hooks.md) | **데스크톱 「직접 고르기」는 훅 없이 커서와 Ctrl을 읽고, 「표시」는 Bot UI가 테두리 창을 띄운다** — 전역 마우스 훅은 다른 앱의 입력을 가로채므로 쓰지 않는다. 화면이 비워 갈 때마다 Ctrl이 눌려 있으면 커서 아래 요소를 읽어 조상으로 올라가고 붙은 창 밖은 버린다. Worker는 사각형(물리 픽셀)만 주고 Qt가 입력을 통과시키는 테두리를 1.5초 띄운다. 배율 100%에서만 보았다 | 수락 |
| [0073](0073-studio-settings-only-what-is-used.md) | **STU-10에는 쓰는 곳이 있는 칸만 둔다** — 「외형」은 테마 하나(저장하는 자리에서 입히고, 캔버스 그림은 밝게 둔다), 「확장별 설정」은 `scope: studio` 기여로 짓고(비밀 칸은 OS 비밀 저장소). 「메일」·「비밀」 분류와 공급자·temperature·화면 인식 모델·캔버스 팔레트는 읽는 곳이 없어 걷는다 | 수락 (결정 2 한 문장은 0074) |
| [0074](0074-ui-task-editor-runs-on-the-worker.md) | **STU-13의 「이 스텝까지 시험」과 「계획 굳히기」는 Studio 시험 실행과 같은 길로 Worker를 부른다** — Bot UI로 넘기지 않는다(시험 실행이 이미 Worker에 직접 붙는다). 편집기도 Worker 자리와 Studio 비밀 창고를 받고, 「BPM 프로세스 설정을 따름」은 새 예약 키 `service.key_ref`로 푼다. 시험은 `report: false`·끝나면 닫고, 굳히기는 `planned_steps`를 받아 사람이 눌러 표에 넣으며 목표로 계획을 끈다 | 수락 |
| [0075](0075-service-console-links-to-center-console.md) | **서비스 앱 콘솔은 Center 콘솔 주소를 자기 설정 하나로 받아 「실행 id」를 CON-01로 잇는다** — `CHK_SVC_CONSOLE__CENTER_CONSOLE_URL`(브라우저가 여는 주소, 선택 — 없으면 링크만 없다). C11을 늘리지 않는다(서비스 앱은 Center를 모른다). UIA-03은 `business_key`의 맨 앞 조각, `run_…`·`test_…` 모양만 잇는다 | 수락 |
| [0076](0076-no-admin-window-yet.md) | **Admin 창(ADM-01~03)은 짓지 않는다** — 서명은 명령 한 번에 키를 열고 닫는 `chk-admin`에 남고, 읽는 일은 Center 콘솔이 한다. 대조하다 빠져 있던 서버 배포 서명(`deploy --server [id] [--max-concurrency]`)을 함께 메웠다. 다시 볼 조건: 서명이 미뤄질 때·하드웨어 키 | 대체됨(ADR-0089) |
| [0077](0077-tool-ui.md) | **UI 셀렉터 등록은 Bot UI 밖의 Tool UI에서 연다** — 확장이 기여한 도구(`tool_ui.tools`)를 띄우는 따로 뜨는 프로그램이고, 로컬 런타임은 띄우지 않고 Bot UI가 띄운 Worker를 빌려 쓴다(Studio와 같은 길). Bot UI 실행 파일이 `--tool-ui`로 되어 Bot UI 설치에 함께 들어간다. 등록 담당자 키는 `scope: tool_ui`로 Bot UI 설정에서 빠진다 | 수락 |
| [0078](0078-field-approval-shows-what-to-judge.md) | **현장 결재·확인도 C6 본문을 요청 파일에 쓰고 결재 창(CMN-01)이 읽는다** — 올릴 파일(`.requests.jsonl`)과 갈라 `.field-requests.jsonl`에 두고 아무 데도 올리지 않는다. 창은 제목·설명·폼·검토 자료를 그대로 싣고, 본문이 아직 없으면 그림의 폼으로 뜬다. 끝나면 지운다 | 수락 |
| [0079](0079-virtual-worker-is-an-intake-bot.md) | **가상 직원의 일괄은 접수 Bot(서버 Bot) 실행 한 번이고, 일괄 결재는 그 안의 보통 C6 결재다** — 일괄 자원·실행 없는 결재·Center 안의 기동기를 만들지 않는다. 기동은 Call Activity 반복 + 위임이고, 위임을 서버 Bot 대상으로 넓히기·반복을 호출에 허락하기·위임 멱등 키에 반복 차례 넣기가 남는다(지금은 2건째부터 같은 작업이 돌아온다). 기동 허용 목록은 서명된 `requires.delegations`다 | 수락 |
| [0080](0080-approval-assignees.md) | **결재 담당자는 이름 목록이다** — C14 `chk:approval.assignees`(이름 배열 또는 변수 이름 하나)를 실행하는 쪽이 풀어 C6 `assignees[]`에 싣는다. 콘솔(관리자 토큰)은 담당자로 막지 않고 보이고 거르기만 한다(`?assignee=`). 막는 것은 대리 답뿐이다. `ApprovalInfo.requested_by`는 Center가 읽을 때 실행의 작업에서 붙인다 | 수락 |
| [0081](0081-answering-on-behalf.md) | **대리 답은 대리 답용 키(`relay`)와 `X-CHK-On-Behalf-Of`로 하고, 그 사람이 담당자일 때만 받는다** — 키 권한은 결재 읽기·답 셋뿐, 담당자 없는 결재는 콘솔에서만 답한다. `answered_by`(사람)와 `answered_via`(키 이름)를 가르고 C3 `human_answered`까지 남긴다. 연동용 키의 작업·메시지는 `on_behalf_of`로 적기만 하고 `requested_by`(키 이름)는 바꾸지 않는다 — `server_bot:` 위임 판별을 흉내 낼 길이 생긴다 | 수락 |
| [0082](0082-batch-start.md) | **일괄 기동은 Call Activity 반복 + 위임이고, 위임 대상의 실행 위치는 대상 패키지가 정한다** — 그림은 그대로 `bpm_process_id`만 적고 Center가 대상 매니페스트의 `run_location`으로 PC·서버를 가른다. 반복 안의 위임은 차례마다 작업 하나(멱등 키에 `loop_index`)이고 차례로 돈다. 건별 업무 결과는 자식 Bot이 `outputs`로 돌려주고, 위임 실패는 반복 전체의 오류 경계로 간다. 결재 없는 반복 위임은 B16 경고 | 수락 (§2 「차례로」는 [0087](0087-parallel-loop-on-the-server.md)이 대체) |
| [0083](0083-review-digest.md) | **결재의 검토 자료는 다이제스트로 고정한다** — Center가 받을 때 `review_digest`(`sha256:` + 정규화 JSON)를 계산해 값을 지운 뒤에도 남기고, 답의 `if_review_digest?`가 다르면 409 `review_changed`. 연동하는 쪽은 Center가 준 값을 그대로 되돌려 보낸다 | 수락 |
| [0084](0084-cancelling-a-batch.md) | **일괄 취소는 접수 실행의 작업 취소다** — 새 API 없이, 맡겨 둔 자식은 C5 취소 규칙대로 거둔다(시작 안 된 것·시작된 서버 자식은 취소, 시작된 PC 자식은 끝까지, 끝난 건은 그대로). 보류·재개는 그림의 메시지 받기로 | 수락 |
| [0085](0085-virtual-worker-resource.md) | **가상 직원은 Center 자원이고, 접수 Bot을 묶을 때 결재 없는 일괄 기동이 없어야 한다** — 이름·감독자·접수 Bot만 저장하고 일괄·자식은 읽을 때 잇는다(`?virtual_worker=`, 상세의 최근 일괄). 기동 허용 목록과 `requested_by = vw:`는 두지 않는다. Center가 저장된 그림을 읽어 B16을 묶을 때·배포할 때 본다. 대리 답용 키는 감독하는 것만 읽는다 | 수락 |
| [0086](0086-run-identity-is-the-package-id.md) | **실행이 말하는 `bpm_process_id`는 패키지 id이고, 실행하는 쪽이 엔진에 넘긴다** — `Engine.start(bpm_process_id=…)`로 받아 C3 `run_started`·C6 결재 요청·C11 `caller`가 쓴다. 호출의 안쪽 실행은 물려받고 스냅샷과 함께 간다. 주지 않으면 그림 id(패키지 없는 시험). 재생 명세의 열쇠는 그림 id 그대로. 가상 직원의 「매니페스트 `process_id`도 본다」를 걷었다 | 수락 |
| [0087](0087-parallel-loop-on-the-server.md) | **서버의 병렬 반복은 차례마다 토큰 하나이고, 한 건의 실패는 나머지를 거둔다** — 그림이 `isSequential=false`이고 실행 위치가 `server`면 주인 토큰이 멈추고 차례 토큰이 같은 노드를 한 번씩 밟는다(기다림은 여전히 토큰 하나에 하나, `Run`에 칸이 늘지 않는다). 결과는 제 자리에 넣어 입력 순서다. 차례 하나가 업무 실패면 나머지를 걷고 맡긴 작업을 포트(`Delegator.withdraw`)로 거둔 뒤 오류 경계가 한 번 받는다. 동기 태스크는 겹치지 않는다(엔진에 스레드가 없다) | 수락 |
| [0088](0088-auto-layout-for-definitions-without-di.md) | **그림 좌표(DI)가 없는 정의는 캔버스가 열 때 `bpmn-auto-layout`으로 배치한다** — 배치 전에 흐름에서 `incoming`·`outgoing`을 채워야 선이 그어진다. DI가 있으면 건드리지 않고, 편집기에서 배치하면 「저장 안 한 변경」이 된다(파일에 쓰는 것은 사람의 저장). 도우미 하나만 esbuild로 묶고 모델러·뷰어는 그대로 복사한다(ADR-0029) | 수락 |
| [0089](0089-admin-ui.md) | **Admin UI를 짓는다** (`chk-admin-ui`, ADR-0076을 대체) — 첫 판은 키(ADM-01)·외부 확장(ADM-04)·Center 연결(ADM-05)이다. 서명은 **누를 때마다 암호를 묻고 키를 버리고**, 확인 문구·서명·키 고르기는 CLI와 **같은 함수**(`admin/ops.py`)다. 연결은 설정 파일(주소)과 OS 비밀 저장소(토큰)에 두고 CLI도 읽는다. 첫 키는 **서버 셸**(이 PC 또는 SSH — 암호는 받지 않는다)에서 compose 컨테이너나 적은 명령으로 넣고 **Center API로 들어갔나 확인한다**. 셸이 없으면 명령을 보이고 복사만 둔다. 네트워크로 넣는 길은 없다. 승인·배포(ADM-02·03)는 다음 판이다 | 수락 |
