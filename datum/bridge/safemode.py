"""``safe_mode`` for run_script: an AST allowlist, checked before running.

Deny by default,
walk every node, refuse what is not listed, and say why. It is a guard on
what a model can be talked into writing (prompt injection through a file
it read, say), not a sandbox: ``run_script`` already runs in a separate
process on a copy of the document, with a timeout, and with the user's own
privileges. Python cannot be made into a sandbox from the inside, and this
does not pretend to.

What it refuses: imports other than a few pure modules, the builtins that
reach outside (open, eval, exec, compile, __import__, globals, ...),
dunder attributes (the ``__class__.__subclasses__`` ladder), and
``getattr``-style calls with a computed name.
"""

from __future__ import annotations

import ast
from typing import List, Optional

ALLOWED_MODULES = frozenset({"math", "itertools", "functools", "collections",
                             "statistics", "fractions", "decimal", "random",
                             "string", "re", "json", "csv", "io"})
FORBIDDEN_CALLS = {
    "eval": "eval() runs arbitrary expressions",
    "exec": "exec() runs arbitrary code",
    "compile": "compile() makes code objects",
    "__import__": "__import__() goes round the import allowlist",
    "open": "open() reaches the file system",
    "input": "input() would wait on a pipe nobody answers",
    "breakpoint": "breakpoint() opens a debugger",
    "exit": "exit() ends the host", "quit": "quit() ends the host",
    "globals": "globals() exposes the namespace",
    "locals": "locals() exposes the namespace",
    "vars": "vars() exposes an object's __dict__",
    "memoryview": "memoryview() reaches raw memory",
    "help": "help() imports arbitrary modules",
}
LITERAL_ONLY = frozenset({"getattr", "setattr", "delattr", "hasattr"})
SAFE_BUILTINS = frozenset({
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter",
    "float", "format", "frozenset", "int", "isinstance", "iter", "len",
    "list", "map", "max", "min", "next", "pow", "print", "range",
    "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple",
    "zip", "ValueError", "TypeError", "KeyError", "IndexError",
    "RuntimeError", "ZeroDivisionError", "Exception", "StopIteration",
    "True", "False", "None", "getattr", "hasattr", "repr", "chr", "ord",
    "hex", "bin", "complex", "callable", "id", "hash", "issubclass",
    "ArithmeticError", "LookupError", "AssertionError", "NotImplemented",
})
# node types a script may contain at all
_NODES = tuple(getattr(ast, n) for n in (
    "Module", "Expr", "Assign", "AugAssign", "AnnAssign", "For", "While",
    "If", "With", "Break", "Continue", "Pass", "Return", "FunctionDef",
    "Lambda", "arguments", "arg", "keyword", "Try", "ExceptHandler",
    "Raise", "Assert", "Delete", "Import", "ImportFrom", "alias",
    "BoolOp", "BinOp", "UnaryOp", "IfExp", "Dict", "Set", "List", "Tuple",
    "ListComp", "SetComp", "DictComp", "GeneratorExp", "comprehension",
    "Compare", "Call", "Constant", "Attribute", "Subscript", "Slice",
    "Starred", "Name", "Load", "Store", "Del", "JoinedStr", "FormattedValue",
    "And", "Or", "Add", "Sub", "Mult", "Div", "FloorDiv", "Mod", "Pow",
    "MatMult", "LShift", "RShift", "BitOr", "BitXor", "BitAnd", "Invert",
    "Not", "UAdd", "USub", "Eq", "NotEq", "Lt", "LtE", "Gt", "GtE", "Is",
    "IsNot", "In", "NotIn", "withitem", "Global", "Nonlocal")
    if hasattr(ast, n))


class SafeModeViolation(ValueError):
    def __init__(self, message: str, line: Optional[int]) -> None:
        super().__init__(message)
        self.line = line or 0


def check(source: str) -> None:
    """Raise :class:`SafeModeViolation` at the first thing not allowed."""
    try:
        tree = ast.parse(source, "<script>", "exec")
    except SyntaxError as exc:
        raise SafeModeViolation("syntax: %s" % exc.msg, exc.lineno) from exc
    for node in ast.walk(tree):
        line = getattr(node, "lineno", None)
        if not isinstance(node, _NODES):
            raise SafeModeViolation("%s is not allowed in safe mode"
                                    % type(node).__name__, line)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_MODULES:
                    raise SafeModeViolation("import %s is not allowed; "
                                            "allowed: %s" % (
                                                alias.name, ", ".join(
                                                    sorted(ALLOWED_MODULES))),
                                            line)
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_MODULES \
                    or node.level:
                raise SafeModeViolation("from %s import is not allowed"
                                        % node.module, line)
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise SafeModeViolation("attribute %s is not allowed (names "
                                    "starting _ are private)" % node.attr,
                                    line)
        if isinstance(node, ast.Name):
            if node.id in FORBIDDEN_CALLS:
                raise SafeModeViolation(FORBIDDEN_CALLS[node.id], line)
            if node.id.startswith("__"):
                raise SafeModeViolation("%s is not allowed" % node.id, line)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in LITERAL_ONLY:
            if len(node.args) < 2 or not isinstance(node.args[1],
                                                    ast.Constant) \
                    or not isinstance(node.args[1].value, str) \
                    or node.args[1].value.startswith("_"):
                raise SafeModeViolation("%s needs a literal, public name"
                                        % node.func.id, line)


def builtins() -> dict:
    import builtins as b
    out = {k: getattr(b, k) for k in SAFE_BUILTINS if hasattr(b, k)}
    real_import = b.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name.split(".")[0] not in ALLOWED_MODULES or level:
            raise ImportError("import %s is not allowed in safe mode" % name)
        return real_import(name, globals, locals, fromlist, level)

    out["__import__"] = guarded
    return out


__all__: List[str] = ["check", "builtins", "SafeModeViolation"]
