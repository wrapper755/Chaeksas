"""계약 모델의 공통 바탕 — 호환 규칙을 한 곳에 둔다 (`docs/03-contracts/README.md` 원칙 2~4).

- **받는 쪽은 관대하게.** 모르는 선택 필드는 거부하지 않고 *보관*한다 (`extra="allow"` —
  `model_dump()`에 그대로 다시 나온다). 필수 필드 누락만 거부한다.
- **보내는 쪽은 엄격하게.** 보낼 때는 모델로 만들고 검증한다.
- **더 높은 `schema`는 거부한다.** 아는 필드의 뜻이 바뀌었을 수 있다. 같거나 낮으면 받는다.
- JSON 키는 `schema`인데 pydantic `BaseModel`의 속성과 겹치므로, 파이썬 이름만
  `schema_version`으로 두고 별명(alias)으로 잇는다. 직렬화는 항상 별명으로 나간다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, ClassVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator


def _iso8601_with_tz(v: str) -> str:
    """ISO 8601이고 시간대가 붙어 있는가. 문자열 그대로 둔다 (해시·서명 대상이라 원문을 지킨다)."""
    try:
        parsed = datetime.fromisoformat(v)
    except ValueError as e:
        raise ValueError(f"ISO 8601이 아니다: {v!r}") from e
    if parsed.tzinfo is None:
        raise ValueError(f"시간대가 없다: {v!r}")
    return v


Timestamp = Annotated[str, AfterValidator(_iso8601_with_tz)]
"""ISO 8601 + 시간대. 문자열로 다룬다."""

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
"""`sha256:<hex 64>` (C2의 `content_hash` 형식)."""


def _with_required_nulls(model: BaseModel, dumped: dict[str, object]) -> dict[str, object]:
    """`exclude_none`이 지워 버린 **필수 필드의 `null`**을 되돌려 놓는다 (중첩까지).

    선택 필드의 `None`은 그대로 빠진 채 둔다 — 보내는 모양을 늘리지 않는다 (C2 서명 대상의
    `canonical_json`이 달라지면 안 된다).
    """
    for name, info in type(model).model_fields.items():
        key = info.alias or name
        value = getattr(model, name, None)
        if info.is_required() and value is None:
            dumped[key] = None
            continue
        slot = dumped.get(key)
        if isinstance(value, BaseModel) and isinstance(slot, dict):
            _with_required_nulls(value, slot)
        elif isinstance(value, list) and isinstance(slot, list):
            for item, item_slot in zip(value, slot, strict=False):
                if isinstance(item, BaseModel) and isinstance(item_slot, dict):
                    _with_required_nulls(item, item_slot)
    return dumped


class ContractModel(BaseModel):
    """모르는 필드를 보관하고, 직렬화할 때 별명을 쓰는 바탕 모델."""

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        serialize_by_alias=True,
    )

    def to_json_dict(self) -> dict[str, object]:
        """JSON으로 보낼 모양 (별명 키, `None`인 **선택** 필드는 뺀다).

        **필수 필드는 `None`이어도 싣는다.** 계약에 「필수이지만 비어 있을 수 있다」고 적은
        자리가 있다 (C4 `current_run` — 실행 자리가 비었다는 뜻을 `null`로 보낸다). 빼 버리면
        받는 쪽이 「필수 필드 누락」으로 거부한다 — Bot UI 하트비트가 실제로 422로 막혔다.
        """
        dumped = self.model_dump(exclude_none=True)
        return _with_required_nulls(self, dumped)


#: 위반의 무게. **경고는 막지 않는다** — 화면에 보이고 사람이 판단한다 (C14 검사 규칙).
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


class Violation(ContractModel):
    """검사·검증 규칙 위반 하나. 응답 `detail[]`의 한 줄이 된다.

    C1의 검사 규칙(R1~R8), C2의 검증 규칙(V1~V8), C13의 E1~E6, C14의 B1~B14가 같은 모양을 쓴다.
    """

    rule: str  # R1~R8 (C1) / V1~V8 (C2) / E1~E6 (C13) / B1~B14 (C14)
    code: str | None = None  # 계약이 정한 사유 코드 (있을 때만)
    message: str
    items: list[str] = Field(default_factory=list)  # 걸린 항목
    #: `error`(막는다) 또는 `warning`(보이고 넘어간다). 기본은 막는 쪽이다.
    severity: str = SEVERITY_ERROR

    @property
    def blocks(self) -> bool:
        return self.severity != SEVERITY_WARNING

    def __str__(self) -> str:
        tail = f" {self.items}" if self.items else ""
        mark = "" if self.blocks else " (경고)"
        return f"[{self.rule}{'/' + self.code if self.code else ''}]{mark} {self.message}{tail}"


class SchemaVersioned(ContractModel):
    """최상위 계약 모델 — `schema` 번호를 가진다.

    `SCHEMA`는 이 코드가 아는 가장 높은 번호다. 계약에 필드를 *추가*할 때는 그대로,
    필드의 뜻을 *바꾸거나 지울* 때는 올린다 (README 원칙 2).
    """

    SCHEMA: ClassVar[int] = 1

    schema_version: int = Field(alias="schema", description="이 계약의 schema 번호")

    @field_validator("schema_version")
    @classmethod
    def _schema_is_known(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"schema는 1부터다: {v}")
        if v > cls.SCHEMA:
            raise ValueError(f"모르는(더 높은) schema {v} — 이 코드가 아는 것은 {cls.SCHEMA}까지")
        return v
