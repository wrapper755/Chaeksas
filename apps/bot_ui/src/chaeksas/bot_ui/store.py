"""디스크에 남겨 두는 상태 — **작업이 사라지지 않게** (C4 「맞추기 규칙」).

Bot UI가 꺼졌다 켜져도 대기열과 아직 Center가 확인하지 않은 ack가 남아 있어야 한다.
그래서 이것만 파일에 둔다.

| 저장하는 것 | 왜 |
| --- | --- |
| `bot_ui_id` | 등록을 다시 하지 않아도 되게 (키 묶음은 Center가 본다) |
| 대기열 | 다시 켜면 이어 간다 (C4) |
| 보내지 못한 ack | Center가 확인할 때까지 다시 보낸다 |
| 본 `job_id` | 같은 작업이 다시 와도 두 번 실행하지 않는다 |

**업무 값은 두지 않는다** — 작업의 `inputs`는 대기열 항목에 필요해서 들고 있지만, 이 파일은
PC 안에만 있고 Center로 되돌려 보내지 않는다 (계약 원칙 6은 *기록·보고*에 값을 넣지 않는 것이다).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chaeksas.contracts.bot_ui import ApprovalAck, DeploymentResult, JobAck, QueueItem
from chaeksas.contracts.signing import AdminKey

log = logging.getLogger(__name__)

#: 본 `job_id`를 몇 개까지 기억할지. 넘으면 오래된 것부터 버린다 (파일이 끝없이 자라지 않게).
SEEN_JOBS_MAX = 2000


@dataclass
class State:
    """디스크에 남는 것 전부. `load()`/`save()`로 오간다."""

    bot_ui_id: str | None = None
    #: 대기열 (순서대로). C4 `queue.items`에 그대로 실린다.
    queue: list[QueueItem] = field(default_factory=list)
    #: 대기열 항목의 입력 값 — `queue_id` → `inputs`. 실행할 때 쓴다 (PC 안에만).
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: 아직 Center가 확인하지 않은 ack. 하트비트마다 다시 보낸다.
    pending_acks: list[JobAck] = field(default_factory=list)
    #: 아직 못 보낸 배포 적용 결정 (C4 `deployment_results`).
    pending_deployments: list[DeploymentResult] = field(default_factory=list)
    #: 아직 못 보낸 결재 ack (C4 `approval_acks`) — 내려온 답·회수를 받아 갔는지.
    pending_approval_acks: list[ApprovalAck] = field(default_factory=list)
    #: 마지막으로 받은 Admin 공개키 (C2 검증용). 하트비트에 없으면 **그대로 쓴다**.
    admin_keys: list[AdminKey] = field(default_factory=list)
    #: 이미 본 `job_id` → 마지막으로 보낸 ack (같은 작업이 다시 오면 이것을 되돌려 보낸다).
    seen_jobs: dict[str, JobAck] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "bot_ui_id": self.bot_ui_id,
            "queue": [item.to_json_dict() for item in self.queue],
            "inputs": self.inputs,
            "pending_acks": [ack.to_json_dict() for ack in self.pending_acks],
            "pending_deployments": [one.to_json_dict() for one in self.pending_deployments],
            "pending_approval_acks": [one.to_json_dict() for one in self.pending_approval_acks],
            "admin_keys": [one.to_json_dict() for one in self.admin_keys],
            "seen_jobs": {job_id: ack.to_json_dict() for job_id, ack in self.seen_jobs.items()},
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> State:
        return cls(
            bot_ui_id=raw.get("bot_ui_id") or None,
            queue=[QueueItem.model_validate(item) for item in raw.get("queue", [])],
            inputs=dict(raw.get("inputs", {})),
            pending_acks=[JobAck.model_validate(ack) for ack in raw.get("pending_acks", [])],
            pending_deployments=[
                DeploymentResult.model_validate(one) for one in raw.get("pending_deployments", [])
            ],
            pending_approval_acks=[
                ApprovalAck.model_validate(one) for one in raw.get("pending_approval_acks", [])
            ],
            admin_keys=[AdminKey.model_validate(one) for one in raw.get("admin_keys", [])],
            seen_jobs={
                job_id: JobAck.model_validate(ack) for job_id, ack in (raw.get("seen_jobs") or {}).items()
            },
        )


@dataclass
class Store:
    """상태 파일 하나. 쓰기는 **임시 파일 → 바꿔치기**라서 쓰다 죽어도 깨지지 않는다."""

    path: Path
    state: State = field(default_factory=State)

    @classmethod
    def load(cls, path: Path) -> Store:
        if not path.exists():
            return cls(path=path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return cls(path=path, state=State.from_json_dict(raw))
        except (OSError, ValueError) as e:
            # 깨진 상태 때문에 Bot UI가 안 뜨면 더 나쁘다. 비우고 뜬다 — 대기열은 Center가
            # 두 주기 뒤 `bot_ui_lost`로 정리한다 (C4).
            log.error("상태 파일을 읽지 못해 비우고 시작한다 (%s): %s", path, e)
            return cls(path=path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        staged = self.path.with_suffix(".json.tmp")
        staged.write_text(
            json.dumps(self.state.to_json_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        staged.replace(self.path)

    # ── ack 다루기 ──

    def remember_deployments(self, found: list[DeploymentResult]) -> None:
        """보낼 결정을 쌓는다. 같은 배포는 **마지막 것만** 남긴다."""
        for one in found:
            self.state.pending_deployments = [
                x for x in self.state.pending_deployments if x.deployment_id != one.deployment_id
            ]
            self.state.pending_deployments.append(one)

    def deployments_sent(self, sent: list[DeploymentResult]) -> None:
        ids = {one.deployment_id for one in sent}
        self.state.pending_deployments = [
            one for one in self.state.pending_deployments if one.deployment_id not in ids
        ]

    def remember_approval_ack(self, ack: ApprovalAck) -> None:
        """같은 결재의 옛 ack는 **마지막 것으로 덮는다**."""
        self.state.pending_approval_acks = [
            one for one in self.state.pending_approval_acks if one.request_id != ack.request_id
        ]
        self.state.pending_approval_acks.append(ack)

    def approval_acks_sent(self, sent: list[ApprovalAck]) -> None:
        ids = {one.request_id for one in sent}
        self.state.pending_approval_acks = [
            one for one in self.state.pending_approval_acks if one.request_id not in ids
        ]

    def remember_ack(self, ack: JobAck) -> None:
        """ack를 기억하고 보낼 목록에 넣는다. 같은 작업의 옛 ack는 **마지막 것으로 덮는다.**"""
        self.state.pending_acks = [found for found in self.state.pending_acks if found.job_id != ack.job_id]
        self.state.pending_acks.append(ack)
        self.state.seen_jobs[ack.job_id] = ack
        self._trim_seen()

    def ack_sent(self, acks: list[JobAck]) -> None:
        """Center가 받았다 — 보낼 목록에서 뺀다 (기억은 남긴다)."""
        sent = {ack.job_id for ack in acks}
        self.state.pending_acks = [found for found in self.state.pending_acks if found.job_id not in sent]

    def _trim_seen(self) -> None:
        if len(self.state.seen_jobs) <= SEEN_JOBS_MAX:
            return
        # dict는 넣은 순서를 지킨다 — 오래된 것부터 버린다.
        extra = len(self.state.seen_jobs) - SEEN_JOBS_MAX
        for job_id in list(self.state.seen_jobs)[:extra]:
            del self.state.seen_jobs[job_id]


__all__ = ["SEEN_JOBS_MAX", "State", "Store"]
