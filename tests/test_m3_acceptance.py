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

from chaeksas.contracts.bpmn_ext import Case  # noqa: E402
from chaeksas.studio.receiver import Receiver  # noqa: E402
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


def answer_for(wanted: dict[str, str]) -> dict[str, Any]:
    """`results: {이름: 타입}`에 맞는 **아무 값** — 모델이 할 말을 흉내 낸다.

    값이 업무적으로 맞는지는 여기서 시험하지 않는다 (그건 모델의 몫이다). 시험하는 것은
    **엔진이 그 답을 받아 끝까지 가는가**다.
    """
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
        """물음에 적힌 「다음 필드를 가진 JSON 객체 하나: 이름(타입), …」을 읽어 그대로 돌려준다."""
        asked = "\n".join(m.get("content") or "" for m in body.get("messages", []))
        line = re.search(r"JSON 객체 하나: (.+)", asked)
        wanted = {}
        for part in (line.group(1) if line else "").split(", "):
            found = re.match(r"(.+?)\((.+?)\)$", part.strip())
            if found:
                wanted[found.group(1)] = found.group(2)
        return json.dumps(answer_for(wanted), ensure_ascii=False)

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

    for month in ("2026-07", "2026-08"):
        folder = root / "samples" / "invoice_reconciliation" / month
        folder.mkdir(parents=True, exist_ok=True)
        book = Book()
        page = book.active
        page.append(["발주번호", "공급사", "공급가액", "입고"])
        page.append([f"PO-{month}-1", "한빛상사", 1250000, True])
        book.save(str(folder / f"ledger_{month}.xlsx"))
        write_pdf(folder / f"invoice_{month}_1.pdf", ["세금계산서", f"발주번호 PO-{month}-1", "공급가액 1,250,000"])

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


def write_pdf(target: Path, lines: list[str]) -> None:
    fpdf = pytest.importorskip("fpdf", reason="표본 PDF를 만들 fpdf2가 없다")
    font = Path(__file__).resolve().parent.parent / "packages/qt/src/chaeksas/qt/fonts/Pretendard-Regular.otf"
    pdf = fpdf.FPDF()
    pdf.add_font("pretendard", "", str(font))
    pdf.set_font("pretendard", size=12)
    pdf.add_page()
    for line in lines:
        pdf.cell(0, 9, line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(target))


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


def run_all(tmp_path: Path, example: str, model: StubModel) -> list[tuple[Case, Outcome]]:
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
            plan = Plan(process=made, definition=definition, case=case, settings=replace(settings))
            out.append((case, drive(CaseRun(plan, receiver))))
    finally:
        receiver.stop()
    return out


#: 아직 초록이 아닌 예제와 **그 이유**. 조각 3f의 남은 일이다.
#:
#: 「스텁이 업무 값을 모른다」가 대부분이다 — 지금 스텁은 `results` 타입에 맞는 **아무 값**을
#: 돌려준다(`list`면 `[]`). 케이스의 기대값(「보류 5건」·「합계 1,320,000」)은 **그 예제의 표본
#: 문서를 읽은 결과**라서, 케이스마다 답을 짜 넣어야 맞는다. 그것이 남은 일이다.
REMAINING = {
    "bx01_invoice_reconciliation": "스텁이 청구서 7건의 값을 모른다 (케이스별 답 필요)",
    "bx02_morning_fx_report": "스텁이 환율 dict를 모른다 (케이스별 답 필요)",
    "bx05_month_end_close": "스텁이 분개 초안을 모른다 (케이스별 답 필요)",
    "bx07_corporate_card_review": "스텁이 카드 내역 분류를 모른다 (케이스별 답 필요)",
    "bx11_bid_collection": "예제 결함 — `기간()`은 `{from,to}`인데 타이머 기한으로 쓴다",
    "bx30_contract_review": "스텁이 조항 점수를 모른다 (케이스별 답 필요)",
    "bx37_clause_review": "스텁이 조항 점수를 모른다 (케이스별 답 필요)",
    "fx06_document_read": "스텁이 견적 금액을 모른다 (케이스별 답 필요)",
    "fx08_error_boundary": "스텁이 환율을 모른다 (케이스별 답 필요)",
    "fx09_sequential_loop": "스텁이 건별 판정을 모른다 (케이스별 답 필요)",
    "fx13_signal": "「문제」 케이스 — `abort` 경계와 메시지 앞당김의 차례",
}

#: 지금 **케이스가 모두 통과하는** 예제. 줄어들면 회귀다 (조각마다 늘려 적는다).
GREEN = [one for one in M3 if one not in REMAINING]


def test_the_bundle_is_read_from_the_examples() -> None:
    """묶음 목록을 사람이 옮겨 적지 않는다 — 어긋나는 순간 시험이 거짓말을 한다."""
    assert len(M3) == 24
    assert set(REMAINING) <= set(M3), "남은 목록에 묶음 밖 예제가 있다"
    assert len(GREEN) == 13, f"초록이 {len(GREEN)}개다 — 늘었으면 여기와 REMAINING을 고쳐 적는다"


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
    assert bad, f"{example}: 이제 통과한다 — GREEN으로 옮기고 REMAINING에서 지운다 ({REMAINING[example]})"
