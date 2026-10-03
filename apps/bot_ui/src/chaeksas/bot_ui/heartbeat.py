"""하트비트를 **배경 스레드**에서 돌린다 (BUI 설계서 「스레딩 규칙」).

Qt 슬롯에서 동기 I/O를 하지 않는다 — 하트비트는 네트워크를 기다리므로 화면이 멈춘다.
그래서 `Agent`를 스레드 하나에 두고, 결과만 신호로 올린다. **위젯은 GUI 스레드에서만** 만진다.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from chaeksas.bot_ui.agent import Agent
from chaeksas.bot_ui.center_client import CenterProblem

log = logging.getLogger(__name__)


class HeartbeatWorker(QObject):
    """주기마다 `Agent.beat()`를 부른다. 신호만 밖으로 보낸다.

    간격은 Center가 정한다 (C4 `next_heartbeat_s`) — 응답마다 타이머를 맞춘다.
    """

    #: 한 주기가 끝났다 (성공·닿지 못함 모두). 화면은 상태를 다시 읽는다.
    beat_done = Signal()
    #: 사람이 고쳐야 하는 문제 (키 거부·다른 PC에 묶인 키). 한 줄로 보낸다.
    problem = Signal(str)

    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self._agent = agent
        self._timer: QTimer | None = None

    @Slot()
    def start(self) -> None:
        """스레드 안에서 부른다 (`QThread.started`에 이어 둔다)."""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.once)
        self._timer.start(self._agent.heartbeat_interval_s * 1000)
        self.once()

    @Slot()
    def once(self) -> None:
        """한 번. 예외를 삼키지 않고 **신호로 드러낸다** (BUI 스레딩 규칙)."""
        try:
            self._agent.beat()
        except CenterProblem as e:
            log.warning("하트비트: %s", e)
            self.problem.emit(str(e))
        except Exception as e:  # noqa: BLE001 — 배경 스레드에서 죽으면 조용히 멈춘다
            log.exception("하트비트가 예상 못 한 오류로 멈췄다")
            self.problem.emit(f"알 수 없는 오류: {e}")
        else:
            self.problem.emit("")
        finally:
            self.beat_done.emit()
            if self._timer is not None:
                # Center가 간격을 바꿀 수 있다 (부하에 따라, C4).
                wanted = max(self._agent.heartbeat_interval_s, 1) * 1000
                if self._timer.interval() != wanted:
                    self._timer.setInterval(wanted)

    @Slot()
    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None


__all__ = ["HeartbeatWorker"]
