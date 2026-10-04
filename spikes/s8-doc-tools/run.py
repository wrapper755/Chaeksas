"""S8 — PDF 글자 뽑기를 무엇으로 하나. 후보 둘을 **만든 쪽이 다른 PDF 둘**에 재 본다.

만드는 쪽에 따라 결과가 갈린다 — 그래서 표본을 둘 둔다 (fpdf2·reportlab). 업무 문서는
포털·회계 프로그램·한글 워드가 뽑아 주는 것이라 **우리가 고를 수 없다.**

재현:
  uv run --no-project --with fpdf2 --with reportlab python spikes/s8-doc-tools/make_pdf.py
  uv run --no-project --with pypdf --with pdfminer.six python spikes/s8-doc-tools/run.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: 만든 쪽이 다른 표본 둘.
SAMPLES = {"fpdf2가 만든 것": HERE / "sample.pdf", "reportlab이 만든 것": HERE / "sample_reportlab.pdf"}

#: 뽑은 글에 반드시 있어야 하는 것 (한글·숫자·쉼표가 섞인 자리).
WANTED = ["세금계산서", "123-45-67890", "1,375,000원", "가온테크", "2026-09-23"]


def clean(text: str) -> str:
    """뽑은 글을 쓸 수 있게 다듬는다 — 제품 도구가 할 일을 여기서도 한다.

    어떤 PDF는 글자 사이에 `\x00`이 끼어 나온다 (ToUnicode CMap을 만든 쪽 문제다).
    """
    return text.replace("\x00", "")


def measure(label: str, sample: Path, name: str, extract) -> None:
    if not sample.is_file():
        print(f"| {label} | {name} | 표본이 없다 | | |")
        return
    start = time.perf_counter()
    try:
        text = clean(extract(sample))
    except Exception as e:  # noqa: BLE001
        print(f"| {label} | {name} | 실패: {type(e).__name__}: {e} | | |")
        return
    elapsed = (time.perf_counter() - start) * 1000
    missing = [w for w in WANTED if w not in text]
    found = "모두 나왔다" if not missing else f"{len(WANTED) - len(missing)}/{len(WANTED)}만 나왔다"
    print(f"| {label} | {name} | {found} | {len(text)}자 | {elapsed:.0f}ms |")


def with_pypdf(path: Path) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def with_pdfminer(path: Path) -> str:
    from pdfminer.high_level import extract_text

    return extract_text(str(path))


def weigh(package: str) -> str:
    """빈 폴더에 그것만 깔아 보고 크기를 잰다 (딸려 오는 것까지 — ADR-0024는 onedir이다)."""
    with tempfile.TemporaryDirectory() as raw:
        target = Path(raw)
        done = subprocess.run(
            ["uv", "pip", "install", "--target", str(target), "--quiet", package],
            capture_output=True,
            text=True,
        )
        if done.returncode != 0:
            return f"재지 못했다 ({done.stderr.strip().splitlines()[-1] if done.stderr else ''})"
        size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
        tops = sorted({p.name for p in target.iterdir() if p.is_dir() and not p.name.endswith(".dist-info")})
    return f"{size / 1_000_000:.1f} MB (딸려 오는 것: {', '.join(tops)})"


def main() -> int:
    if not any(p.is_file() for p in SAMPLES.values()):
        print("먼저 make_pdf.py로 표본 PDF를 만든다.")
        return 2

    print("## 1. 한글 PDF에서 글자를 뽑아 본다\n")
    print("| 표본 | 후보 | 찾는 글 5개 | 뽑힌 길이 | 시간 |")
    print("| --- | --- | --- | --- | --- |")
    for label, sample in SAMPLES.items():
        measure(label, sample, "pypdf", with_pypdf)
        measure(label, sample, "pdfminer.six", with_pdfminer)

    print("\n## 2. 무게 (빈 폴더에 그것만 깔아 본다)\n")
    print("| 후보 | 크기 |")
    print("| --- | --- |")
    for one in ("pypdf", "pdfminer.six"):
        print(f"| {one} | {weigh(one)} |")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
