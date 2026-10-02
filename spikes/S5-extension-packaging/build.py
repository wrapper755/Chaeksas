"""S5: 호스트를 PyInstaller로 변형별로 묶고, 묶인 실행 파일에서 --selftest를 돌린다.

    .venv/Scripts/python.exe build.py            # 전부
    .venv/Scripts/python.exe build.py B C        # 일부

변형
  A  그대로 (botui_main.py, 옵션 없음)               — 엔트리 포인트·동적 import가 빠지는지 보는 기준선
  B  확장 옵션 자동 계산 (엔트리 포인트 그룹을 읽어 --copy-metadata·--collect-submodules·--collect-data)
  C  B + QtWebEngine (studio_main.py)               — Studio 크기·시작 시간
  D  B를 onefile로                                  — 한 파일 실행의 시작 시간
  E  B + 매니페스트(PerMonitorV2)                     — 같은 실행 파일로 뜨는 Worker의 DPI 모드 (ADR-0021)
결과: out/summary.json
"""

import json
import shutil
import subprocess
import sys
import time
from importlib.metadata import entry_points
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "out"


def extension_flags() -> list[str]:
    """설치된 확장(엔트리 포인트 그룹)마다 PyInstaller 옵션을 만든다 — 제품 빌드도 이렇게 계산한다."""
    flags: list[str] = []
    for ep in entry_points(group="chaeksas.extensions"):
        dist = ep.dist.name  # type: ignore[union-attr]
        pkg = ep.value.split(":")[0]  # chaeksas.ext.s5demo
        flags += ["--copy-metadata", dist, "--collect-submodules", pkg, "--collect-data", pkg]
    return flags


VARIANTS = {
    "A": ("botui_main.py", [], "onedir"),
    "B": ("botui_main.py", extension_flags(), "onedir"),
    "C": ("studio_main.py", extension_flags(), "onedir"),
    "D": ("botui_main.py", extension_flags(), "onefile"),
    "E": ("botui_main.py", [*extension_flags(), "--manifest", str(HERE / "app.manifest")], "onedir"),
}


def size_mb(p: Path) -> float:
    files = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file()]
    return round(sum(f.stat().st_size for f in files) / 1024 / 1024, 1)


def build(key: str) -> dict:
    script, flags, mode = VARIANTS[key]
    name = f"s5_{key}"
    t = time.perf_counter()
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN", "--windowed",
           f"--{mode}", "--name", name, "--distpath", str(HERE / "dist"), "--workpath", str(HERE / "build"),
           "--specpath", str(HERE / "build"), *flags, str(HERE / script)]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    res: dict = {"variant": key, "flags": flags, "mode": mode, "build_s": round(time.perf_counter() - t, 1),
                 "build_ok": p.returncode == 0}
    if p.returncode:
        res["build_err"] = p.stderr[-800:]
        return res
    exe = HERE / "dist" / (f"{name}.exe" if mode == "onefile" else f"{name}/{name}.exe")
    res["size_mb"] = size_mb(exe if mode == "onefile" else exe.parent)
    for run in ("cold", "warm"):
        out = OUT / f"selftest-{key}-{run}.json"
        out.unlink(missing_ok=True)
        args = [str(exe), "--selftest", str(out)] + (["--studio"] if script == "studio_main.py" else [])
        t = time.perf_counter()
        code = subprocess.run(args, check=False, timeout=180).returncode
        wall = round((time.perf_counter() - t) * 1000)
        r = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"steps": {}}
        res[run] = {"exit": code, "wall_ms": wall, "all_ok": r.get("all_ok"),
                    "steps": {k: (v["ok"], v.get("ms"), str(v.get("value", v.get("error")))[:100])
                              for k, v in r["steps"].items()}}
    return res


def main() -> None:
    OUT.mkdir(exist_ok=True)
    keys = sys.argv[1:] or list(VARIANTS)
    summary_path = OUT / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    for k in keys:
        if (HERE / "dist" / f"s5_{k}").exists():
            shutil.rmtree(HERE / "dist" / f"s5_{k}")
        summary[k] = build(k)
        s = summary[k]
        print(f"[{k}] build_ok={s['build_ok']} {s['build_s']}s size={s.get('size_mb')}MB "
              f"cold={s.get('cold', {}).get('wall_ms')}ms warm={s.get('warm', {}).get('wall_ms')}ms "
              f"all_ok={s.get('warm', {}).get('all_ok')}", flush=True)
        for name, (ok, ms, v) in s.get("warm", {}).get("steps", {}).items():
            print(f"     {'OK ' if ok else 'ERR'} {name:20} {ms}ms {v}", flush=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
