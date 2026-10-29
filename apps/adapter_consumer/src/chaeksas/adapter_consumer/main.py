"""`chk-adapter-consumer` — 외부 앱을 부르는 범용 일꾼 (C13 §4·C15, ADR-0102).

    CHK_ADAPTER__CENTER__URL=https://center:8800 \\
    CHK_ADAPTER__EXTENSIONS=ext-credit,ext-helpdesk \\
    CHK_ADAPTER__EXT__EXT_CREDIT__KEY=… \\
    chk-adapter-consumer

1. 토큰이 없으면 **들이기 요청**을 보내고 요청 코드를 찍는다 — 관리자가 CON-07 「일꾼 승인 대기」에서
   승인하면 토큰을 받아 `CHK_ADAPTER__DATA_DIR`(기본 `.adapter-consumer`)에 둔다. `CHK_ADAPTER__CENTER__TOKEN`이
   있으면 그것을 쓴다.
2. 맡을 외부 확장의 **정의를 Center에서 받아 봉투를 다시 검증한다** (C13 E6 — 실행하는 쪽과 같은
   `core.app_directory`). 검증되지 않은 정의는 맡지 않는다.
3. 가져가기 루프 (`service_kit.Consumer`) — 일감마다 그 정의의 어댑터를 돌린다.

외부 앱이 있는 망 안에 띄워도 된다 — 나가는 연결(Center로, 외부 앱으로)만 있으면 된다.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import platform
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from chaeksas.adapter_consumer.adapter import ENV_PREFIX, AdapterService
from chaeksas.contracts.signing import AdminKey
from chaeksas.core.app_directory import build, to_json_dict
from chaeksas.service_kit import Consumer, Enrollment, TokenFile

log = logging.getLogger("chaeksas.adapter_consumer")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(f"{ENV_PREFIX}{name}", default).strip()


def load_definitions(
    center_url: str, token: str, extension_ids: Sequence[str], *, client: Any = None
) -> list[AdapterService]:
    """맡을 외부 확장들 — Center에서 정의·봉투를 받아 **다시 검증한 것만** (C13 E6).

    받지 못했거나 검증되지 않은 것은 이유를 로그에 남기고 맡지 않는다 (조용히 사라지지 않는다).
    """
    import httpx  # noqa: PLC0415

    http = client or httpx.Client(base_url=center_url, timeout=10.0)
    keys = [AdminKey.model_validate(one) for one in http.get("/api/v1/signing-keys").json()]
    entries = []
    for extension_id in extension_ids:
        got = http.get(f"/api/v1/resources/extensions/{extension_id}", headers={"Authorization": f"Bearer {token}"})
        if got.status_code >= 400:
            log.warning("외부 확장 %s의 정의를 받지 못했다 (%s)", extension_id, got.status_code)
            continue
        body = got.json()
        if not body.get("definition") or not body.get("envelope"):
            log.warning("외부 확장 %s은 정의·봉투가 없다 (내장·사내 확장은 어댑터 일꾼이 맡지 않는다)", extension_id)
            continue
        entries.append({"definition": body["definition"], "envelope": body["envelope"]})
    directory = build(to_json_dict(keys=keys, extensions=entries))
    for app_id, why in sorted(directory.problems.items()):
        log.warning("외부 확장 정의를 쓰지 못한다 (%s): %s", app_id, why)
    return [AdapterService(definition=one.manifest) for one in directory.externals.values()]


def enroll(center_url: str, tokens: TokenFile, extension_ids: Sequence[str], folder: Path) -> None:
    """토큰을 받을 때까지 들이기를 되풀이한다 (C15 §일꾼 들이기). 요청 코드는 바뀔 때만 찍는다."""
    step = Enrollment(
        center_url=center_url,
        name=_env("NAME") or "어댑터 일꾼",
        topics=list(extension_ids),
        manifests=[],  # 외부 확장 토픽은 비워도 된다 — 작업 목록은 등록된 정의에서 온다 (C15)
        tokens=tokens,
        machine_id=hashlib.sha256(f"{platform.node()}|{folder.resolve()}".encode()).hexdigest(),
    )
    told = None
    while not tokens.token():
        try:
            code = step.step()
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001 — Center가 아직 없을 수 있다
            log.warning("Center에 닿지 못했다 (%s) — 다시 해 본다", type(e).__name__)
            code = told
        if code and code != told:
            print(f"일꾼 들이기 요청 코드: {code} — Center 콘솔 「일꾼 승인 대기」에서 승인하세요", flush=True)
            told = code
        if not tokens.token():
            time.sleep(3)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="chk-adapter-consumer", description="외부 앱을 부르는 범용 일꾼 (C15)")
    parser.add_argument("--center-url", default=_env("CENTER__URL"))
    parser.add_argument("--extensions", default=_env("EXTENSIONS"), help="맡을 외부 확장 id (쉼표로)")
    parser.add_argument("--data-dir", type=Path, default=Path(_env("DATA_DIR") or ".adapter-consumer"))
    found = parser.parse_args(argv)
    extension_ids = [one.strip() for one in str(found.extensions).split(",") if one.strip()]
    if not found.center_url or not extension_ids:
        print("Center 주소(CHK_ADAPTER__CENTER__URL)와 맡을 확장(CHK_ADAPTER__EXTENSIONS)이 필요하다", file=sys.stderr)
        return 2
    tokens = TokenFile.at(found.data_dir, env_prefix=ENV_PREFIX)
    enroll(found.center_url, tokens, extension_ids, found.data_dir)
    token = tokens.token()
    assert token is not None
    services = load_definitions(found.center_url, token, extension_ids)
    if not services:
        print("맡을 수 있는 외부 확장이 없다 — 정의 등록·봉투를 확인하세요", file=sys.stderr)
        return 1
    consumer = Consumer(services, center_url=found.center_url, tokens=tokens)
    consumer.publish(force=True)
    print(f"일꾼으로 붙었다 — {', '.join(one.app_id for one in services)}", flush=True)
    stop = threading.Event()
    try:
        consumer.run(stop)
    except KeyboardInterrupt:
        stop.set()
    return 0


__all__ = ["enroll", "load_definitions", "main"]
