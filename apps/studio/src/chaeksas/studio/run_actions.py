"""실행 메뉴의 시험 실행 몰이 (STU-08·STU-09).

**셋을 가른다** — 이 모듈은 가운데다.

| 어디 | 무엇 |
| --- | --- |
| `run_dialog.py` | STU-08 창 — **무엇을 돌릴까**를 사람에게 묻는다 (`Plan`을 만든다) |
| 이 모듈 | 관문 → 계획 → **차례로 몰기** → 결과 요약 (창의 상태 줄·탭을 움직인다) |
| `runner.py` | `CaseRun` — 엔진을 `QTimer`로 한 걸음씩 민다 (스레드를 만들지 않는다) |

메인 창에서 떼어 낸 글루라 창을 받아 쓴다 (`main_window.py`가 500줄 선을 넘어 가른 자리다,
CLAUDE.md §4). **돌고 있는 것은 창이 쥔다** (`window.running`·`window.queue`) — 한 PC에서
시험 실행도 하나이고, 창이 닫힐 때 그것을 멈춰야 한다.

관문의 순서가 STU-08 그대로다: **적용 안 한 편집 → 저장 → 그림 검사·사전 점검 → 창 →
바깥 앱 한 벌 → 시작**. 검사가 막으면 창을 띄우지 않는다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox

from chaeksas.studio import services
from chaeksas.studio.preflight import inspect
from chaeksas.studio.run_dialog import RunDialog
from chaeksas.studio.runner import CaseRun, Outcome
from chaeksas.studio.runner import summarize as summarize_runs
from chaeksas.studio.ui_sessions import row_of

if TYPE_CHECKING:  # pragma: no cover - 순환 import를 피한다 (창이 이 모듈을 부른다)
    from chaeksas.studio.main_window import MainWindow

NO_DEFINITION = "열린 정의가 없습니다."
ALREADY = "이미 실행 중입니다."
UNREADABLE = "정의를 읽지 못했습니다."


def run_test(window: MainWindow, *, mode: str | None = None) -> None:
    """STU-08 「실행...」 (F5). 관문을 다 지나야 창이 뜨고, 창이 고른 계획을 차례로 몬다.

    `mode`는 **창에서 미리 골라 둘 수행 모드**다 — 「결정 수행 (재생)...」(Ctrl+F5)이 그것으로
    들어온다. **고르는 자리는 그대로 STU-08이다**: 할 수 없으면 창이 그 모드를 끄고 까닭을
    보이므로(U3) 메뉴가 「되는지」를 미리 판단하지 않는다.
    """
    process, definition = window.process, window.definition
    if process is None or definition is None:
        window.say(NO_DEFINITION)
        return
    if window.running is not None:
        window.say(ALREADY)
        return
    # STU-08 실행 순서: 적용 안 한 편집 확인 → 저장 → 사전 점검 → 시작.
    if not window.saved_to_disk():
        return
    found = next((d for d in process.definitions if d.path == definition), None)
    if found is None or found.process is None:
        window.say(UNREADABLE)
        return

    # 그림 검사(B1~B15)와 **사전 점검**(이 PC에서 돌 수 있나)이 같은 관문이다.
    violations = inspect(
        found.process,
        process,
        task_type_locations=window.task_type_locations(),
        # **PC 위임이 받을 값**은 그 Bot의 매니페스트가 아는 것이라 Center에서 받아 둔 것을
        # 쓴다 (C1 → B14, ADR-0062). 못 받았으면 그 대조만 건너뛴다.
        delegated_outputs=window.delegated_outputs(),
        keyless_apps=window.keyless_apps(),
    ) + window.readiness()
    blocking = [v for v in violations if v.blocks]
    if blocking:
        window.show_preflight(found.process, violations)
        QMessageBox.warning(window, window.windowTitle(), f"실행 전 검사가 막습니다 ({len(blocking)}개).")
        return

    plans = RunDialog.ask(window, process, found, window.settings, prefer=mode)
    if not plans:
        return

    # 확장 태스크·데스크톱 AI 태스크가 이 PC Bot UI의 Worker를 쓴다 (STU-10 「Worker」).
    tasks = window.extensions.tasks()
    # 바깥 앱 한 벌 — **실행마다 한 번** 받는다 (케이스마다 Center를 두드리지 않게).
    # 받지 못한 것은 로그에 적고 그 앱을 부르는 순간 분명히 실패한다 (C7·C13 「전송」).
    # 키는 **그 앱의 개발 키**다 — 없으면 Center에 청한다 (ADR-0094 §5).
    keys = window.dev_keys()
    apps = services.from_settings(window.settings, secrets=keys.resolver(window.key_apps()))
    directory = apps.directory()
    for why in apps.problems:
        window.say(f"바깥 앱: {why}")
    for app_id, why in sorted(keys.problems.items()):
        window.say(f"{app_id}의 개발 키를 받지 못했습니다: {why}")
    for plan in plans:
        plan.extensions = tasks
        plan.apps = directory

    window.receiver.start()
    window.queue = plans
    window.outcomes = []
    window.log_view.clear()
    # 「UI 태스크」 탭도 여기서 한 번만 비운다 — **케이스마다 비우지 않는다**. 「모든 케이스
    # 차례로」에서 3번째 케이스의 전환을 보려는데 마지막 케이스가 표를 덮으면 안 된다
    # (어느 케이스의 줄인지는 「케이스」 열이 말한다).
    window.reset_ui_sessions()
    window.variables_running(True)
    window.canvas.mark({})
    next_run(window)


def next_run(window: MainWindow) -> None:
    """대기열에서 하나를 꺼내 돌린다. 비면 끝낸다."""
    if not window.queue:
        all_done(window)
        return
    plan = window.queue.pop(0)
    running = CaseRun(plan, window.receiver, window)
    window.running = running
    running.said.connect(window.say)
    running.marked.connect(window.canvas.mark)
    # 지금 값은 「변수」 탭의 정의 표에 열로 붙는다 (STU-01 「변수」 탭).
    running.varied.connect(window.show_variables)
    # 케이스 이름은 C3 `ui_session`에 없다 — 여기서 넣는다 (STU-09 「UI 태스크」의 「케이스」 열).
    case_name = plan.case.name if plan.case else ""
    running.ui_session.connect(lambda event: window.show_ui_session(row_of(event, case=case_name)))
    running.ended.connect(lambda outcome: one_done(window, outcome))
    window.run_action.setEnabled(False)
    window.replay_action.setEnabled(False)
    window.stop_action.setEnabled(True)
    window.show_running(plan.mode)
    window.statusBar().showMessage(f"실행 중: {plan.case.name if plan.case else '(케이스 없음)'}")
    running.start()


def one_done(window: MainWindow, outcome: Outcome) -> None:
    window.running = None
    window.outcomes.append(outcome)
    name = f"[{outcome.case}] " if outcome.case else ""
    window.say(f"{name}{outcome.detail}")
    next_run(window)


def all_done(window: MainWindow) -> None:
    """다 돌았다. **여럿이면 묶어 한 줄** 더 말한다 (STU-09 「모든 케이스 차례로」)."""
    window.run_action.setEnabled(True)
    window.replay_action.setEnabled(True)
    window.stop_action.setEnabled(False)
    window.show_running(None)
    window.variables_running(False)
    if len(window.outcomes) > 1:
        window.say(summarize_runs(window.outcomes))
    last = window.outcomes[-1] if window.outcomes else None
    window.statusBar().showMessage(last.detail if last else "대기 중")
    if last is not None and last.run is not None and last.verdict in ("통과", "비교 안 함"):
        window.show_variables_tab()


def stop_test(window: MainWindow) -> None:
    """「실행 중지」. **대기열을 먼저 비운다** — 멈춘 뒤에 다음 케이스가 시작되지 않게."""
    window.queue = []
    if window.running is not None:
        window.running.stop()


__all__ = [
    "ALREADY",
    "NO_DEFINITION",
    "UNREADABLE",
    "all_done",
    "next_run",
    "one_done",
    "run_test",
    "stop_test",
]
