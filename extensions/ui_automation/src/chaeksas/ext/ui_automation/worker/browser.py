"""브라우저 백엔드 — Playwright로 **찾고 조작한다** (C10 `Backend`, C8 `Finder`).

여기는 **얇다.** 사다리·치유·세션은 `ladder.py`·`app.py`가 들고 있고, 이 파일은 로케이터
하나를 Playwright 말로 옮기고 동작을 한 번 하는 일만 한다. 그래서 브라우저 없이도 규칙을
시험할 수 있다 (`tests/test_worker_ladder.py`).

- **값을 로그에 남기지 않는다** (원칙 6). 치유 스냅샷은 보내기 전에 가린다.
- **셀렉터는 이 안에만** 있다 (C10 — 시맨틱 키만 경계를 넘는다).
- Playwright가 없거나 브라우저가 깔려 있지 않으면 **세션을 열지 않는다** — 「없는데 된 척」
  하지 않는다 (C10 `browser_unavailable`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec, PlanStep, masked
from chaeksas.ext.ui_automation.contracts.worker_local import SessionRequest, StepRequest, StepResult
from chaeksas.ext.ui_automation.worker.ladder import Match

log = logging.getLogger(__name__)

#: 치유 요청에 싣는 스냅샷 크기 한도 (C8).
ARIA_MAX = 32 * 1024
SUB_DOM_MAX = 16 * 1024


class BrowserUnavailable(RuntimeError):
    """브라우저를 띄우지 못했다 (C10 `browser_unavailable`)."""


def available() -> bool:
    """Playwright가 깔려 있나. **브라우저 바이너리까지는 모른다** — 열어 봐야 안다."""
    try:
        import playwright.sync_api  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


@dataclass
class BrowserFinder:
    """열린 화면 하나에서 찾고 조작한다 (C8 `Finder`).

    `page`는 Playwright의 `Page`다. 타입을 직접 쓰지 않는 것은 Playwright가 없는 PC에서도
    이 모듈을 import할 수 있게 하려는 것이다 (Worker는 깔려 있을 때만 쓴다).
    """

    page: Any
    #: 가릴 업무 값 (입력한 값들). **스냅샷을 보내기 전에** 쓴다 (원칙 6).
    secrets: list[str] = field(default_factory=list)

    def find(self, locator: LocatorSpec, *, timeout_ms: int) -> Match:
        """로케이터 하나로 찾는다. **몇 개 맞았는지**를 돌려준다 (하나여야 쓴다)."""
        try:
            found = self._locate(locator)
            # Playwright의 `count`는 **함수**다 — 속성으로 읽으면 늘 「맞았다」가 된다.
            count = int(found.count())
        except Exception as e:  # noqa: BLE001 — 셀렉터가 깨졌을 수 있다
            return Match(error=f"{type(e).__name__}")
        if count != 1:
            return Match(count=count)
        try:
            found.first.wait_for(state="attached", timeout=timeout_ms)
        except Exception as e:  # noqa: BLE001
            return Match(count=count, error=f"{type(e).__name__}")
        return Match(count=1, handle=found.first)

    def _locate(self, locator: LocatorSpec) -> Any:
        """C8 전략 → Playwright 로케이터. **여기가 셀렉터가 사는 유일한 자리**다."""
        if locator.type == "role":
            return self.page.get_by_role(locator.value, name=locator.name, exact=locator.exact)
        if locator.type == "test_id":
            return self.page.get_by_test_id(locator.value)
        if locator.type == "css":
            return self.page.locator(locator.value)
        if locator.type == "xpath":
            return self.page.locator(f"xpath={locator.value}")
        raise ValueError(f"웹에서 쓸 수 없는 전략이다: {locator.type}")

    def act(self, handle: Any, step: PlanStep, *, timeout_ms: int) -> str | None:
        """조작하거나 읽는다. **읽기 결과만** 글로 돌려준다 (C10 `text`)."""
        action = step.action
        if action == "fill":
            handle.fill(str(step.value), timeout=timeout_ms)
            self.secrets.append(str(step.value))
            return None
        if action == "click":
            handle.click(timeout=timeout_ms)
            return None
        if action == "press":
            handle.press(str(step.value), timeout=timeout_ms)
            return None
        if action == "select":
            handle.select_option(str(step.value), timeout=timeout_ms)
            self.secrets.append(str(step.value))
            return None
        if action == "read":
            return str(handle.inner_text(timeout=timeout_ms))
        if action == "read_table":
            return self._table(handle, timeout_ms)
        if action == "read_options":
            return "\n".join(
                str(one.inner_text(timeout=timeout_ms)) for one in handle.locator("option").all()
            )
        if action == "read_selection":
            return str(handle.input_value(timeout=timeout_ms))
        raise ValueError(f"모르는 동작이다: {action}")

    def _table(self, handle: Any, timeout_ms: int) -> str:
        """표는 **TSV**로 돌려준다 (C10 — 사람이 읽는 형태)."""
        rows = []
        for row in handle.locator("tr").all():
            cells = row.locator("th, td").all()
            rows.append("\t".join(str(cell.inner_text(timeout=timeout_ms)).strip() for cell in cells))
        return "\n".join(rows)

    def snapshot(self) -> tuple[str, str]:
        """치유에 보낼 `(aria, sub_dom)` — **값을 가리고 잘라서** 준다 (C8·원칙 6)."""
        try:
            aria = str(self.page.locator("body").aria_snapshot())
        except Exception:  # noqa: BLE001 — 스냅샷을 못 떠도 치유는 시도할 수 있다
            aria = ""
        try:
            sub_dom = str(self.page.content())
        except Exception:  # noqa: BLE001
            sub_dom = ""
        return (
            masked(aria, self.secrets)[:ARIA_MAX],
            masked(sub_dom, self.secrets)[:SUB_DOM_MAX],
        )

    def url(self) -> str:
        try:
            return str(self.page.url)
        except Exception:  # noqa: BLE001
            return ""


@dataclass
class BrowserBackend:
    """C10 `Backend` — 세션마다 브라우저 탭 하나.

    **Bot 실행은 한 번에 하나**(ADR-0014)라 열린 탭도 하나다. 시험 실행은 `headed=True`로
    사람이 보게 둔다 (STU-08).
    """

    headless: bool = True
    _playwright: Any = None
    _browser: Any = None
    _finders: dict[str, BrowserFinder] = field(default_factory=dict)

    def open(self, request: SessionRequest) -> str:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415 — 열 때만 든다

        if self._playwright is None:
            self._playwright = sync_playwright().start()
        try:
            self._browser = self._browser or self._playwright.chromium.launch(
                headless=self.headless and not request.headed
            )
        except Exception as e:  # noqa: BLE001 — 브라우저가 안 깔렸을 수 있다
            raise BrowserUnavailable(f"브라우저를 띄우지 못했습니다: {type(e).__name__}") from e

        page = self._browser.new_page()
        if request.start_url:
            page.goto(request.start_url)
        self._finders[request.business_key] = BrowserFinder(page=page)
        return str(page.url)

    def finder(self, business_key: str) -> BrowserFinder | None:
        return self._finders.get(business_key)

    def step(self, session_id: str, request: StepRequest) -> StepResult:
        """**여기서는 사다리를 타지 않는다** — 세션이 계획을 들고 `ladder.run_step()`을 부른다.

        > 상태: 계획을 받아 오는 길(C8 `plan`)이 아직 없다. 그때까지 이 백엔드는 스텝을
        > 받지 않는다 — **없는 것을 되는 척하지 않는다.**
        """
        raise NotImplementedError("계획(C8 plan)을 받아 오는 길은 다음 조각이다")

    def goto(self, session_id: str, url: str) -> str:
        found = next(iter(self._finders.values()), None)
        if found is None:
            raise BrowserUnavailable("열린 화면이 없습니다")
        found.page.goto(url)
        return str(found.page.url)

    def close(self, session_id: str) -> None:
        for finder in self._finders.values():
            try:
                finder.page.close()
            except Exception as e:  # noqa: BLE001 — 닫다 실패해도 세션은 끝난다
                log.debug("탭을 닫지 못했다: %s", e)
        self._finders.clear()

    def shutdown(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None


__all__ = [
    "ARIA_MAX",
    "SUB_DOM_MAX",
    "BrowserBackend",
    "BrowserFinder",
    "BrowserUnavailable",
    "available",
]
