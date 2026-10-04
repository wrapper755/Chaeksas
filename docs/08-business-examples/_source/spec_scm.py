"""구매·영업·물류 예제 (BX-10 ~ BX-17)."""

from exdsl import *  # noqa: F401,F403

EXAMPLES = []

# ───────────────────────────── BX-10 ─────────────────────────────
EXAMPLES.append(Example(
    id="BX-10", file="bx10_vendor_onboarding_review", name="신규 거래처 등록 심사", dept="구매·영업·물류",
    origin="프로토타입 시나리오 1 (끝남 — 케이스 3/3) → 검토를 서비스 앱으로 바꿔 다시 씀", 
    run_location="server", trigger="메시지 `vendor_registration` — 구매 포털의 등록 신청",
    background="""
신규 거래처가 등록을 신청하면 서류(사업자등록증, 통장 사본, 신용평가서, 해외 거래처면 수출입 신고서)를 확인한다. **해당하는 점검만** 골라 동시에 돈다: 모든 거래처는 서류 확인, 거래 예상액이 5천만 원 이상이면 신용 점검, 해외 거래처면 제재 목록 점검. 고른 점검이 모두 끝나면 구매팀장이 승인하고 ERP에 거래처를 등록한다.
""",
    why_location="문서 판독·API·결재뿐이다. 신청 서류는 포털이 Center 메시지 본문으로 경로를 넘긴다.",
    inputs=[("신청번호", "string", True, ""), ("거래처명", "string", True, ""), ("사업자번호", "string", True, ""),
            ("해외", "bool", True, ""), ("예상거래액", "int", True, "연간, 원"), ("서류", "list", True, "파일 경로 목록"), ("회신주소", "string", True, "포털 회신 웹훅")],
    nodes=[
        start("Start", "등록 신청", kind="message", message="vendor_registration"),
        igw("Gw_Checks", "필요한 점검 고르기"),
        ai("Task_Docs", "서류 확인",
           goal("`서류`는 거래처가 올린 파일 목록이다.",
                "사업자등록증과 통장 사본이 있는지, 사업자등록증의 번호·상호가 `사업자번호`·`거래처명`과 같은지 확인한다.",
                "신용이나 거래 적합성은 판단하지 않는다.",
                "- `서류결과`: {충족(bool), 빠진서류(list), 불일치(list)}"),
           "doc", {"서류결과": "dict"}, tools=["pdf_text_tool", "image_ocr_tool"]),
        svc("Task_Credit", "신용 점검", "ext-credit", "lookup", {"biz_no": "사업자번호"}, {"신용": "result"}),
        svc("Task_Sanction", "제재 목록 점검", "compliance", "screen_sanctions", {"name": "거래처명"}, {"제재": "hits"}),
        igw("Gw_Join", "점검 모으기"),
        script("Task_Summary", "심사 요약",
               "신용 = 신용 if 예상거래액 >= 50000000 else None\n제재 = 제재 if 해외 else []\n권고 = '반려' if (not 서류결과.충족) or len(제재) > 0 else '승인'\n거래처코드 = ''"),
        appr("Approve_Vendor", "구매팀장 승인", "신규 거래처 등록", ["거래처명", "사업자번호", "서류결과", "신용", "제재", "권고"],
             [fld("결정", "결정", "choice", True, ["승인", "반려", "보완요청"]), fld("의견", "의견")], location="center"),
        xgw("Gw_Decision", "결정"),
        svc("Task_Register", "ERP 거래처 등록", "erp", "create_vendor", {"name": "거래처명", "biz_no": "사업자번호"}, {"거래처코드": "vendor_code"}),
        hook("Task_Reply", "포털에 결과 회신", "{회신주소}", body="fields:[신청번호, 결정, 의견, 거래처코드]", store_as="회신결과"),
        end("End"),
    ],
    flows=[f("Start", "Gw_Checks"),
           f("Gw_Checks", "Task_Docs", "true", "항상"), f("Gw_Checks", "Task_Credit", "예상거래액 >= 50000000", "5천만 이상"),
           f("Gw_Checks", "Task_Sanction", "해외", "해외"),
           f("Task_Docs", "Gw_Join"), f("Task_Credit", "Gw_Join"), f("Task_Sanction", "Gw_Join"),
           f("Gw_Join", "Task_Summary"), f("Task_Summary", "Approve_Vendor"), f("Approve_Vendor", "Gw_Decision"),
           f("Gw_Decision", "Task_Register", "결정 == '승인'", "승인"), f("Gw_Decision", "Task_Reply", default=True, name="반려·보완"),
           f("Task_Register", "Task_Reply"), f("Task_Reply", "End")],
    service_keys={"ext-credit": "purchase-credit", "compliance": "purchase-compliance", "erp": "purchase-erp"},
    extensions=[{"id": "ext-credit", "version": ">=1,<2"}, {"id": "compliance", "version": ">=1,<2"}, {"id": "erp", "version": ">=1,<2"}],
    variables=[("서류결과", "dict", "Task_Docs", ""), ("신용", "dict?", "Task_Credit (5천만 이상일 때만)", "돌지 않으면 없음 → `Task_Summary`에서 None"),
               ("제재", "list?", "Task_Sanction (해외일 때만)", ""), ("결정", "string", "Approve_Vendor", "승인/반려/보완요청")],
    cases=[
        Case("국내 소액", {"신청번호": "VR-001", "거래처명": "가나상사", "사업자번호": "123-45-67890", "해외": False, "예상거래액": 10000000, "서류": ["samples/vendor/biz.pdf", "samples/vendor/bank.pdf"], "회신주소": {"$test_receiver": "reply"}},
             {"권고": "승인"}, {"Approve_Vendor": {"결정": "승인"}}, "서류 확인만 돈다"),
        Case("해외 대액", {"신청번호": "VR-002", "거래처명": "Acme Trading", "사업자번호": "999-99-99999", "해외": True, "예상거래액": 300000000, "서류": ["samples/vendor/biz.pdf"], "회신주소": {"$test_receiver": "reply"}},
             {"권고": "반려"}, {"Approve_Vendor": {"결정": "보완요청", "의견": "통장 사본 누락"}}, "세 점검 모두 돈다. 통장 사본 없음"),
    ],
    features=["포함 게이트웨이(조건에 맞는 가지만 동시에) + 포함 합류", "돌지 않은 가지의 변수는 없음 → 스크립트에서 None 처리",
              "서비스 앱 3개(사내 2·외부 1)와 키 참조 3개", "선택형 결재 칸(choice)"],
    lessons=["세 검토가 각각 만드는 변수 이름을 겹치지 않게 한다 (프로토타입 시나리오 1의 주의).",
             "돌지 않은 가지가 만든다고 가정한 변수를 다음 태스크가 읽으면 「없는 변수」 오류 — 합류 뒤 스크립트에서 기본값을 정한다.",
             "`\"true\"` 조건으로 「항상」 가지를 명시한다 (포함 게이트웨이는 기본 흐름 외에 아무 가지도 안 맞으면 멈춘다)."],
))

# ───────────────────────────── BX-11 ─────────────────────────────
EXAMPLES.append(Example(
    id="BX-11", file="bx11_bid_collection", name="입찰 접수와 마감", dept="구매·영업·물류",
    origin="프로토타입 시나리오 5(입찰 마감, 제안만 됨) → 새로 설계",
    run_location="server", trigger="작업 지시 — 입찰 공고 발행 시",
    background="""
입찰 공고를 낸 뒤 공급사 견적을 마감 시각까지 받는다. 견적이 올 때마다 기록하고, 마감 시각이 되면 접수를 닫는다. 공고가 취소되면(구매 시스템이 이 입찰번호로 「입찰 취소」 메시지를 보냄) 접수를 멈추고 응찰사에 취소를 알린다. 마감 후 AI가 견적을 비교표로 정리하고 구매팀이 낙찰사를 고른다.
""",
    why_location="며칠짜리 대기와 외부 메시지 수신 — 서버.",
    inputs=[("입찰번호", "string", True, ""), ("마감시각", "string", True, "ISO 8601 시각 (예 `2026-10-15T18:00:00+09:00`)"), ("품목", "list", True, ""),
            # 루프가 쌓아 가는 변수는 **입력으로 선언해 기본값을 준다** — 스크립트가 없는 변수를
            # 읽으려 하면 식 오류다 (ADR-0025: 읽기 전에 있어야 한다).
            ("견적목록", "list", False, "받은 견적 (루프가 쌓는다)", []),
            ("응찰사메일", "list", False, "응찰사 회신 주소 (루프가 쌓는다)", [])],
    nodes=[
        start("Start", "공고 발행"),
        recv("Recv_Quote", "견적 받기", "bid_quote", "입찰번호", payload=["견적"]),
        script("Task_Record", "견적 기록", "견적목록 = 견적목록 + [견적]\n응찰사메일 = 응찰사메일 + [견적.회신메일]\n응찰수 = len(견적목록)"),
        script("Task_Close", "접수 마감", "응찰수 = len(견적목록)"),
        xgw("Gw_Any", "응찰 있음?"),
        ai("Task_Compare", "견적 비교표",
           goal("`견적목록`은 공급사별 견적이다 (단가, 납기, 조건). `품목`은 공고 품목이다.",
                "품목별로 견적을 비교하는 표를 만들고, 가격·납기·조건의 장단점을 한 줄씩 적는다.",
                "낙찰사를 정하지 않는다. 견적에 없는 값을 추정하지 않는다.",
                "- `비교표`: markdown 표 문자열\n- `요약`: string"),
           "llm", {"비교표": "string", "요약": "string"}),
        appr("Approve_Award", "낙찰사 선택", "낙찰사 선택", ["입찰번호", "비교표", "요약"],
             [fld("낙찰사", "낙찰사", "text", True), fld("사유", "선정 사유", "text", True)], location="center"),
        mail("Task_NotifyAward", "결과 통보", ["{응찰사메일}"], "[{입찰번호}] 입찰 결과", "낙찰사: {낙찰사}"),
        end("End"),
        end("End_NoBid", "유찰"),
        mail("Task_NotifyCancel", "취소 통보", ["{응찰사메일}"], "[{입찰번호}] 입찰 취소", "공고가 취소되었습니다."),
        end("End_Cancel", "취소로 끝", kind="terminate"),
    ],
    flows=[f("Start", "Recv_Quote"), f("Recv_Quote", "Task_Record"), f("Task_Record", "Recv_Quote"),
           f("Bnd_Deadline", "Task_Close"), f("Task_Close", "Gw_Any"),
           f("Gw_Any", "Task_Compare", "응찰수 > 0", "있음"), f("Gw_Any", "End_NoBid", default=True, name="없음"),
           f("Task_Compare", "Approve_Award"), f("Approve_Award", "Task_NotifyAward"), f("Task_NotifyAward", "End"),
           f("Bnd_Cancel", "Task_NotifyCancel"), f("Task_NotifyCancel", "End_Cancel")],
    # 기한은 **고정된 시각**이다 — 받기를 다시 기다릴 때마다 경계가 새로 서지만 같은 시각이라
    # 마감이 밀리지 않는다 (기간을 매번 계산할 필요가 없다. C14는 ISO 기간과 ISO 시각을 받는다).
    boundaries=[bnd("Bnd_Deadline", "Recv_Quote", "timer", "마감", duration="마감시각"),
                bnd("Bnd_Cancel", "Recv_Quote", "message", "입찰 취소", message="bid_cancelled", correlation="입찰번호")],
    data=[out("Data_Compare", "비교표", "Task_Compare", "입찰/{입찰번호}_비교.md", template="# {입찰번호} 견적 비교\n\n{비교표}\n\n{요약}", store_as="비교표경로")],
    variables=[("견적", "dict", "Recv_Quote (메시지 본문)", "{공급사, 단가, 납기, 조건, 회신메일}"),
               ("견적목록", "list", "Task_Record", "누적"), ("응찰사메일", "list", "Task_Record", "견적의 회신 주소 모음")],
    cases=[Case("견적 3건 후 마감", {"입찰번호": "BID-2610-01", "마감시각": {"$now_plus": "PT20S"}, "품목": ["A4 용지 500박스"]}, {"응찰수": 3},
                {"Approve_Award": {"낙찰사": "가나상사", "사유": "최저가"}}, "견적 3건을 메시지로 넣은 뒤 마감 대기. `{\"$now_plus\": \"PT20S\"}`는 케이스를 돌리는 순간부터 20초 뒤 시각 (C14 케이스 입력 규칙)",
                messages=[dict(after_s=2, name="bid_quote", correlation="BID-2610-01", payload={"견적": {"공급사": "가나상사", "단가": 1002, "납기": "5일", "조건": "-", "회신메일": "q2@example.com"}}), dict(after_s=4, name="bid_quote", correlation="BID-2610-01", payload={"견적": {"공급사": "다라물산", "단가": 1004, "납기": "5일", "조건": "-", "회신메일": "q4@example.com"}}), dict(after_s=6, name="bid_quote", correlation="BID-2610-01", payload={"견적": {"공급사": "마바테크", "단가": 1006, "납기": "5일", "조건": "-", "회신메일": "q6@example.com"}})]),
           Case("유찰", {"입찰번호": "BID-2610-03", "마감시각": {"$now_plus": "PT3S"}, "품목": ["토너"]}, {"응찰수": 0}),
           # 취소는 **접수 마감을 거치지 않는다** (종료 끝 이벤트로 바로 끝난다) — `응찰수`는
           # 생기지 않는다. 그 길에서 실제로 있는 값을 본다.
           Case("공고 취소", {"입찰번호": "BID-2610-02", "마감시각": {"$now_plus": "P1D"}, "품목": ["토너"]}, {"견적목록": []}, description="취소 메시지를 받으면 취소 통보 후 전체 종료",
                messages=[dict(after_s=2, name="bid_cancelled", correlation="BID-2610-02", payload={})])],
    features=["받기 태스크 루프 + 경계 타이머(마감) + 경계 메시지(취소, 상관 키 `입찰번호`)", "루프백 흐름", "경계 타이머에 **고정 시각** (기간이 아니라)",
              "종료(terminate) 끝 이벤트"],
    lessons=["처음에는 「견적 접수」를 하위 프로세스로 묶고 마감 경계를 붙였다. 그런데 **중단 경계가 끊은 하위 프로세스는 안에서 만든 변수를 내보내지 않는다**(BPMN 표준, 프로토타입 시나리오 2에서 확인) — 마감 순간 견적목록이 사라진다. 그래서 받기 태스크에 직접 경계를 붙이고, 누적 변수는 바깥에 둔다.",
             "받기를 다시 기다릴 때마다 경계 타이머가 새로 시작된다 — 기간을 상수(`P5D`)로 두면 마감이 계속 밀린다. **고정된 시각**을 기한으로 준다 (C14는 ISO 기간과 ISO 시각을 모두 받는다). 처음에는 남은 기간을 매번 계산하려 했는데, `기간()`은 `{from,to}`를 주는 다른 도우미다 — 인수 시험이 그것을 잡았다.",
             "취소를 신호로 그리기 쉽지만, 신호는 **한 실행 안의 가지 사이**에서만 쓴다 (C14). 바깥에서 특정 입찰을 멈추려면 메시지 + 상관 키(`chk:receive`를 경계에)로 보낸다.",
             "견적이 0건이면 AI 비교가 빈 표를 지어낼 수 있다 — 「유찰」 가지를 먼저 둔다."],
))

# ───────────────────────────── BX-12 ─────────────────────────────
EXAMPLES.append(Example(
    id="BX-12", file="bx12_shipping_fee", name="배송비 계산", dept="구매·영업·물류",
    origin="프로토타입 시나리오 6 (제안만 됨) + 기능 예제 discount_policy.dmn", 
    run_location="server", trigger="BPM 프로세스 호출 — 견적(BX-15)·주문 처리에서 부름",
    background="""
지역·무게·회원 등급으로 배송비를 정한다. 다른 BPM 프로세스가 호출해 쓰는 **공유 BPM 프로세스**다. 공유 BPM 프로세스는 부르는 쪽 패키지에 **복사되어** 들어간다 (용어집). 규칙이 바뀌면 이 원본과 DMN을 고치고, 부르는 BPM 프로세스들을 다시 패키징·배포한다. 분기마다 현업이 표만 고치는 것이 목표다 (프로토타입 시나리오 6).
""",
    why_location="계산뿐 — 서버. 서버 BPM 프로세스가 부르는 공유 BPM 프로세스도 서버에서 돌 수 있어야 한다 (ADR-0015 §3, C1 R3).",
    inputs=[("지역", "string", True, "수도권/지방/도서산간"), ("무게", "number", True, "kg"), ("등급", "string", True, "일반/우수/VIP")],
    nodes=[
        start("Start"),
        rule("Task_Fee", "배송비 정하기", "shipping_fee", {"지역": "지역", "무게": "무게", "등급": "등급"}, {"배송비": "fee", "근거": "reason"}),
        end("End"),
    ],
    flows=[f("Start", "Task_Fee"), f("Task_Fee", "End")],
    outputs=["배송비", "근거"],
    decisions=[Decision("shipping_fee", "배송비", [("등급", "등급", "string"), ("지역", "지역", "string"), ("무게", "무게", "number")],
                        [("fee", "number"), ("reason", "string")],
                        [(['"VIP"', "-", "-"], ["0", '"VIP 무료"'], ""),
                         (["-", '"도서산간"', "-"], ["8000", '"도서산간"'], ""),
                         (["-", "-", "> 20"], ["6000", '"20kg 초과"'], ""),
                         (['"우수"', "-", "-"], ["1500", '"우수 할인"'], ""),
                         (["-", '"지방"', "-"], ["3500", '"지방"'], ""),
                         (["-", "-", "-"], ["3000", '"기본"'], "")])],
    cases=[Case("기본", {"지역": "수도권", "무게": 2, "등급": "일반"}, {"배송비": 3000}),
           Case("VIP 도서산간", {"지역": "도서산간", "무게": 30, "등급": "VIP"}, {"배송비": 0}, description="FIRST 정책 — 위 규칙이 이긴다"),
           Case("무거운 지방", {"지역": "지방", "무게": 25, "등급": "일반"}, {"배송비": 6000}),
           Case("무게 경계값", {"지역": "수도권", "무게": 20, "등급": "일반"}, {"배송비": 3000}, description="20kg은 초과가 아님")],
    features=["DMN 결정표(FIRST, 다중 출력)", "공유 BPM 프로세스 (BX-15가 호출)", "경계값 케이스"],
    lessons=["규칙 순서가 결과를 바꾼다 (FIRST) — 표 순서 자체가 업무 규칙이다. 경계값 케이스를 꼭 둔다.",
             "DMN 입력 타입을 number로 두지 않으면 `\"25\" > 20`이 문자열 비교가 된다."],
))

# ───────────────────────────── BX-13 ─────────────────────────────
EXAMPLES.append(Example(
    id="BX-13", file="bx13_return_processing", name="반품 처리", dept="구매·영업·물류",
    origin="프로토타입 시나리오 7 (제안만 됨 — 폴더 감시 조건 시작 → 여기서는 메시지 시작)",
    run_location="server", trigger="메시지 `return_request` — 쇼핑몰 반품 신청",
    background="""
고객이 반품을 신청하면 사유를 AI로 분류하고(단순 변심/불량/오배송), 물류센터에서 「입고 완료」 메시지가 올 때까지 기다린다. 입고 검수 결과에 따라 환불하거나 고객에게 반품 불가를 알린다. 14일 안에 입고되지 않으면 신청을 자동 취소한다.
""",
    why_location="외부 시스템 메시지를 며칠 기다림 — 서버.",
    inputs=[("반품번호", "string", True, ""), ("주문번호", "string", True, ""), ("사유", "string", True, "고객이 쓴 글"), ("금액", "int", True, ""), ("고객메일", "string", True, "")],
    nodes=[
        start("Start", "반품 신청", kind="message", message="return_request"),
        ai("Task_Classify", "사유 분류",
           goal("`사유`는 고객이 직접 쓴 반품 사유다.", "단순변심 / 불량 / 오배송 중 하나로 분류하고 근거를 한 줄로 적는다.",
                "환불 여부나 금액을 판단하지 않는다.", "- `분류`: string (단순변심|불량|오배송)\n- `근거`: string"),
           "llm", {"분류": "string", "근거": "string"}),
        recv("Recv_Arrived", "입고 대기", "return_arrived", "반품번호", payload=["검수통과", "검수메모"]),
        xgw("Gw_Inspect", "검수 결과"),
        svc("Task_Refund", "환불", "shop", "refund", {"order_id": "주문번호", "amount": "환불액"}, {"환불결과": "result"}),
        mail("Task_Reject", "반품 불가 안내", ["{고객메일}"], "[{주문번호}] 반품 불가 안내", "검수 결과: {검수메모}"),
        mail("Task_Cancelled", "자동 취소 안내", ["{고객메일}"], "[{주문번호}] 반품 신청 취소", "14일 안에 상품이 도착하지 않아 신청이 취소되었습니다."),
        script("Task_Amount", "환불액 계산", "환불액 = 금액 - (0 if 분류 in ('불량', '오배송') else 3000)"),
        end("End"),
    ],
    flows=[f("Start", "Task_Classify"), f("Task_Classify", "Recv_Arrived"), f("Recv_Arrived", "Gw_Inspect"),
           f("Gw_Inspect", "Task_Amount", "검수통과", "통과"), f("Gw_Inspect", "Task_Reject", default=True, name="불가"),
           f("Task_Amount", "Task_Refund"), f("Task_Refund", "End"), f("Task_Reject", "End"),
           f("Bnd_Timeout", "Task_Cancelled"), f("Task_Cancelled", "End")],
    boundaries=[bnd("Bnd_Timeout", "Recv_Arrived", "timer", "14일", duration="P14D")],
    service_keys={"shop": "sales-shop"}, extensions=[{"id": "shop", "version": ">=1,<2"}],
    variables=[("검수통과", "bool", "Recv_Arrived (메시지 본문)", "물류센터가 보냄"), ("검수메모", "string", "Recv_Arrived", ""),
               ("환불액", "int", "Task_Amount", "단순변심이면 반품비 3,000원 차감")],
    cases=[Case("불량 환불", {"반품번호": "RT-01", "주문번호": "OD-77", "사유": "전원이 안 켜져요", "금액": 59000, "고객메일": "c@example.com"},
                {"분류": "불량", "환불액": 59000},
                messages=[dict(after_s=5, name="return_arrived", correlation="RT-01", payload={"검수통과": True, "검수메모": ""})]),
           Case("단순 변심", {"반품번호": "RT-02", "주문번호": "OD-78", "사유": "색이 마음에 안 들어요", "금액": 30000, "고객메일": "c@example.com"},
                {"분류": "단순변심", "환불액": 27000},
                messages=[dict(after_s=5, name="return_arrived", correlation="RT-02", payload={"검수통과": True, "검수메모": ""})]),
           Case("검수 불가", {"반품번호": "RT-03", "주문번호": "OD-79", "사유": "사용감이 있어요", "금액": 30000, "고객메일": "c@example.com"}, {"검수통과": False},
                messages=[dict(after_s=5, name="return_arrived", correlation="RT-03", payload={"검수통과": False, "검수메모": "사용 흔적"})])],
    features=["메시지 시작 + 받기 태스크(상관 키)", "받기 태스크의 중단 타이머(자동 취소)", "AI 분류 → 스크립트 계산 → 서비스 앱 작업",
              "부작용 있는 작업(환불)의 멱등 — C11 키"],
    lessons=["AI는 분류만, 금액 계산은 스크립트 — 금액이 AI 출력에 직접 기대지 않게 한다.",
             "환불은 같은 요청이 두 번 가면 안 된다 — 사내 확장 `shop`은 C11 서비스 앱이라 멱등 키(실행·노드·시도 단위)로 막는다.",
             "프로토타입 시나리오 7은 「폴더에 신청서가 떨어지면」 조건 시작으로 기획됐다. 조건 시작은 쓰지 않으므로(C14) 쇼핑몰이 메시지를 보내게 한다.",
             "입고 메시지가 받기 태스크보다 먼저 오면(분류 AI가 도는 중) C12가 `no_receiver`로 거부한다 — 메시지 보관은 README 「아직 정하지 않은 것」."],
))

# ───────────────────────────── BX-14 ─────────────────────────────
EXAMPLES.append(Example(
    id="BX-14", file="bx14_supplier_portal_orders", name="공급사 포털 주문 내역 수집", dept="구매·영업·물류",
    origin="프로토타입 시나리오 8 (제안만 됨 — 웹 세션·프로필 유지) → UI 태스크로", 
    run_location="pc", trigger="타이머 — 매일 08:00 (PC Bot)",
    background="""
API가 없는 공급사 웹 포털에서 어제 주문 내역 표를 읽고, 사내 공유 시트(xlsx)에 덧붙인다. 로그인 세션은 그 PC의 브라우저 프로필(`supplier-portal`)에 남아 있다. 세션이 끊기거나 2단계 인증을 요구하면 확인 창이 뜨고, 사람이 로그인한 뒤 Bot이 이어간다.
""",
    why_location="API가 없는 웹 화면, 사내 인증서·2단계 인증이 걸린 브라우저 프로필 → **PC**. 결과 파일 덧붙이기는 PC에서 같이 한다.",
    inputs=[("조회일", "string", False, "`YYYY-MM-DD`, 비우면 어제")],
    nodes=[
        start("Start", "매일 08:00", kind="timer", cycle="0 8 * * *"),
        script("Task_Date", "조회일 정하기", "조회일 = 조회일 or 어제()"),
        ui("Task_Orders", "주문 내역 읽기", "supplier.portal.orders",
           [dict(key="filter.date", action="fill", value="{조회일}"), dict(key="filter.search", action="click"),
            dict(key="orders.table", action="read_table", result="주문")]),
        ai("Task_Append", "공유 시트에 덧붙이기",
           goal("`주문`은 포털 표의 줄 목록이다. 업무 파라미터 `시트경로`가 공유 xlsx다.",
                "`주문`을 시트 마지막 줄 다음에 덧붙이고 저장한다. 이미 같은 주문번호가 있으면 건너뛴다.",
                "기존 줄을 고치거나 지우지 않는다.", "- `추가건수`: int\n- `건너뜀`: int"),
           "doc", {"추가건수": "int", "건너뜀": "int"}, tools=["excel_writer_tool"], params={"시트경로": "\\\\fileserver\\구매\\주문수집.xlsx"}),
        end("End"),
    ],
    flows=[f("Start", "Task_Date"), f("Task_Date", "Task_Orders"), f("Task_Orders", "Task_Append"), f("Task_Append", "End")],
    service_keys={"ui-automation": "purchase-portal"}, extensions=[{"id": "ui-automation", "version": ">=0.4,<0.5"}],
    defaults={"confirm_triggers": ["로그인 화면", "2단계 인증 화면", "캡차"], "forbidden_actions": ["주문 취소·수정 버튼을 누르지 않는다"], "web": {"profile": "supplier-portal"}},
    cases=[Case("어제 주문", {"조회일": "2026-09-30"}, {"추가건수": 3}),
           Case("같은 날 다시 실행", {"조회일": "2026-09-30"}, {"추가건수": 0, "건너뜀": 3}, description="멱등 — 중복 덧붙이지 않음"),
           Case("로그인 만료", {"조회일": "2026-09-30"}, {}, manual=True, description="프로필 세션을 지우고 실행 — 확인 창이 뜨고 사람이 로그인하면 계속")],
    features=["브라우저 프로필 세션 + 확인 트리거로 로그인 처리 (Bot이 비밀번호를 다루지 않음)", "확인 트리거(로그인·2단계 인증·캡차)", "PC의 doc AI 태스크(공유 폴더 파일)",
              "재실행 멱등 (주문번호로 건너뛰기)"],
    lessons=["로그인 정보를 목표·파라미터·UI 스텝 값에 쓰면 패키지에 비밀이 들어간다 — 로그인은 사람이 프로필에 해 두고, 끊기면 확인 트리거로 (CLAUDE.md 보안 규칙).",
             "포털 화면이 바뀌면 셀렉터 사다리 + 자가 치유(C8)가 먼저 버틴다. 치유가 한도를 넘으면 전환(escalated) — PC Bot은 확인 창으로 넘긴다 (C10).",
             "매일 돌리되 「어제」만 읽으면 실행이 하루 빠졌을 때 구멍이 난다 — 재실행 멱등(주문번호로 건너뛰기) 덕분에 조회일을 입력으로 넣어 다시 돌리면 된다.",
             "「같은 날 다시 실행」 케이스를 처음부터 둔다 — 재시도·재실행이 중복을 만들지 않는지."],
))

# ───────────────────────────── BX-15 ─────────────────────────────
EXAMPLES.append(Example(
    id="BX-15", file="bx15_quotation", name="견적서 작성", dept="구매·영업·물류",
    origin="새로 설계", 
    run_location="server", trigger="메시지 `quote_request` — CRM의 견적 요청",
    background="""
영업 담당이 CRM에서 견적을 요청하면 품목 단가를 ERP에서 가져오고, 배송비는 공유 BPM 프로세스 BX-12를 호출해 정한다. 할인율이 10%를 넘으면 영업팀장 결재를 받는다. 견적서 문서를 만들어 CRM에 첨부한다.
""",
    why_location="API·계산·결재 — 서버.",
    inputs=[("요청번호", "string", True, ""), ("고객", "dict", True, "{이름, 지역, 등급}"), ("품목", "list", True, "{코드, 수량}"), ("할인율", "number", False, "0~1")],
    nodes=[
        start("Start", "견적 요청", kind="message", message="quote_request"),
        svc("Task_Price", "단가 조회", "erp", "get_prices", {"codes": "품목"}, {"단가표": "prices"}),
        script("Task_Weight", "무게·소계",
               "단가 = 표를사전(단가표, '코드')\n"
               "소계 = sum(x['수량'] * 단가[x['코드']]['단가'] for x in 품목)\n"
               "무게 = round(sum(x['수량'] * 단가[x['코드']]['무게'] for x in 품목), 2)\n"
               "할인율 = 할인율 or 0\n승인 = True\n조정할인율 = None"),
        call("Call_Shipping", "배송비 (BX-12)", "Proc_bx12_shipping_fee", {"지역": "고객.지역", "무게": "무게", "등급": "고객.등급"}, {"배송비": "배송비"}),
        xgw("Gw_Discount", "할인 10% 초과?"),
        appr("Approve_Discount", "할인 결재", "견적 할인 승인", ["고객", "소계", "할인율", "배송비"],
             [fld("승인", "승인합니까?", "bool", True), fld("조정할인율", "조정 할인율", "number")], location="center"),
        script("Task_Total", "합계", "할인율 = (조정할인율 if 조정할인율 is not None else 할인율) if 승인 else 0.1\n합계 = round(소계 * (1 - 할인율)) + 배송비"),
        ai("Task_Doc", "견적서 문장",
           goal("견적 수치(`소계`, `할인율`, `배송비`, `합계`)는 이미 확정되었다.", "고객 `고객.이름`에게 보낼 견적서 인사말과 조건 문단을 쓴다.",
                "수치를 바꾸거나 새 조건을 만들지 않는다.", "- `문단`: string"), "llm", {"문단": "string"}),
        svc("Task_Attach", "CRM에 첨부", "crm", "attach_document", {"request_id": "요청번호", "file": "견적서경로"}, {"첨부결과": "result"}),
        end("End"),
    ],
    flows=[f("Start", "Task_Price"), f("Task_Price", "Task_Weight"), f("Task_Weight", "Call_Shipping"), f("Call_Shipping", "Gw_Discount"),
           f("Gw_Discount", "Approve_Discount", "할인율 > 0.1", "초과"), f("Gw_Discount", "Task_Total", default=True, name="이하"),
           f("Approve_Discount", "Task_Total"), f("Task_Total", "Task_Doc"), f("Task_Doc", "Task_Attach"), f("Task_Attach", "End")],
    data=[out("Data_Quote", "견적서", "Task_Doc", "견적/{요청번호}.md", template="# 견적서 {요청번호}\n\n{문단}\n\n소계 {소계} / 할인 {할인율} / 배송비 {배송비} / 합계 {합계}", store_as="견적서경로")],
    service_keys={"erp": "sales-erp", "crm": "sales-crm"}, extensions=[{"id": "erp", "version": ">=1,<2"}, {"id": "crm", "version": ">=1,<2"}],
    cases=[Case("할인 없음", {"요청번호": "Q-01", "고객": {"이름": "가나상사", "지역": "수도권", "등급": "일반"}, "품목": [{"코드": "P-100", "수량": 10}]}, {"배송비": 3000}),
           Case("할인 15%", {"요청번호": "Q-02", "고객": {"이름": "다라물산", "지역": "지방", "등급": "우수"}, "품목": [{"코드": "P-100", "수량": 100}], "할인율": 0.15},
                {"할인율": 0.12}, {"Approve_Discount": {"승인": True, "조정할인율": 0.12}})],
    called=["bx12_shipping_fee"],
    features=["BPM 프로세스 호출(call activity) — 넘기는 변수만 넘어감", "점 표기 입력 매핑(`고객.지역`)", "결재로 값 조정, 반려하면 허용 한도(10%)로", "AI는 문장만, 수치는 스크립트"],
    lessons=["호출된 BPM 프로세스(BX-12)는 이 패키지에 복사되어 들어간다 — BX-12를 고치면 이 BPM 프로세스도 다시 패키징해야 반영된다.",
             "호출 매핑에 적은 변수만 오간다 (C14 `call`). 프로토타입은 매핑이 비면 전부 넘겼다 — 그 동작에 기대지 않는다."],
))

# ───────────────────────────── BX-16 ─────────────────────────────
EXAMPLES.append(Example(
    id="BX-16", file="bx16_reorder_proposal", name="재고 발주 제안 (서버) → ERP 입력 (PC)", dept="구매·영업·물류",
    origin="새로 설계 — 서버와 PC를 나누는 대표 예", 
    run_location="server", trigger="타이머 — 매일 07:00",
    background="""
재고 데이터를 API로 읽어 안전재고 아래로 떨어진 품목의 발주 수량을 계산하고 구매 담당이 확인한다. 확인된 발주는 **ERP 화면 입력이 필요한데 ERP에 API가 없다.** 그래서 서버 BPM 프로세스는 「발주 입력」 PC BPM 프로세스(BX-17)의 작업 지시를 만든다. **현재 계약에는 서버 BPM 프로세스가 PC 작업을 만드는 요소가 없다** (「PC 위임」은 [ADR-0016](../decisions/0016-server-first.md) §3에 제안만 — 서버 BPM 프로세스의 Call Activity가 PC BPM 프로세스를 부르는 모양이며, schema 1에서는 C1 R3가 거부한다). 이 예제는 그 자리를 사내 확장 `center-jobs`(Center 작업 지시 API를 감싼 서비스 앱 — Center 연동용 키는 그 앱이 가진다)로 메운다.
""",
    why_location="계산·결재는 서버, 화면 입력만 PC — **업무를 두 BPM 프로세스로 쪼갠다.** PC 쪽은 짧게 끝나 실행 자리를 오래 잡지 않는다.",
    nodes=[
        start("Start", "매일 07:00", kind="timer", cycle="0 7 * * 1-5"),
        svc("Task_Stock", "재고 읽기", "wms", "list_stock", {}, {"재고": "items"}),
        script("Task_Calc", "발주량 계산", "제안 = [dict(품목=x.code, 수량=x.safety * 2 - x.qty) for x in 재고 if x.qty < x.safety]\n제안수 = len(제안)"),
        xgw("Gw_Any", "제안 있음?"),
        appr("Approve_Order", "발주 확인", "발주 제안 확인", ["제안"], [fld("승인", "제안대로 발주합니까?", "bool", True), fld("메모", "메모")], location="center"),
        xgw("Gw_Order", "발주?"),
        script("Task_Confirm", "확정", "확정 = 제안"),
        svc("Task_Dispatch", "ERP 입력 작업 지시", "center-jobs", "create_job",
            {"bpm_process": "'bx17_erp_po_entry'", "target": "'group:구매-PC'", "inputs": "{'발주': 확정}"}, {"작업번호": "job_id"}),
        end("End"),
    ],
    flows=[f("Start", "Task_Stock"), f("Task_Stock", "Task_Calc"), f("Task_Calc", "Gw_Any"),
           f("Gw_Any", "Approve_Order", "제안수 > 0", "있음"), f("Gw_Any", "End", default=True, name="없음"),
           f("Approve_Order", "Gw_Order"), f("Gw_Order", "Task_Confirm", "승인", "발주"), f("Gw_Order", "End", default=True, name="보류"),
           f("Task_Confirm", "Task_Dispatch"), f("Task_Dispatch", "End")],
    service_keys={"wms": "scm-wms", "center-jobs": "scm-center-jobs"}, extensions=[{"id": "wms", "version": ">=1,<2"}, {"id": "center-jobs", "version": ">=1,<2"}],
    cases=[Case("부족 2품목", {}, {"제안수": 2, "작업번호": "*"}, {"Approve_Order": {"승인": True}}, "모의 WMS가 2품목을 안전재고 아래로 돌려준다")],
    features=["서버 + PC 두 BPM 프로세스로 쪼개기", "작업 지시를 사내 확장 서비스 앱으로 (PC 위임의 공백 표시)", "결재 반려 시 발주 안 함"],
    lessons=["한 BPM 프로세스 안에 서버 일과 PC 일을 섞지 않는다 — 실행 위치는 BPM 프로세스 단위다 (ADR-0015).",
             "웹훅 태스크로 Center API를 직접 부르면 키를 붙일 방법이 없다 (웹훅은 인증 헤더를 갖지 않음, 비밀을 BPMN에 둘 수 없음) — 그래서 서비스 앱으로 감쌌다.",
             "PC 위임이 확정되면(ADR-0016 §3, M7) 이 서비스 앱 태스크를 BX-17을 부르는 Call Activity로 바꾼다. 결과·실패는 Call Activity 출력과 오류 경계로 돌아온다."],
))

# ───────────────────────────── BX-17 ─────────────────────────────
EXAMPLES.append(Example(
    id="BX-17", file="bx17_erp_po_entry", name="ERP 발주 화면 입력", dept="구매·영업·물류",
    origin="새로 설계 — BX-16의 PC 쪽", 
    run_location="pc", trigger="작업 지시 — BX-16이 만든다 (대상: 구매 PC 그룹)",
    background="""
확정된 발주 목록을 받아 ERP 데스크톱 클라이언트의 발주 입력 화면에 한 건씩 입력하고 발주번호를 읽어 온다. 입력이 끝나면 결과를 Center에 남긴다 (작업 결과 = 실행 결과).
""",
    why_location="API 없는 데스크톱 ERP 화면 → PC. 결재가 없어 짧게 끝난다.",
    inputs=[("발주", "list", True, "{품목, 수량}")],
    nodes=[
        start("Start", "작업 지시"),
        ui("Task_Entry", "발주 입력", "erp.desktop.po_entry",
           [dict(key="po.item", action="fill", value="{건.품목}"), dict(key="po.qty", action="fill", value="{건.수량}"),
            dict(key="po.save", action="click"), dict(key="po.number", action="read", result="발주번호")],
           loop=dict(collection="발주", item="건", result="발주번호", collect_into="발주번호목록")),
        end("End"),
    ],
    flows=[f("Start", "Task_Entry"), f("Task_Entry", "End")],
    boundaries=[],
    service_keys={"ui-automation": "purchase-erp-ui"}, extensions=[{"id": "ui-automation", "version": ">=0.4,<0.5"}],
    defaults={"confirm_triggers": ["재고 부족 경고 창"], "forbidden_actions": ["삭제 버튼을 누르지 않는다"], "desktop": {"app": "ERP Client"}},
    cases=[Case("2건 입력", {"발주": [{"품목": "P-100", "수량": 40}, {"품목": "P-200", "수량": 10}]}, {"발주번호목록": ["*", "*"]}, description="`*`는 「값이 있음」")],
    features=["데스크톱 UI 태스크 반복", "다른 BPM 프로세스가 만든 작업 지시로 시작", "확인 트리거(경고 창)"],
    lessons=["데스크톱 자동화는 Windows에서 S1 스파이크로 먼저 검증한다 (UIA 백엔드).",
             "건마다 저장 → 발주번호 읽기를 한 세트로. 중간에 실패한 실행을 그대로 다시 돌리면 이미 입력된 건이 또 들어간다 — Worker는 재시작 때 조작 스텝을 자동으로 다시 하지 않으므로(C10) 사람이 ERP에서 확인한 뒤 남은 건만 넣는다."],
))
