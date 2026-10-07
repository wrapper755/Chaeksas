"""실행기에게 내려보내는 길 — 제어 파일 한 벌 ([ADR-0031](../../../../docs/decisions/0031-runner-control-file.md)).

올라오는 것은 **실행 기록**(C3 `runs/<run_id>.jsonl`)이 그대로 쓰인다 (결재 요청만 예외 — 요청
파일, ADR-0038). 내려가는 것만 여기 있다: 중지, **결재 답**, **회수**(답 없이 끝남).

- 한 줄에 하나씩 **덧붙인다** (JSON Lines). 읽는 쪽은 읽은 자리를 `.sent`에 남겨 **두 번
  답하지 않는다** (실행 기록 보내기와 같은 수법).
- **값은 여기에만 있다.** 결재 답은 업무 값이라 실행 기록에 담기지 않는다 (원칙 6) — 이 파일은
  그 PC 안에만 있고 Center로 가지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chaeksas.core.run_log import run_dir

#: 제어 파일과 「어디까지 읽었나」 파일의 꼬리.
CONTROL_SUFFIX = ".control.jsonl"
READ_SUFFIX = ".read"

STOP = "stop"
ANSWER = "answer"
#: Center 결재가 답 없이 끝났다 — 관리자 회수·만료 (ADR-0038). **답이 아니다.**
WITHDRAW = "withdraw"


@dataclass(frozen=True)
class Command:
    """내려온 지시 하나."""

    kind: str
    request_id: str = ""
    answer: dict[str, Any] = field(default_factory=dict)
    answered_by: str = ""
    reason: str = ""

    @property
    def is_stop(self) -> bool:
        return self.kind == STOP


def control_path(data_dir: Path, run_id: str) -> Path:
    return run_dir(data_dir) / f"{run_id}{CONTROL_SUFFIX}"


def _read_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + READ_SUFFIX)


def send(path: Path, command: Command) -> None:
    """지시 한 줄을 덧붙인다 (Bot UI 쪽)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body: dict[str, Any] = {"kind": command.kind}
    if command.kind == ANSWER:
        body |= {
            "request_id": command.request_id,
            "answer": command.answer,
            "answered_by": command.answered_by,
        }
    if command.kind == WITHDRAW:
        body |= {"request_id": command.request_id, "reason": command.reason}
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(body, ensure_ascii=False) + "\n")


def stop(path: Path) -> None:
    send(path, Command(kind=STOP))


def answer(path: Path, request_id: str, body: Mapping[str, Any], *, answered_by: str) -> None:
    send(path, Command(kind=ANSWER, request_id=request_id, answer=dict(body), answered_by=answered_by))


def withdraw(path: Path, request_id: str, *, reason: str) -> None:
    send(path, Command(kind=WITHDRAW, request_id=request_id, reason=reason))


def take(path: Path) -> list[Command]:
    """아직 안 읽은 지시들 (실행기 쪽). 읽은 자리를 남겨 **두 번 쓰지 않는다**."""
    if not path.is_file():
        return []
    mark = _read_path(path)
    try:
        through = int(mark.read_text(encoding="utf-8").strip() or 0) if mark.is_file() else 0
    except (OSError, ValueError):
        through = 0

    out: list[Command] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for raw in lines[through:]:
        if not raw.strip():
            continue
        try:
            found = json.loads(raw)
        except ValueError:
            continue  # 반쯤 쓰인 줄 — 다음에 다시 본다
        out.append(
            Command(
                kind=str(found.get("kind") or ""),
                request_id=str(found.get("request_id") or ""),
                answer=dict(found.get("answer") or {}),
                answered_by=str(found.get("answered_by") or ""),
                reason=str(found.get("reason") or ""),
            )
        )
    if out:
        mark.write_text(f"{len(lines)}\n", encoding="utf-8", newline="\n")
    return out


def clear(path: Path) -> None:
    """끝났으면 치운다 — **답에는 업무 값이 들어 있다** (원칙 6)."""
    for one in (path, _read_path(path)):
        one.unlink(missing_ok=True)


__all__ = [
    "ANSWER",
    "CONTROL_SUFFIX",
    "READ_SUFFIX",
    "STOP",
    "WITHDRAW",
    "Command",
    "answer",
    "clear",
    "control_path",
    "send",
    "stop",
    "take",
    "withdraw",
]
