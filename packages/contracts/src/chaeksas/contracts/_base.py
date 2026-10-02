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


class ContractModel(BaseModel):
    """모르는 필드를 보관하고, 직렬화할 때 별명을 쓰는 바탕 모델."""

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        serialize_by_alias=True,
    )

    def to_json_dict(self) -> dict[str, object]:
        """JSON으로 보낼 모양 (별명 키, `None`인 선택 필드는 뺀다)."""
        return self.model_dump(exclude_none=True)


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
