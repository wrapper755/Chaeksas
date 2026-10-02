"""묶인 앱이 로컬 런타임(Worker 프로세스)을 어떻게 띄우나.

C13의 `bot_ui.local_runtimes[].command`는 `["chk-worker"]`처럼 **PATH의 명령**을 적는다.
묶인 앱 안에는 그 콘솔 스크립트가 없다 (PyInstaller는 실행 파일 하나만 만든다). 그래서 둘을 본다.

1. `chk-worker`를 PATH에서 찾을 수 있나 → 없을 것이다 (설치 파일로 배포하면 PATH에 없다)
2. **자기 자신을 다시 실행**해서 자식을 띄울 수 있나 (`sys.executable` + 인자) → 이것이 되면
   묶인 Bot UI가 로컬 런타임을 띄울 길이 있다
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

MARKER = "RUNTIME_JSON "
CHILD_MARKER = "CHILD_OK "


def main() -> int:
    if "--child" in sys.argv:
        print(CHILD_MARKER + json.dumps({"argv": sys.argv[1:], "frozen": bool(getattr(sys, "frozen", False))}))
        return 0

    out: dict = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "sys_executable": sys.executable,
        "chk_worker_on_path": shutil.which("chk-worker"),
    }
    # 자기 자신을 자식으로 (묶이면 sys.executable이 이 실행 파일이다).
    done = subprocess.run(
        [sys.executable, "--child", "--port", "8899"], capture_output=True, text=True, encoding="utf-8"
    )
    child = next((ln[len(CHILD_MARKER):] for ln in (done.stdout or "").splitlines() if ln.startswith(CHILD_MARKER)), None)
    out["respawn_self"] = json.loads(child) if child else None
    out["respawn_returncode"] = done.returncode
    if child is None:
        out["respawn_stderr"] = " / ".join((done.stderr or "").strip().splitlines()[-2:])
    print(MARKER + json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
