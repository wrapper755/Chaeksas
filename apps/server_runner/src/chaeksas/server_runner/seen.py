"""이미 받은 지시의 **마지막 ack**를 들고 있는 자리 — 그리고 **언제 잊는가** (C4 멱등·C12).

Center는 ack가 올 때까지 같은 지시를 하트비트마다 다시 싣는다 (C4·ADR-0007). 그래서 받는
쪽은 「이미 봤다」를 기억해 **두 번 돌리지 않고 마지막 ack를 되돌려 보내야** 한다. 그 기억이
무한히 자라면 몇 주 떠 있는 실행기가 끝없이 커진다 — 특히 **메시지**는 바깥 시스템이 밀어
넣는 것이라 수가 크다 (C12 §메시지 — BX-11 입찰 견적·BX-13 반품 이벤트).

**잊는 규칙은 하나다** (ADR-0056):

1. ack가 **Center에 닿은 뒤** `GRACE_CYCLES` 주기가 더 지나면 버린다. 닿은 ack는 Center가
   그 자리에서 반영했으므로(`_apply_acks`) 그 지시는 다시 내려오지 않는다.
2. **닿지 않은 ack는 버리지 않는다** — 그것이 이 자리가 있는 까닭이다. 버리면 다시 내려온
   지시를 「처음 본 것」으로 다루어 **업무가 두 번 일어난다**(메시지를 실행에 두 번 넣거나
   같은 작업으로 실행을 둘 만든다).
3. `CAP`을 넘으면 **닿은 것 중 오래된 것부터** 먼저 버린다 (그물 — 규칙 1이 먼저 일한다).

**작업과 메시지가 같은 것을 쓴다** — 둘이 같은 까닭으로 있으므로 규칙을 갈라 두면 한쪽만
고치는 일이 생긴다. 키는 그냥 글자(`job_id`·`message_id`)라서 이 자리는 **무엇의 ack인지
모른다**.

**닿았다를 아는 때는 하나다** — 하트비트가 성공해 응답이 돌아온 그때다 (`Agent._apply`).
보낼 때 잊으면 끊긴 하트비트의 ack를 닿은 것으로 쳐서 규칙 2가 깨진다.
"""

from __future__ import annotations

from collections.abc import Iterable, ValuesView
from dataclasses import dataclass, field

#: ack가 Center에 닿은 뒤 **몇 주기를 더** 들고 있나. 기본 10초 주기로 20초다 (C12).
#: 닿은 그 주기에 버려도 규칙상 맞지만, 그물을 한 겹 둔다 (하트비트는 한 번 어긋날 수 있다).
GRACE_CYCLES = 2

#: 들고 있을 항목 수 상한 (그물). Bot UI의 `SEEN_JOBS_MAX`와 **같은 수**다 — 같은 까닭으로
#: 있는 자리라 숫자가 갈라지면 「서버는 되는데 PC는 안 된다」가 된다.
CAP = 2000


@dataclass
class Seen[A]:
    """키 → 마지막 ack. **무한히 자라지 않고, 닿지 않은 ack는 잃지 않는다.**"""

    #: 닿은 뒤 더 들고 있을 주기 수.
    grace: int = GRACE_CYCLES
    #: 항목 수 상한.
    cap: int = CAP
    _acks: dict[str, A] = field(default_factory=dict)
    #: 닿은 뒤 지난 주기. **키가 없으면 「아직 닿지 않았다」**다 (0과 다르다).
    _since: dict[str, int] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self._acks)

    def __contains__(self, key: object) -> bool:
        return key in self._acks

    def get(self, key: str) -> A | None:
        """이미 본 것인가 — 봤으면 **마지막 ack**를 준다 (그것을 되돌려 보낸다)."""
        return self._acks.get(key)

    def values(self) -> ValuesView[A]:
        return self._acks.values()

    def remember(self, key: str, ack: A) -> None:
        """마지막 ack를 적는다. **새 ack는 다시 「아직 닿지 않았다」**가 된다.

        한 지시의 ack는 바뀐다 (작업은 `started` → `finished`) — 바뀐 ack도 Center에 닿아야
        하므로 나이를 처음으로 되돌린다. 안 그러면 `started`가 닿은 지 오래된 작업이 끝나는
        순간 잊혀 `finished`를 되돌려 줄 수 없다.
        """
        self._acks[key] = ack
        self._since.pop(key, None)

    def delivered(self, keys: Iterable[str]) -> None:
        """하트비트 하나가 **성공했다** — `keys`의 ack는 Center에 닿았다.

        **한 번 부르는 것이 한 주기다** — 닿은 것의 나이를 올리고 때가 된 것을 버린다.
        둘을 따로 부르게 두면 한쪽만 부르는 자리가 생긴다 (나이만 올리거나, 영원히 안 버린다).
        """
        for key in self._since:
            self._since[key] += 1
        for key in keys:
            if key in self._acks:
                self._since[key] = 0
        self._forget_delivered()
        self._trim()

    def _forget_delivered(self) -> None:
        for key in [key for key, age in self._since.items() if age >= self.grace]:
            del self._acks[key]
            del self._since[key]

    def _trim(self) -> None:
        """상한을 넘으면 **닿은 것 중 오래된 것부터** 버린다.

        닿지 않은 것은 **세기만 하고 버리지 않는다** (규칙 2) — 그래서 상한을 넘은 채로
        남을 수 있다. 그 수는 「마지막으로 성공한 하트비트 뒤에 내려온 지시 수」라서 저절로
        묶여 있다 (지시는 하트비트 응답에만 실려 온다 — ADR-0007).
        """
        extra = len(self._acks) - self.cap
        if extra <= 0:
            return
        for key in list(self._acks):  # dict는 넣은 순서를 지킨다 — 오래된 것이 앞이다
            if extra <= 0:
                return
            if key not in self._since:
                continue  # 아직 닿지 않았다 — 버리면 업무가 두 번 일어난다
            del self._acks[key]
            del self._since[key]
            extra -= 1


__all__ = ["CAP", "GRACE_CYCLES", "Seen"]
