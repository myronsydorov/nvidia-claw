"""Static gate: an AST check on generated watcher code, run before any sandbox work.

Defense in depth only (THREAT_MODEL A2). The boundary is still the watcher's own
sandbox plus a policy generated from adapter declarations; this gate just refuses
obviously out-of-bounds code early and gives the model a precise reason to fix.

Rules:
- size: ≤ MAX_BYTES and ≤ MAX_LINES;
- imports: only `watcher_runtime.harness` and `watcher_runtime.adapters.<name>` for
  the adapters this watcher declared, which rules out subprocess, os, socket,
  httpx and everything else. On an imported module, only its public API may be
  used (harness `__all__`, adapter `fetch`/`parse`), so `parcel_dhl.httpx` is
  unreachable;
- attribute access is an ALLOWLIST (module APIs above plus plain dict/list/str/
  datetime methods): no `format`/`format_map` (runtime-built format strings),
  no `gi_frame`/`f_builtins`/`mro` introspection chains (security review T-09);
- no `match` statements (class patterns look up attributes by string) and no
  class definitions; no identifier anywhere (names, attributes, defs, args,
  keywords, aliases) may start with `_`; no "__" inside string literals;
- no dynamic-code or introspection builtins (eval, exec, compile, __import__,
  getattr, type, object, chr, print, ...);
- `open()` only with a literal path under /tmp/;
- every http(s):// literal must match an endpoint this watcher declared.
"""

import ast
from urllib.parse import urlsplit

from warden.adapters.base import Endpoint

MAX_BYTES = 8 * 1024
MAX_LINES = 250

HARNESS_API = frozenset(
    {"emit", "fail", "now", "parse_time", "hours_until", "load_state", "save_state"}
)
ADAPTER_API = frozenset({"fetch", "parse"})
# Methods of the plain values adapters return (dict/list/str) and of datetimes.
VALUE_ATTRIBUTES = frozenset(
    {
        # dict / list
        "get",
        "items",
        "keys",
        "values",
        "append",
        "extend",
        "insert",
        "pop",
        "sort",
        "index",
        "count",
        "copy",
        "setdefault",
        "update",
        # str
        "lower",
        "upper",
        "strip",
        "lstrip",
        "rstrip",
        "startswith",
        "endswith",
        "split",
        "join",
        "replace",
        "find",
        "isdigit",
        "title",
        "casefold",
        "splitlines",
        # a file opened under /tmp/
        "read",
        "write",
        # datetime / timedelta
        "isoformat",
        "date",
        "year",
        "month",
        "day",
        "hour",
        "minute",
        "weekday",
        "total_seconds",
        "days",
        "seconds",
    }
)
FORBIDDEN_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "hasattr",
        "globals",
        "locals",
        "vars",
        "dir",
        "breakpoint",
        "input",
        "exit",
        "quit",
        "help",
        "memoryview",
        "classmethod",
        "staticmethod",
        "super",
        "type",
        "object",
        "chr",
        "print",
        "format",
        "id",
        "iter",
        "next",
        "property",
    }
)


class GateError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def check(code: str, adapters: list[str], endpoints: list[Endpoint]) -> None:
    """Raise GateError listing every problem found; return None if the code passes."""
    problems: list[str] = []
    if len(code.encode("utf-8")) > MAX_BYTES:
        problems.append(f"run.py is larger than {MAX_BYTES} bytes")
    if code.count("\n") + 1 > MAX_LINES:
        problems.append(f"run.py is longer than {MAX_LINES} lines")
    try:
        tree = ast.parse(code, filename="run.py")
    except SyntaxError as exc:
        raise GateError(problems + [f"syntax error on line {exc.lineno}: {exc.msg}"]) from None
    visitor = _Visitor(set(adapters), endpoints)
    visitor.visit(tree)
    _check_identifiers(tree, visitor)
    problems += visitor.problems
    if not visitor.emits:
        problems.append("run.py never calls harness.emit() or harness.fail()")
    if problems:
        raise GateError(problems)


_IDENTIFIER_FIELDS = ("name", "id", "attr", "arg", "asname")


def _check_identifiers(tree: ast.AST, visitor: "_Visitor") -> None:
    """No identifier of any kind may start with `_` (dunder defs, kwargs, match captures...)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Match):
            visitor._bad(node, "match statements are not allowed")
        elif isinstance(node, ast.ClassDef):
            visitor._bad(node, "class definitions are not allowed")
        for field in _IDENTIFIER_FIELDS:
            value = getattr(node, field, None)
            if isinstance(value, str) and value.startswith("_"):
                visitor._bad(node, f"identifier {value!r} is not allowed")
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                if name.startswith("_"):
                    visitor._bad(node, f"identifier {name!r} is not allowed")


class _Visitor(ast.NodeVisitor):
    def __init__(self, adapters: set[str], endpoints: list[Endpoint]) -> None:
        self.adapters = adapters
        self.endpoints = endpoints
        self.problems: list[str] = []
        self.modules: dict[str, frozenset[str]] = {}  # local alias -> its allowed attributes
        self.emits = False

    def _bad(self, node: ast.AST, why: str) -> None:
        self.problems.append(f"line {getattr(node, 'lineno', '?')}: {why}")

    def _module_api(self, dotted: str) -> frozenset[str] | None:
        if dotted == "watcher_runtime.harness":
            return HARNESS_API
        prefix = "watcher_runtime.adapters."
        if dotted.startswith(prefix) and dotted[len(prefix) :] in self.adapters:
            return ADAPTER_API
        return None

    def visit_Module(self, node: ast.Module) -> None:
        # Register every import before checking any use, so a use that appears
        # earlier in the source (e.g. inside a function) is still checked as a module.
        top = [imp for imp in node.body if isinstance(imp, (ast.Import, ast.ImportFrom))]
        for imp in top:
            self.visit(imp)
        for child in ast.walk(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)) and child not in top:
                self._bad(child, "imports must be at the top level of run.py")
        for stmt in node.body:
            if stmt not in top:
                self.visit(stmt)

    # --- imports ---

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            api = self._module_api(alias.name)
            if api is None:
                self._bad(node, f"import of {alias.name!r} is not allowed")
            elif alias.asname is None:
                self._bad(node, f"use 'from ... import' or 'import {alias.name} as <name>'")
            else:
                self.modules[alias.asname] = api

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if node.level != 0:
            self._bad(node, "relative imports are not allowed")
            return
        for alias in node.names:
            bound = alias.asname or alias.name
            if alias.name == "*":
                self._bad(node, "star imports are not allowed")
                continue
            sub_api = self._module_api(f"{module}.{alias.name}")
            if sub_api is not None:  # from watcher_runtime import harness / adapters import x
                self.modules[bound] = sub_api
                continue
            api = self._module_api(module)
            if api is None:
                self._bad(node, f"import from {module!r} is not allowed")
            elif alias.name not in api:
                self._bad(node, f"{module}.{alias.name} is not part of the allowed API")
            elif alias.name in ("emit", "fail"):
                self.emits = True

    # --- names and attributes ---

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in FORBIDDEN_NAMES or node.id.startswith("__"):
            self._bad(node, f"{node.id!r} is not allowed")
        elif node.id in self.modules and isinstance(node.ctx, ast.Load):
            self._bad(node, f"module {node.id!r} may only be used as '{node.id}.<function>'")
        elif node.id == "open":
            self._bad(node, "open() may only be called directly, with a /tmp/ path")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name) and node.value.id in self.modules:
            if node.attr not in self.modules[node.value.id]:
                self._bad(node, f"{node.value.id}.{node.attr} is not part of the allowed API")
            if node.attr in ("emit", "fail"):
                self.emits = True
            return  # the module name itself is fine here
        if node.attr not in VALUE_ATTRIBUTES:
            self._bad(node, f"attribute {node.attr!r} is not allowed")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            self._check_open(node)
            for arg in [*node.args, *(k.value for k in node.keywords)]:
                self.visit(arg)
            return
        self.generic_visit(node)

    def _check_open(self, node: ast.Call) -> None:
        path = node.args[0] if node.args else None
        if not (
            isinstance(path, ast.Constant)
            and isinstance(path.value, str)
            and path.value.startswith("/tmp/")
            and ".." not in path.value
        ):
            self._bad(node, "open() is only allowed with a literal path under /tmp/")

    # --- literals ---

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, str):
            return
        if "__" in node.value:
            self._bad(node, "string literals may not contain '__'")
        text = node.value.strip()
        if text.lower().startswith(("http://", "https://")):
            self._check_url(node, text)

    def _check_url(self, node: ast.Constant, url: str) -> None:
        try:
            parts = urlsplit(url)
            host, port = parts.hostname or "", parts.port or 443
        except ValueError:
            self._bad(node, "malformed URL literal")
            return
        if parts.scheme != "https":
            self._bad(node, "only https URLs are allowed")
            return
        path = parts.path or "/"
        same_host = [e for e in self.endpoints if e.host == host and e.port == port]
        if not same_host:
            self._bad(node, f"URL host {host!r} is not declared by this watcher's adapters")
        elif not any(e.path == path for e in same_host):
            self._bad(node, f"URL path {path!r} on {host!r} is not declared")
