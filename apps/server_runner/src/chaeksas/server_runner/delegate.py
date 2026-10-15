"""엔진이 맡긴 PC 위임을 **Center에 요청한다** (`RunEnv.delegate`, C12 §PC 위임
— ADR-0062, `docs/decisions/0062-pc-delegation.md`).

꽂는 쪽이 둘인 포트의 하나다 — 여기는 Center에 요청하고, Studio 시험 실행은 **케이스가 적어
둔 결과를 돌려준다**. 엔진은 어느 쪽인지 모른다 (C12 §PC 위임).

**어느 PC인가를 고르는 것은 Center다** (ADR-0049 — 배포가 정하는 자리다). 이쪽이 하는 일은
그림이 적어 둔 것을 그대로 옮기고 **돌려받은 작업 id를 엔진에게 주는 것**뿐이다.

**맡기지 못한 것은 업무 실패다** (`DelegationError`) — 배포된 활성 PC가 없거나(404
`no_deployment`), 판이 둘 이상이거나(422), Center에 닿지 못한 것이다. 오류 경계가 받아야
사람이 안다. 「맡길 곳이 아예 없다」(`DelegationUnsupported`)는 여기서 나지 않는다 — 그것은
포트를 꽂지 않았을 때의 일이다 (`NoDelegator`).

**다시 걸지 않는다** — 멱등 키가 Center의 것이라 다시 요청하면 **같은 작업이 돌아오지만**,
그 재시도를 결정하는 것은 업무(오류 경계·타이머)이고 포트가 몰래 붙잡고 있을 일이 아니다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from chaeksas.contracts.server_runner import DelegationRequest
from chaeksas.core.delegation import DelegationCall, DelegationError
from chaeksas.server_runner.center_client import CenterClient, CenterProblem

log = logging.getLogger(__name__)

#: 사유 코드를 모를 때 (C12 오류 본문에 `code`가 없었다).
DEFAULT_CODE = "delegation_failed"


@dataclass
class CenterDelegator:
    """`RunEnv.delegate`에 꽂히는 것. **Center 클라이언트 하나**만 안다."""

    client: CenterClient

    def delegate(self, call: DelegationCall) -> str:
        """맡기고 **작업 id**를 돌려준다 (기다릴 때 그것으로 찾는다)."""
        request = DelegationRequest(
            schema=1,
            run_id=call.run_id,
            node_id=call.node_id,
            node_instance=call.node_instance,
            bpm_process_id=call.bpm_process_id,
            version=call.version,
            bot_ui=call.bot_ui,
            inputs=dict(call.inputs),
        )
        try:
            answer = self.client.create_delegation(request)
        except CenterProblem as e:
            # **업무 실패다** — 오류 경계가 받는다 (ADR-0062 §2). 닿지 못한 것도 여기다:
            # 포트는 돌려줄 작업 id가 없으면 기다릴 수 없다.
            raise DelegationError(str(e), code=e.code or DEFAULT_CODE) from e
        log.info(
            "PC 위임을 맡겼다: %s → 작업 %s (%s)",
            call.bpm_process_id,
            answer.job_id,
            answer.bot_ui_id,
        )
        return answer.job_id


__all__ = ["DEFAULT_CODE", "CenterDelegator"]
