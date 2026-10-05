"""의존 방향 검사 — docs/01-architecture.md §5를 테스트로 강제한다 (M1 완료 기준).

두 가지를 본다.
1. 선언한 의존 (pyproject.toml): 전이 포함. 코드가 없어도 잡힌다.
2. 실제 import (AST): 선언하지 않고 몰래 쓰는 것도 잡힌다.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path
from typing import TypedDict

import pytest

ROOT = Path(__file__).resolve().parent.parent
MEMBER_GLOBS = ("packages/*", "apps/*", "extensions/*")


class Member(TypedDict):
    path: Path
    deps: list[str]


def members() -> dict[str, Member]:
    """배포 이름 → {경로, 의존}."""
    out: dict[str, Member] = {}
    for pattern in MEMBER_GLOBS:
        for p in sorted(ROOT.glob(f"{pattern}/pyproject.toml")):
            data = tomllib.loads(p.read_text(encoding="utf-8"))
            out[data["project"]["name"]] = {
                "path": p.parent,
                "deps": [d for d in data["project"]["dependencies"] if d.startswith("chaeksas-")],
            }
    return out


def reachable(name: str, graph: dict[str, Member]) -> set[str]:
    """전이 의존 (자기 자신 제외)."""
    seen: set[str] = set()
    stack = list(graph[name]["deps"])
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in graph:
            continue
        seen.add(cur)
        stack += graph[cur]["deps"]
    return seen


# (멤버, 의존하면 안 되는 멤버, 근거)
FORBIDDEN_DEPS = [
    ("chaeksas-center", "chaeksas-core", "§5 — center는 core를 import하지 않는다"),
    ("chaeksas-admin", "chaeksas-core", "§5 — admin은 contracts만 본다"),
    ("chaeksas-ext-ui-automation", "chaeksas-core", "§5 — 확장의 service·worker는 core를 import하지 않는다"),
    ("chaeksas-contracts", "chaeksas-extension-api", "§2 — contracts는 로직·I/O를 모른다"),
    ("chaeksas-extension-api", "chaeksas-core", "§5 — 방향은 extension_api ◀── core"),
    ("chaeksas-service-kit", "chaeksas-core", "§5 — service_kit은 contracts만 본다 (업무 로직·실행을 모른다)"),
    ("chaeksas-service-kit", "chaeksas-qt", "§2 — 서비스 앱은 화면이 없다"),
    ("chaeksas-server-runner", "chaeksas-qt", "§2 — 서버 실행기는 화면이 없다"),
    ("chaeksas-core", "chaeksas-qt", "§5 — core는 Qt를 import하지 않는다"),
]


def test_llm_is_the_bottom() -> None:
    """ADR-0034 — 모델 클라이언트는 맨 아래다. 어느 멤버도 의존하지 않는다 (`contracts`도)."""
    graph = members()
    assert graph["chaeksas-llm"]["deps"] == [], graph["chaeksas-llm"]["deps"]


@pytest.mark.parametrize(("member", "forbidden", "why"), FORBIDDEN_DEPS)
def test_forbidden_dependency(member: str, forbidden: str, why: str) -> None:
    graph = members()
    assert member in graph, f"{member} 멤버가 없다"
    assert forbidden not in reachable(member, graph), f"{member} → {forbidden} ({why})"


def test_platform_does_not_depend_on_extensions() -> None:
    """ADR-0018 — 플랫폼(core·apps)은 특정 확장을 의존하지 않는다. 엔트리 포인트로만 찾는다."""
    graph = members()
    platform = ["chaeksas-core", "chaeksas-studio", "chaeksas-bot-ui", "chaeksas-server-runner", "chaeksas-center"]
    for m in platform:
        bad = {d for d in reachable(m, graph) if d.startswith("chaeksas-ext-")}
        assert not bad, f"{m}이 확장 {sorted(bad)}를 의존한다 (ADR-0018)"


def test_extensions_do_not_depend_on_each_other() -> None:
    """ADR-0018 — 확장끼리 import하지 않는다."""
    graph = members()
    for name in [m for m in graph if m.startswith("chaeksas-ext-")]:
        bad = {d for d in reachable(name, graph) if d.startswith("chaeksas-ext-") and d != name}
        assert not bad, f"{name}이 다른 확장 {sorted(bad)}를 의존한다"


# (경로 글롭, 금지 import 접두사, 근거)
FORBIDDEN_IMPORTS = [
    ("packages/core", "chaeksas.ext.", "ADR-0018 — 플랫폼은 특정 확장을 import하지 않는다"),
    ("apps/*", "chaeksas.ext.", "ADR-0018 — 플랫폼은 특정 확장을 import하지 않는다"),
    ("apps/center", "chaeksas.core", "§5"),
    ("apps/admin", "chaeksas.core", "§5"),
    ("extensions/*", "chaeksas.core", "§5 — 확장의 service·worker는 core를 모른다"),
    ("packages/core", "PySide6", "§5 — core는 Qt를 import하지 않는다"),
    ("packages/llm", "chaeksas.", "ADR-0034 — llm은 맨 아래다 (chaeksas의 아무것도 모른다)"),
    ("apps/server_runner", "PySide6", "§2 — 화면 없음"),
    ("apps/center", "PySide6", "§2 — 서버"),
    ("packages/*", "spikes", "CLAUDE.md §3 — 제품 코드는 spikes를 import하지 않는다"),
    ("apps/*", "spikes", "CLAUDE.md §3 — 제품 코드는 spikes를 import하지 않는다"),
    ("extensions/*", "spikes", "CLAUDE.md §3 — 제품 코드는 spikes를 import하지 않는다"),
]


def imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize(("glob", "forbidden", "why"), FORBIDDEN_IMPORTS)
def test_forbidden_import(glob: str, forbidden: str, why: str) -> None:
    offenders = []
    for py in sorted(ROOT.glob(f"{glob}/src/**/*.py")):
        for name in imported_names(py):
            if name == forbidden.rstrip(".") or name.startswith(forbidden):
                offenders.append(f"{py.relative_to(ROOT)}: import {name}")
    assert not offenders, f"{why}\n" + "\n".join(offenders)


def test_extension_worker_does_not_import_service() -> None:
    """Worker(로컬 런타임)는 서버 부분을 import하지 않는다 — HTTP로만 부른다 (C8·C10)."""
    offenders = []
    for py in sorted(ROOT.glob("extensions/*/src/**/worker/**/*.py")):
        for name in imported_names(py):
            if ".service" in name:
                offenders.append(f"{py.relative_to(ROOT)}: import {name}")
    assert not offenders, "\n".join(offenders)
