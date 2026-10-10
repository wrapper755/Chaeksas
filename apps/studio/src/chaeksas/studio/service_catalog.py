"""STU-14가 고를 거리 — 서비스 앱·외부 앱과 그 작업들.

출처가 둘이고 **모양은 하나다** (`studio.services`가 Center에서 받아 온 것을 읽는다).

| 어디서 | 무엇을 읽나 |
| --- | --- |
| C11 서비스 앱 (C7 리소스 등록) | manifest의 `operations` — 이름·설명·수행 모드·`input_schema`·`output_schema` |
| 외부 확장 (C13으로 등록된 정의) | 어댑터의 `operations` — 같은 것 + `retry_on` |

**Studio는 키 값을 모른다** (ADR-0013). 여기 담는 것은 고를 이름과 작업 설명뿐이다.

입력·출력 칸은 `input_schema`·`output_schema`가 있으면 거기서 만든다 (STU-14). **없을 수도
있다** — 선택 칸이기 때문이다. 그때는 편집기가 사람이 적게 두고, 지금 그림에 적힌 것을
그대로 보인다 (없는 것을 지어내지 않는다).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from chaeksas.contracts.extension import ExtensionManifest
from chaeksas.contracts.resources import ServiceAppResource
from chaeksas.contracts.service_app import MODE_DETERMINISTIC

#: 구분 — 화면에 그대로 보인다 (STU-14 「서비스 앱」 콤보).
KIND_C11 = "서비스 앱"
KIND_EXTERNAL = "외부 앱"

#: 상태 표기가 없을 때 (C7 `status`는 `unknown`일 수 있다).
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Field_:
    """입력·출력 칸 하나 — JSON Schema에서 읽은 것."""

    name: str
    type: str = ""
    required: bool = False
    description: str = ""


@dataclass(frozen=True)
class Operation:
    """작업 하나."""

    name: str
    description: str = ""
    modes: tuple[str, ...] = ()
    inputs: tuple[Field_, ...] = ()
    outputs: tuple[Field_, ...] = ()
    timeout_s: int | None = None
    retry_on: tuple[int, ...] = ()
    server_ok: bool = True

    @property
    def deterministic_ok(self) -> bool:
        """Bot(결정 수행)에서 부를 수 있나. 아니면 STU-14가 경고한다."""
        return MODE_DETERMINISTIC in self.modes

    @property
    def has_schema(self) -> bool:
        """manifest가 입력·출력 칸을 알려 주었나 (선택 칸이다)."""
        return bool(self.inputs or self.outputs)


@dataclass(frozen=True)
class App:
    """고를 수 있는 앱 하나."""

    app_id: str
    name: str
    kind: str
    status: str = UNKNOWN
    tier: str = ""
    operations: tuple[Operation, ...] = ()
    #: 그 앱을 서버 부분으로 가진 확장 (C7) — STU-03이 기여 뿌리와 짝지을 때 쓴다.
    extension_id: str = ""
    #: 관리 콘솔 주소 (C7). 없으면 「관리 콘솔에서 보기」를 띄우지 않는다.
    console_url: str = ""

    @property
    def status_text(self) -> str:
        """「정상」·「응답 없음」 — 스타일 가이드의 말 그대로 (STU-03·14가 같이 쓴다)."""
        return _status_text(self.status)

    @property
    def label(self) -> str:
        """콤보에 보일 한 줄 — 「<앱 이름> (<구분>) — <상태>」 (STU-14)."""
        return f"{self.name} ({self.kind}) — {self.status_text}"

    @property
    def healthy(self) -> bool:
        return self.status == "ok"

    def operation(self, name: str) -> Operation | None:
        return next((one for one in self.operations if one.name == name), None)


@dataclass(frozen=True)
class Catalog:
    """고를 거리 한 벌. **고를 것이 없으면 그렇게 말한다** (빈 콤보를 두지 않는다)."""

    apps: tuple[App, ...] = ()
    #: 받지 못한 것들 (화면이 그대로 보인다).
    problems: tuple[str, ...] = ()

    def app(self, app_id: str) -> App | None:
        return next((one for one in self.apps if one.app_id == app_id), None)

    def __bool__(self) -> bool:
        return bool(self.apps)


def _status_text(status: str) -> str:
    """상태 표기 — `docs/07-style-guide.md`의 말과 같게 (「정상」·「응답 없음」)."""
    return {"ok": "정상", "degraded": "일부 이상", "unreachable": "응답 없음"}.get(status, "알 수 없음")


def _fields_of(schema: Mapping[str, Any] | None) -> tuple[Field_, ...]:
    """JSON Schema의 `properties`를 칸 목록으로. **객체 스키마만** 읽는다.

    스키마가 없거나 객체가 아니면 **빈 것**이다 — 지어내지 않는다 (사람이 적는다).
    """
    if not isinstance(schema, Mapping):
        return ()
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return ()
    raw = schema.get("required")
    needed: set[str] = set()
    if isinstance(raw, Sequence) and not isinstance(raw, str):
        needed = {str(one) for one in raw}
    out = []
    for name, body in properties.items():
        spec = body if isinstance(body, Mapping) else {}
        out.append(
            Field_(
                name=str(name),
                type=str(spec.get("type") or ""),
                required=str(name) in needed,
                description=str(spec.get("description") or ""),
            )
        )
    return tuple(out)


def _from_service_app(found: ServiceAppResource) -> App:
    operations = tuple(
        Operation(
            name=one.name,
            description=one.description or "",
            modes=tuple(one.modes),
            inputs=_fields_of(one.input_schema),
            outputs=_fields_of(one.output_schema),
            timeout_s=one.timeout_s,
            server_ok=one.server_ok,
        )
        for one in found.operations
    )
    return App(
        app_id=found.app_id,
        name=found.name or found.app_id,
        kind=KIND_C11,
        status=found.status or UNKNOWN,
        tier="",
        operations=operations,
        extension_id=found.extension_id or "",
        console_url=found.console_url or "",
    )


def _from_external(found: ExtensionManifest) -> App | None:
    """외부 확장의 어댑터 작업들 (C13 §4). 어댑터가 없으면 고를 거리가 없다."""
    adapter = found.adapter
    if adapter is None:
        return None
    operations = tuple(
        Operation(
            name=one.name,
            description=one.description or "",
            modes=tuple(one.modes),
            inputs=_fields_of(one.input_schema),
            outputs=_fields_of(one.output_schema),
            timeout_s=adapter.limits.timeout_s,
            retry_on=tuple(one.retry_on),
            server_ok=one.server_ok,
        )
        for one in adapter.operations
    )
    return App(
        app_id=found.id,
        name=found.name or found.id,
        kind=KIND_EXTERNAL,
        # 외부 앱은 C11이 아니라 `/healthz`가 없다 — Center가 상태를 모른다 (C7).
        status=UNKNOWN,
        tier=found.tier,
        operations=operations,
        # 외부 앱은 확장 그 자체다 — 관리 콘솔은 우리 것이 아니라 주소를 모른다 (C13 E1).
        extension_id=found.id,
    )


def build(
    service_apps: Iterable[ServiceAppResource] = (),
    externals: Iterable[ExtensionManifest] = (),
    *,
    problems: Iterable[str] = (),
) -> Catalog:
    """고를 거리 한 벌 — 앱 id 순이다 (콤보가 흔들리지 않게)."""
    apps = [_from_service_app(one) for one in service_apps]
    apps += [made for one in externals if (made := _from_external(one)) is not None]
    return Catalog(
        apps=tuple(sorted(apps, key=lambda one: one.app_id)), problems=tuple(problems)
    )


def from_center(reader: Any) -> Catalog:
    """Center를 읽어 한 벌 (`studio.services.CenterReader`).

    **한 가지를 못 받아도 나머지는 담는다** — 외부 정의를 못 읽었다고 서비스 앱까지 버리지 않는다.
    """
    from chaeksas.studio.services import CenterUnreachable  # noqa: PLC0415 — 순환 피함

    problems: list[str] = []
    service_apps: list[ServiceAppResource] = []
    externals: list[ExtensionManifest] = []
    if reader is None:
        return Catalog(problems=("Center 주소·Studio 키가 설정되지 않았습니다 (STU-10)",))
    try:
        service_apps = list(reader.service_apps())
    except CenterUnreachable as e:
        problems.append(f"서비스 앱 목록을 받지 못했습니다 — {e}")
    try:
        for one in reader.extensions():
            if one.definition is None:
                continue
            try:
                externals.append(ExtensionManifest.model_validate(one.definition))
            except ValueError:
                problems.append(f"{one.id}: 정의를 읽지 못했습니다")
    except CenterUnreachable as e:
        problems.append(f"외부 확장 목록을 받지 못했습니다 — {e}")
    return build(service_apps, externals, problems=problems)


@dataclass
class Usage:
    """그림이 이미 적어 둔 것 — 편집기가 처음 그릴 때 쓴다."""

    app_id: str = ""
    operation: str = ""
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    key_ref: str = ""
    timeout_s: int | None = None
    retry_max: int = 0
    retry_on: tuple[int, ...] = ()

    @classmethod
    def of(cls, call: Mapping[str, Any]) -> Usage:
        retry = call.get("retry") or {}
        on = retry.get("on") if isinstance(retry, Mapping) else None
        return cls(
            app_id=str(call.get("app_id") or ""),
            operation=str(call.get("operation") or ""),
            inputs={str(k): str(v) for k, v in (call.get("input") or {}).items()},
            outputs={str(k): str(v) for k, v in (call.get("output") or {}).items()},
            key_ref=str(call.get("key_ref") or ""),
            timeout_s=call.get("timeout_s"),
            retry_max=int((retry or {}).get("max") or 0) if isinstance(retry, Mapping) else 0,
            retry_on=tuple(int(one) for one in (on or [])),
        )

    def to_call(self) -> dict[str, Any]:
        """`chk:serviceCall` 본문. **빈 것은 넣지 않는다** — 그림에 쓸모없는 칸을 남기지 않는다."""
        out: dict[str, Any] = {"app_id": self.app_id, "operation": self.operation}
        if self.inputs:
            out["input"] = dict(self.inputs)
        if self.outputs:
            out["output"] = dict(self.outputs)
        if self.key_ref:
            out["key_ref"] = self.key_ref
        if self.timeout_s:
            out["timeout_s"] = int(self.timeout_s)
        if self.retry_max:
            out["retry"] = {"max": int(self.retry_max), "on": [int(one) for one in self.retry_on]}
        return out


def stale_fields(operation: Operation | None, usage: Usage) -> tuple[list[str], list[str]]:
    """작업 정의에 **없는** 입력·출력 칸 — STU-14가 그 줄을 빨갛게 보인다.

    manifest가 칸을 알려 주지 않았으면(스키마 없음) **아무것도 낡지 않았다** — 비교할 것이 없다.
    """
    if operation is None or not operation.has_schema:
        return [], []
    known_in = {one.name for one in operation.inputs}
    known_out = {one.name for one in operation.outputs}
    inputs = sorted(name for name in usage.inputs if known_in and name not in known_in)
    outputs = sorted(
        field_name for field_name in usage.outputs.values() if known_out and field_name not in known_out
    )
    return inputs, outputs


def missing_required(operation: Operation | None, usage: Usage) -> list[str]:
    """값이 비어 있는 **필수** 입력 — 있으면 「적용」을 막는다 (STU-14 검증)."""
    if operation is None:
        return []
    return sorted(
        one.name for one in operation.inputs if one.required and not (usage.inputs.get(one.name) or "").strip()
    )


__all__ = [
    "KIND_C11",
    "KIND_EXTERNAL",
    "UNKNOWN",
    "App",
    "Catalog",
    "Field_",
    "Operation",
    "Usage",
    "build",
    "from_center",
    "missing_required",
    "stale_fields",
]
