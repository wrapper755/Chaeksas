"""`chk-center` — Center API를 띄운다.

    CHK_CENTER__ADMIN_TOKEN=... uv run chk-center

포트·경로는 환경변수로 바꾼다 (`CHK_CENTER__PORT` 등, `docs/04-setup.md` §6).
"""

from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 기본 코드페이지에서 한글이 터진다


def main() -> int:
    import uvicorn

    from chaeksas.center.app import create_app
    from chaeksas.center.settings import Settings

    settings = Settings.from_env()
    if not settings.admin_token:
        print("경고: CHK_CENTER__ADMIN_TOKEN이 없다 — 쓰기 API를 부를 수 없다 (읽기만 된다).")
    print(f"Center API: http://{settings.host}:{settings.port}  (DB {settings.db_path})")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
