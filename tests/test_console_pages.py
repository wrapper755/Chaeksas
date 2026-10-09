"""서비스 앱 콘솔이 확장의 기여를 **실제로 읽는다** (C13 `console.pages`, ADR-0042 §2).

전에는 콘솔(`Shell.tsx`)에 세 줄이 **손으로 베껴** 있어서 확장을 더해도 줄이 생기지 않았다
(09-gaps §4-7). 지금은 확장 정의에서 생성한 레지스트리에서 온다.

파이썬 쪽에서 볼 수 있는 것만 본다 — 타입·빌드는 `web`의 `pnpm typecheck`·`pnpm build`가 보고,
생성물이 최신인지는 `test_contracts.py`의 `--check` 시험이 본다.
"""

from __future__ import annotations

from pathlib import Path

from chaeksas.contracts.service_app import AdminStatus
from chaeksas.core.extensions import load_host

ROOT = Path(__file__).resolve().parent.parent
CONSOLE = ROOT / "web" / "apps" / "svc-console"
REGISTRY = CONSOLE / "lib" / "console-pages.generated.ts"
SHELL = CONSOLE / "components" / "Shell.tsx"


def test_every_contributed_page_reaches_the_console() -> None:
    """기여한 화면 하나하나가 레지스트리에 있다 — **확장을 더하면 줄이 생긴다.**"""
    host = load_host()
    found = host.console_pages()
    assert found, "내장 확장이 콘솔 화면을 기여한다"
    text = REGISTRY.read_text(encoding="utf-8")
    for one in found:
        assert f'"{one.value.module}"' in text, one.value.module
        assert f'"{one.value.label}"' in text, one.value.label
        assert f'"{one.extension_id}"' in text, "어느 확장의 것인지로 묶는다"


def test_every_contributed_page_has_a_module_now() -> None:
    """세 화면(UIA-01~03)이 다 열린다 — 레지스트리에 줄이 있고 경로가 `Route`다 (ADR-0042 §2)."""
    modules = (CONSOLE / "lib" / "console-modules.ts").read_text(encoding="utf-8")
    for one in load_host().console_pages():
        assert f'"{one.value.module}":' in modules, f"{one.value.module}의 화면이 레지스트리에 없다"
    for route in ("overview", "selectors", "monitoring"):
        assert (CONSOLE / "app" / "ext" / "ui-automation" / route / "page.tsx").is_file(), route


def test_the_console_keeps_no_list_of_its_own() -> None:
    """손으로 베낀 목록으로 돌아가면 그 자리에서 다시 거짓말이 된다."""
    text = SHELL.read_text(encoding="utf-8")
    assert "pagesOf(" in text, "탐색 줄은 기여에서 온다"
    assert "APP_PAGES" not in text, "콘솔이 자기 목록을 다시 들면 확장을 더해도 줄이 안 생긴다"


def test_the_console_can_tell_which_extension_the_app_belongs_to() -> None:
    """콘솔이 줄을 고르는 열쇠 (C11 `AdminStatus.extension`) — 없으면 고를 길이 없다."""
    status = AdminStatus.model_validate(
        {
            "schema": 1,
            "app_id": "ui-automation",
            "name": "UI 자동화",
            "version": "0.4.0",
            "category": "system",
            "extension": {"id": "ui-automation", "version": "0.4.0"},
            "started_at": "2026-10-09T09:00:00+09:00",
        }
    )
    assert status.extension is not None
    assert status.extension.id == "ui-automation"
    # 확장의 서버 부분이 아닌 앱은 그냥 없다 (빈 목록이 된다).
    assert AdminStatus.model_validate(
        {
            "schema": 1,
            "app_id": "finance-invoice",
            "name": "청구",
            "version": "1.0.0",
            "category": "business",
            "started_at": "2026-10-09T09:00:00+09:00",
        }
    ).extension is None
