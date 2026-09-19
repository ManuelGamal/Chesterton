"""Deterministic mutation operators, scoped to changed lines.

Two passes. `find_candidates` walks the module and records every node inside
the target lines an operator can act on. `apply_candidate` then rebuilds the
module mutating exactly one of them. One candidate, one mutant — a transformer
that mutated every match at once would produce a single unusable super-mutant.

LibCST rather than `ast` because it round-trips formatting and comments, so a
mutant differs from its original in exactly one way rather than in one way plus
a reformatting.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider


@dataclass(frozen=True)
class Candidate:
    operator: str
    line: int
    description: str
    #: Start column of the target node. Line alone cannot distinguish two
    #: mutable nodes on the same line, and picking the wrong one would
    #: mis-attribute a surviving mutant.
    column: int = 0
    #: Which comparator within a Comparison node. Ignored by other operators.
    index: int = 0


#: Boundary flips that produce an off-by-one rather than a negation.
_WIDEN = {
    cst.LessThan: cst.LessThanEqual,
    cst.LessThanEqual: cst.LessThan,
    cst.GreaterThan: cst.GreaterThanEqual,
    cst.GreaterThanEqual: cst.GreaterThan,
}


def _snippet(node: cst.CSTNode) -> str:
    text = cst.Module(body=[]).code_for_node(node).strip()
    return text if len(text) <= 60 else text[:57] + "..."


def _comparator_text(node: cst.Comparison, index: int) -> str:
    """Render just the one comparison being targeted, e.g. `a > b`."""
    left = node.left if index == 0 else node.comparisons[index - 1].comparator
    target = node.comparisons[index]
    operator = cst.Module(body=[]).code_for_node(target.operator).strip()
    return f"{_snippet(left)} {operator} {_snippet(target.comparator)}"


def _is_bare_call(small: cst.BaseSmallStatement) -> bool:
    return isinstance(small, cst.Expr) and isinstance(small.value, cst.Call)


def _is_guard(node: cst.If) -> bool:
    """True when an if-block exists only to bail out.

    A guard's body ENDS in a raise or a return, and anything before that is a
    bare call: logging or reporting the failure it is about to raise. An if
    that does real work is a different mutation entirely. Deleting it is noisy
    rather than pointed, and the spec's operator is specifically the quiet
    removal of a bail-out.

    Bare calls were admitted on live evidence (2026-09-19). nomenclature PR
    #284's guard logs, then raises, and the old rule (raise/return only) never
    offered the headline operator on the headline case. Assignments before
    the exit are still excluded; widening further is a separate decision.
    """
    if node.orelse is not None:
        return False
    body = node.body.body if isinstance(node.body, cst.IndentedBlock) else []
    smalls: list[cst.BaseSmallStatement] = []
    for statement in body:
        if not isinstance(statement, cst.SimpleStatementLine):
            return False
        smalls.extend(statement.body)
    if not smalls or not isinstance(smalls[-1], (cst.Raise, cst.Return)):
        return False
    return all(
        isinstance(small, (cst.Raise, cst.Return)) or _is_bare_call(small)
        for small in smalls[:-1]
    )


class _Collector(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, lines: set[int]) -> None:
        self.lines = lines
        self.found: list[Candidate] = []

    def _line(self, node: cst.CSTNode) -> int:
        return self.get_metadata(PositionProvider, node).start.line

    def _column(self, node: cst.CSTNode) -> int:
        return self.get_metadata(PositionProvider, node).start.column

    def visit_Decorator(self, node: cst.Decorator) -> None:
        line = self._line(node)
        if line in self.lines:
            self.found.append(
                Candidate(
                    "strip_decorator",
                    line,
                    f"remove {_snippet(node)}",
                    column=self._column(node),
                )
            )

    def visit_If(self, node: cst.If) -> None:
        line = self._line(node)
        if line in self.lines:
            self.found.append(
                Candidate(
                    "invert_condition",
                    line,
                    f"negate {_snippet(node.test)}",
                    column=self._column(node),
                )
            )
        if line in self.lines and _is_guard(node):
            self.found.append(
                Candidate(
                    "delete_guard",
                    line,
                    f"delete guard {_snippet(node.test)}",
                    column=self._column(node),
                )
            )

    def visit_Await(self, node: cst.Await) -> None:
        line = self._line(node)
        if line in self.lines:
            self.found.append(
                Candidate(
                    "drop_await",
                    line,
                    f"drop await on {_snippet(node.expression)}",
                    column=self._column(node),
                )
            )

    def visit_ExceptHandler(self, node: cst.ExceptHandler) -> None:
        line = self._line(node)
        if line in self.lines and node.type is not None:
            self.found.append(
                Candidate(
                    "widen_except",
                    line,
                    f"widen {_snippet(node.type)} to bare except",
                    column=self._column(node),
                )
            )

    def visit_Finally(self, node: cst.Finally) -> None:
        line = self._line(node)
        if line in self.lines:
            self.found.append(
                Candidate(
                    "remove_cleanup",
                    line,
                    "empty the finally block",
                    column=self._column(node),
                )
            )

    def visit_Comparison(self, node: cst.Comparison) -> None:
        line = self._line(node)
        if line not in self.lines:
            return
        column = self._column(node)
        for index, target in enumerate(node.comparisons):
            if type(target.operator) in _WIDEN:
                self.found.append(
                    Candidate(
                        "off_by_one",
                        line,
                        f"shift boundary in {_comparator_text(node, index)}",
                        column=column,
                        index=index,
                    )
                )


class _Applier(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, target: Candidate) -> None:
        self.target = target
        self.applied = False

    def _column(self, node: cst.CSTNode) -> int:
        return self.get_metadata(PositionProvider, node).start.column

    def _hits(self, node: cst.CSTNode, operator: str) -> bool:
        if self.applied or self.target.operator != operator:
            return False
        position = self.get_metadata(PositionProvider, node).start
        return position.line == self.target.line and position.column == self.target.column

    def leave_Decorator(self, original: cst.Decorator, updated: cst.Decorator):
        if self._hits(original, "strip_decorator"):
            self.applied = True
            return cst.RemoveFromParent()
        return updated

    def leave_If(self, original: cst.If, updated: cst.If):
        if self._hits(original, "delete_guard"):
            self.applied = True
            return cst.RemoveFromParent()
        if self._hits(original, "invert_condition"):
            self.applied = True
            return updated.with_changes(
                test=cst.UnaryOperation(
                    operator=cst.Not(),
                    expression=cst.parse_expression(
                        f"({cst.Module(body=[]).code_for_node(updated.test)})"
                    ),
                )
            )
        return updated

    def leave_Await(self, original: cst.Await, updated: cst.Await):
        if self._hits(original, "drop_await"):
            self.applied = True
            return updated.expression
        return updated

    def leave_Try(self, original: cst.Try, updated: cst.Try):
        # Bare `except:` is only legal as a try's *last* handler — LibCST
        # itself enforces this. Whether our target handler is the last one is
        # a property of its parent Try, not of the handler alone, so this
        # candidate is resolved here rather than in leave_ExceptHandler.
        if self.applied or self.target.operator != "widen_except":
            return updated
        for index, handler in enumerate(original.handlers):
            position = self.get_metadata(PositionProvider, handler).start
            if (
                position.line != self.target.line
                or position.column != self.target.column
            ):
                continue
            self.applied = True
            is_last = index == len(original.handlers) - 1
            new_handlers = list(updated.handlers)
            if is_last:
                # Dropping the type leaves LibCST's whitespace_after_except
                # intact, which renders `except :`. Valid Python, but it
                # reads as a tool artifact rather than a plausible human
                # edit — and a mutant that looks machine-generated
                # undermines the finding it supports.
                new_handlers[index] = new_handlers[index].with_changes(
                    type=None,
                    name=None,
                    whitespace_after_except=cst.SimpleWhitespace(""),
                )
            else:
                # A bare `except:` here would make LibCST refuse to render
                # the tree ("must be the last one"). `except Exception:` is
                # legal wherever it sits, and it is exactly the widening an
                # agent quietly makes in real code: it now swallows what the
                # later, narrower handler was written to catch.
                new_handlers[index] = new_handlers[index].with_changes(
                    type=cst.Name("Exception"),
                    name=None,
                    whitespace_after_except=cst.SimpleWhitespace(" "),
                )
            return updated.with_changes(handlers=new_handlers)
        return updated

    def leave_Finally(self, original: cst.Finally, updated: cst.Finally):
        if self._hits(original, "remove_cleanup"):
            self.applied = True
            # Emptied, not deleted: removing the clause from a try that has no
            # except handler would leave invalid Python.
            return updated.with_changes(
                body=cst.IndentedBlock(
                    body=[cst.SimpleStatementLine(body=[cst.Pass()])]
                )
            )
        return updated

    def leave_Comparison(self, original: cst.Comparison, updated: cst.Comparison):
        if not self._hits(original, "off_by_one"):
            return updated
        self.applied = True
        widened = list(updated.comparisons)
        index = self.target.index
        replacement = _WIDEN.get(type(widened[index].operator))
        if replacement is not None:
            widened[index] = widened[index].with_changes(operator=replacement())
        return updated.with_changes(comparisons=widened)


def find_candidates(source: str, lines: Sequence[int]) -> list[Candidate]:
    try:
        wrapper = MetadataWrapper(cst.parse_module(source))
    except cst.ParserSyntaxError:
        return []

    collector = _Collector(set(lines))
    wrapper.visit(collector)
    return collector.found


def apply_candidate(source: str, candidate: Candidate) -> str:
    wrapper = MetadataWrapper(cst.parse_module(source))
    return wrapper.visit(_Applier(candidate)).code
