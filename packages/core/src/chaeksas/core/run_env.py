"""실행 하나가 바깥 세계에 닿는 자리를 짓는다 (`RunEnv`, ADR-0013·0026).

**Bot UI 실행기와 서버 실행기가 같은 코드를 쓴다** — 둘이 꽂는 것이 달라지면 「PC에서는
되는데 서버에서 안 된다」가 된다. 다른 것은 **부르는 쪽이 넘기는 값**뿐이다 (출력 폴더,
모델 주소·키, 확장, 바깥 앱 한 벌, 누가 부르는가, `location: follow` 결재를 어디서 답하나).

**주소·키 값은 여기까지만 온다** — BPM 프로세스와 실행 기록에는 참조 이름만 있다 (ADR-0013).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from chaeksas.core.app_directory import AppDirectory
from chaeksas.core.delegation import Delegator
from chaeksas.core.engine import WHERE_FIELD, RunEnv
from chaeksas.core.extensions import HostTasks
from chaeksas.core.files import Workspace
from chaeksas.core.llm import NoLlm, OpenAiCompatibleLlm
from chaeksas.core.packages import InstalledBot
from chaeksas.core.replay import read_memory
from chaeksas.core.senders import NoSender, Sender
from chaeksas.core.tools import builtin_tools


def make_env(
    package: InstalledBot,
    *,
    output_dir: Path,
    readable: tuple[Path, ...],
    writable: tuple[Path, ...] = (),
    llm_url: str = "",
    llm_key: str = "",
    llm_model: str,
    extensions: HostTasks | None = None,
    approval_where: str = WHERE_FIELD,
    directory: AppDirectory | None = None,
    caller_type: str = "bot_ui",
    sender: Sender | None = None,
    delegate: Delegator | None = None,
) -> RunEnv:
    """바깥 세계 한 벌 — **주소·키는 실행하는 쪽만 안다** (ADR-0013).

    `sender`를 주지 않으면 **보내지 않고 실패한다** (`NoSender`) — 조용히 넘어가지 않는다.

    `delegate`도 그렇다 — 주지 않으면 `NoDelegator`가 남아 PC 위임이 **그림·설치 오류**가
    된다 (ADR-0062 §2). **Bot UI는 주지 않는다**: PC 실행은 자리를 끝까지 쥐므로 PC가 다른
    PC를 기다리면 둘이 서로를 기다릴 수 있다 (C1 R10이 그림에서 이미 막는다).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    space = Workspace(output_dir=output_dir, readable=readable, writable=writable)
    model = (
        OpenAiCompatibleLlm(base_url=llm_url, api_key=llm_key, model=llm_model) if llm_url else NoLlm()
    )
    made = RunEnv(
        workspace=space,
        # **없으면 보내지 않고 실패한다** (조용히 넘어가지 않는다 — C14 §보내기).
        sender=sender or NoSender(),
        processes=package.processes(),
        decisions=package.decisions(),
        llm=model,
        tools=builtin_tools(space),
        memory=read_memory(package.folder),
        # `location: follow` 결재를 어디서 답하나 — BUI-03 「원격 결재」 (ADR-0038).
        approval_where=approval_where,
    )
    if extensions is not None:
        # 확장 태스크·`web`·`desktop` AI 태스크 (ADR-0018·ADR-0037) — 없으면 그림·설치 오류가 된다.
        made = replace(made, extensions=extensions)
    if directory is not None:
        # `chk:serviceCall` — 서비스 앱(C11)과 외부 앱(C13 어댑터)이 **같은 자리**로 간다.
        # `caller_type`은 **누가 부르는가**다 (C11 `caller.type`) — 앱의 기록·수행 모드 판단이
        # 그 값에 걸려 있어 서버 실행기가 「PC가 불렀다」고 말하면 안 된다.
        made = replace(made, services=directory.caller(caller_type=caller_type))
    if delegate is not None:
        # **PC 위임을 맡기는 포트 하나** (ADR-0062 §2) — 엔진은 어디에 맡기는지 모른다.
        made = replace(made, delegate=delegate)
    return made


__all__ = ["make_env"]
