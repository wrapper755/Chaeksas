"""후보 ①: **직접 만든 AST 검사기** (스파이크 S6).

파이썬의 `ast`로 파싱하고, **허용한 노드만** 통과시킨 뒤 직접 걸어 값을 낸다. `eval`을 쓰지
않으므로 통과시킨 문법 밖은 애초에 실행되지 않는다.

이 파일은 스파이크다 — 제품 코드가 import하지 않는다 (CLAUDE.md §3).
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
from typing import Any

#: 식에서 허용하는 AST 노드. 여기 없는 것은 파싱 단계에서 거부한다.
ALLOWED = (
    ast.Expression,
    ast.Module,
    ast.Expr,
    ast.Assign,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.USub,
    ast.UAdd,
    ast.BinOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    ast.IfExp,
    ast.Call,
    ast.keyword,
    ast.Attribute,
    ast.Subscript,
    ast.Slice,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Set,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
    ast.GeneratorExp,
    ast.comprehension,
    ast.JoinedStr,
    ast.FormattedValue,
)

#: 쓸 수 없는 이름 (파이썬 내부를 들여다보는 길).
FORBIDDEN_NAMES = frozenset({"__class__", "__dict__", "__globals__", "__builtins__", "__import__", "__subclasses__"})


class ExprError(ValueError):
    """식을 쓸 수 없거나 값을 낼 수 없다."""


def check(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED):
            raise ExprError(f"식에서 쓸 수 없는 문법이다: {type(node).__name__}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ExprError(f"밑줄로 시작하는 이름은 쓸 수 없다: {node.attr}")
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise ExprError(f"쓸 수 없는 이름이다: {node.id}")


class Walker:
    """허용한 노드를 걸어 값을 낸다."""

    def __init__(self, variables: Mapping[str, Any], helpers: Mapping[str, Callable[..., Any]]) -> None:
        self.variables = dict(variables)
        self.helpers = helpers

    def eval(self, source: str) -> Any:
        tree = ast.parse(source.strip(), mode="eval")
        check(tree)
        return self.visit(tree.body)

    def run(self, source: str) -> dict[str, Any]:
        """스크립트(대입문 여러 줄)를 돌리고 바뀐 변수를 돌려준다."""
        tree = ast.parse(source.strip(), mode="exec")
        check(tree)
        changed: dict[str, Any] = {}
        for statement in tree.body:
            if not isinstance(statement, ast.Assign):
                raise ExprError("스크립트에는 대입문만 쓸 수 있다")
            value = self.visit(statement.value)
            for target in statement.targets:
                if not isinstance(target, ast.Name):
                    raise ExprError("대입 대상은 변수 이름이어야 한다")
                self.variables[target.id] = value
                changed[target.id] = value
        return changed

    # ── 노드별 ──

    def visit(self, node: ast.AST) -> Any:
        method = getattr(self, f"on_{type(node).__name__}", None)
        if method is None:
            raise ExprError(f"아직 다루지 않는 문법이다: {type(node).__name__}")
        return method(node)

    def on_Constant(self, node: ast.Constant) -> Any:  # noqa: N802
        return node.value

    def on_Name(self, node: ast.Name) -> Any:  # noqa: N802
        if node.id in self.variables:
            return self.variables[node.id]
        if node.id in self.helpers:
            return self.helpers[node.id]
        raise ExprError(f"모르는 변수다: {node.id}")

    def on_BoolOp(self, node: ast.BoolOp) -> Any:  # noqa: N802
        values = [self.visit(v) for v in node.values]
        if isinstance(node.op, ast.And):
            found = True
            for v in values:
                if not v:
                    return v
                found = v
            return found
        for v in values:
            if v:
                return v
        return values[-1]

    def on_UnaryOp(self, node: ast.UnaryOp) -> Any:  # noqa: N802
        value = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return not value
        if isinstance(node.op, ast.USub):
            return -value
        return +value

    _BIN = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.FloorDiv: lambda a, b: a // b,
        ast.Mod: lambda a, b: a % b,
        ast.Pow: lambda a, b: a**b,
    }

    def on_BinOp(self, node: ast.BinOp) -> Any:  # noqa: N802
        op = self._BIN.get(type(node.op))
        if op is None:
            raise ExprError("쓸 수 없는 연산이다")
        return op(self.visit(node.left), self.visit(node.right))

    _CMP = {
        ast.Eq: lambda a, b: a == b,
        ast.NotEq: lambda a, b: a != b,
        ast.Lt: lambda a, b: a < b,
        ast.LtE: lambda a, b: a <= b,
        ast.Gt: lambda a, b: a > b,
        ast.GtE: lambda a, b: a >= b,
        ast.In: lambda a, b: a in b,
        ast.NotIn: lambda a, b: a not in b,
        ast.Is: lambda a, b: a is b,
        ast.IsNot: lambda a, b: a is not b,
    }

    def on_Compare(self, node: ast.Compare) -> Any:  # noqa: N802
        left = self.visit(node.left)
        for op, right_node in zip(node.ops, node.comparators, strict=True):
            right = self.visit(right_node)
            if not self._CMP[type(op)](left, right):
                return False
            left = right
        return True

    def on_IfExp(self, node: ast.IfExp) -> Any:  # noqa: N802
        return self.visit(node.body) if self.visit(node.test) else self.visit(node.orelse)

    def on_Call(self, node: ast.Call) -> Any:  # noqa: N802
        if not isinstance(node.func, ast.Name):
            raise ExprError("함수는 이름으로만 부를 수 있다 (허용 목록)")
        name = node.func.id
        if name not in self.helpers:
            raise ExprError(f"쓸 수 없는 함수다: {name}")
        args = [self.visit(a) for a in node.args]
        kwargs = {k.arg: self.visit(k.value) for k in node.keywords if k.arg}
        return self.helpers[name](*args, **kwargs)

    def on_Attribute(self, node: ast.Attribute) -> Any:  # noqa: N802
        """**사전의 키를 점으로 읽는다** — 예제가 `결과.지급`처럼 쓴다."""
        value = self.visit(node.value)
        if isinstance(value, Mapping):
            if node.attr not in value:
                raise ExprError(f"그 값에 「{node.attr}」가 없다")
            return value[node.attr]
        raise ExprError(f"점으로 읽을 수 없는 값이다: {type(value).__name__}")

    def on_Subscript(self, node: ast.Subscript) -> Any:  # noqa: N802
        value = self.visit(node.value)
        index = self.visit(node.slice)
        try:
            return value[index]
        except (KeyError, IndexError, TypeError) as e:
            raise ExprError(f"꺼낼 수 없다: {e}") from e

    def on_Slice(self, node: ast.Slice) -> Any:  # noqa: N802
        return slice(
            self.visit(node.lower) if node.lower else None,
            self.visit(node.upper) if node.upper else None,
            self.visit(node.step) if node.step else None,
        )

    def on_List(self, node: ast.List) -> Any:  # noqa: N802
        return [self.visit(e) for e in node.elts]

    def on_Tuple(self, node: ast.Tuple) -> Any:  # noqa: N802
        return tuple(self.visit(e) for e in node.elts)

    def on_Set(self, node: ast.Set) -> Any:  # noqa: N802
        return {self.visit(e) for e in node.elts}

    def on_Dict(self, node: ast.Dict) -> Any:  # noqa: N802
        return {self.visit(k) if k else None: self.visit(v) for k, v in zip(node.keys, node.values, strict=True)}

    def on_JoinedStr(self, node: ast.JoinedStr) -> Any:  # noqa: N802
        return "".join(str(self.visit(v)) for v in node.values)

    def on_FormattedValue(self, node: ast.FormattedValue) -> Any:  # noqa: N802
        return self.visit(node.value)

    def _comprehend(self, node: Any) -> Any:
        """내포 — 한 겹씩 변수를 묶어 가며 돈다."""
        results: list[Any] = []

        def step(index: int) -> None:
            if index == len(node.generators):
                results.append(node)
                return
            gen = node.generators[index]
            for item in self.visit(gen.iter):
                self._bind(gen.target, item)
                if all(self.visit(c) for c in gen.ifs):
                    step(index + 1)

        made: list[Any] = []

        def collect(index: int) -> None:
            if index == len(node.generators):
                if isinstance(node, ast.DictComp):
                    made.append((self.visit(node.key), self.visit(node.value)))
                else:
                    made.append(self.visit(node.elt))
                return
            gen = node.generators[index]
            for item in self.visit(gen.iter):
                self._bind(gen.target, item)
                if all(self.visit(c) for c in gen.ifs):
                    collect(index + 1)

        collect(0)
        del results
        return made

    def _bind(self, target: ast.expr, value: Any) -> None:
        if isinstance(target, ast.Name):
            self.variables[target.id] = value
            return
        if isinstance(target, ast.Tuple):
            for slot, item in zip(target.elts, value, strict=True):
                self._bind(slot, item)
            return
        raise ExprError("내포의 변수 자리가 이상하다")

    def on_ListComp(self, node: ast.ListComp) -> Any:  # noqa: N802
        return list(self._comprehend(node))

    def on_SetComp(self, node: ast.SetComp) -> Any:  # noqa: N802
        return set(self._comprehend(node))

    def on_GeneratorExp(self, node: ast.GeneratorExp) -> Any:  # noqa: N802
        return list(self._comprehend(node))

    def on_DictComp(self, node: ast.DictComp) -> Any:  # noqa: N802
        return dict(self._comprehend(node))


__all__ = ["ALLOWED", "ExprError", "Walker", "check"]
