"""타이머 시작의 일정 — Center가 쓸어 작업으로 만든다 (ADR-0110, C5 §일정, C1 R13).

식을 읽는 함수(`contracts.schedule`)와 쓰는 쪽(`center/api/timers.py`)을 함께 본다. 보는 것은
「차례가 되면 작업 하나」·「놓친 차례는 가장 최근 한 번」·「두 번 쏘지 않는다」·「배포 전의 차례는
없다」·「하트비트가 쓸어 바로 내려 준다」다.
"""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import center_admin
import pytest
from fastapi.testclient import TestClient

from chaeksas.center.api import jobs as jobs_api
from chaeksas.center.api import timers
from chaeksas.center.app import create_app
from chaeksas.center.errors import ApiError
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.center.storage import Store
from chaeksas.contracts.center_api import job_source, timer_requester
from chaeksas.contracts.hashing import MANIFEST_NAME, content_hash_zip
from chaeksas.contracts.manifest import Manifest, validate
from chaeksas.contracts.schedule import CycleError, cycle_problem, parse_cycle

ADMIN = {"Authorization": "Bearer t-admin"}
ZIP = "application/zip"
SEOUL = ZoneInfo("Asia/Seoul")
VERSION = "1.0.0"
#: 업무 예제 BX-23 — 실행 위치 `server`, **매주 수요일 10시**에 시작한다.
TRAINING = Path("docs/08-business-examples/bpmn/bx23_training_reminder.bpmn")
TRAINING_BOT = "hr.training-reminder"
#: 업무 예제 BX-04 — 실행 위치 `pc`, **매달 1일 9시**에 시작한다.
INVOICE = Path("docs/08-business-examples/bpmn/bx04_tax_invoice_issue.bpmn")
INVOICE_BOT = "fin.tax-invoice-issue"


def seoul(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=SEOUL)


# ─────────────────────────── 식 읽기 ───────────────────────────


def test_cron_reads_the_five_fields() -> None:
    cycle = parse_cycle("0 9 * * 1-5")
    # 금요일 10시 다음은 월요일 9시다.
    assert cycle.next_after(seoul(2026, 10, 30, 10), SEOUL, anchor=seoul(2026, 1, 1)) == seoul(2026, 11, 2, 9)
    steps = parse_cycle("*/15 8-9 * * *").between(seoul(2026, 10, 30, 7), seoul(2026, 10, 30, 10), SEOUL,
                                                  anchor=seoul(2026, 1, 1))
    assert [one.strftime("%H:%M") for one in steps] == [
        "08:00", "08:15", "08:30", "08:45", "09:00", "09:15", "09:30", "09:45",
    ]


def test_l_is_the_last_day_of_the_month() -> None:
    """BX-05의 「매달 말일 18시」 (`0 18 L * *`)."""
    found = parse_cycle("0 18 L * *").between(seoul(2026, 1, 1), seoul(2026, 4, 1), SEOUL, anchor=seoul(2026, 1, 1))
    assert [one.date().isoformat() for one in found] == ["2026-01-31", "2026-02-28", "2026-03-31"]


def test_day_and_weekday_together_mean_either() -> None:
    """cron의 관례 — 일과 요일을 둘 다 적으면 **둘 중 하나**에 맞으면 된다."""
    found = parse_cycle("0 9 1 * 1").between(seoul(2026, 10, 31), seoul(2026, 11, 10), SEOUL, anchor=seoul(2026, 1, 1))
    assert [one.day for one in found] == [1, 2, 9]  # 1일(일요일)과 월요일들
    sunday = parse_cycle("0 9 * * 7").between(seoul(2026, 10, 31), seoul(2026, 11, 2), SEOUL, anchor=seoul(2026, 1, 1))
    assert [one.day for one in sunday] == [1]  # 7도 일요일이다


def test_a_wall_time_that_does_not_exist_is_skipped() -> None:
    """서머타임으로 건너뛰는 시각은 차례가 아니다 (뉴욕 2026-03-08 02:30)."""
    york = ZoneInfo("America/New_York")
    start = datetime(2026, 3, 7, 0, tzinfo=york)
    found = parse_cycle("30 2 * * *").between(start, datetime(2026, 3, 10, 0, tzinfo=york), york, anchor=start)
    assert [one.day for one in found] == [7, 9]


def test_iso_repeat_with_and_without_a_start() -> None:
    monthly = parse_cycle("R3/2026-10-01T09:00/P1M")
    found = monthly.between(seoul(2026, 1, 1), seoul(2027, 6, 1), SEOUL, anchor=seoul(2026, 1, 1))
    assert [one.month for one in found] == [10, 11, 12]  # 셋을 다 썼다
    assert monthly.next_after(seoul(2026, 12, 2), SEOUL, anchor=seoul(2026, 1, 1)) is None
    # 시작이 없으면 **기준(배포가 생긴 때)**부터 센다.
    every = parse_cycle("R/PT90M")
    anchor = seoul(2026, 10, 30, 9)
    assert every.between(anchor, anchor + timedelta(hours=4), SEOUL, anchor=anchor) == [
        anchor + timedelta(minutes=90), anchor + timedelta(minutes=180),
    ]


@pytest.mark.parametrize(
    "text", ["", "0 9 * *", "61 * * * *", "0 9 * * MON", "0 25 * * *", "R0/P1D", "R/PT30S", "R/2026-13-01/P1D", "R/P"]
)
def test_what_cannot_be_read_says_why(text: str) -> None:
    with pytest.raises(CycleError):
        parse_cycle(text)
    assert cycle_problem(text)


def test_every_timer_example_can_be_read() -> None:
    """업무 예제의 시작 타이머가 **모두** 읽힌다 — R13이 올바른 그림을 막지 않는다."""
    import re  # noqa: PLC0415

    found = []
    for path in sorted(Path("docs/08-business-examples/bpmn").glob("*.bpmn")):
        for expr in re.findall(r"<bpmn:timeCycle[^>]*>([^<]+)<", path.read_text(encoding="utf-8")):
            found.append(expr)
            assert cycle_problem(expr) is None, (path.name, expr)
    assert len(found) >= 10


# ─────────────────────────── R13 ───────────────────────────


def _manifest(triggers: list[dict[str, Any]]) -> Manifest:
    return Manifest.model_validate(
        {
            "schema": 1,
            "kind": "bpm_process",
            "id": "x.timer",
            "version": VERSION,
            "name": "x",
            "run_location": "server",
            "entry": "process/main.bpmn",
            "process_id": "P",
            "triggers": triggers,
            "requires": {},
            "human": {},
            "built": {"by": "studio", "at": "2026-10-30T09:00:00+09:00", "core": "0.1.0", "spec_version": 1},
            "content_hash": "sha256:" + "0" * 64,
        }
    )


def test_r13_refuses_a_timer_center_cannot_read() -> None:
    bad = [v for v in validate(_manifest([{"kind": "timer", "expression": "every morning"}])) if v.rule == "R13"]
    assert [v.code for v in bad] == ["timer_expression_invalid"]
    good = validate(_manifest([{"kind": "timer", "expression": "0 9 * * 1-5"}]))
    assert not [v for v in good if v.rule == "R13"]


def test_the_requester_says_where_the_run_came_from() -> None:
    assert job_source(timer_requester("0 9 * * *")) == "schedule"
    assert job_source("server_bot:run_x") == "delegation"
    assert job_source("관리자") == "job"
    assert job_source(None) == "job"


# ─────────────────────────── Center ───────────────────────────


@pytest.fixture
def store() -> Iterator[Store]:
    found = Store(Path(":memory:"))
    yield found
    found.close()


@pytest.fixture
def center(store: Store, tmp_path: Path) -> Iterator[TestClient]:
    settings = CenterSettings(admin_token="t-admin", read_token="t-read", package_dir=tmp_path / "pkg")
    with TestClient(create_app(settings, store=store)) as found:
        yield found


def _key(center: TestClient, *, name: str, kind: str) -> str:
    made = center.post("/api/v1/center-keys", json={"name": name, "type": kind}, headers=ADMIN)
    assert made.status_code == 201, made.text
    return str(made.json()["key"])


def register_runner(center: TestClient, n: int = 1) -> tuple[str, str]:
    key = _key(center, name=f"서버 {n}", kind="server_runner")
    made = center.post(
        "/api/v1/server-runner/register",
        json={
            "schema": 1,
            "machine_id": f"{n:02d}" * 32,
            "name": f"서버 {n}",
            "os": "Linux",
            "versions": {"server_runner": "0.1.0", "core": "0.1.0"},
            "max_concurrency": 3,
        },
        headers={"Authorization": f"Bearer {key}"},
    )
    assert made.status_code in (200, 201), made.text
    return str(made.json()["server_runner_id"]), key


def register_pc(center: TestClient, n: int) -> tuple[str, str]:
    key = _key(center, name=f"PC {n}", kind="bot_ui")
    made = center.post(
        "/api/v1/bot-ui/register",
        json={
            "schema": 1,
            "machine_id": f"{n:02d}" * 32,
            "name": f"PC {n}",
            "os": "windows-11-23H2",
            "versions": {"bot_ui": "0.1.0", "core": "0.1.0"},
        },
        headers={"Authorization": f"Bearer {key}"},
    )
    assert made.status_code < 400, made.text
    return str(made.json()["bot_ui_id"]), key


def package_zip(*, bot: str, path: Path, where: str, expression: str) -> bytes:
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": bot,
        "version": VERSION,
        "name": bot,
        "run_location": where,
        "entry": "process/main.bpmn",
        "process_id": "P",
        "triggers": [{"kind": "timer", "expression": expression}],
        "requires": {},
        "human": {},
        "built": {"by": "studio", "at": "2026-10-30T09:00:00+09:00", "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }

    def made(body: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("process/main.bpmn", path.read_text(encoding="utf-8"))
            archive.writestr(MANIFEST_NAME, body)
        return out.getvalue()

    with tempfile.TemporaryDirectory() as folder:
        staged = Path(folder) / "p.zip"
        staged.write_bytes(made(json.dumps(manifest, ensure_ascii=False)))
        manifest["content_hash"] = content_hash_zip(staged)
    return made(json.dumps(manifest, ensure_ascii=False))


def upload(center: TestClient, *, bot: str, path: Path, where: str, expression: str) -> None:
    sent = center.post(
        "/api/v1/packages",
        files={"file": ("p.zip", package_zip(bot=bot, path=path, where=where, expression=expression), ZIP)},
        headers=ADMIN,
    )
    assert sent.status_code in (200, 201), sent.text
    center_admin.approve(center, bot, VERSION)


def deploy(center: TestClient, store: Store, *, bot: str, target: dict[str, str], at: datetime) -> str:
    """배포하고 **그 배포가 생긴 때를 `at`으로 옮긴다** — 일정은 그때부터 센다 (ADR-0110 §4)."""
    deployment_id = center_admin.deploy_id(center, target=target, bpm_process_id=bot, version=VERSION)
    with store.tx() as cur:
        cur.execute(
            "UPDATE deployments SET at = ? WHERE deployment_id = ?", (at.astimezone(UTC).isoformat(), deployment_id)
        )
    return str(deployment_id)


def sweep(store: Store, now: datetime) -> list[str]:
    return timers.sweep(store, tz=SEOUL, now=now, force=True)


def job(center: TestClient, job_id: str) -> dict[str, Any]:
    return dict(center.get(f"/api/v1/jobs/{job_id}", headers=ADMIN).json())


def fires(store: Store) -> list[Any]:
    return store.rows("SELECT * FROM timer_fires ORDER BY slot")


@pytest.fixture
def training(center: TestClient, store: Store) -> str:
    """BX-23(매주 수요일 10시)을 서버 실행기에 배포했다 — 10월 26일(월)에."""
    runner_id, _ = register_runner(center)
    upload(center, bot=TRAINING_BOT, path=TRAINING, where="server", expression="0 10 * * 3")
    server = {"type": "server_runner", "id": runner_id}
    deploy(center, store, bot=TRAINING_BOT, target=server, at=seoul(2026, 10, 26, 9))
    return runner_id


def test_a_due_timer_becomes_one_job(center: TestClient, store: Store, training: str) -> None:
    assert sweep(store, seoul(2026, 10, 28, 9, 59)) == []  # 아직 차례가 아니다
    made = sweep(store, seoul(2026, 10, 28, 10, 0, 30))
    assert len(made) == 1
    found = job(center, made[0])
    assert found["bpm_process_id"] == TRAINING_BOT
    assert found["version"] == VERSION
    assert found["requested_by"] == "timer:0 10 * * 3"
    assert found["target"] == {"type": "server_runner", "id": ""}  # 실행기는 Center가 고른다
    assert found["inputs"] == {}
    # **다음 차례까지만 산다** (ADR-0110 §5).
    assert datetime.fromisoformat(found["expires_at"]) == seoul(2026, 11, 4, 10)
    assert found["idempotency_key"].startswith("tmr_")
    # 같은 차례는 다시 쏘지 않는다.
    assert sweep(store, seoul(2026, 10, 28, 10, 5)) == []
    assert len(fires(store)) == 1


def test_a_deprecated_package_keeps_its_schedule(center: TestClient, store: Store, training: str) -> None:
    """지원 종료는 **새 배포만** 막는다 — 돌던 일정은 그대로 돈다 (C5 §패키지, 09-gaps §3-22)."""
    said = center.put(f"/api/v1/packages/{TRAINING_BOT}/{VERSION}/status", json={"status": "deprecated"}, headers=ADMIN)
    assert said.status_code == 200, said.text
    made = sweep(store, seoul(2026, 10, 28, 10, 0, 30))
    assert len(made) == 1
    assert job(center, made[0])["bpm_process_id"] == TRAINING_BOT


def test_missed_turns_fire_once_the_latest(center: TestClient, store: Store, training: str) -> None:
    """Center가 3주 꺼져 있었다 — **가장 최근 한 번만** 쏘고 나머지는 센다 (ADR-0110 §4)."""
    made = sweep(store, seoul(2026, 11, 13, 12))
    assert len(made) == 1
    row = fires(store)[0]
    assert datetime.fromisoformat(row["slot"]) == seoul(2026, 11, 11, 10)
    assert row["missed"] == 2  # 10월 28일·11월 4일


def test_turns_before_the_deployment_do_not_count(center: TestClient, store: Store) -> None:
    runner_id, _ = register_runner(center)
    upload(center, bot=TRAINING_BOT, path=TRAINING, where="server", expression="0 10 * * 3")
    # 수요일 10시 반에 배포했다 — 그날 10시는 배포 전이다.
    server = {"type": "server_runner", "id": runner_id}
    deploy(center, store, bot=TRAINING_BOT, target=server, at=seoul(2026, 10, 28, 10, 30))
    assert sweep(store, seoul(2026, 10, 28, 11)) == []


def test_redeploying_does_not_bring_back_old_turns(center: TestClient, store: Store, training: str) -> None:
    sweep(store, seoul(2026, 10, 28, 10, 1))
    revoked = center_admin.revoke_deployment
    deployments = center.get("/api/v1/deployments", headers=ADMIN).json()
    revoked(center, deployments[0]["deployment_id"])
    assert sweep(store, seoul(2026, 11, 4, 10, 1)) == []  # 거둔 동안은 쏘지 않는다
    deploy(center, store, bot=TRAINING_BOT, target={"type": "server_runner", "id": training}, at=seoul(2026, 11, 5, 9))
    assert sweep(store, seoul(2026, 11, 5, 9, 1)) == []  # 11월 4일은 다시 배포하기 전이다
    assert len(sweep(store, seoul(2026, 11, 11, 10, 1))) == 1


def test_two_server_runners_still_make_one_job(center: TestClient, store: Store, training: str) -> None:
    other, _ = register_runner(center, 2)
    deploy(center, store, bot=TRAINING_BOT, target={"type": "server_runner", "id": other}, at=seoul(2026, 10, 27, 9))
    assert len(sweep(store, seoul(2026, 10, 28, 10, 1))) == 1


def test_a_pc_bot_gets_a_job_per_deployed_pc(center: TestClient, store: Store) -> None:
    first, _ = register_pc(center, 1)
    second, _ = register_pc(center, 2)
    upload(center, bot=INVOICE_BOT, path=INVOICE, where="pc", expression="0 9 1 * *")
    for pc in (first, second):
        deploy(center, store, bot=INVOICE_BOT, target={"type": "bot_ui", "id": pc}, at=seoul(2026, 10, 20, 9))
    made = sweep(store, seoul(2026, 11, 1, 9, 0, 10))
    assert sorted(job(center, one)["target"]["id"] for one in made) == sorted([first, second])


def test_a_claimed_turn_without_a_job_is_finished_with_the_same_key(
    center: TestClient, store: Store, training: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """잡은 뒤 작업을 만들기 전에 죽었다 — 다음 쓸기가 **같은 멱등 키로** 마저 만든다 (ADR-0110 §6)."""
    real = jobs_api.create

    def dies(*_: Any, **__: Any) -> Any:
        raise KeyboardInterrupt  # 죽었다

    monkeypatch.setattr(jobs_api, "create", dies)
    with pytest.raises(KeyboardInterrupt):
        sweep(store, seoul(2026, 10, 28, 10, 1))
    assert fires(store)[0]["job_id"] is None
    monkeypatch.setattr(jobs_api, "create", real)

    made = sweep(store, seoul(2026, 10, 28, 10, 2))
    assert len(made) == 1
    assert fires(store)[0]["job_id"] == made[0]
    assert sweep(store, seoul(2026, 10, 28, 10, 3)) == []
    assert len(center.get("/api/v1/jobs", headers=ADMIN).json()) == 1


def test_a_refused_job_is_written_on_the_turn(
    center: TestClient, store: Store, training: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuses(*_: Any, **__: Any) -> Any:
        raise ApiError(422, "input_not_from_caller", "안 된다")

    monkeypatch.setattr(jobs_api, "create", refuses)
    assert sweep(store, seoul(2026, 10, 28, 10, 1)) == []
    assert fires(store)[0]["error"] == "input_not_from_caller"
    # 그 차례는 끝났다 — 다음 쓸기가 같은 것을 다시 부르지 않는다.
    assert sweep(store, seoul(2026, 10, 28, 10, 2)) == []


def test_the_sweep_runs_once_a_minute(store: Store, center: TestClient, training: str) -> None:
    now = seoul(2026, 10, 28, 10, 0, 10)
    assert len(timers.sweep(store, tz=SEOUL, now=now)) == 1
    with store.tx() as cur:
        cur.execute("DELETE FROM timer_fires")
    assert timers.sweep(store, tz=SEOUL, now=now + timedelta(seconds=20)) == []  # 같은 분 — 쓸지 않는다
    assert len(timers.sweep(store, tz=SEOUL, now=now + timedelta(seconds=70))) == 1


def test_the_heartbeat_sweeps_and_hands_the_job_down(center: TestClient, store: Store) -> None:
    """하트비트가 쓸고 **그 하트비트로** 작업이 내려간다 — 작업 지시 없이 (ADR-0110)."""
    runner_id, key = register_runner(center)
    upload(center, bot=TRAINING_BOT, path=TRAINING, where="server", expression="* * * * *")
    deploy(center, store, bot=TRAINING_BOT, target={"type": "server_runner", "id": runner_id},
           at=datetime.now(UTC) - timedelta(days=1))
    beat = center.post(
        "/api/v1/server-runner/heartbeat",
        json={"schema": 1, "status": "running", "capacity": {"max": 3, "running": 0}, "running": [], "waiting": []},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert beat.status_code == 200, beat.text
    sent = beat.json()["jobs"]
    assert [one["bpm_process_id"] for one in sent] == [TRAINING_BOT]
    assert sent[0]["requested_by"] == "timer:* * * * *"


def test_a_timezone_center_cannot_read_stops_it(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="TIMEZONE"):
        create_app(CenterSettings(timezone="Mars/Olympus", package_dir=tmp_path), store=Store(Path(":memory:")))


def test_the_console_reads_the_schedule(center: TestClient, store: Store, training: str) -> None:
    """CON-02 「일정」 — 다음 차례는 **쓸 때와 같은 함수**로 센다 (C5 §일정)."""
    made = sweep(store, seoul(2026, 10, 28, 10, 1))
    found = timers.schedules(store, tz=SEOUL, now=seoul(2026, 10, 30, 12))
    (one,) = found
    assert one.bpm_process_id == TRAINING_BOT and one.target_type == "server_runner" and one.target_id is None
    assert one.expression == "0 10 * * 3" and one.timezone == "Asia/Seoul" and one.problem is None
    assert datetime.fromisoformat(str(one.next_at)) == seoul(2026, 11, 4, 10)
    assert datetime.fromisoformat(str(one.last_slot)) == seoul(2026, 10, 28, 10)
    assert one.last_job_id == made[0] and one.last_missed == 0 and one.last_error is None
    listed = center.get("/api/v1/schedules", headers=ADMIN)
    assert listed.status_code == 200 and [row["bpm_process_id"] for row in listed.json()] == [TRAINING_BOT]


def test_an_unreadable_schedule_is_shown_not_fired(center: TestClient, store: Store, training: str) -> None:
    """R13 전에 올라간 판 — 쏘지 않고 까닭을 보인다."""
    with store.tx() as cur:
        row = store.row("SELECT manifest_json FROM packages WHERE id = ?", (TRAINING_BOT,))
        assert row is not None
        body = json.loads(str(row["manifest_json"]))
        body["triggers"] = [{"kind": "timer", "expression": "매주 수요일"}]
        cur.execute("UPDATE packages SET manifest_json = ? WHERE id = ?", (json.dumps(body), TRAINING_BOT))
    assert sweep(store, seoul(2026, 10, 28, 10, 1)) == []
    (one,) = timers.schedules(store, tz=SEOUL, now=seoul(2026, 10, 28, 12))
    assert one.problem and one.next_at is None


def test_only_the_console_reads_the_schedule(center: TestClient, training: str) -> None:
    _, key = register_runner(center, 3)
    assert center.get("/api/v1/schedules", headers={"Authorization": f"Bearer {key}"}).status_code == 403
