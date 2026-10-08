"""`chk-mock-apps` — 모의 앱을 띄우고, 외부 확장 정의 파일을 쓴다.

    chk-mock-apps list                         # 무엇이 있나, 기본 포트는 몇인가
    chk-mock-apps serve                        # 전부 한 포트에 (/<app_id> 밑에)
    chk-mock-apps serve --app erp              # 하나만, 그 앱의 기본 포트에
    chk-mock-apps definition ext-credit --base-url http://127.0.0.1:8150 -o ext-credit.json

`serve`를 앱 없이 부르면 **한 프로세스·한 포트**에 전부 붙는다. 서비스 앱 주소에 경로가
붙어도 되므로(`{base_url}/v1/ops/…`) Center 리소스 등록에 `http://127.0.0.1:8010/erp`를
그대로 넣을 수 있다. 앱 열여섯 개를 따로 띄우지 않아도 된다.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from chaeksas.mock_apps import catalog
from chaeksas.mock_apps.c11 import SHARED_KEY_ENV, build
from chaeksas.mock_apps.external import apps as external_apps
from chaeksas.mock_apps.external import definitions

log = logging.getLogger(__name__)


def _utf8_stdout() -> None:
    """한글을 찍는 도구는 stdout도 UTF-8로 고정한다 (CLAUDE.md §5)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _say(line: str) -> None:
    """**바로 흘려보낸다** — 안내 줄에 키가 있는데, 로그 파일로 돌리면 버퍼에 갇혀 사라진다."""
    print(line, flush=True)


def _list() -> int:
    print(f"{'app_id':<15} {'종류':<5} {'기본 포트':>9}  쓰는 예제")
    for app_id, kind, port, used_by in catalog.rows():
        print(f"{app_id:<15} {kind:<5} {port:>9}  {used_by}")
    print()
    print(f"키는 {SHARED_KEY_ENV} 하나로 전부에 심을 수 있다 (앱마다 다르게: CHK_SVC_<앱>__DEV_KEY).")
    return 0


def _one(app_id: str) -> tuple[FastAPI, str]:
    """앱 하나와 **보여 줄** 키.

    환경변수로 받은 키는 빈 문자열로 돌려준다 — 사람이 이미 아는 값을 열네 번 되읊지 않는다.
    외부 앱은 키를 발급하지 않는다 (받아서 확인만 한다).
    """
    mock = catalog.c11(app_id)
    if mock is not None:
        made = build(mock)
        return made.app, "" if made.key_from_env else made.key
    make = external_apps.BUILDERS.get(app_id)
    if make is None:
        raise KeyError(app_id)
    return make(), ""


def _serve(app_id: str | None, port: int | None, host: str) -> int:
    import uvicorn  # noqa: PLC0415 — 띄울 때만 든다

    if app_id is not None:
        app, key = _one(app_id)
        chosen = port or catalog.port_of(app_id)
        _say(f"{app_id} → http://{host}:{chosen}")
        if key:
            _say(f"  키: {key}")
        uvicorn.run(app, host=host, port=chosen, log_level="info")
        return 0

    root = FastAPI(title="모의 앱 (전부)")
    chosen = port or catalog.ALL_IN_ONE_PORT
    if os.environ.get(SHARED_KEY_ENV, "").strip():
        _say(f"키는 {SHARED_KEY_ENV}로 받은 것을 쓴다 (앱마다 다르게: CHK_SVC_<앱>__DEV_KEY).")
    for one in catalog.ids():
        app, key = _one(one)
        root.mount(f"/{one}", app)
        _say(f"{one:<15} → http://{host}:{chosen}/{one}" + (f"   키: {key}" if key else ""))

    @root.get("/")
    def index() -> dict[str, Any]:
        return {"apps": list(catalog.ids())}

    uvicorn.run(root, host=host, port=chosen, log_level="info")
    return 0


def _definition(app_id: str, base_url: str, out: Path | None) -> int:
    make = definitions.BUILDERS.get(app_id)
    if make is None:
        print(f"외부 확장이 아니다: {app_id} (있는 것: {', '.join(definitions.BUILDERS)})", file=sys.stderr)
        return 2
    found = make(base_url)
    text = json.dumps(found, ensure_ascii=False, indent=2) + "\n"
    if out is None:
        print(text, end="")
        return 0
    out.write_text(text, encoding="utf-8")
    print(f"썼다: {out}")
    print("다음: chk-admin sign-extension으로 서명하고 Center에 등록한다 (C13 E6).")
    return 0


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(prog="chk-mock-apps", description="업무 예제가 부르는 모의 앱")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="모의 앱 목록과 기본 포트")

    serve = sub.add_parser("serve", help="띄운다 (앱을 고르지 않으면 전부 한 포트에)")
    serve.add_argument("--app", help="하나만 띄운다")
    serve.add_argument("--port", type=int, help="기본 포트를 바꾼다")
    serve.add_argument("--host", default="127.0.0.1", help="기본 127.0.0.1 (모의 앱은 인증 없는 길이 있다)")

    definition = sub.add_parser("definition", help="외부 확장 정의 파일을 쓴다 (C13)")
    definition.add_argument("app", help="ext-credit · ext-helpdesk")
    definition.add_argument("--base-url", required=True, help="그 앱이 떠 있는 주소")
    definition.add_argument("-o", "--out", type=Path, help="쓸 파일 (없으면 화면에)")

    args = parser.parse_args(argv)
    if args.command == "list" or args.command is None:
        return _list()
    if args.command == "serve":
        try:
            return _serve(args.app, args.port, args.host)
        except KeyError:
            print(f"모르는 앱이다: {args.app} (`chk-mock-apps list`를 보라)", file=sys.stderr)
            return 2
    return _definition(args.app, args.base_url, args.out)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
