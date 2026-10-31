"""올라가는 **PC 위임의 결과** — 출력 파일 한 벌 (C4 `JobAck.outputs`, ADR-0062 §4).

실행 기록(C3)은 값을 나르지 않는다 (원칙 6). 그런데 위임의 요점은 **결과를 받아 이어 가는
것**이고, 실행 변수를 아는 것은 **자식 프로세스(실행기)**다. 그래서 결재 요청이 그랬듯
([ADR-0038](../../../../docs/decisions/0038-approval-request-channel.md)) 값은 **따로 이 파일로**
올라간다.

- 실행기가 끝날 때 `runs/<run_id>.outputs.json`에 **한 번** 쓴다 (덧붙이지 않는다 — 실행
  하나에 결과 한 벌이다). **위임으로 받은 작업만** 쓴다: 평범한 실행의 업무 값을 디스크에
  남기지 않는다.
- PC 실행기가 읽어 작업 ack에 실어 올리고 **그 자리에서 지운다** — **PC 실행기는 내용을 짓지 않고
  나르기만 한다** (요청 파일과 같은 결).
- 거르는 자리는 **그 BPM 프로세스가 선언한 `outputs`**다 (C1) — 그것이 곧 「부르는 쪽이 받을 것」이다.
  매핑(`bpm:call.output`)은 서버 그림에만 있어 PC는 모른다. 새 거르기 개념을 들이지 않는다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from chaeksas.core.run_log import run_dir

log = logging.getLogger(__name__)

#: 출력 파일의 꼬리. 같은 `runs/`의 제어·요청 파일처럼 **실행 기록 전송이 건너뛴다** (C3).
OUTPUTS_SUFFIX = ".outputs.json"


def outputs_path(data_dir: Path, run_id: str) -> Path:
    return run_dir(data_dir) / f"{run_id}{OUTPUTS_SUFFIX}"


def pick(declared: Sequence[str], variables: Mapping[str, Any]) -> dict[str, Any]:
    """선언한 `outputs`만 골라낸다 (C1).

    **없는 이름은 넣지 않는다** — `None`을 넣으면 받는 쪽이 「값이 없다」와 「`None`이 왔다」를
    가를 수 없고, 서버 엔진은 **적은 값이 오지 않으면 업무 실패**로 다루어야 한다 (ADR-0062 §2).
    """
    return {name: variables[name] for name in declared if name in variables}


def write(path: Path, values: Mapping[str, Any]) -> None:
    """결과 한 벌을 쓴다 (실행기 쪽). **비어도 쓴다** — 「끝났는데 돌려줄 것이 없다」도 사실이다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(values), ensure_ascii=False, default=str), encoding="utf-8", newline="\n"
    )


def read(path: Path) -> dict[str, Any] | None:
    """쓰여 있는 결과. 없거나 읽을 수 없으면 `None`.

    **반쯤 쓰인 글은 없는 것으로 본다** — 실행기가 쓰다 죽었으면 그 작업은 `failed`로 가고
    (`run_finished`가 없다) 값을 올릴 일이 없다.
    """
    if not path.is_file():
        return None
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("출력 파일을 읽지 못했다 (%s): %s", path.name, e)
        return None
    return dict(found) if isinstance(found, dict) else None


def clear(path: Path) -> None:
    """치운다 — **업무 값이 PC에 남지 않는다** (제어·요청 파일과 같다)."""
    path.unlink(missing_ok=True)


def take(path: Path) -> dict[str, Any]:
    """읽고 **그 자리에서 지운다** (PC 실행기 쪽). 없으면 빈 사전이다.

    읽기와 지우기를 **한 함수로** 둔 것은 둘을 떼어 놓으면 값이 디스크에 남는 길이 생기기
    때문이다 — 올리지 못한 ack는 메모리에 들고 있으면 되고(`pending_acks`), 파일은 들고 있을
    까닭이 없다.
    """
    found = read(path) or {}
    clear(path)
    return found


__all__ = ["OUTPUTS_SUFFIX", "clear", "outputs_path", "pick", "read", "take", "write"]
