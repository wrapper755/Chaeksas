"""식 `chk-expr`·스크립트·템플릿 ([ADR-0025](../../../../docs/decisions/0025-expression-language.md), C14 §식).

세 가지를 다룬다.

| | 어디에 쓰나 | 모양 |
| --- | --- | --- |
| `evaluate()` | 흐름 조건, `serviceCall.input`, `rule.input`, `call.input`, `loop.over` | 값 하나를 내는 식 |
| `run_script()` | `scriptTask`의 본문 | `변수 = 식` 여러 줄 (**대입문만**) |
| `fill()` | `dataOutput.path`·`template`, `email.to`·`subject`·`body` | 텍스트 + `{변수}` (이름 하나만) |

`eval`·`exec`을 쓰지 않는다. `ast`로 파싱해 **허용한 노드만** 통과시킨 뒤 직접 걸어 값을 낸다.
점(`결과.지급`)은 **사전의 키**를 읽는다 — 파이썬 객체의 속성은 읽을 수 없다.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from chaeksas.core.helpers import HELPERS

#: 식에서 허용하는 AST 노드. **이 밖은 파싱 단계에서 거부한다** (ADR-0025 §2).
ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.Module,
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
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.comprehension,
    ast.JoinedStr,
    ast.FormattedValue,
)

#: 템플릿의 `{변수}`. 중괄호 안은 **이름 하나**만 (ADR-0025 §1).
TEMPLATE_RE = re.compile(r"\{\{|\}\}|\{([^{}]*)\}")
#: 변수·입력 이름 규칙 (C14 §5와 같다).
NAME_RE = re.compile(r"^[A-Za-z가-힣_][A-Za-z0-9가-힣_]*$")


class ExprError(ValueError):
    """식·스크립트·템플릿을 쓸 수 없거나 값을 낼 수 없다.

    `where`(노드 id)와 `source`(식 본문)를 붙여 **어디서 틀렸는지** 말한다. 값은 담지 않는다
    (계약 원칙 6 — 실행 기록에 업무 값을 넣지 않는다).
    """

    def __init__(self, message: str, *, where: str | None = None, source: str | None = None) -> None:
        self.reason = message
        self.where = where
        self.source = source
        head = f"[{where}] " if where else ""
        tail = f" — 식: {source.strip()}" if source else ""
        super().__init__(f"{head}{message}{tail}")


def _check(tree: ast.AST, *, where: str | None, source: str) -> None:
    """허용 목록 밖의 문법·이름을 거부한다."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr):
            continue  # 식 하나로 된 줄 (Module 안의 포장)
        if not isinstance(node, ALLOWED_NODES):
            raise ExprError(f"식에서 쓸 수 없는 문법이다: {type(node).__name__}", where=where, source=source)
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ExprError(f"밑줄로 시작하는 이름은 읽을 수 없다: {node.attr}", where=where, source=source)
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ExprError(f"쓸 수 없는 이름이다: {node.id}", where=where, source=source)


@dataclass
class Scope:
    """식이 볼 수 있는 것 — 변수와 도우미 함수.

    `variables`는 **그 실행의 프로세스 변수**다. 도우미는 바꿔 끼울 수 있다 (시험·툴팩).
    """

    variables: dict[str, Any]
    #: 그 실행의 도우미 (`helpers.bind(now=…)`). 주지 않으면 날짜가 묶이지 않은 기본 묶음이다.
    helpers: Mapping[str, Callable[..., Any]] = field(default_factory=lambda: HELPERS)
    where: str | None = None

    def child(self, **extra: Any) -> Scope:
        """내포의 변수처럼 **잠깐만** 더해지는 이름 (바깥 변수를 더럽히지 않는다)."""
        return Scope(variables={**self.variables, **extra}, helpers=self.helpers, where=self.where)


class _Walker:
    """허용한 노드를 걸어 값을 낸다. `Scope` 하나에 묶인다."""

    def __init__(self, scope: Scope, source: str) -> None:
        self.scope = scope
        self.source = source

    def fail(self, message: str) -> ExprError:
        return ExprError(message, where=self.scope.where, source=self.source)

    def visit(self, node: ast.AST) -> Any:
        method = getattr(self, f"_{type(node).__name__}", None)
        if method is None:
            raise self.fail(f"식에서 쓸 수 없는 문법이다: {type(node).__name__}")
        return method(node)

    # ── 값 ──

    def _Constant(self, node: ast.Constant) -> Any:  # noqa: N802 — AST 이름 그대로
        return node.value

    def _Name(self, node: ast.Name) -> Any:  # noqa: N802
        if node.id in self.scope.variables:
            return self.scope.variables[node.id]
        if node.id in self.scope.helpers:
            return self.scope.helpers[node.id]
        raise self.fail(f"모르는 변수다: {node.id}")

    def _List(self, node: ast.List) -> Any:  # noqa: N802
        return [self.visit(e) for e in node.elts]

    def _Tuple(self, node: ast.Tuple) -> Any:  # noqa: N802
        return tuple(self.visit(e) for e in node.elts)

    def _Set(self, node: ast.Set) -> Any:  # noqa: N802
        return {self.visit(e) for e in node.elts}

    def _Dict(self, node: ast.Dict) -> Any:  # noqa: N802
        out: dict[Any, Any] = {}
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                raise self.fail("사전에 `**`는 쓸 수 없다")
            out[self.visit(key)] = self.visit(value)
        return out

    def _JoinedStr(self, node: ast.JoinedStr) -> Any:  # noqa: N802
        return "".join(str(self.visit(v)) for v in node.values)

    def _FormattedValue(self, node: ast.FormattedValue) -> Any:  # noqa: N802
        if node.format_spec is not None:
            return format(self.visit(node.value), str(self.visit(node.format_spec)))
        return self.visit(node.value)

    # ── 연산 ──

    def _BoolOp(self, node: ast.BoolOp) -> Any:  # noqa: N802
        """`and`·`or`는 **짧게 끊는다** (파이썬과 같다) — `대상월 or 지난달()`이 그 덕을 본다."""
        last: Any = None
        for value_node in node.values:
            last = self.visit(value_node)
            if isinstance(node.op, ast.And):
                if not last:
                    return last
            elif last:
                return last
        return last

    def _UnaryOp(self, node: ast.UnaryOp) -> Any:  # noqa: N802
        value = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return not value
        try:
            return -value if isinstance(node.op, ast.USub) else +value
        except TypeError as e:
            raise self.fail(f"부호를 붙일 수 없는 값이다: {e}") from e

    _BIN: dict[type[ast.AST], Callable[[Any, Any], Any]] = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.FloorDiv: lambda a, b: a // b,
        ast.Mod: lambda a, b: a % b,
        ast.Pow: lambda a, b: a**b,
    }

    def _BinOp(self, node: ast.BinOp) -> Any:  # noqa: N802
        op = self._BIN[type(node.op)]
        left, right = self.visit(node.left), self.visit(node.right)
        try:
            return op(left, right)
        except ZeroDivisionError as e:
            # 0으로 나누는 것은 흔한 실수다 — `나누기()`를 알려 준다.
            raise self.fail("0으로 나눌 수 없다 (`나누기(a, b)`는 0을 돌려준다)") from e
        except TypeError as e:
            raise self.fail(f"더하거나 곱할 수 없는 값이다: {e}") from e

    _CMP: dict[type[ast.AST], Callable[[Any, Any], Any]] = {
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

    def _Compare(self, node: ast.Compare) -> Any:  # noqa: N802
        left = self.visit(node.left)
        for op, right_node in zip(node.ops, node.comparators, strict=True):
            right = self.visit(right_node)
            try:
                if not self._CMP[type(op)](left, right):
                    return False
            except TypeError as e:
                # `None > 0`처럼 값이 없을 때 자주 난다 — 무엇과 무엇인지 알려 준다.
                raise self.fail(f"견줄 수 없는 값이다 ({type(left).__name__}와 {type(right).__name__})") from e
            left = right
        return True

    def _IfExp(self, node: ast.IfExp) -> Any:  # noqa: N802
        return self.visit(node.body) if self.visit(node.test) else self.visit(node.orelse)

    # ── 꺼내기 ──

    def _Attribute(self, node: ast.Attribute) -> Any:  # noqa: N802
        """**점은 사전의 키다** (ADR-0025 §3). 객체 속성은 읽을 수 없다."""
        value = self.visit(node.value)
        if isinstance(value, Mapping):
            if node.attr in value:
                return value[node.attr]
            raise self.fail(f"그 값에 「{node.attr}」가 없다 (있는 것: {', '.join(map(str, value))[:60]})")
        raise self.fail(f"점으로 읽을 수 없는 값이다: {type(value).__name__} (사전만 된다)")

    def _Subscript(self, node: ast.Subscript) -> Any:  # noqa: N802
        value = self.visit(node.value)
        index = self.visit(node.slice)
        if isinstance(index, str) and index.startswith("_"):
            raise self.fail(f"밑줄로 시작하는 이름은 읽을 수 없다: {index}")
        try:
            return value[index]
        except (KeyError, IndexError) as e:
            raise self.fail(f"그 자리에 값이 없다: {index!r}") from e
        except TypeError as e:
            raise self.fail(f"첨자로 읽을 수 없는 값이다: {type(value).__name__}") from e

    def _Slice(self, node: ast.Slice) -> Any:  # noqa: N802
        return slice(
            self.visit(node.lower) if node.lower is not None else None,
            self.visit(node.upper) if node.upper is not None else None,
            self.visit(node.step) if node.step is not None else None,
        )

    # ── 호출 ──

    def _Call(self, node: ast.Call) -> Any:  # noqa: N802
        if not isinstance(node.func, ast.Name):
            raise self.fail("함수는 이름으로만 부를 수 있다 (허용 목록)")
        name = node.func.id
        helper = self.scope.helpers.get(name)
        if helper is None:
            raise self.fail(f"쓸 수 없는 함수다: {name}")
        args = [self.visit(a) for a in node.args]
        kwargs = {k.arg: self.visit(k.value) for k in node.keywords if k.arg is not None}
        try:
            return helper(*args, **kwargs)
        except ExprError:
            raise
        except Exception as e:  # noqa: BLE001 — 도우미가 무엇을 낼지 모른다
            raise self.fail(f"{name}(…)이 실패했다: {e}") from e

    # ── 내포 ──

    def _comprehend(self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp) -> Iterable[Any]:
        made: list[Any] = []

        def step(index: int, scope: Scope) -> None:
            if index == len(node.generators):
                inner = _Walker(scope, self.source)
                if isinstance(node, ast.DictComp):
                    made.append((inner.visit(node.key), inner.visit(node.value)))
                else:
                    made.append(inner.visit(node.elt))
                return
            generator = node.generators[index]
            if generator.is_async:
                raise self.fail("`async for`는 쓸 수 없다")
            source = _Walker(scope, self.source).visit(generator.iter)
            try:
                items = list(source)
            except TypeError as e:
                raise self.fail(f"하나씩 돌 수 없는 값이다: {type(source).__name__}") from e
            for item in items:
                bound = scope.child(**self._bind(generator.target, item))
                if all(_Walker(bound, self.source).visit(c) for c in generator.ifs):
                    step(index + 1, bound)

        step(0, self.scope)
        return made

    def _bind(self, target: ast.expr, value: Any) -> dict[str, Any]:
        if isinstance(target, ast.Name):
            return {target.id: value}
        if isinstance(target, ast.Tuple):
            try:
                items = list(value)
            except TypeError as e:
                raise self.fail("여러 변수로 받으려면 값이 목록이어야 한다") from e
            if len(items) != len(target.elts):
                raise self.fail(f"변수 {len(target.elts)}개에 값 {len(items)}개를 받을 수 없다")
            out: dict[str, Any] = {}
            for slot, item in zip(target.elts, items, strict=True):
                out.update(self._bind(slot, item))
            return out
        raise self.fail("내포의 변수 자리는 이름이거나 이름 묶음이어야 한다")

    def _ListComp(self, node: ast.ListComp) -> Any:  # noqa: N802
        return list(self._comprehend(node))

    def _SetComp(self, node: ast.SetComp) -> Any:  # noqa: N802
        return set(self._comprehend(node))

    def _GeneratorExp(self, node: ast.GeneratorExp) -> Any:  # noqa: N802
        # 식 언어에 게으른 값은 두지 않는다 — 바로 목록으로 만든다.
        return list(self._comprehend(node))

    def _DictComp(self, node: ast.DictComp) -> Any:  # noqa: N802
        return dict(self._comprehend(node))


def parse(source: str, *, where: str | None = None) -> ast.Expression:
    """식을 파싱하고 허용 목록으로 검사한다 (값은 내지 않는다 — 검사·Studio용)."""
    text = source.strip()
    if not text:
        raise ExprError("식이 비어 있다", where=where)
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as e:
        raise ExprError(f"식 문법이 틀렸다: {e.msg}", where=where, source=source) from e
    _check(tree, where=where, source=source)
    return tree


def evaluate(source: str, scope: Scope) -> Any:
    """식 하나의 값."""
    tree = parse(source, where=scope.where)
    return _Walker(scope, source).visit(tree.body)


def truthy(source: str, scope: Scope) -> bool:
    """흐름 조건 — 값을 참/거짓으로 본다 (`발행대상`처럼 변수 하나만 쓰기도 한다)."""
    return bool(evaluate(source, scope))


def parse_script(source: str, *, where: str | None = None) -> list[ast.Assign]:
    """스크립트를 파싱한다. **대입문만** 올 수 있다 (ADR-0025 §1)."""
    text = source.strip()
    if not text:
        raise ExprError("스크립트가 비어 있다", where=where)
    try:
        tree = ast.parse(text, mode="exec")
    except SyntaxError as e:
        raise ExprError(f"스크립트 문법이 틀렸다: {e.msg}", where=where, source=source) from e
    _check(tree, where=where, source=source)

    out: list[ast.Assign] = []
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            raise ExprError(
                "스크립트에는 `변수 = 식`만 쓸 수 있다 (반복문·조건문은 BPMN으로 그린다)",
                where=where,
                source=source,
            )
        for target in statement.targets:
            if not isinstance(target, ast.Name):
                raise ExprError("대입 대상은 변수 이름이어야 한다", where=where, source=source)
            if not NAME_RE.match(target.id):
                raise ExprError(f"변수 이름으로 쓸 수 없다: {target.id}", where=where, source=source)
        out.append(statement)
    return out


def run_script(source: str, scope: Scope) -> dict[str, Any]:
    """스크립트를 돌리고 **바뀐 변수만** 돌려준다.

    `scope.variables`도 함께 바뀐다 (뒤 줄이 앞 줄의 결과를 쓴다 — 예제가 그렇게 쓴다).
    """
    changed: dict[str, Any] = {}
    for statement in parse_script(source, where=scope.where):
        value = _Walker(scope, source).visit(statement.value)
        for target in statement.targets:
            # `parse_script`가 이름만 남겼다 — 그래도 타입 검사기에게 말해 준다.
            assert isinstance(target, ast.Name)
            scope.variables[target.id] = value
            changed[target.id] = value
    return changed


def template_names(source: str) -> list[str]:
    """템플릿이 쓰는 변수 이름 (순서대로, 중복 포함하지 않음). 검사 B11·Studio가 쓴다."""
    found: list[str] = []
    for match in TEMPLATE_RE.finditer(source):
        name = match.group(1)
        if name is None:
            continue  # `{{`·`}}`
        name = name.strip()
        if name and name not in found:
            found.append(name)
    return found


def fill(source: str, scope: Scope) -> str:
    """템플릿 — 텍스트의 `{변수}`를 값으로 바꾼다. **중괄호 안은 이름 하나만** (ADR-0025 §1)."""

    def one(match: re.Match[str]) -> str:
        if match.group(0) == "{{":
            return "{"
        if match.group(0) == "}}":
            return "}"
        name = (match.group(1) or "").strip()
        if not name:
            raise ExprError("템플릿의 중괄호가 비어 있다", where=scope.where, source=source)
        if not NAME_RE.match(name):
            raise ExprError(
                f"템플릿의 중괄호에는 변수 이름만 쓸 수 있다 (식은 안 된다): {{{name}}}",
                where=scope.where,
                source=source,
            )
        if name not in scope.variables:
            raise ExprError(f"모르는 변수다: {name}", where=scope.where, source=source)
        value = scope.variables[name]
        return "" if value is None else str(value)

    return TEMPLATE_RE.sub(one, source)


__all__ = [
    "ALLOWED_NODES",
    "HELPERS",
    "NAME_RE",
    "TEMPLATE_RE",
    "ExprError",
    "Scope",
    "evaluate",
    "fill",
    "parse",
    "parse_script",
    "run_script",
    "template_names",
    "truthy",
]
