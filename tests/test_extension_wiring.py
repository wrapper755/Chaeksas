"""실제 Studio·실행 프로세스가 확장을 엔진에 꽂는다 (`HostTasks`, ADR-0018).

규칙만 본다 — 없는 태스크 종류는 `None`, 실행 프로세스·Studio가 확장의 비밀과 호출 토큰을 푼다,
확장별 설정은 파일로 넘긴다. (진짜 확장 한 바퀴는 그 확장이 들어올 때 다시 둔다 — ADR-0114.)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.bot_ui.runner import runner_args  # noqa: E402
from chaeksas.bot_ui.runner_main import RunnerSecrets  # noqa: E402
from chaeksas.core.extensions import HostTasks, load_host  # noqa: E402
from chaeksas.studio.extensions import StudioSecrets  # noqa: E402


def test_host_tasks_say_none_for_an_unknown_task_type() -> None:
    tasks = HostTasks(host=load_host(), make_context=lambda _: None)  # type: ignore[arg-type,return-value]
    assert tasks.executor("없는_태스크") is None, "엔진이 그림·설치 오류로 올린다 (LookupError가 아니다)"


def test_runner_secrets_give_the_call_token_and_extension_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """`call_token`은 이 실행의 호출 토큰(C15 — 제어 파일로 갈아 넣는다), 나머지는 그 확장의 비밀 칸이다."""
    from chaeksas.bot_ui.credentials import Credentials  # noqa: PLC0415
    from chaeksas.bot_ui.runner_main import CallTokenHolder  # noqa: PLC0415

    monkeypatch.setattr(Credentials, "extension_secret", lambda self, ext, ref: f"{ext}/{ref}")
    holder = CallTokenHolder(value="bpm_ctr_first")
    found = RunnerSecrets(Credentials(), "crm", call_token=holder)
    assert found.resolve("note") == "crm/note"
    assert found.resolve("call_token") == "bpm_ctr_first"
    holder.value = "bpm_ctr_renewed"
    assert found.resolve("call_token") == "bpm_ctr_renewed", "새 토큰을 그 자리에서 쓴다"


def test_the_extension_settings_ride_in_a_file_not_on_the_command_line(tmp_path: Path) -> None:
    args = runner_args(
        package=tmp_path / "pkg", run_id="run_20261005_120000_abcdef", data_dir=tmp_path,
        inputs_path=None, mode="deterministic", source="manual", job_id=None,
        extensions_path=tmp_path / "run.extensions.json",
    )
    assert args[args.index("--extensions") + 1].endswith("run.extensions.json")


def test_studio_resolves_extension_secrets_from_the_environment_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BPM_STUDIO__EXT__CRM__NOTE", "from-env")
    assert StudioSecrets(extension_id="crm").resolve("note") == "from-env"
