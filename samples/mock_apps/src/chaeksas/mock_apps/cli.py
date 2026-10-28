"""`chk-mock-apps` — 모의 앱을 띄우고, 외부 확장 정의 파일을 쓴다.

    chk-mock-apps list                         # 무엇이 있나, 기본 포트는 몇인가
    chk-mock-apps serve                        # 전부 한 포트에 (/<app_id> 밑에, 웹 화면은 /site 밑에)
    chk-mock-apps serve --app erp              # 하나만, 그 앱의 기본 포트에
    chk-mock-apps definition ext-credit --base-url http://127.0.0.1:8150 -o ext-credit.json

`serve`를 앱 없이 부르면 **한 프로세스·한 포트**에 전부 붙는다 (관리 API·시나리오 제어·웹 화면).
**업무 호출은 그 포트로 받지 않는다** — `CHK_MOCK_APPS__CENTER__URL`을 주면 C11 앱 열셋이 **일꾼 하나**로
Center에 붙어 일감을 가져간다 (C15, ADR-0102). 토큰이 없으면 들이기 요청을 보내고 요청 코드를 찍는다 —
관리자가 CON-07 「일꾼 승인 대기」에서 승인하면 받아 `CHK_MOCK_APPS__DATA_DIR`(기본 `.mock-apps`)에 둔다.
`CHK_MOCK_APPS__CENTER__TOKEN`이 있으면 그것을 쓴다.

예제가 가리키는 **웹 화면**(공급사 포털·사내 신청서·공지)도 같은 포트의 `/site` 밑에 뜬다
(`sites.py`) — M4 인수 시험이 쓰는 HTML과 **같은 것**이라 현장 PC에서 BUI-06으로 등록하고 Bot이
읽을 수 있다 (예: `http://127.0.0.1:8010/site/transactions`).
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

from chaeksas.mock_apps import catalog, sites
from chaeksas.mock_apps.c11 import SHARED_PREFIX, Built, build
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
    print(f"업무 호출은 Center에서 가져간다 — {SHARED_PREFIX}CENTER__URL을 주면 일꾼으로 붙는다 (C15).")
    return 0


def _one(app_id: str) -> tuple[FastAPI, Built | None]:
    """앱 하나와 (C11이면) 그 작업 수행기. 외부 앱은 그냥 HTTP 서버다 — 어댑터 일꾼이 부른다."""
    mock = catalog.c11(app_id)
    if mock is not None:
        made = build(mock)
        return made.app, made
    make = external_apps.BUILDERS.get(app_id)
    if make is None:
        raise KeyError(app_id)
    return make(), None


def start_consumer(built: list[Built], *, center_url: str, folder: Path) -> Any:
    """C11 모의 앱들을 **일꾼 하나**로 Center에 붙인다 (C15). 토큰이 없으면 들이기를 기다린다.

    돌려주는 것은 멈추는 `threading.Event`다. 들이기·가져가기는 데몬 스레드에서 돈다.
    """
    import hashlib  # noqa: PLC0415
    import platform  # noqa: PLC0415
    import threading  # noqa: PLC0415
    import time  # noqa: PLC0415

    from chaeksas.service_kit import Consumer, Enrollment, TokenFile  # noqa: PLC0415

    tokens = TokenFile.at(folder, env_prefix=SHARED_PREFIX)
    services = [one.service for one in built]
    stop = threading.Event()

    def loop() -> None:
        enroll = Enrollment(
            center_url=center_url,
            name="모의 앱",
            topics=[one.app_id for one in services],
            manifests=[one.manifest.to_json_dict() for one in services],
            tokens=tokens,
            # 서비스 앱은 `core`를 쓰지 않는다 — 기계 id는 이 PC 이름과 데이터 폴더로 짓는다.
            machine_id=hashlib.sha256(f"{platform.node()}|{folder.resolve()}".encode()).hexdigest(),
        )
        told = None
        while not stop.is_set() and not tokens.token():
            try:
                code = enroll.step()
            except Exception as e:  # noqa: BLE001 — Center가 아직 없을 수 있다
                _say(f"일꾼 들이기: Center에 닿지 못했다 ({type(e).__name__}) — 다시 해 본다")
                code = told
            if code and code != told:
                _say(f"일꾼 들이기 요청 코드: {code} — Center 콘솔 CON-07 「일꾼 승인 대기」에서 승인하세요")
                told = code
            if not tokens.token():
                time.sleep(3)
        if stop.is_set():
            return
        consumer = Consumer(services, center_url=center_url, tokens=tokens)
        consumer.publish(force=True)
        _say(f"일꾼으로 붙었다 — 토픽 {len(services)}개 ({center_url})")
        consumer.run(stop)

    threading.Thread(target=loop, name="mock-consumer", daemon=True).start()
    return stop


def _serve(app_id: str | None, port: int | None, host: str) -> int:
    import uvicorn  # noqa: PLC0415 — 띄울 때만 든다

    center_url = os.environ.get(f"{SHARED_PREFIX}CENTER__URL", "").strip()
    folder = Path(os.environ.get(f"{SHARED_PREFIX}DATA_DIR") or ".mock-apps")
    if app_id is not None:
        app, made = _one(app_id)
        chosen = port or catalog.port_of(app_id)
        _say(f"{app_id} → http://{host}:{chosen}")
        if made is not None and center_url:
            start_consumer([made], center_url=center_url, folder=folder)
        uvicorn.run(app, host=host, port=chosen, log_level="info")
        return 0

    chosen = port or catalog.ALL_IN_ONE_PORT
    root, built = all_in_one()
    for one in catalog.ids():
        _say(f"{one:<15} → http://{host}:{chosen}/{one}")
    if center_url:
        start_consumer(built, center_url=center_url, folder=folder)
    else:
        _say(f"{SHARED_PREFIX}CENTER__URL이 없다 — 업무 호출을 받지 않는다 (관리 API·시나리오 제어만)")
    _say(f"{'웹 화면':<13} → http://{host}:{chosen}{sites.MOUNT}/  (" + ", ".join(sorted(sites.PAGES)) + ")")
    uvicorn.run(root, host=host, port=chosen, log_level="info")
    return 0


def all_in_one() -> tuple[FastAPI, list[Built]]:
    """앱 전부 + 웹 화면을 한 앱에 붙인다. 두 번째 값은 C11 앱들 (일꾼이 맡을 것)."""
    root = FastAPI(title="모의 앱 (전부)")
    built: list[Built] = []
    for one in catalog.ids():
        app, made = _one(one)
        root.mount(f"/{one}", app)
        if made is not None:
            built.append(made)
    root.mount(sites.MOUNT, sites.site_app())

    @root.get("/")
    def index() -> dict[str, Any]:
        return {"apps": list(catalog.ids()), "site": sites.MOUNT}

    return root, built


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
    print("다음: Center 콘솔 「리소스 → 확장 추가...」로 등록한다 (Center가 서명한다, C13 E6).")
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
