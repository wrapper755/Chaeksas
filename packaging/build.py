"""데스크톱 앱을 묶는다 — Studio·PC 실행기 ([ADR-0024](../docs/decisions/0024-desktop-packaging-extensions.md)).

    uv run --group build python packaging/build.py              # 둘 다
    uv run --group build python packaging/build.py bot-ui       # 하나만
    uv run --group build python packaging/build.py --want <확장 id>
    uv run --group build python packaging/build.py --version 0.2.0
    uv run --group build python packaging/build.py --installer      # Windows에서만 — 설치 파일까지

**onedir다** (onefile이 아니다) — 설치 프로그램이 그 폴더를 설치한다. 실행마다 압축을 풀면
기동이 느려지고(warm 1.3초 ↔ 3.4초) 자식 프로세스를 띄울 때마다 또 푼다 (스파이크 S5).

**확장 인자를 적지 않는다.** `core`가 주는 PyInstaller 훅(`core/__pyinstaller/`)이 설치된
엔트리 포인트 `chaeksas.extensions`를 훑어 메타데이터·데이터 파일·서브모듈을 넣는다 — 확장을
더해도 이 파일을 고치지 않는다 (ADR-0018: 플랫폼은 특정 확장을 모른다). **그래서 「무엇이
들어가는가」는 빌드 환경에 무엇이 설치됐는가로 정해진다** — 사내 확장이 생기면 ADR-0018 §5의
포함 목록을 설치하는 걸음이 앞에 붙는다.

**묶은 뒤 `--selftest`로 확인한다** (ADR-0024의 빌드 검사) — 확장이 빠지면 **실행 중에야**
드러나므로, `--want`로 적은 것이 하나라도 빠지면 여기서 빌드를 실패시킨다. 무엇이 빠졌는지는
`core.selftest`가 가린다(엔트리 포인트 / `entry` 해석). **지금은 묶을 확장이 없다** (ADR-0114).

**Windows에서만 매니페스트를 넣는다** (`app.manifest` — DPI Per-Monitor v2, ADR-0021). 다른
OS에서는 PyInstaller가 받지 않는다. 개발 PC(Linux)에서 돌리면 **Linux 묶음**이 나온다 — 빌드
자체가 서는지 보는 데는 그것으로 되고, **Windows 산출물은 CI(또는 그 PC)가 만든다**.

**판을 찍는다** ([ADR-0067](../docs/decisions/0067-build-stamp.md)) — `--version`이 이기고, 없으면
지금 커밋의 `v*` 태그, 그것도 없으면 `<core 판>+g<커밋>`(고치다 만 파일이 있으면 `.dirty`)이다.
실행 파일 옆 `chaeksas-build.json`에 적고, `--selftest`가 **되읽은 판**이 다르면 빌드를 멈춘다.
`core`와 그 앱의 dist-info도 넣는다 — 안 넣으면 묶은 앱이 `core`의 판을 `0.0.0`으로 올린다.

**`--installer`면 설치 파일까지 만든다** ([ADR-0068](../docs/decisions/0068-installer-inno-setup-per-user.md)
— Inno Setup, 사용자별, Windows에서만). 스크립트는 `installer/chaeksas.iss` 하나이고 앱마다 다른 값을
여기서 `/D`로 넘긴다. `--check-install`은 그 설치 파일을 **조용히 설치 → 설치된 앱으로 `--selftest` →
조용히 제거**까지 해 본다 — **같은 `AppId`의 설치를 덮으므로 CI에서만** 쓴다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from chaeksas.bot_ui.autostart import TASK_NAME
from chaeksas.core.build_info import STAMP_NAME, Stamp, package_version, valid_version

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
INSTALLERS = ROOT / "build" / "installer"
ISS = HERE / "installer" / "chaeksas.iss"

IS_WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class App:
    """묶을 앱 하나."""

    key: str
    name: str  # 실행 파일·폴더 이름
    script: str
    dist: str  # 그 앱의 배포판 이름 — dist-info를 넣는다 (ADR-0067)
    #: 설치 파일 (ADR-0068) — **`app_id`는 바꾸지 않는다**(바꾸면 덮어쓰기가 아니라 두 번째 설치다).
    app_id: str = ""
    title: str = ""  # 설치·시작 메뉴에 보이는 이름
    dir_name: str = ""  # %LOCALAPPDATA%\Programs\Chaeksas\<여기>
    autostart_task: str | None = None  # 제거할 때 지울 작업 스케줄러 이름

    @property
    def exe(self) -> Path:
        return DIST / self.name / (f"{self.name}.exe" if IS_WINDOWS else self.name)


APPS = (
    App(
        "bot-ui", "ChaeksasBotUI", "botui_main.py", "chaeksas-bot-ui",
        app_id="2F476024-75DF-4DDE-A28C-A05E0E1909CB",
        title="Chaeksas PC 실행기",
        dir_name="BotUI",
        # 이름은 앱이 쓰는 그 자리에서 읽는다 — 베끼면 이름을 바꿀 때 지우지 못한 작업이 남는다.
        autostart_task=TASK_NAME,
    ),
    App(
        "studio", "ChaeksasStudio", "studio_main.py", "chaeksas-studio",
        app_id="AAAE763A-0A3C-4675-BCFB-16CB6B53C0C3",
        title="Chaeksas Studio",
        dir_name="Studio",
    ),
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


def _git(*args: str) -> str | None:
    """git 한 번 — 없거나 실패하면 `None` (git 없이 받은 소스에서도 묶을 수 있어야 한다)."""
    try:
        done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    except OSError:
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def decide_version(given: str | None) -> str:
    """찍을 판 (ADR-0067 §1) — `--version` > 지금 커밋의 `v*` 태그 > `<core 판>+g<커밋>[.dirty]`.

    **판 모양이 아니면 멈춘다** — 「판 올리기」가 견주어야 한다. 태그 없이 묶은 것은 로컬 판이
    붙어 **태그로 착각되지 않는다**.
    """
    if given:
        found = given.removeprefix("v")
    else:
        tag = _git("describe", "--tags", "--exact-match", "--match", "v*", "HEAD")
        if tag:
            found = tag.removeprefix("v")
        else:
            commit = _git("rev-parse", "--short=12", "HEAD")
            base = package_version("chaeksas-core")
            if commit is None:
                found = base
            else:
                dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
                found = f"{base}+g{commit}" + (".dirty" if dirty else "")
    if not valid_version(found):
        raise SystemExit(f"판 모양이 아니다: {found!r} — 예: 0.2.0, 0.2.0rc1 (ADR-0067)")
    return found


def write_stamp(app: App, version: str) -> Stamp:
    """실행 파일 옆에 판을 찍는다 (ADR-0067 §2)."""
    found = Stamp(
        version=version,
        commit=_git("rev-parse", "HEAD") or "unknown",
        built_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    (app.exe.parent / STAMP_NAME).write_text(
        json.dumps(found.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return found


def build(app: App) -> float:
    """PyInstaller onedir 한 벌. 걸린 초를 돌려준다."""
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--log-level", "WARN",
        "--windowed", "--onedir",
        "--name", app.name,
        "--distpath", str(DIST), "--workpath", str(WORK), "--specpath", str(WORK),
        # 판을 읽는 dist-info (ADR-0067) — 훅은 **확장의** 것만 넣는다.
        "--copy-metadata", "chaeksas-core", "--copy-metadata", app.dist,
    ]
    if IS_WINDOWS:
        # DPI 선언 — Per-Monitor v2 (ADR-0021).
        args += ["--manifest", str(HERE / "app.manifest")]
    args.append(str(HERE / app.script))

    started = time.perf_counter()
    done = subprocess.run(args, cwd=ROOT, check=False, env=child_env())
    if done.returncode:
        raise SystemExit(f"{app.key}: PyInstaller가 실패했다 (끝 코드 {done.returncode})")
    return round(time.perf_counter() - started, 1)


def selftest(app: App, want: list[str], version: str, exe: Path | None = None) -> dict:
    """묶은 실행 파일을 `--selftest`로 돌린다 — 확장이 다 보이나 (ADR-0024).

    **결과를 파일로 받는다** — `--windowed`로 묶은 앱에는 콘솔이 없어 표준 출력이 사라진다.
    """
    out = WORK / f"selftest-{app.key}{'-installed' if exe else ''}.json"
    out.unlink(missing_ok=True)
    args = [str(exe or app.exe), "--selftest", str(out), "--expect-version", version]
    if want:
        args += ["--want", ",".join(want)]
    code = subprocess.run(args, check=False, timeout=600, env=child_env()).returncode
    if not out.exists():
        raise SystemExit(f"{app.key}: `--selftest`가 결과를 남기지 않았다 (끝 코드 {code})")
    found = json.loads(out.read_text(encoding="utf-8"))
    if code != 0 or not found.get("all_ok"):
        print(json.dumps(found, ensure_ascii=False, indent=2))
        if not found.get("steps", {}).get("build", {}).get("ok", True):
            raise SystemExit(
                f"{app.key}: 묶은 앱이 읽은 판이 찍은 판({version})과 다르거나 core의 판을 모른다 (ADR-0067)"
            )
        raise SystemExit(f"{app.key}: 묶은 앱에 확장이 빠졌다 — 설치 파일로 내보내지 않는다")
    return dict(found)


def numeric_version(version: str) -> str:
    """파일 속성용 숫자 판 — Windows는 `a.b.c.d`만 받는다 (`0.1.0+g…` → `0.1.0.0`)."""
    head = re.match(r"\d+(\.\d+){0,3}", version)
    parts = (head.group(0) if head else "0").split(".")
    return ".".join([*parts, "0", "0", "0"][:4])


def installer_defines(app: App, version: str) -> list[str]:
    """`iscc`에 넘길 `/D` 값들 — 앱마다 다른 것은 **여기 한 자리**에만 있다 (스크립트는 하나다)."""
    found = {
        "AppKey": app.key,
        "AppId": app.app_id,
        "AppName": app.title,
        # 설치 파일 이름은 **ASCII**로 둔다 — 표시 이름(한글)은 바로가기·제거 목록에만 쓴다 (ADR-0111).
        "AppFileName": app.name,
        "AppExe": app.exe.name,
        "AppDirName": app.dir_name,
        "AppVersion": version,
        "NumericVersion": numeric_version(version),
        "SourceDir": str(app.exe.parent),
        "OutputDir": str(INSTALLERS),
    }
    if app.autostart_task:
        found["AutostartTask"] = app.autostart_task
    return [f"/D{key}={value}" for key, value in found.items()]


def find_iscc() -> Path:
    """Inno Setup 컴파일러 — 환경변수 `ISCC` > PATH > 기본 설치 자리. 없으면 멈춘다."""
    given = os.environ.get("ISCC")
    if given:
        return Path(given)
    on_path = shutil.which("iscc")
    if on_path:
        return Path(on_path)
    for base in ("ProgramFiles(x86)", "ProgramFiles"):
        root = os.environ.get(base)
        if root and (Path(root) / "Inno Setup 6" / "ISCC.exe").exists():
            return Path(root) / "Inno Setup 6" / "ISCC.exe"
    raise SystemExit("Inno Setup 6을 찾지 못했다 — 깔거나(choco install innosetup) 환경변수 ISCC로 알려 주세요")


def make_installer(app: App, version: str) -> Path:
    """설치 파일 한 벌 (ADR-0068). 만든 파일을 돌려준다."""
    INSTALLERS.mkdir(parents=True, exist_ok=True)
    args = [str(find_iscc()), "/Q", *installer_defines(app, version), str(ISS)]
    done = subprocess.run(args, cwd=ROOT, check=False, env=child_env())
    if done.returncode:
        raise SystemExit(f"{app.key}: 설치 파일을 만들지 못했다 (iscc 끝 코드 {done.returncode})")
    made = INSTALLERS / f"{app.name}-setup-{version}.exe"
    if not made.exists():  # pragma: no cover — 스크립트의 OutputBaseFilename과 어긋나면
        raise SystemExit(f"{app.key}: 설치 파일이 없다: {made}")
    return made


def check_install(app: App, setup: Path, want: list[str], version: str) -> float:
    """조용히 설치 → **설치된** 앱으로 `--selftest` → 조용히 제거 (ADR-0068 §6). 걸린 초.

    **같은 `AppId`의 설치를 덮는다** — CI에서만 부른다.
    """
    started = time.perf_counter()
    target = WORK / "install-check" / app.key
    shutil.rmtree(target, ignore_errors=True)
    log = WORK / f"install-{app.key}.log"
    code = subprocess.run(
        [str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DIR={target}", f"/LOG={log}"],
        check=False, timeout=900,
    ).returncode
    installed = target / app.exe.name
    if code != 0 or not installed.exists():
        raise SystemExit(f"{app.key}: 조용한 설치가 실패했다 (끝 코드 {code}, 로그 {log})")
    selftest(app, want, version, exe=installed)

    uninstaller = target / "unins000.exe"
    subprocess.run(
        [str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=False, timeout=600
    )
    # 제거기는 자신을 임시 폴더로 옮겨 다시 뜨고 **곧 돌아온다** — 실행 파일이 사라질 때까지 기다린다.
    until = time.monotonic() + 300
    while installed.exists() and time.monotonic() < until:
        time.sleep(2)
    if installed.exists():
        raise SystemExit(f"{app.key}: 조용한 제거 뒤에도 실행 파일이 남았다: {installed}")
    return round(time.perf_counter() - started, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="데스크톱 앱 묶기 (ADR-0024)")
    parser.add_argument("apps", nargs="*", choices=[one.key for one in APPS], help="비우면 둘 다")
    parser.add_argument("--want", default="", help="묶음에 켜져 있어야 하는 확장 id (쉼표로 여럿)")
    parser.add_argument("--keep", action="store_true", help="이전 산출물을 지우지 않는다")
    parser.add_argument("--version", default=None, help="찍을 판 (비우면 태그 또는 <core 판>+g<커밋>)")
    parser.add_argument("--installer", action="store_true", help="설치 파일까지 만든다 (Windows에서만)")
    parser.add_argument(
        "--check-install", action="store_true",
        help="설치 → 설치된 앱 검사 → 제거까지 해 본다 (같은 앱의 설치를 덮는다 — CI에서만)",
    )
    found = parser.parse_args()
    if (found.installer or found.check_install) and not IS_WINDOWS:
        raise SystemExit("설치 파일은 Windows에서만 만든다 (Inno Setup, ADR-0068)")
    if found.check_install and not found.installer:
        raise SystemExit("--check-install은 --installer와 함께 쓴다")

    version = decide_version(found.version)
    print(f"── 판 {version}")

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
        write_stamp(app, version)
        checked = selftest(app, want, version)
        setup = make_installer(app, version) if found.installer else None
        installed_s = check_install(app, setup, want, version) if setup and found.check_install else None
        summary.append(
            {
                "app": app.key,
                "version": version,
                "exe": str(app.exe.relative_to(ROOT).as_posix()),
                "size_mb": size_mb(app.exe.parent),
                "build_s": seconds,
                "extensions": checked["steps"]["entry_points"]["value"]["enabled"],
                "installer": None if setup is None else f"{setup.relative_to(ROOT).as_posix()} {size_mb(setup)} MB",
                "install_check_s": installed_s,
            }
        )

    print()
    for one in summary:
        print(
            f"{one['app']:7} {one['version']}  {one['size_mb']:7.1f} MB  {one['build_s']:6.1f}초"
            f"  확장 {one['extensions']}"
        )
        print(f"        {one['exe']}")
        if one["installer"]:
            print(f"        설치 파일 {one['installer']}")
        if one["install_check_s"] is not None:
            print(f"        설치 → 검사 → 제거 {one['install_check_s']}초")
    return 0


if __name__ == "__main__":
    sys.exit(main())
