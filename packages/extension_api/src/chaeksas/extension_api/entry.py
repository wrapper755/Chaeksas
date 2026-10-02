"""`entry` 문자열(`"ui_automation.client:UiTaskExecutor"`) → 실제 객체.

확장 정의(C13)의 `executor`·`editor`·`bot_ui.utilities`·`preflight`가 코드를 이 형식으로
가리킨다. 모듈 이름은 **확장 이름 공간(`chaeksas.ext`) 밑에서 먼저** 찾는다 (ADR-0019).

    ui_automation.client:UiTaskExecutor  →  chaeksas.ext.ui_automation.client.UiTaskExecutor

**쓸 수 있는 확장은 설치 파일에 든 것(내장·사내)뿐이다** (ADR-0018 §3). 아무 모듈이나 가리켜
import시키지 못하게, 부르는 쪽이 `root`로 그 확장의 패키지를 못 박는다 — 확장 호스트는 늘 그렇게
부른다 (`root=module_root(확장 id)`).
"""

from __future__ import annotations

import importlib
import re

#: 확장 패키지의 이름 공간 (ADR-0019 — 확장은 `chaeksas.ext.<id>`).
EXTENSION_NAMESPACE = "chaeksas.ext"

_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_ENTRY = re.compile(rf"^(?P<module>{_NAME}(?:\.{_NAME})*):(?P<attr>{_NAME})$")


class EntryError(ValueError):
    """`entry`를 읽을 수 없거나, 가리키는 것이 없거나, 그 확장 밖을 가리킨다."""


def module_root(extension_id: str) -> str:
    """확장 id → 그 확장의 파이썬 패키지 (`ui-automation` → `chaeksas.ext.ui_automation`)."""
    return f"{EXTENSION_NAMESPACE}.{extension_id.replace('-', '_')}"


def split_entry(entry: str) -> tuple[str, str]:
    """`"<모듈>:<이름>"`을 나눈다. 형식이 아니면 `EntryError`."""
    m = _ENTRY.match(entry.strip())
    if m is None:
        raise EntryError(f"entry 형식이 아니다 (<모듈>:<이름>): {entry!r}")
    return m.group("module"), m.group("attr")


def _import_module(module: str, root: str | None) -> tuple[str, object]:
    """이름 공간 밑에서 먼저, 없으면 적은 그대로 import한다."""
    candidates = [f"{EXTENSION_NAMESPACE}.{module}", module]
    if module.startswith(f"{EXTENSION_NAMESPACE}."):
        candidates = [module]
    first_error: ImportError | None = None
    for name in candidates:
        if root is not None and name != root and not name.startswith(f"{root}."):
            continue
        try:
            return name, importlib.import_module(name)
        except ImportError as e:
            first_error = first_error or e
    if root is not None:
        raise EntryError(f"{module!r}은 {root} 밖이거나 없다 (확장은 자기 패키지만 가리킨다)") from first_error
    raise EntryError(f"모듈을 import할 수 없다: {module!r}") from first_error


def resolve(entry: str, *, root: str | None = None) -> object:
    """`entry`가 가리키는 객체 (보통 클래스). **import가 일어나므로 믿는 확장만 부른다.**

    `root`를 주면 그 패키지 안만 허용한다 (확장 호스트가 쓰는 길).
    """
    module_name, attr = split_entry(entry)
    resolved, module = _import_module(module_name, root)
    try:
        return getattr(module, attr)
    except AttributeError as e:
        raise EntryError(f"{resolved}에 {attr}가 없다") from e
