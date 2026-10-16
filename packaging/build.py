"""데스크톱 앱을 묶는다 — Studio·Bot UI ([ADR-0024](../docs/decisions/0024-desktop-packaging-extensions.md)).

    uv run --group build python packaging/build.py              # 둘 다
    uv run --group build python packaging/build.py bot-ui       # 하나만
    uv run --group build python packaging/build.py --want ui-automation

**onedir다** (onefile이 아니다) — 설치 프로그램이 그 폴더를 설치한다. 실행마다 압축을 풀면
기동이 느려지고(warm 1.3초 ↔ 3.4초) 로컬 런타임을 띄울 때마다 또 푼다 (스파이크 S5).

**확장 인자를 적지 않는다.** `core`가 주는 PyInstaller 훅(`core/__pyinstaller/`)이 설치된
엔트리 포인트 `chaeksas.extensions`를 훑어 메타데이터·데이터 파일·서브모듈을 넣는다 — 확장을
더해도 이 파일을 고치지 않는다 (ADR-0018: 플랫폼은 특정 확장을 모른다). **그래서 「무엇이
들어가는가」는 빌드 환경에 무엇이 설치됐는가로 정해진다** — 사내 확장이 생기면 ADR-0018 §5의
포함 목록을 설치하는 걸음이 앞에 붙는다.

**묶은 뒤 `--selftest`로 확인한다** (ADR-0024의 빌드 검사) — 확장이 빠지면 **실행 중에야**
드러나므로, 하나라도 빠지면 여기서 빌드를 실패시킨다. 무엇이 빠졌는지는 `core.selftest`가
가린다(엔트리 포인트 / `entry` 해석).

**Windows에서만 매니페스트를 넣는다** (`app.manifest` — DPI Per-Monitor v2, ADR-0021). 다른
OS에서는 PyInstaller가 받지 않는다. 개발 PC(Linux)에서 돌리면 **Linux 묶음**이 나온다 — 빌드
자체가 서는지 보는 데는 그것으로 되고, **Windows 산출물은 CI(또는 그 PC)가 만든다**.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# **한글을 찍는 CLI는 stdout도 UTF-8로 고정한다** (CLAUDE.md §5) — Windows 기본 코드페이지
# (cp949·cp1252)에서는 `print("── 묶는다")` 한 줄에 `UnicodeEncodeError`로 죽는다. CI가 일부러
# `PYTHONUTF8`을 켜지 않으므로(그래야 빠뜨린 곳이 드러난다) 여기서 고정한다 — 실제로 첫 번째
# Windows 산출물 실행이 이 한 줄 때문에 멈췄다.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DIST = ROOT / "build" / "dist"
WORK = ROOT / "build" / "work"

IS_WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class App:
    """묶을 앱 하나."""

    key: str
    name: str  # 실행 파일·폴더 이름
    script: str

    @property
    def exe(self) -> Path:
        return DIST / self.name / (f"{self.name}.exe" if IS_WINDOWS else self.name)


APPS = (
    App("bot-ui", "ChaeksasBotUI", "botui_main.py"),
    App("studio", "ChaeksasStudio", "studio_main.py"),
)


def size_mb(where: Path) -> float:
    files = [where] if where.is_file() else [f for f in where.rglob("*") if f.is_file()]
    return round(sum(f.stat().st_size for f in files) / 1024 / 1024, 1)


def child_env() -> dict[str, str]:
    """PyInstaller 자식에게 줄 환경 — **한글 출력이 Windows 코드페이지에서 죽지 않게**.

    우리 `core`의 PyInstaller 훅이 묶은 확장 수를 **한글로** 찍는다. 그 글은 **PyInstaller의
    프로세스**에서 나오므로 우리가 stdout을 고칠 수 없다 — **띄우는 쪽이 환경으로** 정해 준다
    (`PYTHONIOENCODING`·`PYTHONUTF8`). 첫 Windows 산출물 실행이 여기서 멈췄다: 빌드 자신의
    `print`를 고친 뒤에도 **자식 안에서** 같은 오류가 또 났다.
    """
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def build(app: App) -> float:
    """PyInstaller onedir 한 벌. 걸린 초를 돌려준다."""
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--log-level", "WARN",
        "--windowed", "--onedir",
        "--name", app.name,
        "--distpath", str(DIST), "--workpath", str(WORK), "--specpath", str(WORK),
    ]
    if IS_WINDOWS:
        # DPI 선언 — 같은 실행 파일로 뜨는 Worker까지 Per-Monitor v2가 된다 (ADR-0021).
        args += ["--manifest", str(HERE / "app.manifest")]
    args.append(str(HERE / app.script))

    started = time.perf_counter()
    done = subprocess.run(args, cwd=ROOT, check=False, env=child_env())
    if done.returncode:
        raise SystemExit(f"{app.key}: PyInstaller가 실패했다 (끝 코드 {done.returncode})")
    return round(time.perf_counter() - started, 1)


def selftest(app: App, want: list[str]) -> dict:
    """묶은 실행 파일을 `--selftest`로 돌린다 — 확장이 다 보이나 (ADR-0024).

    **결과를 파일로 받는다** — `--windowed`로 묶은 앱에는 콘솔이 없어 표준 출력이 사라진다.
    """
    out = WORK / f"selftest-{app.key}.json"
    out.unlink(missing_ok=True)
    args = [str(app.exe), "--selftest", str(out)]
    if want:
        args += ["--want", ",".join(want)]
    code = subprocess.run(args, check=False, timeout=300, env=child_env()).returncode
    if not out.exists():
        raise SystemExit(f"{app.key}: `--selftest`가 결과를 남기지 않았다 (끝 코드 {code})")
    found = json.loads(out.read_text(encoding="utf-8"))
    if code != 0 or not found.get("all_ok"):
        print(json.dumps(found, ensure_ascii=False, indent=2))
        raise SystemExit(f"{app.key}: 묶은 앱에 확장이 빠졌다 — 설치 파일로 내보내지 않는다")
    return dict(found)


def main() -> int:
    parser = argparse.ArgumentParser(description="데스크톱 앱 묶기 (ADR-0024)")
    parser.add_argument("apps", nargs="*", choices=[one.key for one in APPS], help="비우면 둘 다")
    parser.add_argument("--want", default="", help="묶음에 켜져 있어야 하는 확장 id (쉼표로 여럿)")
    parser.add_argument("--keep", action="store_true", help="이전 산출물을 지우지 않는다")
    found = parser.parse_args()

    want = [one.strip() for one in found.want.split(",") if one.strip()]
    chosen = [one for one in APPS if not found.apps or one.key in found.apps]
    if not found.keep and DIST.exists():
        shutil.rmtree(DIST)

    summary = []
    for app in chosen:
        print(f"── {app.key} 묶는다 ({'Windows' if IS_WINDOWS else sys.platform})")
        seconds = build(app)
        if not app.exe.exists():  # pragma: no cover — PyInstaller가 이름을 바꾸면
            raise SystemExit(f"{app.key}: 실행 파일이 없다: {app.exe}")
        checked = selftest(app, want)
        summary.append(
            {
                "app": app.key,
                "exe": str(app.exe.relative_to(ROOT).as_posix()),
                "size_mb": size_mb(app.exe.parent),
                "build_s": seconds,
                "extensions": checked["steps"]["entry_points"]["value"]["enabled"],
            }
        )

    print()
    for one in summary:
        print(f"{one['app']:7} {one['size_mb']:7.1f} MB  {one['build_s']:6.1f}초  확장 {one['extensions']}")
        print(f"        {one['exe']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
