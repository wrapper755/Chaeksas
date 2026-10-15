"""인수 시험이 쓰는 **표본 파일** — 케이스가 가리키는 그 파일들을 **그 자리에서 만든다**.

**이것은 제품 코드가 아니다.** 저장소에 이진 파일(PDF·엑셀)을 두지 않으므로 묶음이 만든다.

**자리가 하나다.** M3(Studio 시험 실행)·M7(서버 재통과)이 같은 예제를 돌리므로, 만드는 자리가
묶음마다 따로 있으면 **같은 그림이 묶음에 따라 다른 파일을 본다** — M7이 BX-01을 돌리지 못한
까닭이 그것이었다. 장부의 값은 짜 둔 모델 답과 **같은 표**에서 온다
(`tests/canned_answers.py`의 `LEDGER`·`INVOICES` — 둘이 어긋나면 대조가 거짓이 된다).

**빈 폴더도 만든다** — git은 빈 폴더를 담지 않아서, 들여다볼 폴더가 아예 없으면 `fileList`가
「폴더가 없다」로 실패한다 (FX-04의 「빈 폴더」 케이스).

경로의 기준은 **부르는 쪽이 주는 `root`**다 — Studio는 작업 폴더, 서버 실행기는 **출력 폴더**다
(상대 경로의 기준이 출력 폴더다 — ADR-0032).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from canned_answers import CLEAN_INVOICES, INVOICES, LEDGER


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


__all__ = ["make_samples", "write_pdf"]
