"""「예제 BPM 프로세스 가져오기」의 기본 폴더 — 폴더를 넘기지 않고 부른다.

다른 시험은 모두 예제 폴더를 직접 넘겨 이 기본값을 밟지 않았다. 그래서 단계 수가 하나 모자란
경로(`…/apps/docs/…`)가 현장 리허설에서 「예제를 찾지 못했습니다」로야 드러났다.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.studio.dialogs import EXAMPLES_DIR, example_ids  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def test_the_default_examples_folder_is_the_one_in_the_checkout() -> None:
    assert EXAMPLES_DIR == REPO / "docs" / "08-business-examples" / "bpmn"


def test_the_default_lists_the_examples_without_being_told_where() -> None:
    found = example_ids()
    assert "bx04_tax_invoice_issue" in found
    assert len(found) == len(list(EXAMPLES_DIR.glob("*.bpmn")))
