"""The only way a mutant becomes eligible for execution.

Three rejections, each for a concrete reason:

- unchanged: nothing to learn, and it would still cost a sandbox operation —
  worse, a no-op survives every suite and would be reported as a behaviour
  change the tests permit. A mutant is admitted only once it is shown to
  differ: by its AST when both sides compile, by its layout-free tokens when
  either does not. No path skips the check;
- unparseable: the mutant will not compile, so its tests ERROR, which the
  runner reads as "killed" — a silent false negative;
- duplicate: the same edit already admitted, from either generator.

Rejections are counted rather than logged so the run can report what it threw
away. A generator quietly producing 90% garbage should be visible.
"""

from __future__ import annotations

import ast
import io
import tokenize
import warnings

from chesterton.mutation.model import Mutant


#: Statements after which the rest of their block can never run.
_TERMINAL = (ast.Return, ast.Raise, ast.Continue, ast.Break)


def _inert(statement: ast.stmt) -> bool:
    """True when an UNREACHABLE statement's mere presence changes nothing.

    Dead code is not always inert. A name bound anywhere in a function is
    local to all of it, so `return x` followed by `x = 1` raises
    UnboundLocalError; a `yield` anywhere makes the function a generator;
    `global`/`nonlocal` change scope for the whole block. Any of those, and
    the statement stays.
    """
    for node in ast.walk(statement):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            return False
        if isinstance(node, (
            ast.Global, ast.Nonlocal, ast.Yield, ast.YieldFrom, ast.Import,
            ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
            ast.NamedExpr,
        )):
            return False
        if isinstance(node, ast.ExceptHandler) and node.name:
            return False
        if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            return False
        if isinstance(node, ast.MatchMapping) and node.rest:
            return False
    return True


def _tidy(block: list[ast.stmt]) -> list[ast.stmt]:
    kept: list[ast.stmt] = []
    for index, statement in enumerate(block):
        kept.append(statement)
        if isinstance(statement, _TERMINAL):
            tail = block[index + 1 :]
            if not all(_inert(s) for s in tail):
                kept.extend(tail)
            break
    real = [s for s in kept if not isinstance(s, ast.Pass)]
    return real or [ast.Pass()]


class _Behaviour(ast.NodeTransformer):
    """Rewrites a tree to what it DOES, under two provably sound rules.

    1. A `pass` beside other statements in a block does nothing.
    2. Inert statements after `return`, `raise`, `continue` or `break` never
       run, and (see _inert) their presence changes nothing either.

    Nothing else. `is None` vs `== None`, `not x` vs `x is False` and
    annotation or docstring changes are all observable in some program, via
    a custom __eq__, a non-bool value, or introspection, so none is erased.
    """

    def generic_visit(self, node: ast.AST) -> ast.AST:
        super().generic_visit(node)
        for field, value in ast.iter_fields(node):
            if isinstance(value, list) and value and all(isinstance(v, ast.stmt) for v in value):
                setattr(node, field, _tidy(value))
        return node


def _behaviour(tree: ast.Module) -> str:
    return ast.dump(_Behaviour().visit(tree))


def _normalised(source: str) -> str | None:
    """The source's AST serialised by `ast.dump`, or None if it will not compile.

    Comparing dumps rather than text means a pure reformatting counts as no
    change, which is exactly what we want — it is not a mutation.

    Parsing alone is not enough to promise the file will import. `ast.parse`
    accepts `return` outside a function, `await` outside a coroutine and
    `break` outside a loop; those are rejected later, by the compiler. A model
    reply spliced in one indentation level too shallow produces exactly that
    shape, so the tree is compiled too.
    """
    try:
        tree = ast.parse(source)
        # compile(), unlike ast.parse(), emits compiler-stage SyntaxWarnings
        # (e.g. `"is" with a literal`). Under a process-wide `-W error` (or
        # any filter that promotes warnings to errors), one of those would
        # raise SyntaxError here for code that is perfectly valid — silently
        # losing a legitimate mutant and mislabelling it "unparseable". Gate
        # admission must not depend on the warnings filter in effect.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            compile(tree, "<mutant>", "exec", dont_inherit=True)
    except (SyntaxError, ValueError):  # ValueError: source with a NUL byte
        return None
    return ast.dump(tree)


#: Tokens that carry layout or commentary, not behaviour.
_LAYOUT_TOKENS = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
    }
)


def _layout_free(source: str) -> tuple[str, ...]:
    """The source's tokens without whitespace, indentation or comments.

    The fallback comparison for source that will not compile, where there is
    no AST to dump. It errs towards "unchanged": a difference in indentation
    alone does not count, because without a tree nothing proves it changes
    behaviour. When even tokenising fails, whitespace-separated words stand in.
    """
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        return tuple(t.string for t in tokens if t.type not in _LAYOUT_TOKENS)
    except (tokenize.TokenError, SyntaxError):
        return tuple(source.split())


class MutantGate:
    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._originals: dict[str, str | None] = {}
        self._behaviours: dict[str, str] = {}
        self.rejected: dict[str, int] = {}

    def _reject(self, reason: str) -> bool:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1
        return False

    def admit(self, mutant: Mutant) -> bool:
        mutated = _normalised(mutant.mutated_src)
        original = self._original(mutant.original_src)

        if mutated is not None and original is not None:
            differs = mutated != original
        else:
            # One side will not compile, so there is no pair of trees to
            # compare. Skipping the check here once admitted a mutant
            # identical to its original — and a no-op survives every suite by
            # construction. Compare layout-free tokens instead; a mutant not
            # shown to differ is never admitted.
            differs = _layout_free(mutant.mutated_src) != _layout_free(
                mutant.original_src
            )
        if not differs:
            return self._reject("unchanged")

        if mutated is None:
            return self._reject("unparseable")

        # Both compile, and they differ as text. Do they differ in what they
        # DO? A provable no-op survives every suite and would be scored as a
        # behaviour change the tests permit (live: `pass` after a `raise`).
        if original is not None and self._behaviour_of(mutant.mutated_src) == (
            self._behaviour_of(mutant.original_src)
        ):
            return self._reject("no_op")

        if mutant.content_hash in self._seen:
            return self._reject("duplicate")

        self._seen.add(mutant.content_hash)
        return True

    def _original(self, source: str) -> str | None:
        """`_normalised`, memoised: every mutant of a file shares its original."""
        if source not in self._originals:
            self._originals[source] = _normalised(source)
        return self._originals[source]

    def _behaviour_of(self, source: str) -> str:
        """`_behaviour` of source already known to compile, memoised."""
        if source not in self._behaviours:
            self._behaviours[source] = _behaviour(ast.parse(source))
        return self._behaviours[source]
