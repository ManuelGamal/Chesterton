"""Survivors that are obvious equivalents, dropped before any model call.

Spec §9's first stage. Only rules that are right by construction belong
here: a survivor dropped here is never shown to anyone, so a wrong rule
would hide a real finding. Anything uncertain goes to the model instead.

One rule so far: every line the mutation changed is a logging or print call.
What those emit is output, not behaviour the program acts on.

The decision is made from a diff between the mutant's WHOLE original and
mutated modules (`difflib.unified_diff` with `n=0`), never from the display
window `Evidence.diff` is built from. Live 2026-09-23: some operators edit
past their own recorded hunk (`remove_cleanup` empties a whole `finally`
body, `delete_guard` removes a whole guard block), so a window sized from
start_line/end_line can show only part of the change — dismissing a
resource-cleanup survivor because the part shown happened to be all log
calls, while the removed `conn.close()` sat just past the window's edge. A
whole-module diff has no such edge: it is right by construction.

A changed line qualifies as logging-only iff textwrap.dedent(line).strip()
parses with ast.parse into a module of exactly ONE statement, that statement
is ast.Expr, and its value is an ast.Call whose callee is one of:
  - the name `print`, with no `file=` keyword (data written to a file is
    observable behaviour, not just output);
  - an attribute <receiver>.<method> where method is in {debug, info, warning,
    warn, error, exception, critical, log} and receiver is a Name in {log,
    logger, _log, _logger, logging, LOG, LOGGER}, or self.<that> / cls.<that>.
`warnings.warn` does NOT qualify: a warning's category is observable
(`pytest.warns`, `-W error`, matplotlib's own `filterwarnings = error`), so a
mutation that drops or changes it is real behaviour, not output.
AND no node anywhere inside the call's arguments (args and keyword values) is
an ast.Call, ast.NamedExpr, ast.Await, ast.Yield or ast.YieldFrom (an argument
with a side effect is real behaviour). A line that fails to parse does not
qualify. The rule is: every non-blank changed line qualifies, and there is at
least one such line.
"""

from __future__ import annotations

import ast
import difflib
import textwrap

from chesterton.mutation.model import Mutant
from chesterton.triage.evidence import Evidence, _lines

LOGGING_ONLY = "logging_only"

#: Logging method names that are safe to call.
_LOGGING_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}

#: Valid receiver names for logging attribute access.
_LOGGING_RECEIVERS = {"log", "logger", "_log", "_logger", "logging", "LOG", "LOGGER"}


def _changed(diff: str) -> list[str]:
    return [
        line[1:]
        for line in diff.splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]


def _is_logging_call(line: str) -> bool:
    """Check if a line is a pure logging call with no side effects."""
    try:
        parsed = ast.parse(textwrap.dedent(line).strip())
    except SyntaxError:
        return False

    # Exactly one statement, and it must be an expression statement.
    if len(parsed.body) != 1 or not isinstance(parsed.body[0], ast.Expr):
        return False

    call = parsed.body[0].value
    if not isinstance(call, ast.Call):
        return False

    # Check if the callee is an allowed logging function.
    callee = call.func
    if isinstance(callee, ast.Name):
        if callee.id != "print":
            return False
        # print(row, file=out) writes data somewhere observable; only a
        # file-less print is pure output.
        if any(keyword.arg in (None, "file") for keyword in call.keywords):
            return False
    elif isinstance(callee, ast.Attribute):
        if callee.attr not in _LOGGING_METHODS:
            return False

        receiver = callee.value
        # warnings.warn is deliberately NOT accepted here: its category is
        # observable behaviour (see the module docstring).
        if isinstance(receiver, ast.Name):
            if receiver.id in _LOGGING_RECEIVERS:
                pass  # Valid: log.debug, logger.info, etc.
            else:
                return False
        # Check for self.logger or cls.log
        elif isinstance(receiver, ast.Attribute):
            if isinstance(receiver.value, ast.Name) and receiver.value.id in ("self", "cls"):
                if receiver.attr in _LOGGING_RECEIVERS:
                    pass  # Valid: self.logger.debug, cls.log.info, etc.
                else:
                    return False
            else:
                return False
        else:
            return False
    else:
        return False

    # Check for side effects in arguments.
    class SideEffectChecker(ast.NodeVisitor):
        def __init__(self):
            self.has_side_effect = False

        def visit_Call(self, node: ast.Call) -> None:
            self.has_side_effect = True

        def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
            self.has_side_effect = True

        def visit_Await(self, node: ast.Await) -> None:
            self.has_side_effect = True

        def visit_Yield(self, node: ast.Yield) -> None:
            self.has_side_effect = True

        def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
            self.has_side_effect = True

    checker = SideEffectChecker()
    for arg in call.args:
        checker.visit(arg)
    for keyword in call.keywords:
        checker.visit(keyword.value)

    return not checker.has_side_effect


def _whole_module_diff(mutant: Mutant) -> str:
    """The diff the decision is made from: never the display window (F1)."""
    before, after = _lines(mutant.original_src), _lines(mutant.mutated_src)
    return "\n".join(difflib.unified_diff(before, after, n=0, lineterm=""))


def prefilter(ev: Evidence) -> str | None:
    changed = [line for line in _changed(_whole_module_diff(ev.mutant)) if line.strip()]
    if changed and all(_is_logging_call(line) for line in changed):
        return LOGGING_ONLY
    return None
