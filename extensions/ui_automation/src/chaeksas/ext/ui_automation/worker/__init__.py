"""Worker 로컬 런타임 — 127.0.0.1 REST, 로케이터 사다리, 셀렉터 등록용 분석

이 패키지는 **다른 프로세스에서** 돈다. Bot UI가 자기 실행 파일을 `--local-runtime
ui-automation:worker`로 다시 띄우고, 그 자식이 `extension.json`의 `entry`(`serve`)를 풀어
부른다 ([ADR-0024](../../../../../../docs/decisions/0024-desktop-packaging-extensions.md)).

Bot UI·실행기와 주고받는 것은 C10(로컬 API)이고, UI 자동화 앱과는 C8로 말한다. 서버 부분을
import하지 않는다 — HTTP로만 부른다 (`tests/test_import_direction.py`가 막는다).
"""

from __future__ import annotations

from pathlib import Path

#: 포트를 쓸 수 없을 때의 종료 코드 — Bot UI가 「포트 <p> 사용 중」으로 바꿔 보인다 (ADR-0023).
EXIT_PORT_IN_USE = 2


def serve(*, port: int, token_dir: Path | None = None) -> int:
    """`bot_ui.local_runtimes[].entry` — `extension_api.LocalRuntimeEntry` (C10 기동 절차).

    **127.0.0.1에만 바인드한다** — 다른 PC에서 닿으면 안 된다. 토큰 파일을 먼저 쓰고(다시
    띄울 때마다 바뀐다) `/v1/health`에 답하기 시작한다.

    **화면을 만지는 백엔드는 아직 없다** (Windows UIA·브라우저는 다음 조각) — 세션을 열면
    503 `browser_unavailable`이다. 「없는데 된 척」하지 않는다.
    """
    import uvicorn  # noqa: PLC0415 — 띄울 때만 든다

    from chaeksas.ext.ui_automation.contracts.worker_local import LOCAL_HOST
    from chaeksas.ext.ui_automation.worker.app import Worker, create_app, write_tokens

    where = token_dir or Path.cwd()
    token, admin = write_tokens(where)
    app = create_app(Worker(token=token, admin_token=admin))

    try:
        uvicorn.run(app, host=LOCAL_HOST, port=port, log_level="warning")
    except OSError:
        return EXIT_PORT_IN_USE
    return 0
