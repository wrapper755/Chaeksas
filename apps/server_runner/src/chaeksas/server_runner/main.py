"""`chk-server-runner` — 서버 실행기를 띄운다 (화면 없음, C12).

서버에서는 systemd·compose가 이것을 돌린다. **SIGTERM을 받으면 곱게 끝낸다** — 컨테이너가
멈출 때 반쯤 쓴 상태를 남기지 않는다.

`--once`는 **등록하고 하트비트까지 한 번** 해 보고 상태 한 줄을 찍는다 (설치·설정을 확인할 때,
그리고 CI). 끝 코드는 0(됐다)·1(사람이 고쳐야 한다)·3(닿지 못했다)이다 — 셋을 가르는 까닭은
`systemd`·설치 스크립트가 **무엇을 할지가 다르기** 때문이다.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from types import FrameType

from chaeksas.server_runner import agent as agent_mod
from chaeksas.server_runner.credentials import ENV_CENTER_API_KEY, Credentials
from chaeksas.server_runner.settings import Settings

# 한글을 찍는 CLI는 stdout을 UTF-8로 고정한다 (Windows 기본 코드페이지에서 죽는다 — CLAUDE.md §5).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

log = logging.getLogger(__name__)

#: 키가 없을 때 사람에게 할 말. **어디에 넣어야 하는지까지** 적는다.
NO_KEY = (
    f"Center API 키가 없습니다 — 환경변수 {ENV_CENTER_API_KEY}에 「서버 실행기용」 키를 넣으세요 "
    "(콘솔 CON-11에서 발급합니다)"
)


def _parser() -> argparse.ArgumentParser:
    found = argparse.ArgumentParser(prog="chk-server-runner", description="서버 실행기 (C12)")
    found.add_argument(
        "--once", action="store_true", help="등록하고 하트비트를 한 번 보낸 뒤 상태를 찍는다"
    )
    found.add_argument("--verbose", action="store_true", help="자세한 로그")
    return found


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = Settings.from_env()
    api_key = Credentials().center_api_key()
    if not api_key:
        print(NO_KEY)
        return 2

    settings.data_path.mkdir(parents=True, exist_ok=True)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    found = agent_mod.build(settings, api_key)

    if args.once:
        # **등록하고 하트비트까지** 한 번 (`Agent.once`) — 등록만 하면 콘솔에 오프라인으로 남는다.
        beat = found.once()
        print(found.status_line())
        if found.blocked_by:
            return 1
        return 0 if beat else 3
    return _loop(found, settings)


def _loop(found: agent_mod.Agent, settings: Settings) -> int:
    """주기마다 한 걸음. **스레드를 만들지 않는다** — 기다리는 것은 `Event.wait()`다.

    `sleep()`이 아니라 `Event`인 까닭은 **SIGTERM이 왔을 때 바로 깨어나야** 해서다. 10초를
    자고 있으면 컨테이너 종료가 그만큼 늦는다.
    """
    stop = threading.Event()

    def _asked_to_stop(signum: int, frame: FrameType | None) -> None:
        log.info("%s를 받았다 — 곱게 끝낸다", signal.Signals(signum).name)
        stop.set()

    for one in (signal.SIGTERM, signal.SIGINT):
        signal.signal(one, _asked_to_stop)

    log.info("서버 실행기를 시작한다 (Center %s, 상한 %d)", settings.center_url, settings.max_concurrency)
    while not stop.is_set():
        found.tick()
        if found.blocked_by:
            # 사람이 고쳐야 하는 문제다 — 두드려도 같다. 끝내는 쪽이 운영자에게 더 분명하다
            # (systemd가 다시 띄우면 로그에 같은 줄이 쌓인다).
            log.error("%s", found.blocked_by)
            return 1
        # 닿지 못했으면 주기 대신 재시도 간격을 쓴다 (ADR-0007 — 부르는 쪽이 다시 온다).
        wait_s = found.next_in_s if found.online else settings.retry_s
        stop.wait(max(1, wait_s))
    return 0


if __name__ == "__main__":  # pragma: no cover - 실행 진입점
    raise SystemExit(main())
