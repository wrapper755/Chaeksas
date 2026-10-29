"""키를 받지 않는 외부 앱 (ADR-0091) — **정의가 스스로 어긋나지 않는다**.

`requires_keys`에 `run`이 있으면 `adapter.auth`도 있다 (E3). Center 등록·STU-15 「정의 파일 열기」가
같은 `validate()`를 쓴다.

키 **값**은 어댑터 일꾼의 설정이 든다 (ADR-0102 — `CHK_ADAPTER__EXT__<앱>__KEY`). 그림·매니페스트에는
키 참조가 없으므로(C14·C1) 「키를 받지 않는 앱」을 가르는 자리는 이 검사 하나만 남았다.
"""

from __future__ import annotations

from typing import Any

import pytest

from chaeksas.contracts.extension import ExtensionManifest
from chaeksas.contracts.extension import validate as validate_extension

APP = "ext-credit"


def external(*, auth: bool, run_key: bool) -> dict[str, Any]:
    adapter: dict[str, Any] = {
        "allowed_hosts": ["credit.example.com"],
        "operations": [
            {
                "name": "score",
                "modes": ["deterministic"],
                "request": {"method": "POST", "path": "/score", "body": {"no": "{{input.no}}"}},
                "response": {"output": {"score": "$.score"}},
            }
        ],
    }
    if auth:
        adapter["auth"] = {"type": "bearer"}
    definition: dict[str, Any] = {
        "schema": 2,
        "id": APP,
        "version": "1.0.0",
        "name": "외부 신용",
        "publisher": "외부 업체",
        "tier": "external",
        "service": {"protocol": "http-adapter", "base_url": "https://credit.example.com", "adapter": adapter},
    }
    if run_key:
        definition["requires_keys"] = [{"purpose": "run"}]
    return definition


def manifest_of(definition: dict[str, Any]) -> ExtensionManifest:
    return ExtensionManifest.model_validate(definition)


# ─────────────────────────── 정의 (C13) ───────────────────────────


def test_a_run_key_without_auth_is_refused() -> None:
    """키를 받는다고 적고 실을 자리를 두지 않으면 거부한다 — 어댑터는 보내지 않는데 점검은 요구한다."""
    found = validate_extension(manifest_of(external(auth=False, run_key=True)))
    assert [(v.rule, v.code) for v in found] == [("E3", "adapter_invalid")]
    assert found[0].items == ["service.adapter.auth"], "칸별 사유를 준다 (CON-07이 그대로 보인다)"


@pytest.mark.parametrize(("auth", "run_key"), [(True, True), (False, False), (True, False)])
def test_the_other_three_shapes_pass(auth: bool, run_key: bool) -> None:
    assert validate_extension(manifest_of(external(auth=auth, run_key=run_key))) == []

