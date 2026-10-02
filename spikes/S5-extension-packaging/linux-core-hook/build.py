"""설정을 바꿔 가며 probe.py를 묶고, 묶인 것을 돌려 결과를 표로 찍는다.

    uv run --with pyinstaller python spikes/S5-extension-packaging/build.py
    uv run --with pyinstaller python spikes/S5-extension-packaging/build.py --only bare --onefile

산출물은 임시 폴더에 둔다 (저장소를 더럽히지 않는다). `--out`으로 바꾼다.
Windows에서도 같은 명령으로 돌아야 한다 — `subprocess`에 인자 리스트로만 넘긴다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 기본 코드페이지에서 한글이 터진다

HERE = Path(__file__).resolve().parent
PROBE = HERE / "probe.py"
EXTENSION_DIST = "chaeksas-ext-ui-automation"
EXTENSION_PKG = "chaeksas.ext.ui_automation"

#: 설정 이름 → PyInstaller에 더 주는 인자. 위에서 아래로 하나씩 더해 간다.
#:
#: **ADR-0024 뒤로는 `bare`가 통과한다** — `chaeksas.core`가 `pyinstaller40` 엔트리 포인트로
#: 훅을 딸려 보내기 때문이다. 아래 손 인자들은 훅이 없던 때 무엇이 필요했는지 남겨 둔 것이고,
#: 처음의 실패 표(NOTES.md)를 다시 보려면 `packages/core/pyproject.toml`의 `[project.entry-points.
#: pyinstaller40]`을 지우고 `uv sync --all-packages`를 한 뒤 돌린다.
CONFIGS: dict[str, list[str]] = {
    "bare": [],
    "metadata": ["--copy-metadata", EXTENSION_DIST],
    "metadata+data": ["--copy-metadata", EXTENSION_DIST, "--collect-data", EXTENSION_PKG],
    "metadata+data+submodules": [
        "--copy-metadata", EXTENSION_DIST,
        "--collect-data", EXTENSION_PKG,
        "--collect-submodules", EXTENSION_PKG,
    ],
}


def build(name: str, extra: list[str], out: Path, *, onefile: bool) -> Path:
    dist = out / name / "dist"
    cmd = [
        "pyinstaller", str(PROBE),
        "--name", f"probe-{name}",
        "--onefile" if onefile else "--onedir",
        "--console",
        "--noconfirm",
        "--clean",
        "--log-level", "WARN",
        "--distpath", str(dist),
        "--workpath", str(out / name / "build"),
        "--specpath", str(out / name),
        *extra,
    ]
    print(f"\n▶ {name}: {' '.join(extra) or '(추가 인자 없음)'}")
    subprocess.run(cmd, check=True)
    exe = dist / f"probe-{name}"
    if sys.platform == "win32":
        exe = exe.with_suffix(".exe") if onefile else dist / f"probe-{name}" / f"probe-{name}.exe"
    elif not onefile:
        exe = dist / f"probe-{name}" / f"probe-{name}"
    return exe


def run_probe(exe: Path) -> dict:
    done = subprocess.run([str(exe)], capture_output=True, text=True, encoding="utf-8")
    for line in (done.stdout or "").splitlines():
        if line.startswith("PROBE_JSON "):
            return json.loads(line[len("PROBE_JSON "):])
    return {
        "_failed": True,
        "returncode": done.returncode,
        "stderr": " / ".join((done.stderr or "").strip().splitlines()[-3:]),
    }


def verdict(result: dict) -> str:
    if result.get("_failed"):
        return f"✗ 터짐 (rc={result['returncode']}) {result['stderr'][:120]}"
    bits = [
        f"entry_points={result['entry_points'] or '없음'}",
        f"확장={result['summary']['enabled'] or '없음'}",
        f"태스크={result['task_types'] or '없음'}",
        f"수행기={result.get('executor') or result.get('executor_error', '없음')}",
        f"편집기={result.get('editor') or result.get('editor_error', '없음')}",
        f"유틸={result.get('utility') or result.get('utility_error', '없음')}",
    ]
    if result["summary"]["failed"]:
        bits.append(f"읽기실패={result['summary']['failed']}")
    return " · ".join(bits)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "chk-s5")
    ap.add_argument("--only", action="append", choices=sorted(CONFIGS), default=None)
    ap.add_argument("--onefile", action="store_true", help="한 파일로 묶는다 (기본은 폴더)")
    args = ap.parse_args()

    print("묶지 않은 상태 (기준선):")
    print("  " + verdict(run_probe_source()))

    results: dict[str, dict] = {}
    for name in args.only or list(CONFIGS):
        exe = build(name, CONFIGS[name], args.out, onefile=args.onefile)
        results[name] = run_probe(exe)

    mode = "onefile" if args.onefile else "onedir"
    print(f"\n{'=' * 100}\n묶은 뒤 ({mode}, {sys.platform}):")
    for name, result in results.items():
        print(f"\n[{name}]\n  {verdict(result)}")
    print(f"\n산출물: {args.out}")
    return 0


def run_probe_source() -> dict:
    done = subprocess.run([sys.executable, str(PROBE)], capture_output=True, text=True, encoding="utf-8")
    for line in (done.stdout or "").splitlines():
        if line.startswith("PROBE_JSON "):
            return json.loads(line[len("PROBE_JSON "):])
    return {"_failed": True, "returncode": done.returncode, "stderr": (done.stderr or "")[-300:]}


if __name__ == "__main__":
    raise SystemExit(main())
