"""시험용 PDF를 만든다 — **만든 쪽이 다른 둘** (fpdf2·reportlab).

`fpdf2`로 **글꼴을 심어** 만든다 (한글 PDF는 CID 글꼴 + ToUnicode CMap이라, ASCII PDF로
재면 진짜 문제를 못 본다 — 우리 업무 문서는 대부분 한글이다).

이것은 스파이크 코드다. 제품 코드에서 import하지 않는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONT = HERE.parent.parent / "packages" / "qt" / "src" / "chaeksas" / "qt" / "fonts" / "Pretendard-Regular.otf"

INVOICE = [
    "세금계산서",
    "공급자: (주)한빛상사    등록번호 123-45-67890",
    "공급받는자: (주)책사스  등록번호 987-65-43210",
    "작성일자: 2026-09-30",
    "품목: 클라우드 사용료 9월분",
    "공급가액: 1,250,000원",
    "부가세: 125,000원",
    "합계: 1,375,000원",
]

TABLE = [
    ["번호", "거래처", "금액", "날짜"],
    ["1", "한빛상사", "1250000", "2026-09-01"],
    ["2", "가온테크", "480000", "2026-09-11"],
    ["3", "다래물산", "2310000", "2026-09-23"],
]


def main() -> int:
    try:
        from fpdf import FPDF
    except ImportError:
        print("fpdf2가 없다: uv run --with fpdf2 python spikes/s8-doc-tools/make_pdf.py")
        return 2

    pdf = FPDF()
    pdf.add_font("pretendard", "", str(FONT))
    pdf.set_font("pretendard", size=12)
    pdf.add_page()
    for line in INVOICE:
        pdf.cell(0, 9, line, new_x="LMARGIN", new_y="NEXT")
    pdf.add_page()
    for row in TABLE:
        for cell in row:
            pdf.cell(45, 9, cell, border=1)
        pdf.ln()
    pdf.output(str(HERE / "sample.pdf"))
    print(f"썼다: {HERE / 'sample.pdf'} ({(HERE / 'sample.pdf').stat().st_size} 바이트)")
    return reportlab_sample()


def reportlab_sample() -> int:
    """같은 글을 **다른 생성기**로 한 번 더 — 뽑기가 생성기를 타는지 보려는 것이다."""
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
    except ImportError:
        print("reportlab이 없다 — 표본 하나만 만들었다.")
        return 0

    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    target = HERE / "sample_reportlab.pdf"
    page = canvas.Canvas(str(target))
    page.setFont("HYSMyeongJo-Medium", 12)
    for index, line in enumerate([*INVOICE, *(" ".join(row) for row in TABLE)]):
        page.drawString(60, 760 - index * 20, line)
    page.save()
    print(f"썼다: {target} ({target.stat().st_size} 바이트)")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
