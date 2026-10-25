"""Center가 내려 준 서비스 앱 키를 받아 둔다 (C4 §서비스 앱 키 전달, ADR-0094).

**Bot UI와 서버 실행기가 같은 코드를 쓴다** — 다른 것은 비밀 저장소(넘겨받는 두 함수)뿐이다.

- 받은 키는 **(Bot, 참조 이름)**으로 둔다 — `svc:<bpm_process_id>:<key_ref>`. 두 Bot이 같은 참조
  이름을 써도 키가 다르다. 도구용 키(`purpose: utility`)는 `util:<app_id>`다 (Tool UI가 읽는다).
- 비밀 저장소는 목록을 뽑을 수 없으니 **어느 id를 어느 이름에 두었나**만 파일에 남긴다
  (`service-keys.json` — 키 값은 없다). 지우라는 지시(`drop_service_keys`)나 회전(`replaces`)이
  오면 그것으로 찾아 지운다.
- 받았다·지웠다는 **다음 하트비트**에 ack로 간다. 보내고 나서야 잊는다(닿지 않은 ack는 버리지 않는다).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from chaeksas.contracts.enrollment import SealError, open_sealed
from chaeksas.contracts.service_keys import (
    ACK_STORE_UNAVAILABLE,
    ACK_UNSEALABLE,
    PURPOSE_UTILITY,
    ServiceKeyAck,
    ServiceKeyDelivery,
)

log = logging.getLogger(__name__)

FILE_NAME = "service-keys.json"
RUN_PREFIX = "svc:"
UTILITY_PREFIX = "util:"


def run_name(bpm_process_id: str, key_ref: str) -> str:
    """Bot이 부를 때 쓰는 키의 비밀 저장소 이름."""
    return f"{RUN_PREFIX}{bpm_process_id}:{key_ref}"


def utility_name(app_id: str) -> str:
    """도구(Tool UI)가 쓰는 키의 비밀 저장소 이름 (ADR-0094 §6)."""
    return f"{UTILITY_PREFIX}{app_id}"


def names_of(one: ServiceKeyDelivery) -> list[str]:
    if one.purpose == PURPOSE_UTILITY:
        return [utility_name(one.app_id)]
    if not one.bpm_process_id:
        return []
    return [run_name(one.bpm_process_id, ref) for ref in one.key_refs]


@dataclass
class ReceivedKeys:
    """받아 둔 키의 **자리**(id → 이름들)와 아직 보내지 못한 ack. 값은 비밀 저장소에만 있다."""

    path: Path
    placed: dict[str, list[str]] = field(default_factory=dict)
    pending: list[ServiceKeyAck] = field(default_factory=list)

    @classmethod
    def at(cls, folder: Path) -> ReceivedKeys:
        path = folder / FILE_NAME
        found = cls(path=path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return found  # 없거나 깨졌다 — 처음부터 받는다 (Center가 ack 전까지 다시 싣는다)
        found.placed = {str(k): [str(n) for n in v] for k, v in (raw.get("placed") or {}).items()}
        found.pending = [ServiceKeyAck.model_validate(one) for one in raw.get("pending") or []]
        return found

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = {"placed": self.placed, "pending": [one.to_json_dict() for one in self.pending]}
        self.path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")

    def _ack(self, ack: ServiceKeyAck) -> None:
        self.pending = [one for one in self.pending if one.service_key_id != ack.service_key_id]
        self.pending.append(ack)

    def take(
        self,
        keys: Sequence[ServiceKeyDelivery],
        drops: Sequence[str],
        *,
        secret: str | None,
        put: Callable[[str, str], None],
        delete: Callable[[str], None],
    ) -> bool:
        """하트비트 답의 키를 연다. 무엇이든 바뀌었으면 참 (사전 점검을 다시 재야 한다).

        `secret`은 이 PC의 X25519 비밀 반쪽(등록 요청 때 만든 것)이다. 없으면 열 수 없다.
        """
        changed = False
        for one in keys:
            if secret is None:
                self._ack(ServiceKeyAck(service_key_id=one.service_key_id, accepted=False, reason=ACK_UNSEALABLE))
                continue
            try:
                raw = open_sealed(secret, one.sealed_key, salt=one.service_key_id)
            except SealError as e:
                log.warning("서비스 앱 키 %s를 열지 못했다: %s", one.service_key_id, e)
                self._ack(ServiceKeyAck(service_key_id=one.service_key_id, accepted=False, reason=ACK_UNSEALABLE))
                continue
            names = names_of(one)
            try:
                for name in names:
                    put(name, raw)
            except Exception as e:  # 비밀 저장소가 없다 — Center는 계속 싣는다
                log.warning("서비스 앱 키를 비밀 저장소에 두지 못했다: %s", e)
                self._ack(
                    ServiceKeyAck(service_key_id=one.service_key_id, accepted=False, reason=ACK_STORE_UNAVAILABLE)
                )
                continue
            del raw
            self.placed[one.service_key_id] = names
            if one.replaces and one.replaces in self.placed:
                # 회전 — 같은 이름이면 이미 새 값이 들어갔다. 다른 이름만 지운다.
                for name in self.placed.pop(one.replaces):
                    if name not in names:
                        _quietly(delete, name)
            self._ack(ServiceKeyAck(service_key_id=one.service_key_id, accepted=True))
            changed = True
        for key_id in drops:
            names = self.placed.pop(key_id, [])
            # 다른 id가 같은 이름을 쥐고 있으면(회전 뒤) 지우지 않는다 — 새 키를 지우게 된다.
            still = {n for other in self.placed.values() for n in other}
            for name in names:
                if name not in still:
                    _quietly(delete, name)
            self._ack(ServiceKeyAck(service_key_id=key_id, accepted=True))
            changed = changed or bool(names)
        if keys or drops:
            self.save()
        return changed

    def sent(self, acks: Sequence[ServiceKeyAck]) -> None:
        """하트비트가 닿았다 — 그때 실어 보낸 ack는 잊는다."""
        gone = {(one.service_key_id, one.accepted) for one in acks}
        before = len(self.pending)
        self.pending = [one for one in self.pending if (one.service_key_id, one.accepted) not in gone]
        if len(self.pending) != before:
            self.save()


def _quietly(delete: Callable[[str], None], name: str) -> None:
    try:
        delete(name)
    except Exception as e:  # 없는 이름·저장소 없음 — 지울 것이 없는 것과 같다
        log.debug("비밀 저장소에서 %s를 지우지 못했다: %s", name, e)


__all__ = ["FILE_NAME", "ReceivedKeys", "names_of", "run_name", "utility_name"]
