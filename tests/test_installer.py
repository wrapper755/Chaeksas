"""설치 파일 — Inno Setup, 사용자별 (ADR-0068).

진짜 설치 파일은 **Windows에서만** 만든다(`iscc`). 산출물 워크플로가 그것을 조용히 설치·검사·제거까지
해 본다(`build.py --check-install`). 여기서는 어느 OS에서나 볼 수 있는 것을 본다 — 스크립트와 빌드가
**같은 값을 말하는가**, 그리고 바꾸면 현장이 깨지는 값이 그대로인가.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from chaeksas.bot_ui.autostart import TASK_NAME

ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "packaging" / "installer" / "chaeksas.iss"
BUILD = ROOT / "packaging" / "build.py"

#: **바꾸면 덮어쓰기가 아니라 두 번째 설치가 된다** (ADR-0068 §1) — 현장 PC에 같은 앱이 둘 깔린다.
PINNED_APP_IDS = {
    "bot-ui": "2F476024-75DF-4DDE-A28C-A05E0E1909CB",
    "studio": "AAAE763A-0A3C-4675-BCFB-16CB6B53C0C3",
}

#: build.py는 모듈 수준에서 stdout을 다시 설정하므로 **따로 돌린다** (pytest의 stdout에 걸지 않는다).
_PEEK = (
    "import importlib.util, json, sys\n"
    "s = importlib.util.spec_from_file_location('b', sys.argv[1])\n"
    "m = importlib.util.module_from_spec(s); sys.modules['b'] = m; s.loader.exec_module(m)\n"
    "print(json.dumps({\n"
    "    'apps': [{'key': a.key, 'app_id': a.app_id, 'title': a.title, 'dir_name': a.dir_name,\n"
    "              'autostart_task': a.autostart_task,\n"
    "              'defines': m.installer_defines(a, '0.1.0+g4c30aeba3267')} for a in m.APPS],\n"
    "    'numeric': {v: m.numeric_version(v) for v in sys.argv[2:]},\n"
    "}, ensure_ascii=False))\n"
)


def _peek(*versions: str) -> dict[str, Any]:
    done = subprocess.run(
        [sys.executable, "-c", _PEEK, str(BUILD), *versions],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, check=True,
    )
    return dict(json.loads(done.stdout))


def _script() -> str:
    return ISS.read_text(encoding="utf-8-sig")


def test_the_script_is_utf8_with_a_bom() -> None:
    """Inno Setup 6은 BOM이 있어야 한글을 유니코드로 읽는다 — 없으면 설치 화면의 한글이 깨진다."""
    assert ISS.read_bytes().startswith(b"\xef\xbb\xbf")


def test_the_script_and_the_build_name_the_same_values() -> None:
    """스크립트가 쓰는 `{#값}`·`#ifdef 값`은 **빌드가 넘기는 것**이어야 한다 — 하나라도 어긋나면
    `iscc`가 Windows에서야 멈춘다(Linux CI는 그 컴파일러를 돌리지 못한다)."""
    text = _script()
    used = set(re.findall(r"\{#(\w+)\}", text)) | set(re.findall(r"#ifn?def\s+(\w+)", text))
    used |= set(re.findall(r"\{#StringChange\((\w+),", text))
    for app in _peek()["apps"]:
        passed = {one[2:].split("=", 1)[0] for one in app["defines"]}
        optional = {"AutostartTask", "ToolUiName"}
        assert used - optional <= passed, (app["key"], sorted(used - passed))
        assert passed <= used, (app["key"], sorted(passed - used))


def test_app_ids_never_change() -> None:
    found = {app["key"]: app["app_id"] for app in _peek()["apps"]}
    assert found == PINNED_APP_IDS


def test_only_bot_ui_removes_the_autostart_task_and_by_the_apps_own_name() -> None:
    """이름은 `autostart.TASK_NAME` 한 자리다 — 베끼면 이름을 바꿀 때 지우지 못한 작업이 남는다."""
    apps = {app["key"]: app for app in _peek()["apps"]}
    assert apps["bot-ui"]["autostart_task"] == TASK_NAME
    assert f"/DAutostartTask={TASK_NAME}" in apps["bot-ui"]["defines"]
    assert apps["studio"]["autostart_task"] is None
    assert not any(one.startswith("/DAutostartTask=") for one in apps["studio"]["defines"])


def test_the_script_keeps_the_decisions() -> None:
    """ADR-0068에서 정한 것 — 바꾸려면 ADR부터 바꾼다."""
    text = _script()
    assert "PrivilegesRequired=lowest" in text  # §2 사용자별
    assert "PrivilegesRequiredOverridesAllowed" not in text  # PC 전체로 넘어가는 길을 열지 않는다
    assert "DisableDirPage=yes" in text  # 자리는 하나
    assert re.search(r'^Type: filesandordirs; Name: "\{app\}\\_internal"', text, re.M)  # §3 옛 파일
    assert "CloseApplications=yes" in text  # 실행 중이면 닫고 깐다
    assert 'MessagesFile: "compiler:Languages\\Korean.isl"' in text


@pytest.mark.parametrize(
    ("given", "numeric"),
    [("0.2.0", "0.2.0.0"), ("0.1.0+g4c30aeba3267", "0.1.0.0"), ("1.2.3rc1", "1.2.3.0"), ("1.2", "1.2.0.0")],
)
def test_file_properties_get_a_numeric_version(given: str, numeric: str) -> None:
    """Windows 파일 속성은 `a.b.c.d`만 받는다 — 찍힌 판의 로컬 부분은 표시 판에만 남는다."""
    assert _peek(given)["numeric"][given] == numeric


@pytest.mark.skipif(sys.platform == "win32", reason="Windows에서는 진짜로 만든다")
def test_installers_are_refused_off_windows() -> None:
    done = subprocess.run(
        [sys.executable, str(BUILD), "--installer"],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, check=False,
    )
    assert done.returncode != 0 and "Windows에서만" in done.stderr + done.stdout
