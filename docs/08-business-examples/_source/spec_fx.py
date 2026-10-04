"""기능 예제 (FX-01 ~ FX-20) — BPMN 요소·플랫폼 기능 하나씩. 프로토타입 `processes/example_*.bpmn`을 새 형식(C14)으로 옮기고 공백을 메웠다.

기능 예제는 Studio 시험·엔진 회귀의 최소 단위다. 업무 예제(BX)보다 작고, 실행 시간이 짧게(대부분 10초 안) 만든다.
"""

from exdsl import *  # noqa: F401,F403

EXAMPLES = []


def FX(id, file, name, origin, run_location, trigger, background, why, nodes, flows, **kw):
    EXAMPLES.append(Example(id=id, file=file, name=name, dept="기능 예제", origin=origin,
                            run_location=run_location, trigger=trigger, background=background,
                            why_location=why, nodes=nodes, flows=flows, kind="feature", **kw))


SRV = "서버 기본 (ADR-0016)."

FX("FX-01", "fx01_api_call", "API AI 태스크", "프로토타입 example_api", "server", "수동 실행",
   "공개 API 한 번 호출해 값을 꺼낸다. 업무 파라미터로 주소를 두면 재생 때 그대로 쓰인다.", SRV,
   [start("Start"),
    ai("Task_Api", "API 호출", goal("업무 파라미터 `주소`가 JSON API다.", "GET으로 한 번 불러 `rates.KRW`를 꺼낸다.", "값을 지어내지 않는다. 응답에 없으면 실패한다.", "- `원화`: number"),
       "api", {"원화": "number"}, tools=["http_request_tool"], params={"주소": "https://api.frankfurter.dev/v1/latest?base=USD&symbols=KRW"}),
    end("End")],
   [f("Start", "Task_Api"), f("Task_Api", "End")],
   cases=[Case("기본", {}, {"원화": {"$gt": 0}})],
   features=["`domain: api`", "업무 파라미터", "결정 수행 재생"],
   lessons=["결과 타입을 적지 않으면 문자열 `\"1380.5\"`가 와서 뒤 비교가 틀렸다 — 결과에 타입을 적는다."])

FX("FX-02", "fx02_business_rule", "규칙 태스크 (DMN)", "프로토타입 example_business_rule + discount_policy.dmn", "server", "수동 실행",
   "금액·등급으로 할인율과 사유를 정한다.", SRV,
   [start("Start"), rule("Task_Rule", "할인 정하기", "discount_policy", {"amount": "금액", "grade": "등급"}, {"할인율": "discount", "사유": "discount_reason"}),
    script("Task_Price", "최종가", "최종가 = round(금액 * (1 - 할인율))"), end("End")],
   [f("Start", "Task_Rule"), f("Task_Rule", "Task_Price"), f("Task_Price", "End")],
   inputs=[("금액", "int", True, ""), ("등급", "string", True, "")],
   decisions=[Decision("discount_policy", "할인 정책", [("금액", "amount", "number"), ("등급", "grade", "string")], [("discount", "number"), ("discount_reason", "string")],
                       [([">= 1000000", '"VIP"'], ["0.2", '"VIP 대량 주문"'], ""), ([">= 1000000", "-"], ["0.1", '"대량 주문"'], ""),
                        (["-", '"VIP"'], ["0.05", '"VIP"'], ""), (["-", "-"], ["0", '"할인 없음"'], "")])],
   cases=[Case("VIP 대량", {"금액": 1500000, "등급": "VIP"}, {"할인율": 0.2, "최종가": 1200000}),
          Case("일반 소량", {"금액": 50000, "등급": "일반"}, {"할인율": 0})],
   features=["`businessRuleTask` + `chk:rule` 입력·출력 매핑", "다중 출력 DMN"],
   lessons=["프로토타입은 DMN 입력 이름(amount)과 변수 이름(금액)이 같아야 했다 — 새 형식은 `input` 매핑으로 잇는다."])

FX("FX-03", "fx03_call_mapping", "BPM 프로세스 호출과 매핑", "프로토타입 example_call_mapping", "server", "수동 실행",
   "같은 하위 BPM 프로세스(FX-03b)를 다른 입력으로 두 번 부르고 출력 이름을 나눈다.", SRV,
   [start("Start"), script("Task_Prepare", "두 금액", "신청자금액 = 3000000\n보증인금액 = 800000"),
    call("Call_A", "신청자", "Proc_fx03b_amount_branch", {"금액": "신청자금액"}, {"신청자구분": "구분"}),
    call("Call_B", "보증인", "Proc_fx03b_amount_branch", {"금액": "보증인금액"}, {"보증인구분": "구분"}),
    script("Task_Report", "정리", "요약 = f'{신청자구분}/{보증인구분}'"), end("End")],
   [f("Start", "Task_Prepare"), f("Task_Prepare", "Call_A"), f("Call_A", "Call_B"), f("Call_B", "Task_Report"), f("Task_Report", "End")],
   cases=[Case("기본", {}, {"신청자구분": "고액", "보증인구분": "소액"})], called=["fx03b_amount_branch"],
   features=["`chk:call` 입력·출력 매핑", "같은 대상 두 번 호출"],
   lessons=["출력 매핑 없이 두 번 부르면 `구분`이 덮어써진다."])

FX("FX-03b", "fx03b_amount_branch", "금액 분기 (호출 대상)", "프로토타입 example_call_mapping의 하위", "server", "BPM 프로세스 호출",
   "금액이 100만 원 이상이면 고액.", SRV,
   [start("Start"), xgw("Gw", "100만 이상?"), script("Task_Big", "고액", "구분 = '고액'"), script("Task_Small", "소액", "구분 = '소액'"), end("End")],
   [f("Start", "Gw"), f("Gw", "Task_Big", "금액 >= 1000000", "예"), f("Gw", "Task_Small", default=True, name="아니오"), f("Task_Big", "End"), f("Task_Small", "End")],
   inputs=[("금액", "int", True, "")], outputs=["구분"], cases=[Case("고액", {"금액": 1000000}, {"구분": "고액"}), Case("소액", {"금액": 999999}, {"구분": "소액"})],
   features=["배타 게이트웨이 + 기본 흐름", "경계값"])

FX("FX-04", "fx04_folder_poll", "폴더 감시 (조건 시작 대체)", "프로토타입 example_conditional_start", "server", "타이머 — 5분마다",
   "받은 폴더에 파일이 있으면 처리한다. 프로토타입은 조건 시작 이벤트를 썼지만 엔진이 조건을 계속 평가하지 못했다 → **타이머 + 게이트웨이**로 바꾼다.", SRV,
   [start("Start", "5분마다", kind="timer", cycle="*/5 * * * *"),
    flist("Task_List", "파일 목록", "{감시폴더}", "파일", count_as="건수"),
    xgw("Gw_Any", "있음?"), appr("Approve_Confirm", "처리 확인", "받은 파일 처리", ["파일"], [fld("처리", "처리함", "bool", True)], location="center"),
    end("End_None", "없음"), end("End")],
   [f("Start", "Task_List"), f("Task_List", "Gw_Any"), f("Gw_Any", "Approve_Confirm", "건수 > 0", "있음"), f("Gw_Any", "End_None", default=True, name="없음"),
    f("Approve_Confirm", "End")],
   inputs=[("감시폴더", "string", False, "")],
   cases=[Case("빈 폴더", {"감시폴더": "samples/inbox-empty"}, {"건수": 0}), Case("2건", {"감시폴더": "samples/inbox"}, {"건수": 2}, {"Approve_Confirm": {"처리": True}})],
   features=["조건 시작 이벤트는 지원하지 않음 (C14) → 타이머 폴링", "끝 이벤트 둘", "파일 목록 태스크 (`chk:fileList`)"],
   lessons=["조건 시작은 「무엇이 바뀌면 다시 평가하나」가 정의되지 않아 프로토타입에서 한 번만 돌았다.", "폴링은 실행이 자주 생긴다 — 「없음」 실행은 이력에서 접어 보이게(CON-04 필터).",
            "폴더를 훑는 것은 식이 아니라 태스크다 — 디스크를 읽고 실행마다 결과가 달라진다 (ADR-0025·ADR-0026)."])

FX("FX-05", "fx05_desktop_autonomous", "데스크톱 AI 태스크 (자율)", "프로토타입 example_desktop", "pc", "PC Bot 수동 실행",
   "등록되지 않은 데스크톱 앱(계산기)을 AI가 보고 조작한다.", "데스크톱 화면 → PC.",
   [start("Start"), ai("Task_Calc", "계산기", goal("계산기 앱을 연다.", "`식`을 계산해 결과 표시값을 읽는다.", "다른 앱을 열지 않는다.", "- `결과`: number"),
                       "desktop", {"결과": "number"}), end("End")],
   [f("Start", "Task_Calc"), f("Task_Calc", "End")],
   inputs=[("식", "string", True, "")], 
   defaults={"desktop": {"app": "Calculator"}, "limits": {"timeout_s": 120}},
   cases=[Case("곱셈", {"식": "12*34"}, {"결과": 408})],
   features=["`domain: desktop` (자율)", "PC 전용 — 서버로 두면 B6 오류"],
   lessons=["Linux에서 합성 키 입력이 무시되는 일이 있었다 — Windows UIA로 S1에서 검증.", "반복 업무면 화면을 등록해 UI 태스크로 바꾼다."])

FX("FX-06", "fx06_document_read", "문서 AI 태스크", "프로토타입 example_document", "server", "수동 실행",
   "PDF 한 장에서 정해진 값을 읽는다.", SRV,
   [start("Start"), ai("Task_Read", "PDF 읽기", goal("`파일`은 견적서 PDF다.", "공급자·합계·유효기간을 읽는다.", "값을 계산하지 않는다.", "- `견적`: {공급자, 합계(int), 유효기간(date)}"),
                       "doc", {"견적": "dict"}, tools=["pdf_text_tool"]), end("End")],
   [f("Start", "Task_Read"), f("Task_Read", "End")],
   inputs=[("파일", "string", True, "")], cases=[Case("샘플", {"파일": "samples/docs/quote.pdf"}, {"견적": {"합계": 1320000}})],
   features=["`domain: doc`", "도구 지정"])

FX("FX-07", "fx07_email", "메일 보내기", "프로토타입 example_email", "server", "수동 실행",
   "변수를 넣은 제목·본문과 첨부 파일로 메일을 보낸다.", SRV,
   [start("Start"), script("Task_Body", "본문", "본문 = '안녕하세요'\n보고 = '# 보고\\n내용'"),
    mail("Task_Mail", "보내기", ["{받는사람}"], "[시험] {오늘}", "{본문}", attachments=["보고경로"], store_as="발송결과"), end("End")],
   [f("Start", "Task_Body"), f("Task_Body", "Task_Mail"), f("Task_Mail", "End")],
   data=[out("Data_Report", "보고", "Task_Body", "fx07/보고.md", template="{보고}", store_as="보고경로")],
   inputs=[("받는사람", "string", True, "")], cases=[Case("로컬 SMTP", {"받는사람": "test@example.com"}, {"발송결과": {"ok": True}})],
   features=["`sendTask` + `chk:email`", "파일 출력 → 첨부", "`store_as`"],
   lessons=["첨부는 파일 경로 **변수 이름**을 적는다 — 경로 문자열을 직접 쓰지 않는다."])

FX("FX-08", "fx08_error_boundary", "오류 경계와 대체 경로", "프로토타입 example_error_boundary", "server", "수동 실행",
   "API 조회가 실패하면 기본값을 쓰고, 어느 쪽이든 사람이 확인한다.", SRV,
   [start("Start"),
    ai("Task_Fetch", "환율 조회", goal("업무 파라미터 `주소`를 GET.", "`rates.KRW`를 꺼낸다.", "값을 지어내지 않는다. 응답이 없으면 실패한다 (오류 경계가 받는다).", "- `원화`: number"), "api", {"원화": "number"},
       tools=["http_request_tool"], params={"주소": "https://invalid.example/latest"}, limits={"timeout_s": 20, "max_steps": 3}),
    script("Task_Fallback", "기본값", "원화 = 1350\n대체 = True"),
    appr("Approve_Check", "확인", "환율 확인", ["원화", "대체"], [fld("확인", "확인", "bool", True)], location="center"), end("End")],
   [f("Start", "Task_Fetch"), f("Task_Fetch", "Approve_Check"), f("Bnd_Fail", "Task_Fallback"), f("Task_Fallback", "Approve_Check"), f("Approve_Check", "End")],
   boundaries=[bnd("Bnd_Fail", "Task_Fetch", "error", "실패", error="TASK_FAILED")],
   cases=[Case("주소 실패", {}, {"원화": 1350, "대체": True}, {"Approve_Check": {"확인": True}})],
   features=["오류 경계 `TASK_FAILED`", "실패 후 합류"],
   lessons=["프로토타입 오류 코드 `AgentFailed`는 새 형식에서 `TASK_FAILED`로 (C14).", "`error_message` 변수로 원인을 남긴다."])

FX("FX-09", "fx09_sequential_loop", "차례 반복", "프로토타입 example_loop", "server", "수동 실행",
   "경비 신청 여러 건을 한 건씩 판정하고 결과를 모은다.", SRV,
   [start("Start"),
    ai("Task_Judge", "한 건 판정", goal("`신청`은 경비 한 건이다.", "업무 규칙(영수증 있음, 50만 원 이하)에 맞으면 승인.", "다른 건과 비교하지 않는다. 금액을 바꾸지 않는다.", "- `판정`: {id, 승인(bool), 사유}"),
       "llm", {"판정": "dict"}, loop=dict(collection="신청목록", item="신청", result="판정", collect_into="판정목록")),
    script("Task_Total", "합계", "승인수 = len([x for x in 판정목록 if x.승인])"), end("End")],
   [f("Start", "Task_Judge"), f("Task_Judge", "Task_Total"), f("Task_Total", "End")],
   inputs=[("신청목록", "list", True, "")],
   cases=[Case("3건", {"신청목록": [{"id": 1, "금액": 30000, "영수증": True}, {"id": 2, "금액": 900000, "영수증": True}, {"id": 3, "금액": 10000, "영수증": False}]}, {"승인수": 1}),
          Case("빈 목록", {"신청목록": []}, {"승인수": 0})],
   features=["`multiInstanceLoopCharacteristics isSequential=true`", "`collect_into` 필수 (C14)", "빈 목록 케이스"],
   lessons=["`collect_into`가 없으면 마지막 결과만 남았다 — 필수로 바꿨다.", "반복 진행은 STU-08에서 `node_instance`별로 보인다."])

FX("FX-10", "fx10_operator_routing", "요청 라우팅 (운영 비서)", "프로토타입 example_operator", "server", "메시지 `work_request`",
   "요청을 AI가 분류해 세 가지 처리 중 하나로 보낸다. 각 처리에 실패 경계가 있다.", SRV,
   [start("Start", "요청", kind="message", message="work_request"),
    ai("Task_Triage", "분류", goal("`요청`은 직원 메시지다.", "intent를 exchange_rate | answer | web_summary 중 하나로.", "요청을 처리하지 않는다.", "- `intent`: string"), "llm", {"intent": "string"}),
    xgw("Gw_Intent", "종류?"),
    ai("Task_Rate", "환율 조회", goal("직원이 환율을 물었다. 공개 환율 API(업무 파라미터 `주소`)를 쓴다.", "USD/KRW 환율을 조회해 한 문장으로 답한다.", "환율 전망·투자 조언을 하지 않는다.", "- `답`: string"), "api", {"답": "string"}, tools=["http_request_tool"], params={"주소": "https://api.frankfurter.dev/v1/latest?base=USD&symbols=KRW"}),
    ai("Task_Answer", "답변", goal("`요청`은 직원 메시지다.", "`요청`에 짧게 답한다.", "사내 정책·규정은 지어내지 않는다 — 모르면 모른다고 답한다.", "- `답`: string"), "llm", {"답": "string"}),
    svc("Task_Web", "웹 요약", "web-reader", "summarize_url", {"url": "요청"}, {"답": "summary"}),
    script("Task_Fail", "실패 답", "답 = '처리하지 못했습니다: ' + error_message"),
    hook("Task_Reply", "회신", "{회신주소}", body="fields:[답]"), end("End")],
   [f("Start", "Task_Triage"), f("Task_Triage", "Gw_Intent"),
    f("Gw_Intent", "Task_Rate", "intent == 'exchange_rate'", "환율"), f("Gw_Intent", "Task_Web", "intent == 'web_summary'", "웹"), f("Gw_Intent", "Task_Answer", default=True, name="답변"),
    f("Task_Rate", "Task_Reply"), f("Task_Answer", "Task_Reply"), f("Task_Web", "Task_Reply"),
    f("Bnd_Rate", "Task_Fail"), f("Bnd_Answer", "Task_Fail"), f("Bnd_Web", "Task_Fail"), f("Task_Fail", "Task_Reply"), f("Task_Reply", "End")],
   boundaries=[bnd("Bnd_Rate", "Task_Rate", "error", "실패", error="TASK_FAILED"), bnd("Bnd_Answer", "Task_Answer", "error", "실패", error="TASK_FAILED"),
               bnd("Bnd_Web", "Task_Web", "error", "실패", error="TASK_FAILED")],
   inputs=[("요청", "string", True, "직원 메시지"), ("회신주소", "string", True, "")],
   service_keys={"web-reader": "ops-web-reader"}, extensions=[{"id": "web-reader", "version": ">=1,<2"}],
   cases=[Case("환율", {"요청": "오늘 달러 환율?", "회신주소": {"$test_receiver": "reply"}}, {"intent": "exchange_rate"}),
          Case("질문", {"요청": "회의실 예약 어떻게 해요?", "회신주소": {"$test_receiver": "reply"}}, {"intent": "answer"})],
   features=["메시지 시작 + AI 라우팅", "가지마다 오류 경계 → 한 실패 처리로 합류", "웹 읽기는 서버에서 확장(서비스 앱)으로 — 서버에서 `domain: web` 불가"],
   lessons=["프로토타입은 웹 요약을 WEB AI 태스크로 했다 → 서버 BPM 프로세스에서는 B6 오류. 서버용 웹 읽기 확장으로 바꿨다.",
            "기본 흐름을 「답변」으로 두면 분류가 이상한 값을 내도 멈추지 않는다."])

FX("FX-11", "fx11_parallel", "병렬 분기·합류", "프로토타입 example_parallel", "server", "수동 실행",
   "세 계산을 동시에 하고 모두 끝나면 합친다.", SRV,
   [start("Start"), pgw("Gw_Split"), script("Task_A", "A", "a = 1"), script("Task_B", "B", "b = 2"), script("Task_C", "C", "c = 3"), pgw("Gw_Join"),
    script("Task_Sum", "합", "합 = a + b + c"), end("End")],
   [f("Start", "Gw_Split"), f("Gw_Split", "Task_A"), f("Gw_Split", "Task_B"), f("Gw_Split", "Task_C"), f("Task_A", "Gw_Join"), f("Task_B", "Gw_Join"), f("Task_C", "Gw_Join"),
    f("Gw_Join", "Task_Sum"), f("Task_Sum", "End")],
   cases=[Case("기본", {}, {"합": 6})], features=["병렬 게이트웨이 짝"],
   lessons=["합류 게이트웨이를 빼면 뒤 태스크가 세 번 돈다."])

FX("FX-12", "fx12_daily_report", "타이머 시작 + 파일 출력", "프로토타입 example_schedule", "server", "타이머 — 매일 09:00",
   "매일 요약 파일을 만든다.", SRV,
   [start("Start", "매일 09:00", kind="timer", cycle="0 9 * * *"), script("Task_Summary", "요약", "요약 = f'{오늘} 요약'"), end("End")],
   [f("Start", "Task_Summary"), f("Task_Summary", "End")],
   data=[out("Data_Report", "일일 보고서", "Task_Summary", "일일/{오늘}.md", template="# {요약}", store_as="보고경로")],
   cases=[Case("기본", {}, {"보고경로": "*"})],
   features=["타이머 시작(cron)", "`dataObjectReference` + `chk:dataOutput`"],
   lessons=["경로에 `outputs/`를 다시 쓰면 `outputs/outputs/`가 된다 — 경로는 출력 루트 기준 상대 경로."])

FX("FX-13", "fx13_signal", "신호 던지기·받기", "프로토타입 example_signal", "server", "수동 실행",
   "가지 A가 준비되면 `ready` 신호를, 검사에서 문제가 나오면 `abort` 신호를 던진다. 가지 B는 `ready`를 기다렸다가 일하고, 일하는 중 `abort`가 오면 정리한다.", SRV,
   [start("Start"), pgw("Gw_Fork"),
    catch("Wait_A", "1초 뒤", "timer", duration="PT1S"),
    script("Task_Prepare", "준비 (A)", "준비 = True"), throw("Thr_Ready", "ready", "signal", "ready"),
    script("Task_Inspect", "검사 (A)", "result = 검사결과"), xgw("Gw_Problem", "문제?"), throw("Thr_Abort", "abort", "signal", "abort"),
    end("End_A", "A 끝"),
    catch("Wait_Ready", "ready 대기", "signal", signal="ready"), recv("Recv_Work", "본 작업 완료 받기", "work_done", "작업번호"),
    script("Task_Work", "본 작업 기록 (B)", "작업 = '완료'"),
    script("Task_Cleanup", "정리 (B)", "작업 = '중단'"), end("End_B", "B 끝")],
   [f("Start", "Gw_Fork"), f("Gw_Fork", "Wait_A"), f("Gw_Fork", "Wait_Ready"),
    f("Wait_A", "Task_Prepare"), f("Task_Prepare", "Thr_Ready"), f("Thr_Ready", "Task_Inspect"), f("Task_Inspect", "Gw_Problem"),
    f("Gw_Problem", "Thr_Abort", "result != 'ok'", "문제"), f("Gw_Problem", "End_A", default=True, name="정상"), f("Thr_Abort", "End_A"),
    f("Wait_Ready", "Recv_Work"), f("Recv_Work", "Task_Work"), f("Task_Work", "End_B"), f("Bnd_Abort", "Task_Cleanup"), f("Task_Cleanup", "End_B")],
   inputs=[("검사결과", "string", False, "", "ok"), ("작업번호", "string", False, "", "W-1")],
   boundaries=[bnd("Bnd_Abort", "Recv_Work", "signal", "abort", signal="abort")],
   cases=[Case("정상", {}, {"작업": "완료"}, messages=[dict(after_s=4, name="work_done", correlation="W-1", payload={})]),
          Case("문제", {"검사결과": "bad"}, {"작업": "중단"}, description="abort가 1초쯤 오므로 4초 뒤 완료 메시지는 받을 곳이 없다",
               messages=[dict(after_s=4, name="work_done", correlation="W-1", payload={})])],
   features=["중간 던지기 신호 / 중간 받기 신호 / 경계 신호", "한 실행 안의 가지 사이 신호 (C14 범위)", "중간 받기 타이머로 순서 잡기", "받기 태스크의 신호 경계"],
   lessons=["신호는 **한 실행 안의 가지 사이**에서만 오간다 (C14). 다른 실행·외부 시스템에 알리려면 메시지를 쓴다 (BX-11).",
            "받는 쪽이 아직 기다리지 않을 때 던진 신호는 사라진다. 가지 A 앞에 1초 대기를 두어 B가 먼저 `ready 대기`에 서게 한다 — 시험용 순서 잡기이며, 실제 업무에서는 신호에 순서를 기대지 않는다.",
            "`abort` 경계는 바깥 작업 완료를 기다리는 받기 태스크에 붙였다. 경계는 태스크에만 붙는다(이벤트에는 못 붙임). 순간에 끝나는 스크립트에 붙이면 신호가 닿기 전에 끝나 버린다."])

FX("FX-14", "fx14_timers", "중간 타이머와 결재 시간 제한", "프로토타입 example_timer", "server", "수동 실행",
   "3초 기다린 뒤 결재를 띄우고, 15초 안에 답이 없으면 보류 처리한다.", SRV,
   [start("Start"), catch("Wait", "3초 대기", "timer", duration="PT3S"),
    appr("Approve_Review", "15초 결재", "빠른 결재", ["오늘"], [fld("승인", "승인", "bool", True)], location="center"),
    script("Task_Answered", "응답", "결과 = '응답'"), script("Task_Timeout", "보류", "결과 = '보류'"), end("End")],
   [f("Start", "Wait"), f("Wait", "Approve_Review"), f("Approve_Review", "Task_Answered"), f("Bnd_Timeout", "Task_Timeout"),
    f("Task_Answered", "End"), f("Task_Timeout", "End")],
   boundaries=[bnd("Bnd_Timeout", "Approve_Review", "timer", "15초", duration="PT15S")],
   cases=[Case("응답", {}, {"결과": "응답"}, {"Approve_Review": {"승인": True}}), Case("시간 초과", {}, {"결과": "보류"})],
   features=["중간 받기 타이머", "결재 + 중단 타이머 경계"],
   lessons=["시간 초과로 끝난 결재는 「취소됨」(실패 아님)으로 표시된다."])

FX("FX-15", "fx15_web_form", "웹 양식 제출 (PC)", "프로토타입 example_web_form", "pc", "PC Bot 수동 실행",
   "웹 신청서를 채워 제출하고, 제출되면 담당자 연락처를 읽는다.", "사내 웹 화면 조작 → PC.",
   [start("Start"), script("Task_Prepare", "신청 내용", "신청 = dict(이름='홍길동', 내용='장비 요청')"),
    ui("Task_Submit", "제출", "intranet.request.form",
       [dict(key="form.name", action="fill", value="{신청.이름}"), dict(key="form.body", action="fill", value="{신청.내용}"),
        dict(key="form.submit", action="click", navigates=True), dict(key="result.message", action="read", result="제출메시지")]),
    xgw("Gw_Submitted", "제출됨?"),
    ui("Task_Lookup", "담당자 연락처", "intranet.request.done", [dict(key="owner.contact", action="read", result="연락처")]),
    script("Task_NotSubmitted", "미제출 기록", "메모 = '제출 실패'"), end("End")],
   [f("Start", "Task_Prepare"), f("Task_Prepare", "Task_Submit"), f("Task_Submit", "Gw_Submitted"),
    f("Gw_Submitted", "Task_Lookup", "'접수' in 제출메시지", "예"), f("Gw_Submitted", "Task_NotSubmitted", default=True, name="아니오"),
    f("Task_Lookup", "End"), f("Task_NotSubmitted", "End")],
   service_keys={"ui-automation": "test-ui"}, extensions=[{"id": "ui-automation", "version": ">=0.4,<0.5"}], 
   cases=[Case("시험 페이지", {}, {"제출메시지": "*", "연락처": "*"})],
   features=["UI 태스크 fill/click/read (C10 동작)", "화면 이동(`navigates`)", "읽은 문구로 분기"],
   lessons=["프로토타입은 WEB AI 태스크(자율)였다 — 등록 화면이면 UI 태스크로."])

FX("FX-16", "fx16_web_review_field", "현장 확인 (PC 결재 위치)", "프로토타입 example_web_review", "pc", "PC Bot 수동 실행",
   "웹 페이지에서 정보를 모으고, **그 PC 앞의 사람이** 바로 확인한 뒤 다음 단계로 간다. PC Bot은 확인이 끝날 때까지 자리를 쥔다 (ADR-0014).",
   "사람이 화면을 같이 보며 확인해야 하는 짧은 확인 — PC, 현장 결재.",
   [start("Start"),
    ui("Task_Collect", "정보 모으기", "intranet.notice.list", [dict(key="notice.table", action="read_table", result="공지")]),
    appr("Approve_Review", "현장 확인", "수집 결과 확인", ["공지"], [fld("승인", "다음 단계로", "bool", True)], location="field"),
    xgw("Gw_Ok", "승인?"),
    ui("Task_Follow", "첫 링크 열기", "intranet.notice.list", [dict(key="notice.first_link", action="click")]),
    script("Task_Skip", "건너뜀", "메모 = '사용자 보류'"), end("End")],
   [f("Start", "Task_Collect"), f("Task_Collect", "Approve_Review"), f("Approve_Review", "Gw_Ok"),
    f("Gw_Ok", "Task_Follow", "승인", "예"), f("Gw_Ok", "Task_Skip", default=True, name="아니오"), f("Task_Follow", "End"), f("Task_Skip", "End")],
   service_keys={"ui-automation": "test-ui"}, extensions=[{"id": "ui-automation", "version": ">=0.4,<0.5"}], 
   cases=[Case("승인", {}, {"승인": True}, {"Approve_Review": {"승인": True}}), Case("사람이 확인", {}, {}, manual=True)],
   features=["결재 위치 `field` (BUI-04 창)", "확인 중에도 실행 자리 유지"],
   lessons=["며칠 걸릴 수 있는 결재는 `field`로 두지 않는다 — 서버 BPM 프로세스로 옮기고 `center`. 실행 전 검사가 `field` + 긴 시간 제한을 경고한다."])

FX("FX-17", "fx17_webhook", "웹훅 보내기", "프로토타입 example_webhook", "server", "수동 실행",
   "변수 일부를 JSON으로 POST하고 응답을 저장한다.", SRV,
   [start("Start"), script("Task_Make", "보낼 값", "건수 = 3\n상태 = '완료'"),
    hook("Task_Hook", "보내기", "{대상주소}", body="fields:[건수, 상태]", store_as="응답"), script("Task_Fail", "실패", "실패 = error_message"), end("End")],
   [f("Start", "Task_Make"), f("Task_Make", "Task_Hook"), f("Task_Hook", "End"), f("Bnd_Fail", "Task_Fail"), f("Task_Fail", "End")],
   boundaries=[bnd("Bnd_Fail", "Task_Hook", "error", "실패", error="SEND_FAILED")],
   inputs=[("대상주소", "string", True, "")],
   cases=[Case("로컬 수신기", {"대상주소": {"$test_receiver": "hook"}}, {"응답": {"status": 200}}), Case("주소 없음", {"대상주소": "https://unreachable.invalid/hook"}, {"실패": "*"}, description="DNS 실패 → `SEND_FAILED` 경계")],
   features=["`chk:webhook` body `fields:[…]`", "`SEND_FAILED`"],
   lessons=["body `all`은 모든 변수를 보낸다 — 비밀이 섞일 수 있어 `fields`를 권장 (실행 전 검사 경고)."])

FX("FX-18", "fx18_parallel_loop", "병렬 반복", "새로 — 프로토타입 공백", "server", "수동 실행",
   "목록의 URL 다섯 개를 서버에서 동시에 확인한다 (BPM 프로세스당 동시 상한 안에서).", SRV,
   [start("Start"), svc("Task_Check", "상태 확인", "web-reader", "head", {"url": "주소"}, {"상태": "status"},
                        loop=dict(collection="주소목록", item="주소", result="상태", collect_into="상태목록", parallel=True)),
    script("Task_Count", "정상 수", "정상 = len([s for s in 상태목록 if s == 200])"), end("End")],
   [f("Start", "Task_Check"), f("Task_Check", "Task_Count"), f("Task_Count", "End")],
   service_keys={"web-reader": "ops-web-reader"}, extensions=[{"id": "web-reader", "version": ">=1,<2"}],
   inputs=[("주소목록", "list", True, "")],
   cases=[Case("5개", {"주소목록": ["https://example.com"] * 5}, {"정상": 5})],
   features=["`isSequential=false`", "결과 순서 = 입력 순서 (C14)", "PC에서는 차례로 돈다"],
   lessons=["병렬 반복의 결과 목록이 끝난 순서로 쌓이면 시험이 흔들린다 — 입력 순서로 모은다."])

FX("FX-19", "fx19_manual_task_pc", "수동 확인 (PC)", "프로토타입 manualTask 사용 예", "pc", "PC Bot 수동 실행",
   "사람이 PC 앞에서 실제 행동(프린터에 용지 넣기 등)을 한 뒤 확인 버튼을 누른다. 입력 칸이 없는 확인.", "그 PC 앞의 물리적 행동 → PC.",
   [start("Start"), appr("Manual_Paper", "용지 넣기", "프린터에 용지를 넣어 주세요", ["오늘"], [], location="field", manual=True),
    script("Task_Done", "기록", "확인됨 = True"), end("End")],
   [f("Start", "Manual_Paper"), f("Manual_Paper", "Task_Done"), f("Task_Done", "End")],
   cases=[Case("확인", {}, {"확인됨": True}, {"Manual_Paper": {"decision": "approve"}})],
   features=["`manualTask` + `chk:approval` (칸 없음)"],
   lessons=["수동 작업은 결재와 같은 창(C6)을 쓰되 칸이 없다 — 화면에는 「확인」 하나만. 프로토타입 시나리오 2도 실물 수령을 이렇게 확인했다.",
            "**칸이 없어도 답은 비어 있지 않다** — 폼이 없는 결재의 답은 `decision`(`approve`/`reject`)이다 (C6). "
            "케이스에 `{}`를 적었더니 Studio 시험 실행이 답을 거절하고 같은 자리를 되풀이했다 (조각 3e-3).",
            "PC에서 `field`로 둘 때는 몇 분 안에 끝나는 일만. 며칠 걸릴 수 있으면 서버 BPM 프로세스 + Center 결재함 (BX-20)."])

FX("FX-20", "fx20_external_adapter", "외부 확장 HTTP 어댑터 호출", "새로 — ADR-0018", "server", "수동 실행",
   "우리 계약을 따르지 않는 외부 앱을 C13 HTTP 어댑터 정의로 부른다. 키는 서버 실행기의 비밀 저장소에서 `key_ref`로.", SRV,
   [start("Start"), svc("Task_Lookup", "외부 조회", "ext-credit", "lookup", {"biz_no": "사업자번호"}, {"결과": "result"}, key_ref="finance-credit-test"),
    end("End")],
   [f("Start", "Task_Lookup"), f("Task_Lookup", "End")],
   extensions=[{"id": "ext-credit", "version": ">=1,<2"}], inputs=[("사업자번호", "string", True, "")], 
   cases=[Case("모의 서버", {"사업자번호": "123-45-67890"}, {"결과": {"score": 780}})],
   features=["외부 확장 어댑터", "태스크 단위 `key_ref` (BPM 프로세스 기본 대신)", "Admin 서명된 정의만 사용"],
   lessons=["외부 정의의 `allowed_hosts` 밖으로는 어댑터가 부르지 않는다 (C13 §4-3)."])
