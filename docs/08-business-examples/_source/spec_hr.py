"""인사·총무 예제 (BX-20 ~ BX-24)."""

from exdsl import *  # noqa: F401,F403

EXAMPLES = []

# ───────────────────────────── BX-20 ─────────────────────────────
EXAMPLES.append(Example(
    id="BX-20", file="bx20_employee_onboarding", name="입사자 온보딩", dept="인사·총무",
    origin="프로토타입 시나리오 2 (끝남 — 케이스 3/3, 재생 3/3)", 
    run_location="server", trigger="메시지 `new_hire` — 인사 시스템의 입사 확정",
    background="""
입사 확정이 오면 계정 준비(메일·메신저·그룹웨어)를 하위 프로세스로 묶어 진행한다. 계정 준비가 이틀 안에 끝나지 않으면 IT팀에 에스컬레이션한다. 계정이 준비되면 AI가 입사자에게 보낼 환영 안내를 쓰고, 장비 지급을 총무팀이 확인한 뒤 입사자와 팀장에게 메일을 보낸다.
""",
    why_location="""
프로토타입 시나리오 2는 장비 수령을 PC의 수동 작업으로 확인했다. 실제 업무에서 총무팀 확인은 입사일까지 며칠 걸릴 수 있고, PC Bot이면 그동안 실행 자리를 쥔다 (ADR-0014). 그래서 **Center 결재함의 확인**으로 바꿔 서버에서 기다린다.
""",
    inputs=[("사번", "string", True, ""), ("이름", "string", True, ""), ("부서", "string", True, ""), ("입사일", "date", True, ""),
            ("팀장메일", "string", True, ""), ("개인메일", "string", True, ""), ("IT팀메일", "string", False, "", "it@example.com")],
    nodes=[
        start("Start", "입사 확정", kind="message", message="new_hire"),
        sub("Sub_Accounts", "계정 준비", [
            start("Acc_Start", "시작"),
            pgw("Acc_Split", "동시에"),
            svc("Acc_Mail", "메일 계정", "directory", "create_mail_account", {"emp_id": "사번", "name": "이름"}, {"회사메일": "email"}),
            svc("Acc_Chat", "메신저 계정", "directory", "create_chat_account", {"emp_id": "사번"}, {"메신저": "account"}),
            svc("Acc_Group", "그룹웨어 부서 배정", "directory", "assign_department", {"emp_id": "사번", "dept": "부서"}, {"배정": "result"}),
            pgw("Acc_Join", "모두 끝"),
            end("Acc_End", "끝"),
        ], [f("Acc_Start", "Acc_Split"), f("Acc_Split", "Acc_Mail"), f("Acc_Split", "Acc_Chat"), f("Acc_Split", "Acc_Group"),
            f("Acc_Mail", "Acc_Join"), f("Acc_Chat", "Acc_Join"), f("Acc_Group", "Acc_Join"), f("Acc_Join", "Acc_End")]),
        ai("Task_Welcome", "환영 안내 쓰기",
           goal("입사자 `이름`(`부서`)이 `입사일`에 첫 출근한다. 회사 메일은 `회사메일`이다. 업무 파라미터 `첫날안내`에 공통 일정이 있다.",
                "입사자에게 보낼 따뜻하고 간결한 환영 메일 본문을 쓴다. 첫날 일정과 계정 정보를 포함한다.",
                "급여·평가·계약 조건을 언급하지 않는다.", "- `환영본문`: string"),
           "llm", {"환영본문": "string"}, params={"첫날안내": "09:30 로비 집결 → 10:00 오리엔테이션 → 13:00 팀 합류"}),
        appr("Approve_Equipment", "장비 지급 확인", "장비 지급 확인", ["이름", "부서", "입사일"],
             [fld("노트북", "노트북 자산번호", "text", True), fld("출입카드", "출입카드 지급", "bool", True)], location="center",
             description="총무팀: 장비를 지급한 뒤 자산번호를 입력하세요."),
        mail("Task_MailHire", "입사자에게", ["{개인메일}"], "{이름}님, 입사를 환영합니다", "{환영본문}"),
        mail("Task_MailLead", "팀장에게", ["{팀장메일}"], "[온보딩] {이름} 준비 완료", "계정·장비 준비가 끝났습니다. 노트북 {노트북}"),
        mail("Task_Escalate", "IT 에스컬레이션", ["{IT팀메일}"], "[온보딩 지연] {이름} 계정 준비 2일 초과", "확인 부탁드립니다."),
        end("End_Escalated", "에스컬레이션 끝"),
        end("End"),
    ],
    flows=[f("Start", "Sub_Accounts"), f("Sub_Accounts", "Task_Welcome"), f("Task_Welcome", "Approve_Equipment"),
           f("Approve_Equipment", "Task_MailHire"), f("Task_MailHire", "Task_MailLead"), f("Task_MailLead", "End"),
           f("Bnd_Late", "Task_Escalate"), f("Task_Escalate", "End_Escalated")],
    boundaries=[bnd("Bnd_Late", "Sub_Accounts", "timer", "2일", interrupting=False, duration="P2D")],
    service_keys={"directory": "hr-directory"}, extensions=[{"id": "directory", "version": ">=1,<2"}],
    cases=[Case("정상 입사", {"사번": "E2610-01", "이름": "박지민", "부서": "재무팀", "입사일": "2026-10-12", "팀장메일": "lead@example.com", "개인메일": "jimin@example.net"},
                {"회사메일": "*"}, {"Approve_Equipment": {"노트북": "NB-2210", "출입카드": True}}),
           Case("정상 입사 (사람이 확인)", {"사번": "E2610-02", "이름": "이도윤", "부서": "영업팀", "입사일": "2026-10-12", "팀장메일": "lead@example.com", "개인메일": "doyun@example.net"},
                {}, manual=True)],
    features=["하위 프로세스 + 안의 병렬", "하위 프로세스의 비중단 타이머 경계(에스컬레이션)", "PC 수동 작업 → Center 결재함 확인으로 옮긴 사례", "AI 문장 + 업무 파라미터"],
    lessons=["하위 프로세스 안에서 만든 변수(`회사메일`)는 정상으로 끝나면 밖에서도 보인다 (호출과 다름). 그러나 **중단 경계가 끊은 하위 프로세스는 안에서 만든 변수를 하나도 내보내지 않는다** (프로토타입 시나리오 2에서 확인). 그래서 이 예제의 2일 경계는 비중단 — 에스컬레이션만 하고 계정 준비는 계속한다.",
             "하위 프로세스 안에는 시작 이벤트만 저절로 생긴다. 끝 이벤트를 직접 넣지 않으면 마지막 안쪽 태스크에 나가는 흐름이 없어 실행 전 검사(B9)가 막는다 (프로토타입 시나리오 2).",
             "마감·경계로 끊긴 태스크를 실패로 세면 마감을 시험하는 케이스가 다른 케이스의 판정을 지운다 — 취소는 판정이 아니다 (프로토타입 결함 C-21)."],
))

# ───────────────────────────── BX-21 ─────────────────────────────
EXAMPLES.append(Example(
    id="BX-21", file="bx21_leave_request", name="휴가 신청", dept="인사·총무",
    origin="새로 설계", 
    run_location="server", trigger="메시지 `leave_request` — 그룹웨어 휴가 신청",
    background="""
직원이 휴가를 신청하면 잔여 휴가를 확인한다 (공유 BPM 프로세스 BX-24 호출). 잔여가 모자라면 바로 반려, 3일 이하면 팀장 결재, 3일 초과면 팀장 → 부서장 순서로 결재한다. 승인되면 근태 시스템에 등록한다.
""",
    why_location="결재 대기 — 서버.",
    inputs=[("신청번호", "string", True, ""), ("사번", "string", True, ""), ("시작일", "date", True, ""), ("일수", "number", True, "반차 0.5"), ("회신주소", "string", True, "그룹웨어 회신 웹훅")],
    nodes=[
        start("Start", "휴가 신청", kind="message", message="leave_request"),
        call("Call_Balance", "잔여 휴가 (BX-24)", "Proc_bx24_leave_balance", {"사번": "사번"}, {"잔여": "잔여"}),
        xgw("Gw_Enough", "잔여 충분?"),
        appr("Approve_Lead", "팀장 결재", "휴가 결재 (팀장)", ["사번", "시작일", "일수", "잔여"], [fld("승인", "승인", "bool", True), fld("의견", "의견")], location="center"),
        xgw("Gw_Long", "3일 초과?"),
        appr("Approve_Head", "부서장 결재", "휴가 결재 (부서장)", ["사번", "시작일", "일수", "잔여", "의견"], [fld("승인", "승인", "bool", True)], location="center"),
        xgw("Gw_Result", "승인?"),
        svc("Task_Register", "근태 등록", "hris", "register_leave", {"emp_id": "사번", "start": "시작일", "days": "일수"}, {"등록": "result"}),
        script("Task_Approved", "승인 정리", "결과 = '승인'"),
        script("Task_Reject", "반려 정리", "결과 = '반려'"),
        hook("Task_Reply", "그룹웨어 회신", "{회신주소}", body="fields:[신청번호, 결과]"),
        end("End"),
    ],
    flows=[f("Start", "Call_Balance"), f("Call_Balance", "Gw_Enough"),
           f("Gw_Enough", "Approve_Lead", "잔여 >= 일수", "충분"), f("Gw_Enough", "Task_Reject", default=True, name="부족"),
           f("Approve_Lead", "Gw_Long"), f("Gw_Long", "Approve_Head", "승인 and 일수 > 3", "초과"), f("Gw_Long", "Gw_Result", default=True, name="이하·반려"),
           f("Approve_Head", "Gw_Result"),
           f("Gw_Result", "Task_Register", "승인", "승인"), f("Gw_Result", "Task_Reject", default=True, name="반려"),
           f("Task_Register", "Task_Approved"), f("Task_Approved", "Task_Reply"), f("Task_Reject", "Task_Reply"), f("Task_Reply", "End")],
    service_keys={"hris": "hr-hris"}, extensions=[{"id": "hris", "version": ">=1,<2"}],
    cases=[Case("2일 승인", {"신청번호": "LV-1", "사번": "E001", "시작일": "2026-10-20", "일수": 2, "회신주소": {"$test_receiver": "reply"}}, {"승인": True},
                {"Approve_Lead": {"승인": True}}),
           Case("5일 부서장 반려", {"신청번호": "LV-2", "사번": "E001", "시작일": "2026-11-02", "일수": 5, "회신주소": {"$test_receiver": "reply"}}, {"결과": "반려"},
                {"Approve_Lead": {"승인": True}, "Approve_Head": {"승인": False}}),
           Case("잔여 부족", {"신청번호": "LV-3", "사번": "E002", "시작일": "2026-10-20", "일수": 20, "회신주소": {"$test_receiver": "reply"}}, {"결과": "반려"})],
    called=["bx24_leave_balance"],
    features=["순차 결재 2단계 (조건부)", "같은 변수(`승인`)를 두 결재가 덮어쓰는 패턴", "공유 BPM 프로세스 호출", "여러 길이 한 태스크로 합류"],
    lessons=["두 결재가 같은 칸 이름(`승인`)을 쓰면 뒤 결재가 앞 값을 덮는다 — 의도한 것이면 괜찮지만, 둘 다 남기려면 칸 이름을 다르게 한다.",
             "결재자 지정(누가 결재하나)은 Center 결재함의 배정 규칙(C6)이 정한다. BPMN에 사람 이름을 쓰지 않는다."],
))

# ───────────────────────────── BX-22 ─────────────────────────────
EXAMPLES.append(Example(
    id="BX-22", file="bx22_offboarding_access", name="퇴사자 계정 회수", dept="인사·총무",
    origin="새로 설계",
    run_location="server", trigger="메시지 `employee_left` — 인사 시스템이 퇴사 처리 때 한 사람씩 보냄",
    background="""
퇴사 처리된 직원 한 사람의 계정을 세 시스템(메일, VPN, ERP)에서 동시에 회수한다. 한 시스템에서 실패해도 다른 시스템 회수는 계속되고, 실패한 것만 모아 보안팀에 알려 수동으로 처리하게 한다.
""",
    why_location="API만 쓴다 — 서버. 세 시스템을 동시에.",
    nodes=[
        start("Start", "퇴사 처리", kind="message", message="employee_left"),
        sub("Sub_Revoke", "계정 회수", [
            start("Rv_Start", "시작"),
            script("Rv_Init", "실패 칸 비우기", "메일실패 = None\nVPN실패 = None\nERP실패 = None"),
            pgw("Rv_Split", "동시에"),
            svc("Rv_Mail", "메일", "directory", "disable_mail", {"emp_id": "사번"}, {"메일회수": "result"}, retry={"max": 2, "on": [503]}),
            svc("Rv_Vpn", "VPN", "directory", "disable_vpn", {"emp_id": "사번"}, {"VPN회수": "result"}, retry={"max": 2, "on": [503]}),
            svc("Rv_Erp", "ERP", "erp", "disable_user", {"emp_id": "사번"}, {"ERP회수": "result"}, retry={"max": 2, "on": [503]}),
            script("Rv_MailFail", "메일 실패 기록", "메일실패 = dict(시스템='메일', 오류=error_message)"),
            script("Rv_VpnFail", "VPN 실패 기록", "VPN실패 = dict(시스템='VPN', 오류=error_message)"),
            script("Rv_ErpFail", "ERP 실패 기록", "ERP실패 = dict(시스템='ERP', 오류=error_message)"),
            xgw("Rv_MailDone", "메일 끝"), xgw("Rv_VpnDone", "VPN 끝"), xgw("Rv_ErpDone", "ERP 끝"),
            pgw("Rv_Join", "모두 끝"),
            end("Rv_End", "끝"),
        ], [f("Rv_Start", "Rv_Init"), f("Rv_Init", "Rv_Split"),
            f("Rv_Split", "Rv_Mail"), f("Rv_Split", "Rv_Vpn"), f("Rv_Split", "Rv_Erp"),
            f("Rv_Mail", "Rv_MailDone"), f("Bnd_MailFail", "Rv_MailFail"), f("Rv_MailFail", "Rv_MailDone"),
            f("Rv_Vpn", "Rv_VpnDone"), f("Bnd_VpnFail", "Rv_VpnFail"), f("Rv_VpnFail", "Rv_VpnDone"),
            f("Rv_Erp", "Rv_ErpDone"), f("Bnd_ErpFail", "Rv_ErpFail"), f("Rv_ErpFail", "Rv_ErpDone"),
            f("Rv_MailDone", "Rv_Join"), f("Rv_VpnDone", "Rv_Join"), f("Rv_ErpDone", "Rv_Join"),
            f("Rv_Join", "Rv_End")],
            [bnd("Bnd_MailFail", "Rv_Mail", "error", "실패", error="TASK_FAILED"),
             bnd("Bnd_VpnFail", "Rv_Vpn", "error", "실패", error="TASK_FAILED"),
             bnd("Bnd_ErpFail", "Rv_Erp", "error", "실패", error="TASK_FAILED")]),
        script("Task_Count", "실패 모으기", "실패 = [x for x in [메일실패, VPN실패, ERP실패] if x is not None]\n실패수 = len(실패)"),
        xgw("Gw_Fail", "실패 있음?"),
        mail("Task_Security", "보안팀 알림", ["{보안팀메일}"], "[계정 회수] {이름}({사번}) 수동 처리 {실패수}건", "실패한 시스템: {실패}"),
        end("End"),
    ],
    flows=[f("Start", "Sub_Revoke"), f("Sub_Revoke", "Task_Count"), f("Task_Count", "Gw_Fail"),
           f("Gw_Fail", "Task_Security", "실패수 > 0", "있음"), f("Gw_Fail", "End", default=True, name="없음"), f("Task_Security", "End")],
    service_keys={"directory": "sec-directory", "erp": "sec-erp"},
    extensions=[{"id": "directory", "version": ">=1,<2"}, {"id": "erp", "version": ">=1,<2"}],
    inputs=[("사번", "string", True, ""), ("이름", "string", True, ""), ("퇴사일", "date", True, ""), ("보안팀메일", "string", False, "", "security@example.com")],
    cases=[Case("정상", {"사번": "E008", "이름": "최서연", "퇴사일": "2026-10-31"}, {"실패수": 0}),
           Case("ERP 실패", {"사번": "E009", "이름": "정하준", "퇴사일": "2026-10-31"}, {"실패수": 1, "실패": [{"시스템": "ERP"}]},
                description="모의 ERP가 E009에 503을 계속 돌려준다 — 재시도 2번 뒤 실패")],
    features=["병렬 가지마다 오류 경계 → 배타 합류 → 병렬 합류 (가지 수 맞추기)", "하위 프로세스", "`TASK_FAILED` + 재시도 정책", "가지별 변수 → 합류 뒤 모으기",
              "건마다 실행 하나 (메시지 시작)"],
    lessons=["오류 경계의 대체 흐름을 병렬 합류에 바로 이으면 합류가 5개를 기다리는데 3개만 온다 — 영원히 멈춘다. 각 가지를 배타 게이트웨이로 먼저 모아 **가지 수와 합류 수를 맞춘다** (build.py가 검사).",
             "여러 가지가 같은 목록 변수에 덧붙이면 동시 쓰기가 된다 — 가지마다 자기 변수에 쓰고, 합류 뒤 모은다. 그 변수는 분기 전에 비워 둔다 (B11).",
             "여러 사람을 한 실행에서 돌리지 않고 **사람마다 실행 하나** — 실패·재시도·감사가 사람 단위로 깔끔하다. 서버는 동시에 여러 실행을 돌린다.",
             "오류 경계가 없는 병렬 가지가 실패하면 실행 전체가 실패한다 — 「계속해야 하는」 가지에는 오류 경계를 붙인다."],
))

# ───────────────────────────── BX-23 ─────────────────────────────
EXAMPLES.append(Example(
    id="BX-23", file="bx23_training_reminder", name="필수 교육 이수 독려", dept="인사·총무",
    origin="새로 설계", 
    run_location="server", trigger="타이머 — 매주 수요일 10:00",
    background="""
법정 필수 교육(개인정보·성희롱 예방 등)의 미이수자를 교육 시스템에서 가져와, 마감까지 남은 날짜에 따라 본인 안내 / 팀장 참조 / 인사팀 보고로 나눠 메일을 보낸다.
""",
    why_location="API·메일 — 서버.",
    nodes=[
        start("Start", "매주 수요일", kind="timer", cycle="0 10 * * 3"),
        svc("Task_List", "미이수자", "lms", "list_incomplete", {}, {"미이수": "items"}),
        rule("Task_Level", "독려 단계", "training_nudge", {"남은일수": "사람.남은일수"}, {"단계": "단계"},
             loop=dict(collection="미이수", item="사람", result="단계", collect_into="단계목록")),
        script("Task_Merge", "대상 만들기", "대상목록 = [dict(p, 단계=s) for p, s in zip(미이수, 단계목록)]"),
        ai("Task_Write", "안내 메일 쓰기",
           goal("`대상`은 미이수자 한 명(이름, 메일, 팀장메일, 교육명, 마감일, 남은일수, 링크, 단계)이다. 교육 시스템이 돌려준 값에 `단계`를 붙였다.", "단계에 맞는 안내 메일 제목과 본문을 쓴다. 받는 사람은 `대상.메일`, 「팀장참조」·「인사팀보고」면 참조에 `대상.팀장메일`(인사팀보고는 업무 파라미터 `인사팀메일`도). 이수 링크는 `대상.링크`를 그대로 쓴다.",
                "불이익을 과장하지 않는다.", "- `메일`: {받는사람, 참조, 제목, 본문}"),
           "llm", {"메일": "dict"}, params={"인사팀메일": "hr@example.com"}, loop=dict(collection="대상목록", item="대상", result="메일", collect_into="메일목록", parallel=True)),
        svc("Task_Send", "일괄 발송", "mailer", "send_bulk", {"mails": "메일목록"}, {"발송": "result"}),
        end("End"),
    ],
    flows=[f("Start", "Task_List"), f("Task_List", "Task_Level"), f("Task_Level", "Task_Merge"), f("Task_Merge", "Task_Write"), f("Task_Write", "Task_Send"), f("Task_Send", "End")],
    service_keys={"lms": "hr-lms", "mailer": "hr-mailer"}, extensions=[{"id": "lms", "version": ">=1,<2"}, {"id": "mailer", "version": ">=1,<2"}],
    decisions=[Decision("training_nudge", "독려 단계", [("남은일수", "남은일수", "number")], [("단계", "string")],
                        [(["< 0"], ['"인사팀보고"'], "마감 지남 — 인사팀에도 보고"), (["[0..7]"], ['"팀장참조"'], "팀장을 참조로"), (["> 7"], ['"본인안내"'], "")])],
    cases=[Case("3명", {}, {"메일목록": ["*", "*", "*"]})],
    features=["병렬 반복 AI 태스크 (서버)", "DMN 다중 출력", "일괄 발송 서비스 앱"],
    lessons=["사람마다 메일 1통씩 메일 태스크를 반복하면 SMTP 연결이 수십 번 — 일괄 발송 작업을 쓴다."],
))

# ───────────────────────────── BX-24 ─────────────────────────────
EXAMPLES.append(Example(
    id="BX-24", file="bx24_leave_balance", name="잔여 휴가 조회 (공유)", dept="인사·총무",
    origin="새로 설계 — 호출 대상", 
    run_location="server", trigger="BPM 프로세스 호출 — BX-21 등",
    background="근태 시스템에서 연차 발생·사용 내역을 가져와 잔여 일수를 계산한다. 여러 BPM 프로세스가 호출한다.",
    why_location="API·계산 — 서버.",
    inputs=[("사번", "string", True, "")],
    nodes=[
        start("Start"),
        svc("Task_Ledger", "연차 원장", "hris", "get_leave_ledger", {"emp_id": "사번"}, {"원장": "ledger"}),
        script("Task_Calc", "잔여 계산", "잔여 = 원장.발생 - 원장.사용 - 원장.예정"),
        end("End"),
    ],
    flows=[f("Start", "Task_Ledger"), f("Task_Ledger", "Task_Calc"), f("Task_Calc", "End")],
    outputs=["잔여"],
    service_keys={"hris": "hr-hris"}, extensions=[{"id": "hris", "version": ">=1,<2"}],
    cases=[Case("E001", {"사번": "E001"}, {"잔여": 11.5}), Case("E002", {"사번": "E002"}, {"잔여": 3})],
    features=["가장 작은 공유 BPM 프로세스 — 호출 대상의 모범"],
    lessons=["호출 대상은 입력(`chk:process.inputs`)과 출력(`chk:process.outputs`)을 분명히 적는다 — 호출하는 쪽이 매핑할 이름이고, build.py가 호출 매핑과 대조한다."],
))
