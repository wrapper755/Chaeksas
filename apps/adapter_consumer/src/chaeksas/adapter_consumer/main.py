"""`bpm-adapter-consumer` — 외부 앱을 부르는 범용 일꾼 (C13 §4·C15, ADR-0102·0122).

    BPM_ADAPTER__CENTER__URL=https://center:8800 \\
    BPM_ADAPTER__CENTER__TOKEN=bpm_ctr_… \\
    BPM_ADAPTER__DEFINITIONS=ext-credit.extension.json:ext-helpdesk.extension.json \\
    BPM_ADAPTER__EXT__EXT_CREDIT__KEY=… \\
    bpm-adapter-consumer

1. **들이기는 없다** — Center의 일꾼 폴더에 이 일꾼의 `<이름>.consumer.json`(토큰 해시·토픽 = 맡을 확장 id)이 있어야
   한다(`bpm-center consumer-file`이 짓고 토큰 원문을 한 번 찍는다). 원문은 `BPM_ADAPTER__CENTER__TOKEN` 또는
   `BPM_ADAPTER__DATA_DIR`(기본 `.adapter-consumer`)의 `consumer-token.json`.
2. 맡을 외부 확장의 **정의는 이 일꾼이 들고 있다** — `BPM_ADAPTER__DEFINITIONS`(파일 경로, `os.pathsep`으로 여럿)를
   읽어 뜰 때 Center에 올리고 Center가 검사·서명한다 (`PUT /consumers/self/extension`). 읽지 못한 정의는 맡지 않는다.
3. 가져가기 루프 (`service_kit.Consumer`) — 일감마다 그 정의의 어댑터를 돌린다.

외부 앱이 있는 망 안에 띄워도 된다 — 나가는 연결(Center로, 외부 앱으로)만 있으면 된다.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from chaeksas.adapter_consumer.adapter import ENV_PREFIX, AdapterService
from chaeksas.contracts.extension import ExtensionManifest
from chaeksas.service_kit import Consumer, TokenFile

log = logging.getLogger("chaeksas.adapter_consumer")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(f"{ENV_PREFIX}{name}", default).strip()


def service_of(raw: dict[str, Any], *, environ: Mapping[str, str] | None = None) -> AdapterService:
    """정의 하나(원문 그대로) → 토픽 하나. 모양이 C13과 맞지 않으면 `ValueError`."""
    definition = ExtensionManifest.model_validate(raw)
    if environ is None:
        return AdapterService(definition=definition, raw=raw)
    return AdapterService(definition=definition, raw=raw, environ=environ)


def load_files(paths: Sequence[Path]) -> list[AdapterService]:
    """맡을 외부 확장 정의 파일들. 읽지 못한 것은 이유를 로그에 남기고 맡지 않는다 (조용히 사라지지 않는다)."""
    out: list[AdapterService] = []
    for path in paths:
        try:
            out.append(service_of(json.loads(path.read_text(encoding="utf-8-sig"))))
        except (OSError, ValueError) as e:
            log.warning("외부 확장 정의 %s를 읽지 못했다: %s", path, str(e).splitlines()[0])
    return out


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="bpm-adapter-consumer", description="외부 앱을 부르는 범용 일꾼 (C15)")
    parser.add_argument("--center-url", default=_env("CENTER__URL"))
    parser.add_argument(
        "--definitions", default=_env("DEFINITIONS"), help=f"맡을 외부 확장 정의 파일 ({os.pathsep}로 여럿)"
    )
    parser.add_argument("--data-dir", type=Path, default=Path(_env("DATA_DIR") or ".adapter-consumer"))
    found = parser.parse_args(argv)
    paths = [Path(one) for one in str(found.definitions).split(os.pathsep) if one.strip()]
    if not found.center_url or not paths:
        print(
            "Center 주소(BPM_ADAPTER__CENTER__URL)와 정의 파일(BPM_ADAPTER__DEFINITIONS)이 필요하다", file=sys.stderr
        )
        return 2
    tokens = TokenFile.at(found.data_dir, env_prefix=ENV_PREFIX)
    if not tokens.token():
        print(
            "일꾼 토큰이 없다 — Center 일꾼 폴더에 이 일꾼의 파일을 두고(bpm-center consumer-file) 받은 토큰을"
            " BPM_ADAPTER__CENTER__TOKEN에 넣으세요",
            file=sys.stderr,
        )
        return 2
    services = load_files(paths)
    if not services:
        print("맡을 수 있는 외부 확장이 없다 — 정의 파일을 확인하세요", file=sys.stderr)
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


__all__ = ["load_files", "main", "service_of"]
