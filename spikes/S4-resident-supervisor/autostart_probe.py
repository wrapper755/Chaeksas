"""자동 시작으로 불려 로그인 뒤 몇 초 만에 떴는지 기록하고 끝난다 (HKCU Run 시험용).

    pythonw autostart_probe.py   → outputs/autostart.jsonl 한 줄
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from wts import seconds_since_logon  # noqa: E402

OUT = Path(__file__).parent / "outputs"
OUT.mkdir(exist_ok=True)
tasks = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, encoding="mbcs",
                       check=False, creationflags=0x08000000).stdout.lower()
row = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "since_logon_s": round(seconds_since_logon(), 1),
       "pid": os.getpid(), "exe": sys.executable, "cwd": os.getcwd(),
       "explorer_running": "explorer.exe" in tasks, "argv": sys.argv}
with (OUT / "autostart.jsonl").open("a", encoding="utf-8") as f:
    f.write(json.dumps(row, ensure_ascii=False) + "\n")
