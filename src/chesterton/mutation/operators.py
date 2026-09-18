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
