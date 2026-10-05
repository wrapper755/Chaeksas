"""`chk-center` — Center API를 띄운다.

    CHK_CENTER__ADMIN_TOKEN=... uv run chk-center

포트·경로는 환경변수로 바꾼다 (`CHK_CENTER__PORT` 등, `docs/04-setup.md` §6).
"""

from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 기본 코드페이지에서 한글이 터진다


def bootstrap(argv: list[str]) -> int:
    """`chk-center admin-keys bootstrap <public>` — 첫 Admin 키 (C2 §부트스트랩).

    **서버 셸에서만** 쓴다. 키가 하나라도 있으면 거부한다 — 그다음부터는 서명한 봉투로만
    더한다. 파일은 `chk-admin keys new`가 적어 둔 base64 공개키(`.pub`)다.
    """
    import base64

    from chaeksas.center.api.signing import bootstrap_key
    from chaeksas.center.errors import ApiError
    from chaeksas.center.settings import Settings
    from chaeksas.center.storage import Store

    if len(argv) < 2 or argv[0] != "bootstrap":
        print("쓰는 법: chk-center admin-keys bootstrap <공개키 파일> [이름]")
        return 2
    path = Path(argv[1])
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as e:
        print(f"공개키 파일을 읽지 못했다: {e}")
        return 2
    try:
        public = base64.b64decode(raw, validate=True)
    except Exception:  # noqa: BLE001 — 사람이 아무 파일이나 줄 수 있다
        print("공개키가 base64(raw 32바이트)가 아니다 — `chk-admin keys new`가 만든 `.pub`를 주세요")
        return 2
    if len(public) != 32:
        print(f"Ed25519 공개키는 32바이트다 (받은 것 {len(public)}바이트)")
        return 2

    store = Store(Settings.from_env().db_path)
    try:
        found = bootstrap_key(store, public_key=public, label=argv[2] if len(argv) > 2 else None)
    except ApiError as e:
        print(f"오류: {e.message}")
        return 2
    finally:
        store.close()
    print(f"첫 Admin 키를 넣었다 — {found.key_id}")
    return 0


def main() -> int:
    import uvicorn

    from chaeksas.center.app import create_app
    from chaeksas.center.settings import Settings

    if len(sys.argv) > 1 and sys.argv[1] == "admin-keys":
        return bootstrap(sys.argv[2:])

    settings = Settings.from_env()
    if not settings.admin_token:
        print("경고: CHK_CENTER__ADMIN_TOKEN이 없다 — 쓰기 API를 부를 수 없다 (읽기만 된다).")
    print(f"Center API: http://{settings.host}:{settings.port}  (DB {settings.db_path})")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
