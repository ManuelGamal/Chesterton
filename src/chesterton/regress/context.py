"""The one existing test the model should imitate, not the whole file.

A covering test shows the model how this repository builds the objects the
code needs, and which fixtures and imports exist. The whole test file can be
thousands of lines (matplotlib's test_axes.py), so only its imports and the
test itself are sent.
"""

from __future__ import annotations

import ast

FALLBACK_LINES = 60


def _target(test_id: str) -> tuple[str | None, str]:
    parts = test_id.split("::")[1:]
    name = parts[-1].split("[", 1)[0] if parts else ""
    owner = parts[0] if len(parts) > 1 else None
    return owner, name


def _segment(lines: list[str], node: ast.AST) -> str:
    first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    return "\n".join(lines[first - 1 : node.end_lineno])


def covering_test_source(module_src: str, test_id: str) -> str:
    lines = module_src.split("\n")
    try:
        tree = ast.parse(module_src)
    except SyntaxError:
        return "\n".join(lines[:FALLBACK_LINES])
    owner, name = _target(test_id)
    imports = [
        _segment(lines, node) for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    scope = tree.body
    if owner is not None:
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner]
        scope = classes[0].body if classes else []
    found = [
        _segment(lines, node) for node in scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    if not found:
        return "\n".join(lines[:FALLBACK_LINES])
    return "\n".join(imports) + "\n\n\n" + found[0]
