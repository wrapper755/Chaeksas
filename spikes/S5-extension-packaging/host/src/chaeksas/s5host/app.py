"""S5 호스트 (Bot UI·Studio 흉내). 확장은 엔트리 포인트 `chaeksas.extensions`로만 찾는다.

    s5host --selftest <결과.json> [--studio]     # 자동 점검 후 종료
    s5host --local-runtime <확장>:<런타임> --port <p>  # 확장의 로컬 런타임으로 동작 (자기 자신을 다시 띄움)

로컬 런타임은 **같은 실행 파일을 인자만 바꿔 다시 띄운다.** 묶인 앱 안에 Python 인터프리터가 따로 없으므로
`python -m ...`을 쓸 수 없고, 런타임마다 실행 파일을 따로 묶으면 Qt·Python이 겹쳐 크기가 커진다.
"""

import importlib
import json
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

GROUP = "chaeksas.extensions"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def load_entry(spec: str) -> Any:
    mod, _, attr = spec.partition(":")
    obj = importlib.import_module(mod)
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj


def discover() -> dict[str, Any]:
    return {ep.name: ep for ep in entry_points(group=GROUP)}


def self_command(*args: str) -> list[str]:
    if frozen():
        return [sys.executable, *args]
    return [sys.executable, "-m", "chaeksas.s5host.app", *args]


def run_local_runtime(spec: str, port: int) -> None:
    ext_id, _, rt_id = spec.partition(":")
    ext = discover()[ext_id].load()
    rt = next(r for r in ext["bot_ui.local_runtimes"] if r["id"] == rt_id)
    load_entry(rt["entry"])(port)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def selftest(out: Path, studio: bool) -> int:
    r: dict[str, Any] = {"frozen": frozen(), "exe": sys.executable, "studio": studio, "steps": {}}
    t0 = time.perf_counter()

    def step(name: str, fn: Any) -> Any:
        t = time.perf_counter()
        try:
            v = fn()
            r["steps"][name] = {"ok": True, "ms": round((time.perf_counter() - t) * 1000), "value": v}
            return v
        except Exception as e:
            r["steps"][name] = {"ok": False, "error": f"{type(e).__name__}: {e}",
                                "trace": traceback.format_exc().splitlines()[-3:]}
            return None

    eps = step("entry_points", lambda: sorted(discover()))
    ext = step("load_extension", lambda: discover()["s5demo"].load()["id"]) and discover()["s5demo"].load()
    step("namespace_paths", lambda: [str(p) for p in importlib.import_module("chaeksas").__path__])
    step("manifest_data_file", lambda: importlib.import_module("chaeksas.ext.s5demo").manifest()["name"])

    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    app = QApplication.instance() or QApplication(sys.argv)

    def utility() -> str:
        cls = load_entry(ext["bot_ui.utilities"][0]["entry"])
        w = cls()
        w.show()
        app.processEvents()
        title = w.windowTitle()
        w.close()
        return title

    if ext:
        step("utility_widget", utility)

        def runtime() -> dict:
            port = free_port()
            p = subprocess.Popen(self_command("--local-runtime", "s5demo:worker", "--port", str(port)),
                                 creationflags=0x08000000)  # CREATE_NO_WINDOW
            try:
                deadline = time.perf_counter() + 30
                while time.perf_counter() < deadline:
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=1) as h:
                            body = json.loads(h.read())
                            body["start_ms"] = round((deadline - 30 - time.perf_counter()) * -1000)
                            return body
                    except OSError:
                        time.sleep(0.05)
                raise TimeoutError("health 30s")
            finally:
                p.kill()
                p.wait(5)

        step("local_runtime", runtime)

    if studio:
        def webengine() -> str:
            mod = importlib.import_module("chaeksas.s5host.studio")
            return mod.check(app)

        step("webengine", webengine)

    r["eps"] = eps
    r["total_ms"] = round((time.perf_counter() - t0) * 1000)
    r["all_ok"] = all(s["ok"] for s in r["steps"].values())
    out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if r["all_ok"] else 1


def main() -> None:
    a = sys.argv[1:]
    if a[:1] == ["--local-runtime"]:
        run_local_runtime(a[1], int(a[a.index("--port") + 1]))
    elif a[:1] == ["--selftest"]:
        sys.exit(selftest(Path(a[1]), "--studio" in a))
    else:
        from PySide6.QtWidgets import QApplication, QLabel  # noqa: PLC0415

        app = QApplication(sys.argv)
        lbl = QLabel("확장: " + ", ".join(sorted(discover())) or "(없음)")
        lbl.setWindowTitle("S5 host")
        lbl.resize(360, 80)
        lbl.show()
        app.exec()


if __name__ == "__main__":
    main()
