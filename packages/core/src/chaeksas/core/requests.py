"""올라가는 결재 요청 — 요청 파일 한 벌 ([ADR-0038](../../../../docs/decisions/0038-approval-request-channel.md)).

실행 기록(C3)은 값을 나르지 않는다 (원칙 6). 그런데 Center 결재함에 올릴 결재에는 결재자가
판단할 값(C6 `review`)이 있어야 한다. 그래서 **값이 필요한 결재 요청만** 이 파일로 올라간다.

- 실행기가 `runs/<run_id>.requests.jsonl`에 **C6 `ApprovalCreateRequest` 본문 그대로** 한 줄씩
  덧붙인다. `where=center`인 것만 쓴다 (현장 결재는 올릴 이유가 없다).
- Bot UI가 하트비트 뒤에 읽어 `POST /approvals`로 올리고, 보낸 자리를 `.sent`에 남긴다 —
  **Bot UI는 내용을 짓지 않고 나르기만** 한다 (배포 봉투를 다루는 방식과 같다).
- 끝나면 지운다 — 업무 값이 PC에 남지 않는다 (제어 파일과 같다).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from chaeksas.contracts.approvals import ApprovalCreateRequest
from chaeksas.core.run_log import run_dir
from chaeksas.core.run_state import Pending, Run

#: 요청 파일과 「어디까지 보냈나」 파일의 꼬리.
REQUESTS_SUFFIX = ".requests.jsonl"
SENT_SUFFIX = ".sent"


def requests_path(data_dir: Path, run_id: str) -> Path:
    return run_dir(data_dir) / f"{run_id}{REQUESTS_SUFFIX}"


def _sent_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + SENT_SUFFIX)


def create_request(run: Run, pending: Pending) -> ApprovalCreateRequest:
    """기다리는 결재 하나 → C6 본문. **내용을 아는 것은 엔진뿐이다** — 제목·폼·검토 자료."""
    return ApprovalCreateRequest(
        schema=1,
        request_id=pending.request_id,
        layer=pending.layer,
        run_id=run.run_id,
        node_id=pending.node_id,
        node_instance=pending.node_instance,
        bpm_process_id=run.process.id,
        version=run.version,
        title=pending.title or None,
        description=pending.description,
        form=pending.form,
        review=dict(pending.review),
        expires_at=pending.expires_at,
    )


def append(path: Path, body: Mapping[str, Any]) -> None:
    """한 줄 덧붙인다 (실행기 쪽)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(dict(body), ensure_ascii=False, default=str) + "\n")


def unsent(path: Path) -> list[tuple[int, dict[str, Any]]]:
    """아직 안 보낸 줄 `(줄 번호, 본문)` (Bot UI 쪽). 반쯤 쓰인 줄은 다음에 다시 본다."""
    if not path.is_file():
        return []
    mark = _sent_path(path)
    try:
        through = int(mark.read_text(encoding="utf-8").strip() or 0) if mark.is_file() else 0
    except (OSError, ValueError):
        through = 0
    out: list[tuple[int, dict[str, Any]]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if number <= through or not raw.strip():
            continue
        try:
            found = json.loads(raw)
        except ValueError:
            break  # 쓰는 중 — 여기서 멈추고 다음 주기에 이어서 (순서를 지킨다)
        if isinstance(found, dict):
            out.append((number, found))
    return out


def mark_sent(path: Path, through: int) -> None:
    """그 줄까지 보냈다 (또는 거부돼 지나갔다 — 한 줄이 큐를 영원히 막으면 안 된다)."""
    _sent_path(path).write_text(f"{through}\n", encoding="utf-8", newline="\n")


def clear(path: Path) -> None:
    """끝났으면 치운다 — **검토 자료에는 업무 값이 들어 있다** (원칙 6)."""
    for one in (path, _sent_path(path)):
        one.unlink(missing_ok=True)


__all__ = [
    "REQUESTS_SUFFIX",
    "append",
    "clear",
    "create_request",
    "mark_sent",
    "requests_path",
    "unsent",
]
