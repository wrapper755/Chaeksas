"""산출물의 판 — 빌드가 찍고 앱이 읽어 올린다 (ADR-0067).

진짜 묶기는 몇 분이 걸려 여기서 돌리지 않는다 — 묶은 앱이 **되읽어** 확인하는 것은
`packaging/build.py`가 매번 한다. 여기서는 그 둘이 쓰는 조각을 본다: 찍힌 파일 읽기, 판 모양,
빌드 검사의 `build` 단계, 판을 정하는 규칙, C4 `versions`로 가는 길.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from chaeksas.contracts.bot_ui import BuildStamp, Versions
from chaeksas.core import build_info
from chaeksas.core.build_info import STAMP_NAME, Stamp, read_stamp, valid_version

ROOT = Path(__file__).resolve().parents[1]

GOOD = Stamp(version="0.2.0", commit="13bca2382f33034f7d2cbc3d41f533ea2cd1ab47", built_at="2026-10-17T03:18:55Z")


def _write(where: Path, body: object) -> Path:
    path = where / STAMP_NAME
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "value",
    ["0.2.0", "1.0", "0.2.0rc1", "0.2.0.post1", "0.2.0.dev4", "0.1.0+g13bca2382f33", "0.1.0+g13bca2382f33.dirty"],
)
def test_version_shapes_that_can_be_compared(value: str) -> None:
    assert valid_version(value)


@pytest.mark.parametrize("value", ["", "v0.2.0", "banana", "0.2", "0.2.0-beta", "0.2.0+", "0.2.0 "])
def test_version_shapes_that_cannot(value: str) -> None:
    """「판 올리기」가 견주어야 하므로 아무 글이나 받지 않는다 (`0.2`만은 받는다 — PEP 440)."""
    if value == "0.2":
        assert valid_version(value)
        return
    assert not valid_version(value)


def test_a_stamp_reads_back_what_was_written(tmp_path: Path) -> None:
    assert read_stamp(_write(tmp_path, GOOD.to_json())) == GOOD


@pytest.mark.parametrize(
    "body",
    [
        "깨진 JSON",
        ["목록"],
        {"version": "0.2.0", "commit": "abc"},  # built_at 없음
        {"version": "banana", "commit": "abc", "built_at": "2026-10-17T00:00:00Z"},
        {"version": "", "commit": "abc", "built_at": "2026-10-17T00:00:00Z"},
    ],
)
def test_a_broken_stamp_is_no_stamp(tmp_path: Path, body: object) -> None:
    """**판 하나로 앱이 죽지 않는다** — 없는 것으로 보고 dist-info로 간다."""
    path = tmp_path / STAMP_NAME
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    assert read_stamp(path) is None
    assert read_stamp(tmp_path / "없는 파일") is None


def test_an_unpacked_app_has_no_stamp_and_reports_its_package_version() -> None:
    """묶지 않은 것은 `python` 옆을 뒤지지 않는다 — dist-info가 판이다."""
    assert not getattr(sys, "frozen", False)
    assert build_info.stamp() is None
    assert build_info.product_version("chaeksas-bot-ui") == build_info.package_version("chaeksas-bot-ui")
    assert build_info.package_version("chaeksas-core") != build_info.UNKNOWN
    assert build_info.package_version("없는-배포판") == build_info.UNKNOWN


def test_a_packed_app_reads_the_stamp_next_to_its_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, GOOD.to_json())
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ChaeksasBotUI.exe"))
    assert build_info.stamp() == GOOD
    assert build_info.product_version("chaeksas-bot-ui") == "0.2.0"


# ───────────────────── 빌드 검사의 `build` 단계 ─────────────────────


def test_selftest_shows_the_stamp_and_only_judges_when_asked() -> None:
    from chaeksas.core.selftest import check  # noqa: PLC0415

    shown = check(stamp=GOOD)
    assert shown["steps"]["build"]["ok"]
    assert shown["steps"]["build"]["value"]["stamp"]["version"] == "0.2.0"
    assert shown["steps"]["build"]["value"]["core"] == build_info.package_version("chaeksas-core")

    # 묶지 않은 앱에는 찍힌 것이 없다 — 판단을 부탁하지 않으면 막지 않는다.
    assert check()["steps"]["build"] == {
        "ok": True,
        "value": {"stamp": None, "core": build_info.package_version("chaeksas-core")},
    }


def test_selftest_fails_when_the_app_reads_another_version() -> None:
    """빌드가 넘긴 판과 **묶은 앱이 읽은 판**이 다르면 빌드가 멈춘다 (ADR-0067 §4)."""
    from chaeksas.core.selftest import check  # noqa: PLC0415

    assert check(stamp=GOOD, expect_version="0.2.0")["all_ok"]
    wrong = check(stamp=GOOD, expect_version="0.3.0")
    assert not wrong["all_ok"] and not wrong["steps"]["build"]["ok"]
    missing = check(expect_version="0.2.0")  # 파일이 안 들어갔다
    assert not missing["all_ok"]


def test_both_apps_read_the_same_selftest_flags(tmp_path: Path) -> None:
    """깃발은 `core.selftest.main` 한 자리가 읽는다 — 한 앱에만 늘리면 빌드가 한쪽에만 넘긴다."""
    from chaeksas.core.selftest import main  # noqa: PLC0415

    out = tmp_path / "selftest.json"
    code = main(["--selftest", str(out), "--want", "ui-automation", "--expect-version", "0.2.0"], prog="t")
    found = json.loads(out.read_text(encoding="utf-8"))
    assert code == 1  # 묶지 않은 앱에는 찍힌 판이 없다
    assert found["steps"]["entry_points"]["ok"]
    assert not found["steps"]["build"]["ok"]


# ───────────────────── 판을 정하는 규칙 (`packaging/build.py`) ─────────────────────

#: 그 파일은 모듈 수준에서 stdout을 다시 설정하므로 **따로 돌린다** (pytest의 stdout에 걸지 않는다).
_DECIDE = (
    "import importlib.util, sys\n"
    "s = importlib.util.spec_from_file_location('b', sys.argv[1])\n"
    "m = importlib.util.module_from_spec(s); sys.modules['b'] = m; s.loader.exec_module(m)\n"
    "given = sys.argv[2] or None\n"
    "try:\n"
    "    print(m.decide_version(given))\n"
    "except SystemExit as e:\n"
    "    print('STOP', e)\n"
)


def _decide(given: str) -> str:
    done = subprocess.run(
        [sys.executable, "-c", _DECIDE, str(ROOT / "packaging" / "build.py"), given],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, check=True,
    )
    return done.stdout.strip()


def test_the_given_version_wins_and_loses_its_v() -> None:
    assert _decide("0.2.0") == "0.2.0"
    assert _decide("v0.2.0rc1") == "0.2.0rc1"  # 태그 이름을 그대로 넘겨도 된다


def test_a_version_that_cannot_be_compared_stops_the_build() -> None:
    assert _decide("banana").startswith("STOP")


def test_without_a_tag_the_build_says_so_in_the_version() -> None:
    """태그 없이 묶은 것은 **로컬 판**이 붙어 태그로 착각되지 않는다 (체크아웃이면 커밋이 붙는다)."""
    found = _decide("")
    assert valid_version(found)
    assert found.startswith(build_info.package_version("chaeksas-core"))
    if (ROOT / ".git").exists() and "+g" not in found:  # pragma: no cover — 태그가 붙은 커밋에서 돌 때
        assert "+" not in found


# ───────────────────── C4 `versions`로 가는 길 ─────────────────────


def test_bot_ui_reports_build_only_when_packed(monkeypatch: pytest.MonkeyPatch) -> None:
    """`versions.build`가 있으면 묶은 것, **없으면 체크아웃**이다 (C4 — 「모른다」가 아니다)."""
    from chaeksas.bot_ui import agent as bot_agent  # noqa: PLC0415

    class _Agent:
        supervisors: dict[str, object] = {}

    monkeypatch.setattr(build_info, "stamp", lambda: None)
    plain = bot_agent.Agent.versions(_Agent())  # type: ignore[arg-type]
    assert plain.build is None and plain.worker is None

    monkeypatch.setattr(build_info, "stamp", lambda: GOOD)
    packed = bot_agent.Agent.versions(_Agent())  # type: ignore[arg-type]
    assert packed.build == BuildStamp(commit=GOOD.commit, built_at=GOOD.built_at)
    # 옛 Center도 읽는다 — 선택 칸이고 모양은 계약 그대로다.
    assert Versions.model_validate(packed.to_json_dict()) == packed


def test_server_runner_reports_installed_versions_not_a_written_one() -> None:
    """서버 실행기는 묶지 않는다 — 판은 dist-info다 (코드에 적은 `0.1.0`이 아니다)."""
    from chaeksas.server_runner import agent as runner_agent  # noqa: PLC0415

    assert runner_agent.RUNNER_VERSION == build_info.package_version("chaeksas-server-runner")
    assert runner_agent.CORE_VERSION == build_info.package_version("chaeksas-core")
    assert runner_agent.RUNNER_VERSION != build_info.UNKNOWN
