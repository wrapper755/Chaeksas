"""Center의 SQL이 PostgreSQL로 옮겨질 모양인지 — ADR-0070 §2.

Center는 SQLite로 남지만 **SQLite 전용 문법 없이** 적는다. 그래야 옮길 때 고칠 자리가 연결이 사는
네 파일과 자리표시(`?` ↔ `%s`)로 줄어든다. 사람이 주석으로 막던 것을 시험으로 굳힌다.

보는 것은 **파이썬 문자열 안의 SQL**이다(AST) — 주석·독스트링은 보지 않는다(거기서는 「쓰지 않는다」고
말하려고 그 이름을 적는다).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CENTER = ROOT / "apps" / "center" / "src" / "chaeksas" / "center"

#: 연결·잠금·WAL이 사는 자리 — `sqlite3`를 import해도 되고 `PRAGMA`·`BEGIN IMMEDIATE`를 써도 된다.
CONNECTION_FILES = {"storage.py", "migrations.py", "repair.py", "__main__.py"}

#: 어디에서도 쓰지 않는 SQLite 전용 문법. PostgreSQL에 같은 뜻의 것이 있지만 글이 다르다.
SQLITE_ONLY = {
    "INSERT OR": r"\bINSERT\s+OR\b",
    "REPLACE INTO": r"\bREPLACE\s+INTO\b",
    "AUTOINCREMENT": r"\bAUTOINCREMENT\b",
    "rowid": r"\b(?:_?rowid_?|oid)\b",
    "GROUP_CONCAT": r"\bGROUP_CONCAT\s*\(",
    "datetime()": r"\b(?:date|time|datetime)\s*\(",
    "julianday": r"\bjulianday\s*\(",
    "strftime": r"\bstrftime\s*\(",
    "IIF": r"\bIIF\s*\(",
}
#: 연결 파일에서만 받는 것.
CONNECTION_ONLY = {
    "PRAGMA": r"\bPRAGMA\b",
    "BEGIN IMMEDIATE": r"\bBEGIN\s+IMMEDIATE\b",
}

SQL_START = re.compile(r"^\s*(?:SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|WITH|PRAGMA|BEGIN)\b", re.I)


def sources() -> list[Path]:
    return sorted(p for p in CENTER.rglob("*.py") if "__pycache__" not in p.parts)


def docstring_ids(tree: ast.AST) -> set[int]:
    """모듈·클래스·함수의 독스트링 노드 — SQL이 아니다."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                out.add(id(body[0].value))
    return out


def sql_strings(path: Path) -> list[tuple[int, str]]:
    """그 파일의 SQL 글 (줄 번호, 글). 이어 붙인 문자열은 파이썬이 이미 하나로 만든다."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = docstring_ids(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            if SQL_START.search(node.value) or "CREATE TABLE" in node.value:
                found.append((node.lineno, node.value))
    return found


def offenders(rules: dict[str, str], files: list[Path]) -> list[str]:
    out = []
    for path in files:
        for line, sql in sql_strings(path):
            for name, pattern in rules.items():
                if re.search(pattern, sql, re.I):
                    out.append(f"{path.relative_to(ROOT).as_posix()}:{line} — {name}")
    return out


def test_the_scanner_sees_center_sql() -> None:
    """빈 손으로 통과하지 않는다 — 기준선과 API의 SQL이 정말 잡힌다."""
    by_file = {p.name: sql_strings(p) for p in sources()}
    assert any("CREATE TABLE" in sql for _, sql in by_file["storage.py"])
    assert sum(len(v) for v in by_file.values()) > 50


def test_no_sqlite_only_sql_anywhere() -> None:
    bad = offenders(SQLITE_ONLY, sources())
    assert not bad, "SQLite에만 있는 문법이다 — PostgreSQL에서도 통하는 글로 적는다 (ADR-0070 §2):\n" + "\n".join(bad)


def test_connection_details_stay_in_the_connection_files() -> None:
    elsewhere = [p for p in sources() if p.name not in CONNECTION_FILES or p.parent != CENTER]
    bad = offenders(CONNECTION_ONLY, elsewhere)
    assert not bad, "연결·잠금은 연결 파일 넷에만 둔다 (ADR-0070 §2):\n" + "\n".join(bad)


def test_only_the_connection_files_import_sqlite3() -> None:
    """API 모듈은 `Store`를 거친다 — 옮길 때 바뀌는 자리가 늘지 않게."""
    bad = []
    for path in sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n.split(".")[0] == "sqlite3" for n in names):
                if path.name not in CONNECTION_FILES or path.parent != CENTER:
                    bad.append(path.relative_to(ROOT).as_posix())
    assert not bad, "`sqlite3`는 연결 파일 넷만 import한다 (ADR-0070 §2): " + ", ".join(bad)


def test_the_rules_catch_what_they_name() -> None:
    """규칙이 정말 잡는지 — 정규식이 조용히 아무것도 못 잡으면 시험이 거짓말을 한다."""
    samples = {
        "INSERT OR": "INSERT OR IGNORE INTO x VALUES (?)",
        "REPLACE INTO": "REPLACE INTO x VALUES (?)",
        "AUTOINCREMENT": "CREATE TABLE x (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        "rowid": "SELECT rowid FROM x",
        "GROUP_CONCAT": "SELECT GROUP_CONCAT(a) FROM x",
        "datetime()": "SELECT datetime('now')",
        "julianday": "SELECT julianday(a) FROM x",
        "strftime": "SELECT strftime('%s', a) FROM x",
        "IIF": "SELECT IIF(a, 1, 0) FROM x",
        "PRAGMA": "PRAGMA foreign_keys=ON",
        "BEGIN IMMEDIATE": "BEGIN IMMEDIATE",
    }
    rules = SQLITE_ONLY | CONNECTION_ONLY
    assert set(samples) == set(rules)
    for name, sql in samples.items():
        assert re.search(rules[name], sql, re.I), name
    # 이식되는 것은 잡지 않는다.
    for ok in ("INSERT INTO x VALUES (?) ON CONFLICT (a) DO NOTHING", "SELECT created_at FROM x"):
        assert not any(re.search(p, ok, re.I) for p in rules.values()), ok
