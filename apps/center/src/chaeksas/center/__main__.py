"""`bpm-center` — Center API를 띄운다.

    BPM_CENTER__FIRST_ADMIN__PASSWORD=... uv run bpm-center

포트·경로는 환경변수로 바꾼다 (`BPM_CENTER__PORT` 등, `docs/04-setup.md` §6).
"""

from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 기본 코드페이지에서 한글이 터진다


def signing_key(argv: list[str]) -> int:
    """`bpm-center signing-key list|rotate|retire <key_id>` — Center 서명 키 (ADR-0090 §5).

    **서버 셸에서만** 쓴다. `rotate`는 새 키가 그 뒤의 서명을 맡고 옛 키는 믿는 목록에 남는다.
    `retire`는 그 키가 서명한 승인·배포를 **모두 무효**로 만든다 — 그래서 한 번 더 묻는다.
    """
    from chaeksas.center import signer
    from chaeksas.center.api.signing import admin_keys
    from chaeksas.center.settings import Settings
    from chaeksas.center.storage import Store

    if not argv or argv[0] not in ("list", "rotate", "retire") or (argv[0] == "retire" and len(argv) < 2):
        print("쓰는 법: bpm-center signing-key list | rotate | retire <key_id> [-y]")
        return 2
    store = Store(Settings.from_env().db_path)
    try:
        current = signer.current_key_id(store)
        if argv[0] == "list":
            for one in admin_keys(store):
                state = "버림" if one.revoked else ("서명 중" if one.key_id == current else "믿음")
                print(f"{one.key_id}  {one.label or '-':12}  {state}")
            return 0
        if argv[0] == "rotate":
            print(f"새 서명 키 {signer.rotate(store)} — 옛 키 {current}는 믿는 목록에 남는다")
            return 0
        key_id = argv[1]
        if "-y" not in argv:
            answer = input(f"{key_id}가 서명한 승인·배포가 모두 무효가 됩니다. 계속할까요? [y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                print("그만두었다")
                return 1
        try:
            signer.retire(store, key_id)
        except (ValueError, LookupError) as e:
            print(f"오류: {e}")
            return 2
        print(f"{key_id}를 버렸다")
        return 0
    finally:
        store.close()


def hosts(argv: list[str]) -> int:
    """`bpm-center hosts duplicates|retire <id>` — 겹친 기계 행을 **사람이** 고른다 (ADR-0066).

    3판(키 묶기 UNIQUE)의 지킴에 걸려 Center가 뜨지 않을 때 쓴다. **`Store`를 열지 않는다** —
    열면 옮기기가 돌고 그 지킴에 다시 걸린다. Center를 **멈춘 채로** 쓴다.
    """
    import sqlite3

    from chaeksas.center.repair import RepairError, describe, duplicates, retire
    from chaeksas.center.settings import Settings

    if not argv or argv[0] not in ("duplicates", "retire") or (argv[0] == "retire" and len(argv) < 2):
        print("쓰는 법: bpm-center hosts duplicates | bpm-center hosts retire <bot_ui_id|server_runner_id>")
        return 2
    path = Settings.from_env().db_path
    if not Path(path).is_file():
        print(f"DB가 없다: {path}")
        return 2
    conn = sqlite3.connect(str(path))
    try:
        if argv[0] == "duplicates":
            print(describe(duplicates(conn)))
            return 0
        try:
            table = retire(conn, argv[1])
        except RepairError as e:
            print(f"오류: {e}")
            return 2
        print(f"{argv[1]}을 은퇴시켰다 ({table}) — 남은 겹침:\n{describe(duplicates(conn))}")
        return 0
    finally:
        conn.close()


def consumer_file(argv: list[str]) -> int:
    """`bpm-center consumer-file <이름> --topics a,b [--dir 폴더]` — 일꾼 폴더의 파일을 짓는다 (ADR-0122).

    파일에는 토큰의 **해시만** 쓰고 원문은 **여기서 한 번만** 찍는다 — 그 값을 일꾼의 `…CENTER__TOKEN`에 넣는다.
    Center를 다시 띄워야 들어온다.
    """
    import argparse  # noqa: PLC0415

    from chaeksas.center.consumer_folder import write_file  # noqa: PLC0415
    from chaeksas.center.settings import Settings  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="bpm-center consumer-file", description="일꾼 폴더의 일꾼 파일을 짓는다")
    parser.add_argument("name", help="일꾼 이름 — 파일 이름(<이름>.consumer.json)이기도 하다")
    parser.add_argument("--topics", required=True, help="맡을 토픽 (쉼표로) — 서비스 앱 id·외부 확장 id")
    parser.add_argument("--dir", type=Path, default=None, help="일꾼 폴더 (기본: BPM_CENTER__CONSUMERS_DIR)")
    found = parser.parse_args(argv)
    topics = [one.strip() for one in str(found.topics).split(",") if one.strip()]
    folder = found.dir or Settings.from_env().consumers_dir
    if not topics or folder is None:
        print("토픽과 일꾼 폴더가 필요하다")
        return 2
    path, raw = write_file(folder, found.name, topics)
    print(f"일꾼 파일을 썼다: {path}")
    print(f"토큰 (이번 한 번만 보인다 — 일꾼의 …CENTER__TOKEN에 넣으세요): {raw}")
    print("Center를 다시 띄우면 들어온다.")
    return 0


def key_file(argv: list[str]) -> int:
    """`bpm-center key-file <이름> --type integration|relay [--dir 폴더]` — 일꾼 폴더의 키 파일을 짓는다 (ADR-0123).

    파일에는 키의 **해시만** 쓰고 원문은 **여기서 한 번만** 찍는다. Center를 다시 띄워야 들어온다.
    """
    import argparse  # noqa: PLC0415

    from chaeksas.center.consumer_folder import write_key_file  # noqa: PLC0415
    from chaeksas.center.settings import Settings  # noqa: PLC0415
    from chaeksas.contracts.center_keys import FOLDER_KEY_TYPES  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="bpm-center key-file", description="일꾼 폴더의 키 파일을 짓는다")
    parser.add_argument("name", help="키 이름 — 파일 이름(<이름>.key.json)이기도 하다")
    parser.add_argument("--type", required=True, choices=sorted(FOLDER_KEY_TYPES), help="키 종류")
    parser.add_argument("--dir", type=Path, default=None, help="일꾼 폴더 (기본: BPM_CENTER__CONSUMERS_DIR)")
    found = parser.parse_args(argv)
    folder = found.dir or Settings.from_env().consumers_dir
    if folder is None:
        print("일꾼 폴더가 필요하다")
        return 2
    path, raw = write_key_file(folder, found.name, found.type)
    print(f"키 파일을 썼다: {path}")
    print(f"키 (이번 한 번만 보인다 — 부르는 시스템의 설정에 넣으세요): {raw}")
    print("Center를 다시 띄우면 들어온다.")
    return 0


def main() -> int:
    import uvicorn

    from chaeksas.center.accounts import FirstAdminError
    from chaeksas.center.app import create_app
    from chaeksas.center.settings import Settings

    if len(sys.argv) > 1 and sys.argv[1] == "signing-key":
        return signing_key(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "hosts":
        return hosts(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "consumer-file":
        return consumer_file(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "key-file":
        return key_file(sys.argv[2:])

    settings = Settings.from_env()
    try:
        app = create_app(settings)
    except FirstAdminError as e:
        # 설치할 때 고치는 것이 가장 싸다 — 규칙에 안 맞는 비밀번호로 뜨지 않는다 (ADR-0090 §2).
        print(f"오류: {e} — .env의 BPM_CENTER__FIRST_ADMIN__*를 고치세요")
        return 2
    print(f"Center API: http://{settings.host}:{settings.port}  (DB {settings.db_path})")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
