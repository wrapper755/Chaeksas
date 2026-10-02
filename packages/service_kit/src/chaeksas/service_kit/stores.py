"""키·멱등·사용 기록 저장소 — 인터페이스와 메모리 구현.

앱마다 실제 저장소(SQLite 등)를 끼울 수 있게 프로토콜로 두고, 뼈대·시험용으로 메모리
구현을 함께 준다. 멱등 저장소가 C11의 「같은 멱등 키로 다시 오면 수행하지 않는다」를 담당한다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from chaeksas.contracts.service_app import OpRequest, OpResponse, ServiceAppKey, UsageRecord

BeginOutcome = Literal["new", "replay", "in_progress", "conflict"]


def body_hash(req: OpRequest) -> str:
    """멱등 충돌 판정용 본문 해시 — C11은 `input`·`mode`를 본다.

    C2의 `canonical_json`을 쓰지 않는다. 그쪽은 **서명 대상이라 실수를 금지**하는데,
    작업 입력에는 금액 같은 실수가 들어올 수 있다. 여기서는 서명이 아니라 같고 다름만 본다.
    """
    import hashlib

    payload = json.dumps(
        {"mode": req.mode, "input": req.input},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class KeyStore(Protocol):
    """키 저장소. 폐기·만료된 키도 돌려준다 (401과 403을 구분하려고)."""

    def all_keys(self) -> Iterator[ServiceAppKey]: ...

    def touch(self, key: ServiceAppKey, *, at: str) -> None:
        """`last_used_at` 갱신."""


class IdempotencyStore(Protocol):
    """멱등 저장소."""

    def begin(self, key: tuple[Any, ...], *, body: str) -> tuple[BeginOutcome, OpResponse | None]: ...

    def finish(self, key: tuple[Any, ...], *, response: OpResponse) -> None: ...

    def abandon(self, key: tuple[Any, ...]) -> None:
        """작업이 실패했을 때 자리를 비운다 (같은 `attempt`로 다시 부를 수 있게)."""


class UsageLog(Protocol):
    """사용 기록 (SVC-03). **입력·출력 값은 기록하지 않는다.**"""

    def record(self, entry: UsageRecord) -> None: ...


@dataclass
class InMemoryKeyStore:
    keys: list[ServiceAppKey] = field(default_factory=list)

    def all_keys(self) -> Iterator[ServiceAppKey]:
        return iter(list(self.keys))

    def touch(self, key: ServiceAppKey, *, at: str) -> None:
        key.last_used_at = at

    def add(self, key: ServiceAppKey) -> None:
        self.keys.append(key)


@dataclass
class _Entry:
    body: str
    response: OpResponse | None = None  # None이면 아직 수행 중


@dataclass
class InMemoryIdempotencyStore:
    entries: dict[tuple[Any, ...], _Entry] = field(default_factory=dict)

    def begin(self, key: tuple[Any, ...], *, body: str) -> tuple[BeginOutcome, OpResponse | None]:
        entry = self.entries.get(key)
        if entry is None:
            self.entries[key] = _Entry(body=body)
            return "new", None
        if entry.body != body:
            return "conflict", None
        if entry.response is None:
            return "in_progress", None
        return "replay", entry.response

    def finish(self, key: tuple[Any, ...], *, response: OpResponse) -> None:
        self.entries[key].response = response

    def abandon(self, key: tuple[Any, ...]) -> None:
        self.entries.pop(key, None)


@dataclass
class InMemoryUsageLog:
    entries: list[UsageRecord] = field(default_factory=list)

    def record(self, entry: UsageRecord) -> None:
        self.entries.append(entry)
