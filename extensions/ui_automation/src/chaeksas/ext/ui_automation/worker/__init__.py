"""Worker 로컬 런타임 — 127.0.0.1 REST, 로케이터 사다리, 셀렉터 등록용 분석

이 패키지는 **다른 프로세스에서** 돈다. Bot UI가 자기 실행 파일을 `--local-runtime
ui-automation:worker`로 다시 띄우고, 그 자식이 `extension.json`의 `entry`(`serve`)를 풀어
부른다 ([ADR-0024](../../../../../../docs/decisions/0024-desktop-packaging-extensions.md)).

Bot UI·실행기와 주고받는 것은 C10(로컬 API)이고, UI 자동화 앱과는 C8로 말한다. 서버 부분을
import하지 않는다 — HTTP로만 부른다 (`tests/test_import_direction.py`가 막는다).
"""

from __future__ import annotations

from pathlib import Path


def serve(*, port: int, token_dir: Path | None = None) -> int:
    """`bot_ui.local_runtimes[].entry` — `extension_api.LocalRuntimeEntry`.

    > 상태: **뼈대만.** 실제 로컬 API(C10)와 UI 세션은 M4다.

    할 일은 C10 「기동 절차」에 있다. 127.0.0.1에만 바인드하고, 토큰 파일을 `token_dir`에 쓴 뒤
    `/v1/health`에 답하기 시작한다. 포트를 쓸 수 없으면 종료 코드 2로 끝낸다 (Bot UI가
    「포트 <p> 사용 중」으로 바꿔 보인다, ADR-0023).
    """
    raise NotImplementedError("Worker 로컬 API(C10)는 M4다")
