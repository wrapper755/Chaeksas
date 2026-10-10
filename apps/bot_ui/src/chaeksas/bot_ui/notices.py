"""BUI-05 알림 — 트레이가 띄울 거리를 모으는 자리.

**알릴 거리를 아는 쪽(Agent)과 띄우는 쪽(트레이)을 가른다.** 이 모듈은 Qt를 모른다 — 그래서
화면 없이 시험할 수 있고, 트레이가 없는 환경에서도 같은 판단이 돈다 (U15).

- Agent가 **그 일이 일어난 자리에서** `Notices`에 넣고(배포를 적용한 자리, 실행이 끝난 자리…),
  화면이 주기마다 `take()`로 **거둬 간다**. 하트비트 사이에 생긴 것도 쌓여 있다가 함께 나간다.
- **같은 알림을 두 번 띄우지 않는다** — 아직 거둬 가지 않은 것과 같으면 넣지 않고, 「바뀌었나」로
  내는 알림(연결·런타임)은 **지난 값**을 들고 있다가 바뀔 때만 낸다.
- **쌓이기만 하지는 않는다** — 창을 오래 닫아 둔 PC에서 알림이 수백 개가 되면 거둬 갈 때 다
  띄우게 된다. 상한을 넘으면 **오래된 것부터 버린다** (방금 일이 더 급하다).
- 「사람이 볼 때까지」는 `sticky`다. 밀리초는 **참고값**이다 — Windows는 표시 시간을 제 설정대로
  쓴다. 그래서 급한 알림은 **알림 센터에 남는 것**으로 지킨다 (운영자가 나중에 본다).
- 문구는 `06-screens/bot-ui.md`의 BUI-05 표가 원본이다. **런타임 이름은 확장이 준 `label`**을
  쓴다 — 플랫폼 코드에 「Worker」라고 적으면 Bot UI가 어느 확장인지 아는 셈이다 (ADR-0018).

아직 알릴 수 없는 두 줄은 `docs/09-gaps.md` §4-8에 **왜**와 함께 남겼다 (Center API 키 만료
임박, 서비스 앱 키 만료 임박·거부) — 둘 다 **이 PC가 그 값을 모른다**.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from chaeksas.bot_ui.runner import Request

#: 누르면 할 일. 화면이 이 글로 창을 고른다 (여기서 Qt를 부르지 않는다).
ACTION_APPROVAL = "approval"
ACTION_SETTINGS = "settings"
ACTION_KEYS = "keys"
ACTION_WINDOW = "window"

#: 알림 종류 — 시험과 화면이 고르는 열쇠다 (문구로 고르지 않는다).
APPROVAL_NEEDED = "approval_needed"
APPROVAL_AT_CENTER = "approval_at_center"
CONFIRMATION_NEEDED = "confirmation_needed"
RUN_FAILED = "run_failed"
DEPLOYED = "deployed"
DEPLOY_REFUSED = "deploy_refused"
DEPLOYED_NEEDS_KEY = "deployed_needs_key"
CENTER_OFFLINE = "center_offline"
CENTER_BACK = "center_back"
KEY_REJECTED = "key_rejected"
RUNTIME_RESTARTED = "runtime_restarted"
RUNTIME_GAVE_UP = "runtime_gave_up"
QUEUED = "queued"
QUEUE_FULL = "queue_full"
QUEUE_EXPIRED = "queue_expired"

#: 보통 알림은 5초, 지나가도 괜찮지만 읽을 거리가 있는 것은 8초 (BUI-05 표).
SHORT_S = 5
LONG_S = 8

#: 쌓아 둘 상한 — 넘으면 오래된 것부터 버린다.
MAX_PENDING = 20


@dataclass(frozen=True)
class Notice:
    """띄울 알림 하나."""

    kind: str
    text: str
    #: 누르면 할 일 (`ACTION_*`). 비어 있으면 누를 거리가 없다.
    action: str = ""
    #: 「사람이 볼 때까지」 — 지나가게 두지 않는다 (BUI-05).
    sticky: bool = False
    seconds: int = SHORT_S
    #: 경고·오류로 보일 것 (트레이 아이콘). 보통은 알림이다.
    level: str = "info"


def _bot(name: str) -> str:
    """Bot 이름이 비면 그렇게 쓴다 — **모르는 것을 지어내지 않는다**."""
    return name or "Bot"


@dataclass
class Notices:
    """아직 띄우지 않은 알림과, 「바뀌었나」를 보려고 들고 있는 지난 값."""

    pending: list[Notice] = field(default_factory=list)
    limit: int = MAX_PENDING
    #: 이미 알린 결재·확인 요청 id (같은 요청에 두 번 알리지 않는다).
    _told: set[str] = field(default_factory=set)
    #: 지난 주기에 Center에 닿았나 — `None`은 아직 한 번도 돌지 않았다는 뜻이다.
    _online: bool | None = None
    #: 런타임마다 지난 `(상태, 연속 실패 수)`.
    _runtimes: dict[str, tuple[str, int]] = field(default_factory=dict)

    # ── 넣기·거두기 ──

    def add(self, notice: Notice) -> None:
        """하나 넣는다. **아직 거둬 가지 않은 것과 같으면 넣지 않는다.**"""
        if any(one.kind == notice.kind and one.text == notice.text for one in self.pending):
            return
        self.pending.append(notice)
        if len(self.pending) > self.limit:
            del self.pending[: len(self.pending) - self.limit]

    def take(self) -> list[Notice]:
        """쌓인 것을 거둬 간다 (화면이 부른다). 거둬 가면 비워진다."""
        found = list(self.pending)
        self.pending.clear()
        return found

    # ── 결재·확인 (C6, ADR-0038) ──

    def requests(self, pendings: Sequence[Request], *, bot: str) -> None:
        """답을 기다리는 요청마다 한 번 (C3 `human_requested`를 읽어 둔 것).

        **Center로 올라간 결재는 여기서 알리지 않는다** — 올리는 데 성공했을 때
        `sent_to_center()`가 알린다. 여기서 알리면 올리기 전에 「올라갔습니다」가 뜬다.
        """
        here = {one.request_id for one in pendings}
        for one in pendings:
            if not one.request_id or one.request_id in self._told or one.where == "center":
                continue
            self._told.add(one.request_id)
            if one.is_confirmation:
                self.add(
                    Notice(
                        kind=CONFIRMATION_NEEDED,
                        text=f"{_bot(bot)}: 실행 확인이 필요합니다 — {one.node_id or '태스크'}",
                        action=ACTION_APPROVAL,
                        sticky=True,
                    )
                )
            else:
                self.add(
                    Notice(
                        kind=APPROVAL_NEEDED,
                        text=f"{_bot(bot)}: 결재가 필요합니다",
                        action=ACTION_APPROVAL,
                        sticky=True,
                    )
                )
        # 끝난 요청은 잊는다 — 집합이 실행마다 자라지 않게 (id는 다시 쓰이지 않는다).
        self._told &= here

    def sent_to_center(self, *, bot: str) -> None:
        """결재를 Center 결재함으로 올렸다 (ADR-0038). **현장에서도 답할 수 있다**고 말한다."""
        self.add(
            Notice(
                kind=APPROVAL_AT_CENTER,
                text=f"{_bot(bot)}: 결재가 Center 결재함으로 올라갔습니다 — 여기서 답하려면 누르세요",
                action=ACTION_APPROVAL,
                seconds=LONG_S,
            )
        )

    # ── 실행 ──

    def run_failed(self, *, bot: str, why: str) -> None:
        self.add(
            Notice(
                kind=RUN_FAILED,
                text=f"{_bot(bot)} 실패 — {why or '사유를 기록에서 보세요'}",
                action=ACTION_WINDOW,
                seconds=LONG_S,
                level="error",
            )
        )

    # ── 배포 (C2·C4) ──

    def deployed(self, *, bot: str, version: str, missing_keys: Iterable[str] = ()) -> None:
        """설치했다. **키가 빠져 있으면 그것을 말한다** — 설치됐지만 돌지 않는다 (BUI-10으로)."""
        refs = ", ".join(missing_keys)
        if refs:
            self.add(
                Notice(
                    kind=DEPLOYED_NEEDS_KEY,
                    text=f"{_bot(bot)} 설치됨 — 서비스 앱 키 {refs}를 등록해야 실행할 수 있습니다",
                    action=ACTION_KEYS,
                    sticky=True,
                    level="warning",
                )
            )
            return
        self.add(Notice(kind=DEPLOYED, text=f"{_bot(bot)} {version}을 설치했습니다"))

    def deploy_refused(self, *, why: str) -> None:
        """설치하지 않았다 (C2 V1~V7). **사유가 운영자의 일거리다** — 지나가게 두지 않는다."""
        self.add(
            Notice(
                kind=DEPLOY_REFUSED,
                text=f"배포를 거부했습니다 — {why}",
                action=ACTION_WINDOW,
                sticky=True,
                level="warning",
            )
        )

    # ── Center 연결 (ADR-0007) ──

    def connection(self, *, online: bool, shipped: int = 0) -> None:
        """닿았나가 **바뀔 때만** 낸다 — 꺼진 Center 앞에서 주기마다 알리지 않는다.

        **첫 바퀴는 한쪽만 알린다** — 켜자마자 닿지 못하면 그것은 소식이지만(기록이 쌓인다),
        잘 닿은 것은 「복구」가 아니다 (평소다).
        """
        if self._online is None:
            self._online = online
            if online:
                return
        elif self._online == online:
            return
        self._online = online
        if not online:
            self.add(
                Notice(
                    kind=CENTER_OFFLINE,
                    text="Center에 닿지 못합니다 — 기록은 쌓아 두었다가 보냅니다",
                    level="warning",
                )
            )
            return
        more = f" — 기록 {shipped}건 보냄" if shipped else ""
        self.add(Notice(kind=CENTER_BACK, text=f"Center 연결 복구{more}"))

    def key_rejected(self) -> None:
        """Center가 키를 거부했다 (C4 403). 사람이 설정에서 새 키를 넣어야 한다.

        **사유(폐기·만료·키 종류)는 글에 넣지 않는다** — 어느 쪽이든 할 일이 같고, 사유는
        트레이 상태와 BUI-02 상태 줄에 이미 있다.
        """
        self.add(
            Notice(
                kind=KEY_REJECTED,
                text="Center가 이 PC의 키를 거부했습니다 — 설정에서 새 키를 넣으세요",
                action=ACTION_SETTINGS,
                sticky=True,
                level="error",
            )
        )

    # ── 로컬 런타임 (C13 — 이름은 확장이 준다) ──

    def runtime(self, runtime_id: str, *, label: str, state: str, restarts: int, why: str = "") -> None:
        """런타임 상태가 **바뀔 때만** 낸다 (`restarting` → 다시 띄웠다, `stopped` → 그만뒀다)."""
        now = (state, restarts)
        before = self._runtimes.get(runtime_id)
        self._runtimes[runtime_id] = now
        if before is None or before == now:
            return
        if state == "stopped":
            self.add(
                Notice(
                    kind=RUNTIME_GAVE_UP,
                    text=(
                        f"{label}를 띄울 수 없습니다 — {why or '사유를 모릅니다'}. "
                        "UI 태스크가 있는 Bot은 실행되지 않습니다"
                    ),
                    action=ACTION_WINDOW,
                    sticky=True,
                    level="error",
                )
            )
            return
        if state == "restarting" or (state == "running" and restarts > before[1]):
            self.add(Notice(kind=RUNTIME_RESTARTED, text=f"{label}가 멈춰 다시 띄웠습니다", level="warning"))

    # ── 대기열 (ADR-0014) ──

    def queued(self, *, bot: str, position: int, running: str) -> None:
        """수동 실행이 기다리게 됐다 — **무엇 때문에 기다리나**까지 말한다."""
        self.add(
            Notice(
                kind=QUEUED,
                text=f"{_bot(bot)}: 대기열 {position}번째"
                + (f" — 실행 중 {running}" if running else ""),
                action=ACTION_WINDOW,
            )
        )

    def queue_full(self, *, bot: str, limit: int) -> None:
        self.add(
            Notice(
                kind=QUEUE_FULL,
                text=f"대기열이 가득 찼습니다 ({limit}건) — {_bot(bot)} 요청을 받지 않았습니다",
                action=ACTION_WINDOW,
                seconds=LONG_S,
                level="warning",
            )
        )

    def queue_expired(self, *, bot: str) -> None:
        """기다리는 동안 작업의 유효 시간이 지났다 (C4 `expired`)."""
        self.add(
            Notice(
                kind=QUEUE_EXPIRED,
                text=f"{_bot(bot)} 작업이 기다리는 동안 만료되었습니다",
                seconds=LONG_S,
                level="warning",
            )
        )


__all__ = [
    "ACTION_APPROVAL",
    "ACTION_KEYS",
    "ACTION_SETTINGS",
    "ACTION_WINDOW",
    "APPROVAL_AT_CENTER",
    "APPROVAL_NEEDED",
    "CENTER_BACK",
    "CENTER_OFFLINE",
    "CONFIRMATION_NEEDED",
    "DEPLOYED",
    "DEPLOYED_NEEDS_KEY",
    "DEPLOY_REFUSED",
    "KEY_REJECTED",
    "LONG_S",
    "MAX_PENDING",
    "QUEUED",
    "QUEUE_EXPIRED",
    "QUEUE_FULL",
    "RUNTIME_GAVE_UP",
    "RUNTIME_RESTARTED",
    "RUN_FAILED",
    "SHORT_S",
    "Notice",
    "Notices",
]
