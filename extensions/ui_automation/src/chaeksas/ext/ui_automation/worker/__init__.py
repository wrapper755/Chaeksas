"""Worker 로컬 런타임 — 127.0.0.1 REST, 로케이터 사다리, 셀렉터 등록용 분석

이 패키지는 **다른 프로세스에서** 돈다. Bot UI가 자기 실행 파일을 `--local-runtime
ui-automation:worker`로 다시 띄우고, 그 자식이 `extension.json`의 `entry`(`serve`)를 풀어
부른다 ([ADR-0024](../../../../../../docs/decisions/0024-desktop-packaging-extensions.md)).

Bot UI·실행기와 주고받는 것은 C10(로컬 API)이고, UI 자동화 앱과는 C8로 말한다. 서버 부분을
import하지 않는다 — HTTP로만 부른다 (`tests/test_import_direction.py`가 막는다).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from chaeksas.contracts import SERVICE_URL_ENV

#: 포트를 쓸 수 없을 때의 종료 코드 — Bot UI가 「포트 <p> 사용 중」으로 바꿔 보인다 (ADR-0023).
EXIT_PORT_IN_USE = 2




def plans_for(token_dir: Path, base_url: str) -> object:
    """세션 하나의 계획·보고 길을 만드는 함수 (C8).

    **키는 세션이 준다** (C10 `service_key`) — Worker는 키를 저장하지 않는다. 주소가
    비어 있으면 `None`이라 계획을 받아 올 수 없다 (「없는데 된 척」하지 않는다).
    """
    from chaeksas.ext.ui_automation.contracts.worker_local import SessionRequest  # noqa: PLC0415
    from chaeksas.ext.ui_automation.worker.plans import (  # noqa: PLC0415
        QUEUE_DIR,
        HttpOps,
        PlanCache,
        PlanService,
        ReportQueue,
    )

    def make(request: SessionRequest) -> object | None:
        if not base_url or not request.service_key:
            return None
        return PlanService(
            ops=HttpOps(
                base_url=base_url,
                api_key=request.service_key,
                business_key=request.business_key,
                mode=request.mode,
            ),
            cache=PlanCache(folder=token_dir / "plans"),
            queue=ReportQueue(folder=token_dir / QUEUE_DIR),
        )

    return make


def unsent_counter(token_dir: Path) -> Callable[[], int]:
    """밀린 보고를 세는 함수 (C10 `/v1/status`의 `unsent_reports`, BUI-09).

    큐는 `plans` 쪽에 있고 세션마다 새로 만들어지므로, **세는 일만** 떼어 Worker에 준다.
    """
    from chaeksas.ext.ui_automation.worker.plans import QUEUE_DIR, ReportQueue  # noqa: PLC0415

    queue = ReportQueue(folder=token_dir / QUEUE_DIR)
    return lambda: len(queue.waiting())


def backend(data_dir: Path | None = None) -> object | None:
    """화면을 만지는 쪽. **둘 다 없으면 `None`** — 세션을 열면 503이다 (「없는데 된 척」하지 않는다).

    브라우저(Playwright)와 Windows 데스크톱(UIA)을 하나로 묶어, 세션의 화면이 웹이냐 데스크톱이냐에
    따라 보낸다 (ADR-0033). 데스크톱 앱의 실행 명령은 `data_dir`의 `desktop-apps.json`이다 (C10).
    """
    from chaeksas.ext.ui_automation.worker import browser, desktop  # noqa: PLC0415
    from chaeksas.ext.ui_automation.worker.routing import RoutingBackend  # noqa: PLC0415

    # 브라우저는 **기본으로 안 보이게** 돈다 (서버·CI에는 화면이 없다). 사람이 봐야 하는 세션은
    # `SessionRequest.headed`로 켠다 (등록·시험이 그렇게 연다, C10).
    web = browser.BrowserBackend(headless=True) if browser.available() else None
    apps_file = (data_dir / desktop.APPS_FILE) if data_dir else None
    screen = desktop.DesktopBackend(launcher=desktop.AppLauncher(apps_file=apps_file)) if desktop.available() else None
    if web is None and screen is None:
        return None
    return RoutingBackend(web=web, desktop=screen)


def serve(*, port: int, token_dir: Path | None = None) -> int:
    """`bot_ui.local_runtimes[].entry` — `extension_api.LocalRuntimeEntry` (C10 기동 절차).

    **127.0.0.1에만 바인드한다** — 다른 PC에서 닿으면 안 된다. 토큰 파일을 먼저 쓰고(다시
    띄울 때마다 바뀐다) `/v1/health`에 답하기 시작한다.

    브라우저 백엔드는 Playwright가 깔려 있을 때만 붙는다. 없으면 세션을 열 때 503
    `browser_unavailable`이다 — **없는 것을 되는 척하지 않는다.**

    계획·보고(C8)는 UI 자동화 앱 주소(`CHK_WORKER__SERVICE_URL`)와 **세션이 준 키**가 함께
    있을 때만 돈다.
    """
    import uvicorn  # noqa: PLC0415 — 띄울 때만 든다

    from chaeksas.ext.ui_automation.contracts.worker_local import LOCAL_HOST
    from chaeksas.ext.ui_automation.worker.app import Backend, Worker, create_app, write_tokens

    where = token_dir or Path.cwd()
    token, admin = write_tokens(where)
    found = backend(where)
    worker = Worker(
        token=token,
        admin_token=admin,
        backend=cast("Backend | None", found),
        plans_factory=cast("Any", plans_for(where, os.environ.get(SERVICE_URL_ENV, ""))),
        unsent=unsent_counter(where),
    )
    app = create_app(worker)

    # **`uvicorn.run`이 아니라 `Server`다** — `POST /v1/admin/shutdown`(C10)이 멈출 것을 쥐어야
    # 한다. 그냥 끄면 열린 세션의 보고를 저장할 틈이 없다 (C13 `shutdown`).
    server = uvicorn.Server(uvicorn.Config(app, host=LOCAL_HOST, port=port, log_level="warning"))
    worker.stopper = lambda: setattr(server, "should_exit", True)
    try:
        server.run()
    except OSError:
        return EXIT_PORT_IN_USE
    return 0
