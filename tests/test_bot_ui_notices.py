"""BUI-05 알림 — 알릴 거리를 모으는 쪽과 띄우는 쪽 (M6 조각 17).

보는 것:

1. **알릴 거리를 아는 쪽(Agent)과 띄우는 쪽(화면)이 갈려 있다** — `Notices`는 Qt를 모르고,
   화면은 쌓인 것을 거둬 가 띄울 뿐이다.
2. **같은 말을 주기마다 띄우지 않는다** — 연결·런타임은 **바뀔 때만**, 같은 알림은 한 번만.
3. **문구가 BUI-05 표 그대로다** — Bot 이름·순번·사유가 들어가고, 「사람이 볼 때까지」는 sticky다.
4. **알릴 거리가 생기는 자리가 Agent에 붙어 있다** — 실패·배포·만료·키 거부·대기열.
5. **기다리는 동안 만료된 작업은 버린다** (C4 `expired`) — 붙이기 전까지 `expires_at`을 아무도
   보지 않아 지난 작업이 그대로 돌았다.
6. **Center API 키 만료는 Center가 말해 준 값으로** 알린다 (C4 `key_expires_at`) — 14일 전부터
   **하루 한 번**이고, 이미 만료된 키는 「거부」가 말한다.
7. **서비스 앱 키는 반쪽이 둘이고 묻는 때가 다르다** (ADR-0052) — 거부는 **실행 기록**의
   `service_call`에서 읽고(값이 이 PC에 없는 것은 거부가 아니다), 만료 임박만 주기가 **쓰는
   키에만·들고 있는 주소로·하루 한 번·주기마다 하나** 묻는다.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeCredentials

from chaeksas.bot_ui import agent as module_agent
from chaeksas.bot_ui import notices as module
from chaeksas.bot_ui.agent import Agent
from chaeksas.bot_ui.center_client import KeyRejected, Unreachable
from chaeksas.bot_ui.notices import Notice, Notices
from chaeksas.bot_ui.runner import Request, Running
from chaeksas.bot_ui.settings import ServiceKeyRef, Settings, data_dir
from chaeksas.bot_ui.store import Store
from chaeksas.contracts.bot_ui import DeploymentResult, HeartbeatResponse, JobDispatch, QueueItem, RegisterResponse
from chaeksas.contracts.manifest import Manifest, ServiceAppNeed
from chaeksas.core.key_check import KeyFacts
from chaeksas.core.packages import InstalledBot
from chaeksas.core.processes import ChildProcess

NOW = "2026-10-10T09:00:00+09:00"
BOT_UI_ID = "bui_a81c22d0"


# ─────────────────────────── 모으는 쪽 (Qt 없음) ───────────────────────────


def test_the_same_notice_is_not_queued_twice() -> None:
    """두 번 넣어도 하나다 — 주기마다 같은 말을 띄우면 사람이 알림을 끈다."""
    found = Notices()
    found.queue_full(bot="fin.invoice", limit=20)
    found.queue_full(bot="fin.invoice", limit=20)
    assert len(found.pending) == 1

    # 거둬 간 뒤에는 **다시 알릴 수 있다** (같은 일이 또 생긴 것이다).
    assert len(found.take()) == 1
    assert not found.pending
    found.queue_full(bot="fin.invoice", limit=20)
    assert len(found.pending) == 1


def test_old_notices_are_dropped_when_they_pile_up() -> None:
    """창을 오래 닫아 둔 PC에서 수백 개가 쌓이면 거둬 갈 때 다 띄우게 된다 — 상한을 둔다."""
    found = Notices(limit=3)
    for at in range(5):
        found.add(Notice(kind="x", text=f"{at}번"))
    assert [one.text for one in found.take()] == ["2번", "3번", "4번"], "방금 일이 더 급하다"


def test_the_first_round_does_not_say_anything_about_the_connection() -> None:
    """켤 때 「복구」라고 할 일이 아니다 — 지난 값이 없으면 알리지 않는다."""
    found = Notices()
    found.connection(online=True)
    assert not found.pending


def test_the_connection_is_told_only_when_it_changes() -> None:
    """꺼진 Center 앞에서 주기마다 띄우지 않는다 (ADR-0007 — 닿지 못해도 업무는 돈다)."""
    found = Notices()
    found.connection(online=True)  # 첫 바퀴
    found.connection(online=False)
    found.connection(online=False)
    found.connection(online=False)
    told = found.take()
    assert [one.kind for one in told] == [module.CENTER_OFFLINE]
    assert told[0].text == "Center에 닿지 못합니다 — 기록은 쌓아 두었다가 보냅니다"

    found.connection(online=True, shipped=7)
    told = found.take()
    assert [one.kind for one in told] == [module.CENTER_BACK]
    assert told[0].text == "Center 연결 복구 — 기록 7건 보냄"


def test_coming_back_with_nothing_to_send_says_just_that() -> None:
    """보낸 것이 없으면 **개수를 적지 않는다** — 「0건 보냄」은 말이 안 된다."""
    found = Notices()
    found.connection(online=True)
    found.connection(online=False)
    found.take()
    found.connection(online=True, shipped=0)
    assert found.take()[0].text == "Center 연결 복구"


def test_a_runtime_that_was_restarted_and_then_gave_up() -> None:
    """이름은 **확장이 준 `label`**이다 (ADR-0018 — 플랫폼은 어느 확장인지 모른다)."""
    found = Notices()
    found.runtime("worker", label="Worker 프로세스", state="running", restarts=0)
    assert not found.pending, "처음 본 상태는 알릴 거리가 아니다"

    found.runtime("worker", label="Worker 프로세스", state="restarting", restarts=1)
    told = found.take()
    assert [(one.kind, one.text) for one in told] == [
        (module.RUNTIME_RESTARTED, "Worker 프로세스가 멈춰 다시 띄웠습니다")
    ]

    found.runtime("worker", label="Worker 프로세스", state="stopped", restarts=4, why="포트가 쓰이고 있습니다")
    told = found.take()
    assert told[0].kind == module.RUNTIME_GAVE_UP
    assert "포트가 쓰이고 있습니다" in told[0].text
    assert "UI 태스크가 있는 Bot은 실행되지 않습니다" in told[0].text
    assert told[0].sticky, "사람이 볼 때까지 — 이 PC에서 UI 태스크가 아예 안 돈다"


def test_the_same_runtime_state_is_not_told_again() -> None:
    found = Notices()
    found.runtime("worker", label="Worker", state="running", restarts=0)
    found.runtime("worker", label="Worker", state="stopped", restarts=4, why="왜")
    found.take()
    found.runtime("worker", label="Worker", state="stopped", restarts=4, why="왜")
    assert not found.pending


def test_approvals_and_confirmations_are_told_apart() -> None:
    """결재는 「결재가 필요합니다」, 확인은 **어느 태스크**인지까지 (BUI-05 표)."""
    found = Notices()
    found.requests(
        [
            Request(request_id="r1", node_id="Approval_1", layer="approval"),
            Request(request_id="r2", node_id="Confirm_2", layer="confirmation"),
        ],
        bot="청구서 처리",
    )
    told = found.take()
    assert [(one.kind, one.text) for one in told] == [
        (module.APPROVAL_NEEDED, "청구서 처리: 결재가 필요합니다"),
        (module.CONFIRMATION_NEEDED, "청구서 처리: 실행 확인이 필요합니다 — Confirm_2"),
    ]
    assert all(one.sticky and one.action == module.ACTION_APPROVAL for one in told)


def test_the_same_request_is_told_once_and_then_forgotten() -> None:
    """주기마다 같은 결재가 보인다 — 한 번만 알리고, 끝난 요청은 잊는다."""
    found = Notices()
    asked = [Request(request_id="r1", node_id="Approval_1")]
    found.requests(asked, bot="청구서 처리")
    found.requests(asked, bot="청구서 처리")
    assert len(found.take()) == 1

    found.requests([], bot="청구서 처리")
    assert not found._told, "끝난 요청 id를 들고 있지 않는다"  # noqa: SLF001


def test_an_approval_bound_for_center_is_not_told_as_a_field_one() -> None:
    """ADR-0038 — Center로 올라갈 결재는 **올린 뒤에** 알린다 (올리기 전에 「올라갔습니다」는 거짓)."""
    found = Notices()
    found.requests([Request(request_id="r1", node_id="A", where="center")], bot="청구서 처리")
    assert not found.pending

    found.sent_to_center(bot="청구서 처리")
    told = found.take()
    assert told[0].kind == module.APPROVAL_AT_CENTER
    assert "여기서 답하려면 누르세요" in told[0].text
    assert told[0].action == module.ACTION_APPROVAL


def test_a_deployment_that_needs_a_key_says_so_instead() -> None:
    """설치는 됐는데 돌지 않는다 — 「설치했습니다」만 띄우면 왜 안 도는지 모른다 (BUI-10으로)."""
    found = Notices()
    found.deployed(bot="청구서 처리", version="1.2.0")
    assert found.take()[0].text == "청구서 처리 1.2.0을 설치했습니다"

    found.deployed(bot="청구서 처리", version="1.2.0", missing_keys=["fin-erp", "fin-crm"])
    told = found.take()
    assert told[0].kind == module.DEPLOYED_NEEDS_KEY
    assert told[0].text == "청구서 처리 설치됨 — 서비스 앱 키 fin-erp, fin-crm를 등록해야 실행할 수 있습니다"
    assert told[0].action == module.ACTION_KEYS
    assert told[0].sticky


# ─────────────────────────── Agent에 붙은 자리 ───────────────────────────


def install_bot(*, bot_id: str = "fin.invoice", name: str = "청구서 처리") -> InstalledBot:
    manifest = Manifest.model_validate(
        {
            "schema": 1,
            "id": bot_id,
            "version": "1.0.0",
            "name": name,
            "kind": "bpm_process",
            "run_location": "pc",
            "entry": "main.bpmn",
            "content_hash": "sha256:" + "0" * 64,
            "human": {"approval_center": False, "approval_field": False, "confirmation": False},
            "built": {"by": "studio", "at": NOW, "core": "0.1.0", "spec_version": 1},
            "requires": {},
        }
    )
    folder = data_dir() / "bots" / manifest.id / manifest.version
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    return InstalledBot(manifest=manifest, folder=folder)


def agent_with(tmp_path: Path, *, client: Any = None) -> Agent:
    return Agent(
        settings=Settings(center_url="http://center.test"),
        store=Store.load(tmp_path / "state.json"),
        credentials=FakeCredentials("chk_ctr_test"),
        client_factory=(lambda _url, _key: client) if client is not None else None,
    )


class FakeCenter:
    """등록·하트비트만 하는 Center (여기서 보는 것은 **알림**이다)."""

    def __init__(self, *, fail: Exception | None = None) -> None:
        self.fail = fail
        self.beats = 0

    def register(self, _request: Any) -> RegisterResponse:
        # `bot_ui_id`는 C4 모양을 지킨다 (`bui_<hex8>`) — 등록을 거치는 시험이 있다.
        return RegisterResponse(bot_ui_id=BOT_UI_ID, heartbeat_interval_s=30, server_time=NOW)

    def heartbeat(self, _request: Any) -> HeartbeatResponse:
        self.beats += 1
        if self.fail is not None:
            raise self.fail
        return HeartbeatResponse(server_time=NOW)


def test_an_unreachable_center_is_told_once(tmp_path: Path) -> None:
    """ADR-0007 — 닿지 못하는 동안 주기마다 띄우지 않는다."""
    agent = agent_with(tmp_path, client=FakeCenter(fail=Unreachable("닿지 못합니다")))
    agent.store.state.bot_ui_id = "bui_1"

    assert agent.beat() is None
    told = agent.notices.take()
    assert [one.kind for one in told] == [module.CENTER_OFFLINE]

    assert agent.beat() is None
    assert not agent.notices.take(), "같은 말을 두 번 하지 않는다"


# ─────────────────────────── Center API 키 만료 (C4 `key_expires_at`) ───────────────────────────


def test_an_expiring_center_key_is_told_once_a_day() -> None:
    """14일 전부터 **하루 한 번** (BUI-05) — 주기마다 띄우면 30초에 한 번 같은 말을 한다."""
    found = Notices()
    soon = "2026-10-20T09:00:00+09:00"  # 열흘 뒤
    found.center_key_expiring(expires_at=soon, now=NOW)
    [one] = found.take()
    assert one.kind == module.KEY_EXPIRING
    assert one.text == "Center API 키가 2026-10-20에 만료됩니다 — 운영자에게 새 키를 요청하세요"
    assert (one.action, one.level) == (module.ACTION_SETTINGS, "warning")

    found.center_key_expiring(expires_at=soon, now="2026-10-10T09:00:30+09:00")
    assert not found.take(), "같은 날에는 다시 알리지 않는다"
    found.center_key_expiring(expires_at=soon, now="2026-10-11T09:00:00+09:00")
    assert [one.kind for one in found.take()] == [module.KEY_EXPIRING], "날이 바뀌면 다시"


def test_a_key_that_is_not_near_its_end_is_not_told() -> None:
    """**없으면 「만료 없음」**이다 (C4) — 「모른다」가 아니므로 알릴 거리도 없다."""
    found = Notices()
    found.center_key_expiring(expires_at=None, now=NOW)
    found.center_key_expiring(expires_at="2027-10-10T09:00:00+09:00", now=NOW)
    assert not found.take()


def test_an_already_expired_key_is_left_to_the_rejection_notice() -> None:
    """만료된 키는 Center가 거부한다 — 「미리 알림」이 할 일이 아니다 (할 말이 다르다)."""
    found = Notices()
    found.center_key_expiring(expires_at="2026-10-01T09:00:00+09:00", now=NOW)
    assert not found.take()


def test_a_longer_key_period_can_be_told_again_later() -> None:
    """운영자가 기간을 늘려 주면 **들고 있던 「알렸다」를 버린다** — 다음에 또 알린다."""
    found = Notices()
    found.center_key_expiring(expires_at="2026-10-20T09:00:00+09:00", now=NOW)
    assert found.take()
    found.center_key_expiring(expires_at="2027-10-10T09:00:00+09:00", now=NOW)  # 늘어났다
    found.center_key_expiring(expires_at="2027-10-10T09:00:00+09:00", now="2027-10-01T09:00:00+09:00")
    assert [one.kind for one in found.take()] == [module.KEY_EXPIRING]


def test_the_agent_tells_it_from_what_center_sent(tmp_path: Path) -> None:
    """**만료일은 Center만 안다** (C4) — 등록·하트비트 응답에서 와야 알릴 수 있다."""
    soon = "2026-10-20T09:00:00+09:00"

    class WithExpiry(FakeCenter):
        def register(self, _request: Any) -> RegisterResponse:
            return RegisterResponse(
                bot_ui_id=BOT_UI_ID, heartbeat_interval_s=30, server_time=NOW, key_expires_at=soon
            )

        def heartbeat(self, _request: Any) -> HeartbeatResponse:
            self.beats += 1
            return HeartbeatResponse(server_time=NOW, key_expires_at=soon)

    agent = agent_with(tmp_path, client=WithExpiry())
    assert agent.beat() is not None
    assert module.KEY_EXPIRING in [one.kind for one in agent.notices.take()]


def test_a_rejected_key_is_told_with_what_to_do(tmp_path: Path) -> None:
    """C4 403 — 사람이 설정에서 새 키를 넣어야 한다 (지나가게 두지 않는다)."""
    agent = agent_with(tmp_path, client=FakeCenter(fail=KeyRejected("키가 폐기됐습니다", code="key_revoked")))
    agent.store.state.bot_ui_id = "bui_1"

    with pytest.raises(KeyRejected):
        agent.beat()
    told = agent.notices.take()
    assert [(one.kind, one.action, one.sticky) for one in told] == [
        (module.KEY_REJECTED, module.ACTION_SETTINGS, True)
    ]


def test_coming_back_online_tells_how_many_records_went_out(tmp_path: Path) -> None:
    agent = agent_with(tmp_path, client=FakeCenter())
    agent.store.state.bot_ui_id = "bui_1"
    agent.notices.connection(online=True)  # 첫 바퀴를 지나 보낸다
    agent.notices.connection(online=False)
    agent.notices.take()

    assert agent.beat() is not None
    assert [one.kind for one in agent.notices.take()] == [module.CENTER_BACK]


def test_a_failed_run_is_told_with_the_line_from_the_log(tmp_path: Path) -> None:
    """사유는 **기록에 적힌 한 줄**이다 (C3 — 업무 값은 없다)."""
    agent = agent_with(tmp_path)
    bot = install_bot()
    running = Running(
        bot=bot,
        run_id="run_1",
        source="manual",
        started_at=NOW,
        child=ChildProcess(args=["true"], log_path=tmp_path / "runner.log"),
        data_dir=data_dir(),
    )
    running._apply(  # noqa: SLF001 — 기록을 읽는 길 그대로 쓴다
        "run_finished", None, {"status": "failed", "message": "서비스 앱에 닿지 못했습니다"}, NOW
    )

    agent._finished(running)  # noqa: SLF001 — 실행이 끝나는 자리다
    told = agent.notices.take()
    assert [one.kind for one in told] == [module.RUN_FAILED]
    assert told[0].text == "청구서 처리 실패 — 서비스 앱에 닿지 못했습니다"


def test_a_run_that_ended_well_is_not_told(tmp_path: Path) -> None:
    """잘 끝난 것은 알림 거리가 아니다 (BUI-05 표에 없다) — BUI-02 기록에 있다."""
    agent = agent_with(tmp_path)
    running = Running(
        bot=install_bot(),
        run_id="run_1",
        source="manual",
        started_at=NOW,
        child=ChildProcess(args=["true"], log_path=tmp_path / "runner.log"),
        data_dir=data_dir(),
    )
    running._apply("run_finished", None, {"status": "success"}, NOW)  # noqa: SLF001
    agent._finished(running)  # noqa: SLF001
    assert not agent.notices.pending


def test_a_deployment_result_is_told_and_a_refusal_sticks(tmp_path: Path, monkeypatch: Any) -> None:
    """C4 `deployment_results` — 설치는 5초, **거부는 사람이 볼 때까지**다."""
    agent = agent_with(tmp_path)
    install_bot()

    class FakeDeployer:
        def apply(self, _envelopes: list[dict[str, Any]]) -> list[DeploymentResult]:
            return [
                DeploymentResult(
                    deployment_id="dep_1",
                    bpm_process_id="fin.invoice",
                    version="1.0.0",
                    result="applied",
                    at=NOW,
                ),
                DeploymentResult(
                    deployment_id="dep_2",
                    bpm_process_id="ops.scan",
                    version="2.0.0",
                    result="rejected",
                    at=NOW,
                    reason="서명이 맞지 않습니다",
                ),
            ]

    monkeypatch.setattr(agent, "deployer", FakeDeployer)
    agent.apply_deployments(HeartbeatResponse(server_time=NOW, deployments=[{"있다": True}]))

    told = agent.notices.take()
    assert [one.kind for one in told] == [module.DEPLOYED, module.DEPLOY_REFUSED]
    assert told[0].text == "청구서 처리 1.0.0을 설치했습니다", "이름은 설치된 매니페스트에서 온다"
    assert told[1].text == "배포를 거부했습니다 — 서명이 맞지 않습니다"
    assert told[1].sticky


def test_a_queue_that_is_full_tells_the_pc_too(tmp_path: Path) -> None:
    """Center만 알면 PC 앞에서는 「왜 안 도나」가 된다 (C4 `queue_full`)."""
    agent = agent_with(tmp_path)
    agent.settings = Settings(queue_max=1)
    agent.store.state.queue.append(
        QueueItem(queue_id="q1", source="manual", bpm_process_id="fin.invoice", requested_at=NOW)
    )

    ack = agent.take_job(
        JobDispatch(job_id="job_1", bpm_process_id="ops.scan", requested_by="홍길동", requested_at=NOW)
    )
    assert ack.result == "rejected" and ack.reason == "queue_full"
    told = agent.notices.take()
    assert told[0].text == "대기열이 가득 찼습니다 (1건) — ops.scan 요청을 받지 않았습니다"


def test_a_manual_run_that_has_to_wait_says_what_is_running(tmp_path: Path) -> None:
    agent = agent_with(tmp_path)
    agent.current_run = None
    agent.enqueue_manual("fin.invoice")
    assert not agent.notices.pending, "바로 돌 것은 알릴 거리가 아니다"

    from chaeksas.contracts.bot_ui import CurrentRun

    agent.current_run = CurrentRun(
        run_id="run_1",
        bpm_process_id="ops.scan",
        version="1.0.0",
        state="running",
        started_at=NOW,
        source="manual",
    )
    agent.enqueue_manual("fin.invoice")
    told = agent.notices.take()
    assert told[0].kind == module.QUEUED
    assert told[0].text == "fin.invoice: 대기열 2번째 — 실행 중 ops.scan"


# ─────────────────────────── 기다리는 동안 만료 (C4) ───────────────────────────


def test_a_job_that_expired_while_waiting_is_dropped_and_acked(tmp_path: Path) -> None:
    """**붙이기 전까지 `expires_at`을 아무도 보지 않았다** — 지난 작업이 그대로 돌았다.

    C4의 작업 흐름은 `expired` ack를 적어 두었고, 현장에도 알려야 한다 (BUI-05).
    """
    agent = agent_with(tmp_path)
    gone = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    later = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    agent.store.state.queue += [
        QueueItem(
            queue_id="q1",
            source="job",
            bpm_process_id="fin.invoice",
            job_id="job_1",
            requested_at=NOW,
            expires_at=gone,
        ),
        QueueItem(
            queue_id="q2",
            source="job",
            bpm_process_id="ops.scan",
            job_id="job_2",
            requested_at=NOW,
            expires_at=later,
        ),
        QueueItem(queue_id="q3", source="manual", bpm_process_id="hr.leave", requested_at=NOW),
    ]
    agent.store.state.inputs["q1"] = {"금액": 1000}

    made = agent.drop_expired()

    assert [ack.job_id for ack in made] == ["job_1"]
    assert [ack.result for ack in made] == ["expired"]
    assert [item.queue_id for item in agent.queue] == ["q2", "q3"], "아직 남은 것·만료 없는 것은 그대로"
    assert "q1" not in agent.store.state.inputs, "버린 항목의 입력도 함께 지운다"
    told = agent.notices.take()
    assert told[0].text == "fin.invoice 작업이 기다리는 동안 만료되었습니다"
    # 다시 켜도 돌아오지 않는다 (상태 파일에 적었다).
    assert [item.queue_id for item in Store.load(tmp_path / "state.json").state.queue] == ["q2", "q3"]


# ─────────────────────────── 띄우는 쪽 (화면) ───────────────────────────


@pytest.fixture
def qt_app() -> Any:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    existing = QApplication.instance()
    if existing is not None:
        return existing
    try:
        return QApplication([])
    except Exception as e:  # pragma: no cover - 환경 문제
        pytest.skip(f"Qt 플랫폼 플러그인을 띄울 수 없다: {e}")


def test_without_a_tray_the_status_bar_is_the_notice_place(qt_app: Any, tmp_path: Path) -> None:
    """U15 — 트레이가 없는 환경에서도 알림이 사라지지 않는다 (창의 상태 줄로 간다)."""
    from PySide6.QtWidgets import QSystemTrayIcon

    from chaeksas.bot_ui.app import BotUiApp

    if QSystemTrayIcon.isSystemTrayAvailable():
        pytest.skip("이 환경에는 트레이가 있다 — 풍선 쪽은 Windows 실기에서 본다")

    agent = agent_with(tmp_path)
    made = BotUiApp(qt_app, agent)
    try:
        agent.notices.queue_expired(bot="fin.invoice")
        made.show_notices()
        assert "만료되었습니다" in made.window.statusBar().currentMessage()
        assert not agent.notices.pending, "거둬 간 것은 다시 띄우지 않는다"
    finally:
        made.window.close()


def test_clicking_a_notice_opens_what_it_points_at(qt_app: Any, tmp_path: Path, monkeypatch: Any) -> None:
    """누르면 **그 알림이 가리키는 자리**가 열린다 (BUI-05 — 결재는 CMN-01, 키는 BUI-10)."""
    from chaeksas.bot_ui.app import BotUiApp
    from chaeksas.bot_ui.main_window import MainWindow

    agent = agent_with(tmp_path)
    made = BotUiApp(qt_app, agent)
    opened: list[str] = []
    monkeypatch.setattr(MainWindow, "open_keys", lambda _self: opened.append("keys"))
    monkeypatch.setattr(MainWindow, "open_approval", lambda _self: opened.append("approval"))
    try:
        agent.notices.deployed(bot="청구서 처리", version="1.0.0", missing_keys=["fin-erp"])
        made.show_notices()
        made.on_notice_clicked()
        assert opened == ["keys"]

        agent.notices.requests([Request(request_id="r1", node_id="A")], bot="청구서 처리")
        made.show_notices()
        made.on_notice_clicked()
        assert opened == ["keys", "approval"]

        # 누를 거리가 없는 알림 뒤에는 **아무 일도 일어나지 않는다**.
        made.on_notice_clicked()
        assert opened == ["keys", "approval"]
    finally:
        made.window.close()


def test_the_heartbeat_problem_signal_does_not_make_its_own_notice(qt_app: Any, tmp_path: Path) -> None:
    """하트비트의 `problem` 신호는 **기록만** 한다 — 알림은 `Notices`가 가른다.

    전에는 이 자리에서 풍선을 띄워, 닿지 못하는 동안 같은 말이 주기마다 떴다.
    """
    from chaeksas.bot_ui.app import BotUiApp

    agent = agent_with(tmp_path)
    made = BotUiApp(qt_app, agent)
    try:
        made.on_problem("Center에 닿지 못합니다")
        assert not agent.notices.pending
    finally:
        made.window.close()


# ─────────────────────── 서비스 앱 키 (BUI-05, ADR-0052) ───────────────────────
#
# 반쪽이 둘이고 **묻는 때가 다르다**: 거부는 실행 기록에서 읽고(실행이 이미 물었다), 만료 임박만
# 주기가 하루 한 번 묻는다.

APP_ID = "tax-invoice"
KEY_REF = "finance-invoice"
SOON = "2026-10-20T09:00:00+09:00"  # NOW에서 열흘 뒤


def a_refusal(*, status: int = 403, app_id: str = APP_ID, ref: str = KEY_REF) -> Any:
    from chaeksas.bot_ui.runner import KeyRefusal

    return KeyRefusal(app_id=app_id, key_ref=ref, status=status)


def test_a_refused_service_app_key_is_told_with_what_to_do() -> None:
    """BUI-05 — 「<앱>이 키 <참조>를 거부했습니다」. **까닭은 넣지 않는다**(할 일이 같다)."""
    found = Notices()
    found.service_keys_refused([a_refusal()], bot="청구서 처리", run_id="run_1")
    [one] = found.take()
    assert one.kind == module.SERVICE_KEY_REFUSED
    assert one.text == "tax-invoice이 키 finance-invoice를 거부했습니다 — 새 키를 넣으세요"
    assert (one.action, one.sticky, one.level) == (module.ACTION_KEYS, True, "error")


def test_the_same_refusal_is_told_once_per_run_and_again_in_the_next_run() -> None:
    """재시도가 `service_call` 줄을 여럿 남긴다 — 한 실행에서는 한 번이다.

    **새 실행이 또 거부당하면 다시 알린다**: 지난 알림이 아니라 방금 실패한 업무다.
    """
    found = Notices()
    found.service_keys_refused([a_refusal(), a_refusal(status=401)], bot="청구서 처리", run_id="run_1")
    assert len(found.take()) == 1, "앱·참조가 같으면 한 줄"
    found.service_keys_refused([a_refusal()], bot="청구서 처리", run_id="run_1")
    assert not found.take(), "같은 실행에서는 다시 알리지 않는다"

    found.service_keys_refused([a_refusal()], bot="청구서 처리", run_id="run_2")
    assert [one.kind for one in found.take()] == [module.SERVICE_KEY_REFUSED]


def test_an_expiring_service_app_key_is_told_once_a_day_per_ref() -> None:
    """Center 키와 **같은 규칙**이다 — 14일 전부터 하루 한 번, 참조마다."""
    found = Notices()
    found.service_key_expiring(ref=KEY_REF, expires_at=SOON, now=NOW)
    [one] = found.take()
    assert one.kind == module.SERVICE_KEY_EXPIRING
    assert one.text == "서비스 앱 키 finance-invoice가 2026-10-20에 만료됩니다"
    assert (one.action, one.level, one.seconds) == (module.ACTION_KEYS, "warning", module.LONG_S)

    found.service_key_expiring(ref=KEY_REF, expires_at=SOON, now="2026-10-10T09:00:30+09:00")
    assert not found.take(), "같은 날에는 다시 알리지 않는다"
    found.service_key_expiring(ref="ops-scan", expires_at=SOON, now=NOW)
    assert [one.kind for one in found.take()] == [module.SERVICE_KEY_EXPIRING], "다른 참조는 따로 센다"
    found.service_key_expiring(ref=KEY_REF, expires_at=SOON, now="2026-10-11T09:00:00+09:00")
    assert found.take(), "날이 바뀌면 다시"


def test_a_service_app_key_that_is_not_near_its_end_is_not_told() -> None:
    """**없으면 「만료 없음」**이고, 이미 만료된 것은 「거부」가 말한다 (목소리를 둘 두지 않는다)."""
    found = Notices()
    found.service_key_expiring(ref=KEY_REF, expires_at=None, now=NOW)
    found.service_key_expiring(ref=KEY_REF, expires_at="2027-10-10T09:00:00+09:00", now=NOW)
    found.service_key_expiring(ref=KEY_REF, expires_at="2026-10-01T09:00:00+09:00", now=NOW)
    assert not found.take()


# ── 거부를 읽는 자리 (C3 `service_call`) ──


def a_running(tmp_path: Path, *, run_id: str = "run_1") -> Running:
    return Running(
        bot=install_bot(),
        run_id=run_id,
        source="manual",
        started_at=NOW,
        child=ChildProcess(args=["true"], log_path=tmp_path / "runner.log"),
        data_dir=data_dir(),
    )


def call_data(**more: Any) -> dict[str, Any]:
    """C3 `service_call`의 `data` (필수 키는 계약 표 그대로)."""
    return {
        "app_id": APP_ID,
        "operation": "issue",
        "mode": "deterministic",
        "mode_used": "deterministic",
        "status": 403,
        "duration_ms": 12,
        "key_ref": KEY_REF,
        "node_instance": 1,
        "attempt": 1,
        "call_seq": 1,
        **more,
    }


@pytest.mark.parametrize("status", [401, 403])
def test_the_run_log_says_the_app_refused_the_key(tmp_path: Path, status: int) -> None:
    """**묻지 않고 안다** — 401·403은 앱이 분명히 거부한 것이다 (C11 오류표)."""
    running = a_running(tmp_path)
    running._apply("service_call", "task_1", call_data(status=status), NOW)  # noqa: SLF001
    assert running.key_refusals == [a_refusal(status=status)]


def test_a_key_missing_on_this_pc_is_not_a_refusal(tmp_path: Path) -> None:
    """값이 이 PC에 없는 것은 **사전 점검이 할 말**이다 (「서비스 앱 키 없음: <참조>」).

    뭉치면 키를 넣으면 될 일에 「앱이 거부했다」고 한다 — 앱은 불린 적도 없다.
    """
    running = a_running(tmp_path)
    running._apply(  # noqa: SLF001 - 닿지 못한 호출은 `status`가 0으로 남는다
        "service_call", "task_1", call_data(status=0, error_code="key_missing"), NOW
    )
    running._apply("service_call", "task_1", call_data(status=503, error_code="dependency_down"), NOW)  # noqa: SLF001
    assert running.key_refusals == [], "앱이 거부한 것만 본다"


def test_retries_of_the_same_call_make_one_refusal(tmp_path: Path) -> None:
    running = a_running(tmp_path)
    for attempt in (1, 2, 3):
        running._apply("service_call", "task_1", call_data(attempt=attempt), NOW)  # noqa: SLF001
    assert len(running.key_refusals) == 1


def test_the_agent_tells_a_refusal_even_when_the_run_is_already_over(tmp_path: Path) -> None:
    """한 틱 안에 거부당하고 끝난 실행은 `pump()`이 못 본다 — 거둘 때도 본다."""
    agent = agent_with(tmp_path)
    running = a_running(tmp_path)
    running._apply("service_call", "task_1", call_data(), NOW)  # noqa: SLF001
    running._apply("run_finished", None, {"status": "failed", "message": "키가 거부되었습니다"}, NOW)  # noqa: SLF001

    agent._finished(running)  # noqa: SLF001
    assert [one.kind for one in agent.notices.take()] == [module.SERVICE_KEY_REFUSED, module.RUN_FAILED]


# ── 만료 임박을 묻는 자리 (C11 `GET /v1/keys/self`) ──


def install_bot_calling_an_app(*, bot_id: str = "fin.invoice", ref: str = KEY_REF) -> InstalledBot:
    """그 Bot이 **실제로 쓰는** 키 참조 하나 (C1 `requires.service_apps`)."""
    bot = install_bot(bot_id=bot_id)
    needs = [ServiceAppNeed(app_id=APP_ID, operations=["issue"], key_ref=ref)]
    manifest = bot.manifest.model_copy(
        update={"requires": bot.manifest.requires.model_copy(update={"service_apps": needs})}
    )
    (bot.folder / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    return InstalledBot(manifest=manifest, folder=bot.folder)


def hold_address(*, app_id: str = APP_ID, base_url: str = "http://app.test") -> None:
    """Center에서 받아 **들고 있는** 주소 (C7 — 묻기 위해 Center를 두드리지 않는다)."""
    from chaeksas.bot_ui.services import CACHE_NAME

    path = data_dir() / CACHE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"apps": {app_id: {"base_url": base_url}}, "extensions": []}, ensure_ascii=False),
        encoding="utf-8",
    )


def agent_asking(tmp_path: Path, monkeypatch: Any, facts: Any, *, refs: Sequence[str] = (KEY_REF,)) -> Any:
    """키를 가진 Agent + 묻는 길을 바꿔 끼운 것. 물어본 주소·키 참조를 적어 둔다."""
    agent = agent_with(tmp_path)
    for ref in refs:
        agent.credentials.set_service_app_key(ref, "chk_svc_" + "a" * 40)
    asked: list[tuple[str | None, str | None]] = []

    def fake(base_url: str | None, key: str | None, **_more: Any) -> Any:
        asked.append((base_url, key))
        if isinstance(facts, Exception):
            raise facts
        return facts

    monkeypatch.setattr(module_agent, "key_facts", fake)
    return agent, asked


def test_an_expiring_service_app_key_is_asked_for_and_told(tmp_path: Path, monkeypatch: Any) -> None:
    """만료일은 **그 앱만 안다** (C11) — 묻지 않으면 미리 알릴 수 없다."""
    install_bot_calling_an_app()
    hold_address()
    agent, asked = agent_asking(tmp_path, monkeypatch, KeyFacts(line="정상", answered=True, expires_at=SOON))

    assert agent.ask_service_key() == KEY_REF
    assert asked == [("http://app.test", "chk_svc_" + "a" * 40)], "들고 있는 주소로 묻는다"
    [one] = agent.notices.take()
    assert one.kind == module.SERVICE_KEY_EXPIRING


def test_only_one_key_is_asked_per_round_and_once_a_day(tmp_path: Path, monkeypatch: Any) -> None:
    """하트비트는 **화면과 같은 자리**에서 돈다 — 한 주기에 여럿을 물으면 그만큼 멈춘다."""
    install_bot_calling_an_app(bot_id="fin.invoice", ref=KEY_REF)
    install_bot_calling_an_app(bot_id="ops.scan", ref="ops-key")
    hold_address()
    agent, asked = agent_asking(
        tmp_path, monkeypatch, KeyFacts(line="정상", answered=True), refs=(KEY_REF, "ops-key")
    )

    first, second, third = agent.ask_service_key(), agent.ask_service_key(), agent.ask_service_key()
    assert {first, second} == {KEY_REF, "ops-key"}, "주기마다 하나씩"
    assert third is None and len(asked) == 2, "같은 날에는 다시 묻지 않는다"


def test_a_key_without_a_held_address_is_not_asked(tmp_path: Path, monkeypatch: Any) -> None:
    """**닿을 데를 모르면 묻지 않는다** — 이것 때문에 Center를 두드리지 않는다 (ADR-0052)."""
    install_bot_calling_an_app()
    agent, asked = agent_asking(tmp_path, monkeypatch, KeyFacts(line="정상", answered=True))

    assert agent.ask_service_key() is None
    assert asked == []


def test_a_key_no_installed_bot_uses_is_not_asked(tmp_path: Path, monkeypatch: Any) -> None:
    """BUI-10에 **등록만 해 둔** 키는 묻지 않는다 — 쓰는 Bot이 없으면 알릴 거리도 없다."""
    hold_address()
    agent, asked = agent_asking(tmp_path, monkeypatch, KeyFacts(line="정상", answered=True), refs=("남은-키",))
    agent.settings = replace(agent.settings, service_keys=(ServiceKeyRef(ref="남은-키", app_id=APP_ID),))

    assert agent.ask_service_key() is None
    assert asked == []


@pytest.mark.parametrize(
    "facts",
    [
        KeyFacts(line="앱에 닿지 못함"),
        KeyFacts(line="폐기됨", answered=True, refused=True),
        KeyFacts(line="정상", answered=True, expires_at="2027-10-10T09:00:00+09:00"),
    ],
    ids=["unreachable", "refused", "far-off"],
)
def test_what_the_asking_does_not_tell(tmp_path: Path, monkeypatch: Any, facts: Any) -> None:
    """닿지 못한 것은 알릴 거리가 아니고(ADR-0007), **거부는 실행 기록이 말한다**."""
    install_bot_calling_an_app()
    hold_address()
    agent, _asked = agent_asking(tmp_path, monkeypatch, facts)

    assert agent.ask_service_key() == KEY_REF
    assert not agent.notices.pending


def test_asking_does_not_break_the_round(tmp_path: Path, monkeypatch: Any) -> None:
    """주기가 깨지면 하트비트·대기열이 멈춘다 — 묻다 터진 것은 기록만 남긴다."""
    install_bot_calling_an_app()
    hold_address()
    agent, _asked = agent_asking(tmp_path, monkeypatch, ValueError("깨진 답"))

    assert agent.ask_service_key() == KEY_REF
    assert not agent.notices.pending


def test_keys_are_asked_even_when_center_is_down(tmp_path: Path, monkeypatch: Any) -> None:
    """**Center보다 먼저 묻는다** — Center가 꺼져 있어도 서비스 앱 키는 만료된다."""
    install_bot_calling_an_app()
    hold_address()
    agent, asked = agent_asking(tmp_path, monkeypatch, KeyFacts(line="정상", answered=True, expires_at=SOON))
    agent.client_factory = lambda _url, _key: FakeCenter(fail=Unreachable("닿지 못합니다"))
    agent.store.state.bot_ui_id = "bui_1"

    assert agent.beat() is None
    assert len(asked) == 1
    assert module.SERVICE_KEY_EXPIRING in [one.kind for one in agent.notices.take()]


def test_refusals_of_past_runs_are_forgotten(tmp_path: Path) -> None:
    """들고 있는 것이 PC 수명만큼 자라지 않는다 — 실행이 바뀌면 잊는다 (`requests()`와 같은 결)."""
    agent = agent_with(tmp_path)
    first = a_running(tmp_path, run_id="run_1")
    first._apply("service_call", "task_1", call_data(), NOW)  # noqa: SLF001
    agent._tell_key_refusals(first)  # noqa: SLF001
    agent.notices.take()

    agent._tell_key_refusals(a_running(tmp_path, run_id="run_2"))  # noqa: SLF001 - 거부가 없는 실행
    assert not agent.notices._refusals_told  # noqa: SLF001
