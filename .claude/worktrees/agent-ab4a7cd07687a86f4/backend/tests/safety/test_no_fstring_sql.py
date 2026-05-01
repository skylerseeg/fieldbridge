"""Vista / mart SQL safety lint.

Rule: no production module under `app/modules/**/service.py` may build
SQL with an f-string whose interpolated values are not provably safe.
Bind values through `text(":name")` + a params dict, or use SQLAlchemy
core constructs.

Why we care:
* Mart and Vista services run with tenant-scoped credentials. A loose
  f-string SQL bug = cross-tenant leakage.
* Vista SQL is read-only by contract (see docs/ARCHITECTURE.md), but
  injection still leaks data.
* CI runs in 30s. A lint test runs in milliseconds. Cheap insurance.

Implementation:
* AST-walk every `app/modules/**/service.py`.
* Find every `JoinedStr` (f-string) whose static body looks like SQL
  (matches one of `SQL_KEYWORDS` at word boundary).
* For each such f-string, every `FormattedValue.value` (the `{x}` part)
  must resolve to a *module-level* `Name` bound to a `str` literal,
  a `tuple/list of str literals`, or a join of those. Anything else
  (function args, attribute access, computed values) is a fail.
* When a known-safe pattern is structurally too complex for the AST
  resolver (e.g. function-local generator expressions over a literal
  frozenset), we waive it via `KNOWN_SAFE_FSTRING_SQL` with a comment.

Adding a new entry to the allowlist:
* Each entry must be (file_relative_to_backend, line_number,
  snippet_substring) — exact-line-match defends against careless waivers
  drifting onto unrelated lines.
* Add a comment explaining *why* it's safe.
* If you can refactor the offender to use bound params instead, do that
  and skip the allowlist entry.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.safety


BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODULES_ROOT = BACKEND_ROOT / "app" / "modules"


# Tokens that flag an f-string body as "this is SQL".
SQL_KEYWORDS = (
    "SELECT ",
    "INSERT ",
    "UPDATE ",
    "DELETE ",
    "FROM ",
    "WHERE ",
    "JOIN ",
    "VALUES ",
)


# (file_relative_to_backend, joined_str_lineno, expected_snippet, reason)
# `expected_snippet` must appear inside `ast.unparse(formatted_value)` for the
# waiver to apply. Adding entries requires a 1-line justification — every
# new waiver should also have a TODO to refactor away from f-string SQL.
KNOWN_SAFE_FSTRING_SQL: list[tuple[str, int, str, str]] = [
    # equipment/service.py — hour_tokens is built from the module-level
    # frozenset HOUR_UNIT_TOKENS via a generator expression of literals:
    #   hour_tokens = ", ".join(f"'{t}'" for t in sorted(HOUR_UNIT_TOKENS))
    # No path from request input → SQL fragment.
    (
        "app/modules/equipment/service.py",
        83,
        "hour_tokens",
        "tokens generated from module-level frozenset HOUR_UNIT_TOKENS",
    ),
    # productivity/service.py — _fetch_resource(engine, tid, table_name).
    # Callers pass literal mart names; tenant_id stays bound via :tenant_id.
    # No path from request input → table_name.
    (
        "app/modules/productivity/service.py",
        199,
        "table_name",
        "table_name only ever passed literal mart names by internal callers",
    ),
    # timecards/service.py — _count(engine, tid, table). Callers pass
    # literal mart names; tenant_id is bound via :tid.
    (
        "app/modules/timecards/service.py",
        170,
        "table",
        "table only ever passed literal mart names by internal callers",
    ),
    # bids/service.py — col_sql = ", ".join(_BASE_COLS + _RISK_COLS +
    # _COMPETITOR_COLS). Each input is a literal list, a list comprehension
    # over range(1, 18) with literal suffixes, or list(RISK_FLAG_COLUMNS).
    # AST resolver doesn't follow list() / range() so we waive explicitly.
    (
        "app/modules/bids/service.py",
        340,
        "col_sql",
        "join of module-level literal-derived column constants",
    ),
    # proposals/service.py — col_sql = ", ".join(["_row_hash", "competitor",
    # *FEE_COLUMNS]). Star expansion of a module-level constant tuple of
    # literals; AST resolver doesn't follow Starred() so we waive.
    (
        "app/modules/proposals/service.py",
        222,
        "col_sql",
        "join of module-level literal-derived column constants",
    ),
]


def _iter_module_services() -> list[Path]:
    return sorted(MODULES_ROOT.glob("*/service.py"))


def _looks_like_sql(static_body: str) -> bool:
    upper = static_body.upper()
    return any(kw in upper for kw in SQL_KEYWORDS)


def _static_body(joined: ast.JoinedStr) -> str:
    """Concatenate the literal portions of an f-string, ignoring `{x}`
    parts. Good enough to keyword-check."""
    out: list[str] = []
    for v in joined.values:
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            out.append(v.value)
    return "".join(out)


def _safe_module_constants(tree: ast.Module) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Names assigned at module scope to a literal-derived value.

    Returns (safe_strs, safe_lists).
    Recognized RHS shapes:
      NAME = "literal"
      NAME = [..str literals only..]            (list / tuple)
      NAME = NAME_A + NAME_B                    (concat of safe lists or strs)
      NAME = ", ".join(SAFE_LIST)               (or literal list of literals)
    """
    safe_lists: dict[str, list[str]] = {}
    safe_strs: dict[str, str] = {}

    def resolve_list(expr: ast.AST) -> list[str] | None:
        if isinstance(expr, (ast.List, ast.Tuple)) and all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in expr.elts
        ):
            return [e.value for e in expr.elts]
        if isinstance(expr, ast.Name) and expr.id in safe_lists:
            return list(safe_lists[expr.id])
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
            left = resolve_list(expr.left)
            right = resolve_list(expr.right)
            if left is not None and right is not None:
                return left + right
        return None

    def resolve_str(expr: ast.AST) -> str | None:
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return expr.value
        if isinstance(expr, ast.Name) and expr.id in safe_strs:
            return safe_strs[expr.id]
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
            left = resolve_str(expr.left)
            right = resolve_str(expr.right)
            if left is not None and right is not None:
                return left + right
        if (
            isinstance(expr, ast.Call)
            and isinstance(expr.func, ast.Attribute)
            and expr.func.attr == "join"
            and isinstance(expr.func.value, ast.Constant)
            and isinstance(expr.func.value.value, str)
            and len(expr.args) == 1
        ):
            sep = expr.func.value.value
            elts = resolve_list(expr.args[0])
            if elts is not None:
                return sep.join(elts)
        return None

    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        as_list = resolve_list(node.value)
        if as_list is not None:
            safe_lists[target.id] = as_list
        as_str = resolve_str(node.value)
        if as_str is not None:
            safe_strs[target.id] = as_str

    return safe_strs, safe_lists


def _scan(path: Path) -> list[str]:
    """Return human-readable findings for a single file. [] = clean."""
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as e:
        return [f"{path}: could not read source ({e})"]

    tree = ast.parse(src, filename=str(path))
    mod_strs, mod_lists = _safe_module_constants(tree)

    try:
        rel = str(path.relative_to(BACKEND_ROOT))
    except ValueError:
        rel = path.name

    waivers = {
        (e_path, e_line, e_snippet): e_reason
        for (e_path, e_line, e_snippet, e_reason) in KNOWN_SAFE_FSTRING_SQL
    }

    findings: list[str] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.local_strs: list[dict[str, str]] = [dict(mod_strs)]
            self.local_lists: list[dict[str, list[str]]] = [dict(mod_lists)]

        @property
        def cur_str(self) -> dict[str, str]:
            return self.local_strs[-1]

        @property
        def cur_list(self) -> dict[str, list[str]]:
            return self.local_lists[-1]

        def _push(self) -> None:
            self.local_strs.append(dict(self.cur_str))
            self.local_lists.append(dict(self.cur_list))

        def _pop(self) -> None:
            self.local_strs.pop()
            self.local_lists.pop()

        def _resolve_list(self, expr: ast.AST) -> list[str] | None:
            if isinstance(expr, (ast.List, ast.Tuple)) and all(
                isinstance(e, ast.Constant) and isinstance(e.value, str) for e in expr.elts
            ):
                return [e.value for e in expr.elts]
            if isinstance(expr, ast.Name) and expr.id in self.cur_list:
                return list(self.cur_list[expr.id])
            if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
                left = self._resolve_list(expr.left)
                right = self._resolve_list(expr.right)
                if left is not None and right is not None:
                    return left + right
            return None

        def _resolve_str(self, expr: ast.AST) -> str | None:
            if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
                return expr.value
            if isinstance(expr, ast.Name) and expr.id in self.cur_str:
                return self.cur_str[expr.id]
            if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
                left = self._resolve_str(expr.left)
                right = self._resolve_str(expr.right)
                if left is not None and right is not None:
                    return left + right
            if (
                isinstance(expr, ast.Call)
                and isinstance(expr.func, ast.Attribute)
                and expr.func.attr == "join"
                and isinstance(expr.func.value, ast.Constant)
                and isinstance(expr.func.value.value, str)
                and len(expr.args) == 1
            ):
                sep = expr.func.value.value
                elts = self._resolve_list(expr.args[0])
                if elts is not None:
                    return sep.join(elts)
            return None

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._push()
            try:
                self.generic_visit(node)
            finally:
                self._pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._push()
            try:
                self.generic_visit(node)
            finally:
                self._pop()

        def visit_Assign(self, node: ast.Assign) -> None:
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                as_list = self._resolve_list(node.value)
                if as_list is not None:
                    self.cur_list[name] = as_list
                as_str = self._resolve_str(node.value)
                if as_str is not None:
                    self.cur_str[name] = as_str
            self.generic_visit(node)

        def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
            body = _static_body(node)
            if _looks_like_sql(body):
                for v in node.values:
                    if not isinstance(v, ast.FormattedValue):
                        continue
                    resolved = self._resolve_str(v.value)
                    if resolved is None:
                        snippet = ast.unparse(v.value)
                        line = node.lineno
                        # Honor the explicit waiver, if any.
                        for (w_path, w_line, w_snip), reason in waivers.items():
                            if w_path == rel and w_line == line and w_snip in snippet:
                                # Waiver matched.
                                break
                        else:
                            findings.append(
                                f"{rel}:{line} — "
                                f"unsafe interpolation `{{{snippet}}}` in "
                                "SQL f-string. Use bound params "
                                '(`text(":name")`) or a SQLAlchemy core '
                                "construct."
                            )
            self.generic_visit(node)

    Visitor().visit(tree)
    return findings


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


def test_modules_root_resolves():
    assert MODULES_ROOT.is_dir(), (
        f"app/modules not found at {MODULES_ROOT}; the repo layout changed"
    )


@pytest.mark.parametrize(
    "service_path",
    _iter_module_services(),
    ids=lambda p: str(p.relative_to(MODULES_ROOT)),
)
def test_no_unsafe_fstring_sql(service_path: Path):
    findings = _scan(service_path)
    assert not findings, "Unsafe SQL f-string detected:\n  " + "\n  ".join(findings)


def test_lint_actually_catches_bad_pattern(tmp_path: Path):
    """Self-test — make sure the linter would actually reject a real
    bad pattern. If this regresses to passing on bad code, the rule
    above is silently broken."""
    bad = tmp_path / "bad_service.py"
    bad.write_text(
        "from sqlalchemy import text\n"
        "def fetch(conn, table_name):\n"
        "    return conn.execute(\n"
        "        text(f'SELECT * FROM {table_name} WHERE x = 1')\n"
        "    )\n",
        encoding="utf-8",
    )

    findings = _scan(bad)

    assert findings, (
        "Linter failed to flag a literal f-string SQL with a function-arg "
        "interpolation — the rule is broken."
    )
    assert "table_name" in findings[0]


def test_lint_allows_known_safe_pattern(tmp_path: Path):
    """Module-level constant interpolation (column lists) should pass."""
    good = tmp_path / "good_service.py"
    good.write_text(
        "from sqlalchemy import text\n"
        "_COLS = ['a', 'b', 'c']\n"
        "_COL_SQL = ', '.join(_COLS)\n"
        "def fetch(conn):\n"
        "    return conn.execute(\n"
        "        text(f'SELECT {_COL_SQL} FROM mart_x WHERE tenant_id = :tid'),\n"
        "        {'tid': 'abc'},\n"
        "    )\n",
        encoding="utf-8",
    )

    findings = _scan(good)
    assert not findings, f"Linter incorrectly flagged a safe column-list interpolation: {findings}"


def test_lint_allows_concat_of_safe_lists(tmp_path: Path):
    """`cols = _A + _B` where both are module-level literal lists is safe."""
    good = tmp_path / "good_concat.py"
    good.write_text(
        "from sqlalchemy import text\n"
        "_A = ['a', 'b']\n"
        "_B = ['c', 'd']\n"
        "def fetch(conn):\n"
        "    cols = _A + _B\n"
        "    col_sql = ', '.join(cols)\n"
        "    return conn.execute(\n"
        "        text(f'SELECT {col_sql} FROM m WHERE tenant_id = :tid'),\n"
        "        {'tid': 'x'},\n"
        "    )\n",
        encoding="utf-8",
    )

    findings = _scan(good)
    assert not findings, f"Linter rejected concat-of-safe-lists: {findings}"


def test_waivers_are_well_formed():
    """Each KNOWN_SAFE_FSTRING_SQL entry must:
      * point at a real file,
      * point at an in-range line, and
      * actually wave a finding when `_scan` runs against the file with
        the waiver entry temporarily removed.

    The third check is the strict one: it guarantees a stale waiver
    (one whose target was already refactored away) shows up red rather
    than silently rotting in the allowlist."""
    global KNOWN_SAFE_FSTRING_SQL  # noqa: PLW0603

    for rel, line, snippet, reason in KNOWN_SAFE_FSTRING_SQL:
        path = BACKEND_ROOT / rel
        assert path.exists(), f"waiver target missing: {rel}"

        src = path.read_text(encoding="utf-8").splitlines()
        assert 1 <= line <= len(src), f"waiver line {line} out of range for {rel}"

        # Run _scan with this single waiver removed — the file should
        # produce a finding that matches our (line, snippet). If it
        # doesn't, the waiver is stale and should be deleted.
        original = list(KNOWN_SAFE_FSTRING_SQL)
        KNOWN_SAFE_FSTRING_SQL = [
            e
            for e in KNOWN_SAFE_FSTRING_SQL
            if not (e[0] == rel and e[1] == line and e[2] == snippet)
        ]
        try:
            findings = _scan(path)
        finally:
            KNOWN_SAFE_FSTRING_SQL = original

        match = any(f"{rel}:{line}" in finding and snippet in finding for finding in findings)
        assert match, (
            f"stale waiver: {rel}:{line} `{snippet}` no longer triggers "
            f"a finding when removed. Either delete the waiver, fix the "
            f"SQL, or update line/snippet. Reason: {reason}"
        )
