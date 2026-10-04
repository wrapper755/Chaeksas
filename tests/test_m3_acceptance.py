"""M3 인수 시험 — 업무 예제의 M3 묶음을 **Studio 시험 실행**으로 돌린다 (조각 3f).

로드맵의 M3 마지막 기준이다: 「[업무 예제](08-business-examples/README.md)의 M3 묶음이 Studio
시험 실행에서 케이스 모두 통과 (AI 태스크는 자율 수행 → 결정 수행 재생 둘 다)」.

**바깥에 나가지 않는다.** 모델은 127.0.0.1에 띄운 작은 OpenAI 호환 스텁이고(S7이 쓰던 수법),
표본 파일은 시험이 그 자리에서 만든다 (PDF·엑셀·CSV). 저장소에 이진 파일을 두지 않는다.

**묶음 목록은 예제에서 읽는다** — `README.md`의 표를 사람이 옮겨 적으면 어긋난다.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Iterator
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts.bpmn_ext import Case, read_process  # noqa: E402
from chaeksas.studio.receiver import Receiver  # noqa: E402
from chaeksas.studio.run_dialog import AUTONOMOUS, DETERMINISTIC  # noqa: E402
from chaeksas.studio.runner import (  # noqa: E402
    NO_EXPECT,
    PASS,
    CaseRun,
    Outcome,
    Plan,
    read_cases,
)
from chaeksas.studio.settings import Settings  # noqa: E402
from chaeksas.studio.workspace import BpmProcess, Workspace  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples"
EXAMPLES = DOCS / "bpmn"


def bundle() -> list[str]:
    """M3 묶음의 예제 파일 이름 — `README.md`의 「마일스톤별 인수 시험 묶음」 표에서 읽는다."""
    body = (DOCS / "README.md").read_text(encoding="utf-8")
    row = next(line for line in body.splitlines() if line.startswith("| M3 |"))
    ids = [x.strip().lower().replace("-", "") for x in row.split("|")[2].split(",")]
    found = []
    for one in ids:
        match = next((p.stem for p in sorted(EXAMPLES.glob(f"{one}_*.bpmn"))), None)
        assert match, f"묶음에 적힌 {one}에 맞는 예제 파일이 없다"
        found.append(match)
    return found


M3 = bundle()


# ─────────────────────────── 스텁 모델 ───────────────────────────


def canned(wanted: dict[str, str], given: dict[str, Any]) -> dict[str, Any] | None:
    """예제가 **그 값이어야 뜻이 통하는** 자리의 답. 열쇠는 `results`의 이름들이다.

    모델이 똑똑한지는 여기서 시험하지 않는다. 시험하는 것은 **엔진·케이스·기대값이 한 줄로
    맞물리는가**다 — 그래서 답은 모델이 아니라 시험이 정한다. `given`은 C14 §「AI 태스크가 보는
    값」대로 모델에게 간 값이라, 건마다 다른 답(반복)도 여기서 만들 수 있다.
    """
    key = tuple(sorted(wanted))

    if key == ("발주목록",):  # BX-01 발주 대장
        return {"발주목록": LEDGER}
    if key == ("청구",):  # BX-01 청구서 한 장 (반복) — 파일 이름의 번호로 건을 가른다
        number = _number(str(given.get("청구서", "")))
        clean = "2026-07" in str(given.get("청구서", ""))
        table = CLEAN_INVOICES if clean else INVOICES
        return {"청구": table[(number - 1) % len(table)]}
    if key == ("기준일", "환율"):  # BX-02
        return {"환율": {"KRW": 1387.5, "EUR": 0.92, "JPY": 151.3}, "기준일": "2026-09-30"}
    if key == ("원화",):  # FX-01·FX-08
        if "invalid" in str(given.get("주소", "")):
            # FX-08은 **실패해야** 오류 경계가 받는다. 스텁은 도구를 부르지 않으므로 「수를
            # 못 냈다」로 답한다 — `results` 검증이 업무 실패로 올리고, 거기서 대체 경로다.
            return {"원화": "모름"}
        return {"원화": 1350}
    if key == ("분개초안", "불일치"):  # BX-05
        return {"분개초안": [{"계정": "미지급금", "금액": 1000}], "불일치": []}
    if key == ("내역",):  # BX-07 카드 내역
        return {"내역": [
            {"승인번호": "A1", "일시": "2026-09-21 12:10", "요일": "월", "시": 12,
             "가맹점": "한빛식당", "업종": "음식점", "금액": 18000, "사용자": "김책사"},
            {"승인번호": "A2", "일시": "2026-09-26 23:40", "요일": "토", "시": 23,
             "가맹점": "밤길택시", "업종": "택시", "금액": 32000, "사용자": "이책사"},
        ] if "W4" in str(given.get("내역파일", "")) else [
            {"승인번호": "B1", "일시": "2026-09-15 12:10", "요일": "화", "시": 12,
             "가맹점": "한빛식당", "업종": "음식점", "금액": 18000, "사용자": "김책사"},
        ]}
    if key == ("분류",):  # BX-07 계정과목 (반복)
        건 = given.get("건") or {}
        업종 = str(건.get("업종", ""))
        계정 = {"음식점": "복리후생비", "택시": "여비교통비"}.get(업종, "소모품비")
        return {"분류": {"승인번호": 건.get("승인번호", ""), "계정과목": 계정, "근거": f"{업종} 기본 계정"}}
    if key == ("손해배상조항", "지재권조항", "해지조항"):  # BX-30
        높음 = "unlimited" in str(given.get("계약서", ""))
        return {
            "손해배상조항": "모든 손해를 배상한다" if 높음 else "직접 손해로 한정한다",
            "지재권조항": "산출물의 권리는 갑에게 있다",
            "해지조항": "30일 전 서면 통지로 해지할 수 있다",
        }
    if key == ("의견서",):  # BX-30
        return {"의견서": "손해배상 범위를 직접 손해로 한정할 것을 권합니다."}
    if key == ("결과",):  # BX-37 조항 검토 (BX-30이 호출하기도 한다)
        조항 = str(given.get("조항", ""))
        # 빈 조항은 「판단할 거리가 없다」 3, 무제한 배상은 5, 표준 문구는 1.
        점수 = 3 if not 조항.strip() else (5 if "모든 손해" in 조항 else 1)
        return {"결과": {"점수": 점수, "사유": "표준 범위" if 점수 < 4 else "배상 범위가 무제한이다"}}
    if key == ("견적",):  # FX-06
        return {"견적": {"공급사": "한빛상사", "합계": 1320000}}
    if key == ("판정",):  # FX-09 신청 한 건 (반복)
        신청 = given.get("신청") or {}
        승인 = bool(신청.get("영수증")) and int(신청.get("금액", 0)) <= 50000
        return {"판정": {"id": 신청.get("id"), "승인": 승인, "사유": "기준 충족" if 승인 else "기준 미달"}}
    return None


#: BX-01이 쓰는 발주 대장 — 지급 2건·보류 5건·미청구 2건이 나오게 짰다.
LEDGER = [
    {"발주번호": "PO-1", "공급사": "한빛상사", "공급가액": 2780000, "입고": True},
    {"발주번호": "PO-2", "공급사": "가온테크", "공급가액": 3000000, "입고": True},
    {"발주번호": "PO-4", "공급사": "다래물산", "공급가액": 1000000, "입고": True},
    {"발주번호": "PO-5", "공급사": "마바상사", "공급가액": 1500000, "입고": False},
    {"발주번호": "PO-6", "공급사": "사아공업", "공급가액": 2000000, "입고": True},
    {"발주번호": "PO-8", "공급사": "자차산업", "공급가액": 900000, "입고": True},
    {"발주번호": "PO-9", "공급사": "카타테크", "공급가액": 800000, "입고": True},
]


def _invoice(발주번호: str, 공급가액: int, *, 부가세: int | None = None) -> dict[str, Any]:
    세액 = round(공급가액 * 0.1) if 부가세 is None else 부가세
    return {
        "공급사": "한빛상사",
        "청구번호": f"IV-{발주번호}",
        "발주번호": 발주번호,
        "공급가액": 공급가액,
        "부가세": 세액,
        "합계": 공급가액 + 세액,
    }


#: 청구서 7장 — 지급 2(PO-1·PO-2), 미등록 1, 금액 불일치 1, 미입고 1, 중복 2(PO-6).
INVOICES = [
    _invoice("PO-1", 2780000),
    _invoice("PO-2", 3000000),
    _invoice("PO-없음", 500000),
    _invoice("PO-4", 1000001),
    _invoice("PO-5", 1500000),
    _invoice("PO-6", 2000000),
    _invoice("PO-6", 2000000),
]
#: 「문제 없는 달」 — 보류가 없어야 한다.
CLEAN_INVOICES = [_invoice("PO-1", 2780000), _invoice("PO-2", 3000000)]


def _number(path: str) -> int:
    """`invoice_2026-08_3.pdf` → 3 (없으면 1). 반복에서 건을 가르는 데 쓴다."""
    found = re.findall(r"_(\d+)\.pdf$", path)
    return int(found[0]) if found else 1


def answer_for(wanted: dict[str, str]) -> dict[str, Any]:
    """`results: {이름: 타입}`에 맞는 **아무 값** — 짜 둔 답이 없는 자리에서 쓴다."""
    by_type: dict[str, Any] = {
        "string": "스텁 답",
        "number": 1,
        "int": 1,
        "bool": True,
        "date": "2026-09-30",
        "list": [],
        "dict": {},
    }
    return {name: by_type.get(kind, "스텁 답") for name, kind in wanted.items()}


class StubModel:
    """OpenAI 호환 `/v1/chat/completions` 하나. **도구는 부르지 않고** 최종 JSON만 답한다."""

    def __init__(self) -> None:
        self.asked = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 — http.server가 정한 이름
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.asked += 1
                raw = json.dumps({
                    "choices": [{"message": {"role": "assistant", "content": outer.reply(body)}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10},
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def reply(self, body: dict[str, Any]) -> str:
        """물음에서 **받을 필드**와 **함께 온 값**을 읽어 답을 만든다."""
        asked = "\n".join(m.get("content") or "" for m in body.get("messages", []))
        line = re.search(r"JSON 객체 하나: (.+)", asked)
        wanted = {}
        for part in (line.group(1) if line else "").split(", "):
            found = re.match(r"(.+?)\((.+?)\)$", part.strip())
            if found:
                wanted[found.group(1)] = found.group(2)
        body_line = re.search(r"## 파라미터\n(.+)", asked)
        try:
            given = json.loads(body_line.group(1)) if body_line else {}
        except ValueError:
            given = {}
        made = canned(wanted, given if isinstance(given, dict) else {})
        return json.dumps(made if made is not None else answer_for(wanted), ensure_ascii=False)

    def __enter__(self) -> StubModel:
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    @property
    def base_url(self) -> str:
        # `/v1/chat/completions`는 어댑터가 붙인다 (ADR-0027) — 여기는 주소 뿌리만.
        return f"http://127.0.0.1:{self.server.server_address[1]}"


@pytest.fixture(scope="module")
def model() -> Iterator[StubModel]:
    with StubModel() as made:
        yield made


@pytest.fixture(scope="session")
def app() -> Any:
    from PySide6.QtWidgets import QApplication

    try:
        return QApplication.instance() or QApplication([])
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Qt를 띄울 수 없다: {type(e).__name__}: {e}")


# ─────────────────────────── 표본 파일 ───────────────────────────


def make_samples(root: Path) -> None:
    """케이스가 가리키는 표본 파일을 **그 자리에서** 만든다 (저장소에 이진 파일을 두지 않는다)."""
    from openpyxl import Workbook as Book

    cards = root / "samples" / "card"
    cards.mkdir(parents=True, exist_ok=True)
    for week in ("2026-09-W3", "2026-09-W4"):
        (cards / f"{week}.csv").write_text(
            "승인번호,일시,가맹점,업종,금액,사용자\n"
            f"A{week[-1]}1,2026-09-21 12:10,한빛식당,음식점,18000,김책사\n"
            f"A{week[-1]}2,2026-09-26 23:40,밤길택시,택시,32000,이책사\n",
            encoding="utf-8",
        )

    for month, count in (("2026-07", len(CLEAN_INVOICES)), ("2026-08", len(INVOICES))):
        folder = root / "samples" / "invoice_reconciliation" / month
        folder.mkdir(parents=True, exist_ok=True)
        book = Book()
        page = book.active
        page.append(["발주번호", "공급사", "공급가액", "입고"])
        for row in LEDGER:
            page.append([row["발주번호"], row["공급사"], row["공급가액"], row["입고"]])
        book.save(str(folder / f"ledger_{month}.xlsx"))
        for i in range(1, count + 1):
            write_pdf(folder / f"invoice_{month}_{i}.pdf", ["세금계산서", f"청구서 {i}장 중 {i}번"])

    # 「청구서 없음」 케이스가 가리키는 달 — **폴더는 있고 안이 비어 있다** (실패가 아니다).
    (root / "samples" / "invoice_reconciliation" / "2026-06").mkdir(parents=True, exist_ok=True)

    inbox = root / "samples" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "하나.txt").write_text("첫 파일", encoding="utf-8")
    (inbox / "둘.txt").write_text("둘째 파일", encoding="utf-8")
    (root / "samples" / "inbox-empty").mkdir(parents=True, exist_ok=True)

    docs = root / "samples" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    write_pdf(docs / "계약서.pdf", ["표준 용역 계약서", "제1조 손해배상", "제2조 해지"])
    write_pdf(docs / "청구서.pdf", ["세금계산서", "합계 1,375,000원"])


#: 같은 PDF를 예제마다 다시 만들지 않는다 (글꼴을 심는 데 시간이 든다).
_PDFS: dict[tuple[str, ...], bytes] = {}


def write_pdf(target: Path, lines: list[str]) -> None:
    key = tuple(lines)
    if key not in _PDFS:
        fpdf = pytest.importorskip("fpdf", reason="표본 PDF를 만들 fpdf2가 없다")
        font = (
            Path(__file__).resolve().parent.parent
            / "packages/qt/src/chaeksas/qt/fonts/Pretendard-Regular.otf"
        )
        pdf = fpdf.FPDF()
        pdf.add_font("pretendard", "", str(font))
        pdf.set_font("pretendard", size=12)
        pdf.add_page()
        for line in lines:
            pdf.cell(0, 9, line, new_x="LMARGIN", new_y="NEXT")
        _PDFS[key] = bytes(pdf.output())
    target.write_bytes(_PDFS[key])


# ─────────────────────────── 돌리기 ───────────────────────────


def studio(tmp_path: Path, example: str, model: StubModel) -> tuple[BpmProcess, Settings]:
    data = tmp_path / "studio"
    settings = replace(
        Settings(), data_dir=data, llm_base_url=model.base_url, llm_model="stub", readable_dirs=()
    )
    made = Workspace(settings.workspace_dir).ensure().import_example(EXAMPLES, example)
    # 상대 경로의 기준은 **출력 폴더**다 (ADR-0026) — 표본을 거기에 만든다.
    outputs = settings.outputs_dir / made.id
    outputs.mkdir(parents=True, exist_ok=True)
    make_samples(outputs)
    return made, settings


def drive(run: CaseRun, *, timeout_ms: int = 30_000) -> Outcome:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    box: list[Outcome] = []
    def done(outcome: Outcome) -> None:
        box.append(outcome)
        loop.quit()

    run.ended.connect(done)
    QTimer.singleShot(timeout_ms, loop.quit)
    run.start()
    loop.exec()
    if not box:
        pytest.fail(f"시험 실행이 {timeout_ms}ms 안에 끝나지 않았다")
    return box[0]


def ai_tasks(example: str) -> list[str]:
    """그 예제의 AI 태스크 노드 id — 재생이 있어야 하는 자리들."""
    found = read_process((EXAMPLES / f"{example}.bpmn").read_text(encoding="utf-8"))
    return [n.id for n in found.all_nodes() if n.prop("aiTask") is not None]


def run_all(
    tmp_path: Path, example: str, model: StubModel, *, mode: str = AUTONOMOUS
) -> list[tuple[Case, Outcome]]:
    made, settings = studio(tmp_path, example, model)
    definition = made.entry_definition
    assert definition is not None
    # 웹훅은 **시험 수신기로만** 간다 (메인 창도 실행 전에 이것을 켠다).
    receiver = Receiver(port=0).start()
    out = []
    try:
        for case in read_cases(made, definition):
            if case.manual:
                continue  # 사람이 창을 보는 케이스 — 자동으로 돌릴 것이 아니다
            plan = Plan(
                process=made, definition=definition, case=case, mode=mode, settings=replace(settings)
            )
            out.append((case, drive(CaseRun(plan, receiver))))
    finally:
        receiver.stop()
    return out


#: 아직 초록이 아닌 예제와 **그 이유**. 비어 있으면 묶음이 다 돈다는 뜻이다.
#:
#: 하나라도 새로 막히면 여기에 **이유를 적고** 넣는다. 조용히 빼면 묶음이 거짓말을 한다.
REMAINING: dict[str, str] = {}

#: 케이스가 모두 통과하는 예제. 줄어들면 회귀다.
GREEN = [one for one in M3 if one not in REMAINING]


def test_the_bundle_is_read_from_the_examples() -> None:
    """묶음 목록을 사람이 옮겨 적지 않는다 — 어긋나는 순간 시험이 거짓말을 한다."""
    assert len(M3) == 24
    assert set(REMAINING) <= set(M3), "남은 목록에 묶음 밖 예제가 있다"
    assert len(GREEN) == 24, f"초록이 {len(GREEN)}개다 — 막힌 것이 있으면 REMAINING에 이유를 적는다"


@pytest.mark.parametrize("example", GREEN)
def test_an_m3_example_passes_all_its_cases(
    app: Any, tmp_path: Path, model: StubModel, example: str
) -> None:
    """케이스가 **모두 통과**한다 (기대 결과가 없는 케이스는 비교하지 않는다)."""
    results = run_all(tmp_path, example, model)
    assert results, f"{example}: 돌릴 케이스가 없다"
    bad = [(c.name, o.verdict, o.detail) for c, o in results if o.verdict not in (PASS, NO_EXPECT)]
    assert not bad, f"{example}: {bad}"


@pytest.mark.parametrize("example", sorted(REMAINING))
def test_a_remaining_example_still_fails_for_the_written_reason(
    app: Any, tmp_path: Path, model: StubModel, example: str
) -> None:
    """아직 안 되는 것은 **안 된다고 적어 둔다** — 조용히 초록이 되면 목록이 썩는다."""
    results = run_all(tmp_path, example, model)
    bad = [(c.name, o.verdict) for c, o in results if o.verdict not in (PASS, NO_EXPECT)]
    assert bad, f"{example}: 이제 통과한다 — REMAINING에서 지운다 ({REMAINING[example]})"


# ─────────────────────────── 결정 수행 (재생) ───────────────────────────

#: AI 태스크가 있어도 **배우는 것이 없는** 예제와 그 이유.
NO_LEARNING = {
    "fx08_error_boundary": "AI 태스크가 실패하는 길만 시험한다 — 실패한 수행은 배우지 않는다",
}

#: AI 태스크가 있고 배울 거리도 있는 예제 — 재생을 볼 수 있다.
WITH_AI = [one for one in GREEN if ai_tasks(one) and one not in NO_LEARNING]


def test_some_of_the_bundle_has_ai_tasks() -> None:
    """재생 시험이 **아무것도 안 돌리는** 일을 막는다."""
    assert len(WITH_AI) >= 8, WITH_AI


@pytest.mark.parametrize("example", WITH_AI)
def test_the_same_cases_pass_again_as_a_replay(
    app: Any, tmp_path: Path, model: StubModel, example: str
) -> None:
    """**자율 수행 → 결정 수행**. 로드맵 M3 인수 기준의 남은 반쪽이다.

    자율 수행이 배운 것을 Studio가 패키지(`memory/specs.json`)에 적고, 결정 수행이 그것을
    되밟는다 (ADR-0028). 보는 것 둘.

    1. **판정이 같다** — 재생이 결과를 바꾸면 운영 실행이 개발 실행과 달라진다.
    2. **정말 되밟았다** — `node_state: replayed`가 남는다 (C3 `replayed_tasks`가 센다).
       이것을 안 보면 「재생이 안 되고 그냥 또 자율로 돌았다」를 통과로 읽는다.
    """
    made, settings = studio(tmp_path, example, model)
    definition = made.entry_definition
    assert definition is not None
    replayed_at_least_once: list[str] = []
    receiver = Receiver(port=0).start()
    try:
        for case in read_cases(made, definition):
            if case.manual:
                continue
            first = drive(CaseRun(_plan(made, definition, case, settings, AUTONOMOUS), receiver))
            again = drive(CaseRun(_plan(made, definition, case, settings, DETERMINISTIC), receiver))

            assert again.verdict == first.verdict, f"{example}/{case.name}: {again.detail}"
            # **배운 것이 있을 때만** 되밟을 거리가 있다 — 조건 때문에 AI 태스크를 지나지
            # 않거나(BX-11 유찰·FX-09 빈 목록) 실패한 길(FX-08)은 배우는 것이 없다.
            if first.learned:
                assert _replayed(again) >= 1, f"{example}/{case.name}: 되밟은 AI 태스크가 없다"
                replayed_at_least_once.append(f"{example}/{case.name}")
    finally:
        receiver.stop()
    assert replayed_at_least_once, f"{example}: 되밟은 케이스가 하나도 없다 (배운 것이 없다)"


def _plan(made: BpmProcess, definition: Any, case: Case, settings: Settings, mode: str) -> Plan:
    return Plan(process=made, definition=definition, case=case, mode=mode, settings=replace(settings))


def _replayed(outcome: Outcome) -> int:
    """`node_state: replayed`가 몇 번 남았나 (C3)."""
    if outcome.run is None:
        return 0
    return sum(
        1
        for event in outcome.run.log.events
        if event.kind == "node_state" and event.data.get("state") == "replayed"
    )
