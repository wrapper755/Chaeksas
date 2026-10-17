"""빌드 검사가 로컬 런타임을 **정말 띄워 본다** (`--start-runtimes`, ADR-0024).

`--selftest`의 다른 단계는 `entry`가 풀리는지까지만 본다. 묶은 실행 파일이 자신을
`--local-runtime`으로 다시 띄워 포트를 여는지는 **띄워 봐야** 안다. 여기서는 소스에서 같은 길을
돈다 — 묶지 않았으니 자식은 `python -m chaeksas.bot_ui`다 (`runtime_args`). 묶은 쪽은
`packaging/build.py`가 매번 본다.

이 파일은 **진짜 자식 프로세스를 띄운다** (`test_bot_ui_runtimes.py`와 다르다) — 진짜 Worker 하나,
그리고 일부러 못 뜨는 것 하나. 각각 몇 초다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.bot_ui.runtimes import RUNTIME_FILE, Runtimes, check_start, free_port  # noqa: E402
from chaeksas.bot_ui.settings import RuntimeSettings, Settings  # noqa: E402
from chaeksas.core.extensions import ExtensionHost, load_host  # noqa: E402
from chaeksas.core.selftest import START_RUNTIMES_FLAG, main  # noqa: E402

#: 일부러 못 뜨는 런타임 — 정의는 이 프로세스에만 있어 자식은 그 확장을 찾지 못한다.
BROKEN: dict[str, Any] = {
    "schema": 2,
    "id": "demo",
    "version": "1.0.0",
    "name": "데모",
    "publisher": "Chaeksas",
    "tier": "builtin",
    "api": ">=1,<2",
    "contributes": {
        "bot_ui.local_runtimes": [
            {"id": "helper", "label": "도우미", "entry": "demo.runtime:serve",
             "health": "/v1/health", "token_dir": True}
        ],
    },
}


@pytest.fixture
def user_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """사용자 데이터 위치 — 빌드 검사가 **여기에 아무것도 남기지 않아야** 한다."""
    where = tmp_path / "user"
    monkeypatch.setenv("CHK_BOT_UI__DATA_DIR", str(where))
    return where


def test_the_installed_runtime_really_starts_answers_and_stops(user_dir: Path) -> None:
    """진짜 Worker — `health`가 답하고, **토큰을 파일에서 읽어** `status`도 답한다. 끝나면 끈다."""
    found = check_start(load_host(), timeout_s=60)
    assert found["ok"], found
    (one,) = [row for row in found["value"] if row["runtime"] == "ui-automation:worker"]
    assert one["healthy"] and one["status"]
    # 사용자 자리에 `runtime.json`을 남기면 Studio가 없는 런타임을 찾는다.
    assert not user_dir.exists() or not any(user_dir.rglob(RUNTIME_FILE))


def test_a_runtime_that_cannot_start_fails_the_check_with_its_log(user_dir: Path) -> None:
    """못 뜨면 **실패로 적고** 자식 로그의 끝을 싣는다 — 빌드 로그에서 바로 까닭이 보이게."""
    host = ExtensionHost()
    host.add_installed(json.dumps(BROKEN).encode("utf-8"), origin="test", root="demo")
    found = check_start(host, timeout_s=20)
    assert not found["ok"]
    (one,) = found["value"]
    assert one["runtime"] == "demo:helper" and not one["ok"]
    assert "도우미" in one["error"]
    assert one["log"], "자식 로그가 비었다 — 왜 못 떴는지 빌드가 말하지 못한다"


def test_the_flag_without_a_launcher_is_a_failure_not_a_pass(tmp_path: Path) -> None:
    """런타임을 띄우지 않는 앱(Studio)에 깃발이 오면 **실패**다 — 빌드가 「봤다」고 믿으면 안 된다."""
    out = tmp_path / "selftest.json"
    assert main(["--selftest", str(out), START_RUNTIMES_FLAG], prog="chk-studio") == 1
    step = json.loads(out.read_text(encoding="utf-8"))["steps"]["runtimes"]
    assert not step["ok"] and "띄우지 않는다" in step["value"]


def test_without_the_flag_nothing_is_started(tmp_path: Path) -> None:
    out = tmp_path / "selftest.json"
    main(["--selftest", str(out)], prog="chk-bot-ui", start_runtimes=lambda: pytest.fail("띄웠다"))
    assert "runtimes" not in json.loads(out.read_text(encoding="utf-8"))["steps"]


def test_the_root_moves_tokens_and_the_port_file(tmp_path: Path) -> None:
    """`Runtimes.root`가 토큰·`runtime.json`의 자리를 옮긴다 (빌드 검사가 임시 폴더를 준다)."""
    host = ExtensionHost()
    host.add_installed(json.dumps(BROKEN).encode("utf-8"), origin="test", root="demo")
    port = free_port()
    found = Runtimes(
        host=host,
        settings=Settings(runtimes=(RuntimeSettings(runtime_id="helper", port=port),)),
        root=tmp_path,
        supervisor_factory=lambda *_: None,  # type: ignore[arg-type]
    )
    found.supervisor("helper")
    written = json.loads((tmp_path / "runtimes" / "helper" / RUNTIME_FILE).read_text(encoding="utf-8"))
    assert written == {"runtime": "demo:helper", "port": port}
    assert found.host_settings(("helper",))["runtime.helper.token_dir"] == str(tmp_path / "runtimes" / "helper")
