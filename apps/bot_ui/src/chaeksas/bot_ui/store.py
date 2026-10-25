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

**본 `job_id`를 언제 잊는지는 `core.seen`이 쥔다** (ADR-0056·0057) — 서버 실행기와 **같은
규칙·같은 코드**다. 파일에 남기는 것은 **ack뿐이고 나이는 남기지 않는다**: 「아직 닿지
않았다」는 `pending_acks`가 이미 말해 주므로 되살릴 때 그것으로 가른다 (ADR-0057).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chaeksas.contracts.bot_ui import ApprovalAck, DeploymentResult, JobAck, QueueItem
from chaeksas.contracts.enrollment import EnrollStatus
from chaeksas.contracts.signing import AdminKey
from chaeksas.core.seen import Seen

log = logging.getLogger(__name__)


@dataclass
class State:
    """디스크에 남는 것 전부. `load()`/`save()`로 오간다."""

    bot_ui_id: str | None = None
    #: 대기열 (순서대로). C4 `queue.items`에 그대로 실린다.
    queue: list[QueueItem] = field(default_factory=list)
    #: 대기열 항목의 입력 값 — `queue_id` → `inputs`. 실행할 때 쓴다 (PC 안에만).
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: **PC 위임으로 받은 항목** — `queue_id` → 맡긴 서버 실행 (ADR-0062 §6, C3
    #: `run_started.parent_run_id`). 작업의 `requested_by`에서 읽는다. **C4 `QueueItem`에
    #: 칸을 더하지 않는다** — Center는 `requested_by`로 이미 알고, 대기열 보고에 쓸 데가 없다.
    parents: dict[str, str] = field(default_factory=dict)
    #: 아직 Center가 확인하지 않은 ack. 하트비트마다 다시 보낸다.
    pending_acks: list[JobAck] = field(default_factory=list)
    #: 아직 못 보낸 배포 적용 결정 (C4 `deployment_results`).
    pending_deployments: list[DeploymentResult] = field(default_factory=list)
    #: 아직 못 보낸 결재 ack (C4 `approval_acks`) — 내려온 답·회수를 받아 갔는지.
    pending_approval_acks: list[ApprovalAck] = field(default_factory=list)
    #: 마지막으로 받은 Admin 공개키 (C2 검증용). 하트비트에 없으면 **그대로 쓴다**.
    admin_keys: list[AdminKey] = field(default_factory=list)
    #: 이미 본 `job_id` → 마지막으로 보낸 ack (같은 작업이 다시 오면 이것을 되돌려 보낸다).
    #: **무한히 자라지 않고, 닿지 않은 ack는 잃지 않는다** (`core.seen`, ADR-0056·0057).
    seen_jobs: Seen[JobAck] = field(default_factory=Seen)
    #: 보낸 등록 요청 (C4 §등록 요청과 승인) — 다시 떠도 같은 요청을 묻는다. **봉한 키는 담지
    #: 않는다**(받은 키는 비밀 저장소로 간다).
    enrollment: EnrollStatus | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "bot_ui_id": self.bot_ui_id,
            "queue": [item.to_json_dict() for item in self.queue],
            "inputs": self.inputs,
            "parents": self.parents,
            "pending_acks": [ack.to_json_dict() for ack in self.pending_acks],
            "pending_deployments": [one.to_json_dict() for one in self.pending_deployments],
            "pending_approval_acks": [one.to_json_dict() for one in self.pending_approval_acks],
            "admin_keys": [one.to_json_dict() for one in self.admin_keys],
            "seen_jobs": {job_id: ack.to_json_dict() for job_id, ack in self.seen_jobs.items()},
            "enrollment": self.enrollment.model_copy(update={"sealed_key": None}).to_json_dict()
            if self.enrollment is not None
            else None,
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> State:
        pending_acks = [JobAck.model_validate(ack) for ack in raw.get("pending_acks", [])]
        return cls(
            bot_ui_id=raw.get("bot_ui_id") or None,
            queue=[QueueItem.model_validate(item) for item in raw.get("queue", [])],
            inputs=dict(raw.get("inputs", {})),
            parents=dict(raw.get("parents", {})),
            pending_acks=pending_acks,
            pending_deployments=[
                DeploymentResult.model_validate(one) for one in raw.get("pending_deployments", [])
            ],
            pending_approval_acks=[
                ApprovalAck.model_validate(one) for one in raw.get("pending_approval_acks", [])
            ],
            admin_keys=[AdminKey.model_validate(one) for one in raw.get("admin_keys", [])],
            enrollment=EnrollStatus.model_validate(raw["enrollment"]) if raw.get("enrollment") else None,
            # **나이는 파일에 없다** — 「아직 닿지 않았다」는 `pending_acks`가 말해 준다
            # (ADR-0057). 되살린 나이는 0부터라 닿은 것도 두 주기를 더 들고 있는다.
            seen_jobs=Seen.restore(
                {
                    job_id: JobAck.model_validate(ack)
                    for job_id, ack in (raw.get("seen_jobs") or {}).items()
                },
                undelivered={ack.job_id for ack in pending_acks},
            ),
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
        self.state.seen_jobs.remember(ack.job_id, ack)

    def ack_sent(self, acks: list[JobAck]) -> None:
        """하트비트 하나가 **성공했다** — 보낸 ack는 Center에 닿았다 (기억은 아직 남긴다).

        **한 번 부르는 것이 한 주기다** (ADR-0056) — 멱등 기억은 이 부름으로 나이를 센다.
        그래서 **하트비트가 성공했을 때만** 부른다: 보낼 때 부르면 끊긴 하트비트에 실렸던
        ack를 닿은 것으로 쳐서, 다시 내려온 작업이 「처음 본 것」이 되어 **두 번 실행된다**.

        **비우기 전에** 알린다 — 무엇이 실려 올라갔는지는 이 자리에서만 안다.
        """
        sent = {ack.job_id for ack in acks}
        self.state.seen_jobs.delivered(sent)
        self.state.pending_acks = [found for found in self.state.pending_acks if found.job_id not in sent]


__all__ = ["State", "Store"]
