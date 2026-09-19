"""The only way a mutant becomes eligible for execution.

Three rejections, cheapest first, each for a concrete reason:

- unparseable: the mutant will not compile, so its tests ERROR, which the
  runner reads as "killed" — a silent false negative;
- unchanged: nothing to learn, and it would still cost a sandbox operation;
- duplicate: the same edit already admitted, from either generator.

Rejections are counted rather than logged so the run can report what it threw
away. A generator quietly producing 90% garbage should be visible.
"""

from __future__ import annotations

import ast

from chesterton.mutation.model import Mutant


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
        compile(tree, "<mutant>", "exec", dont_inherit=True)
    except (SyntaxError, ValueError):  # ValueError: source with a NUL byte
        return None
    return ast.dump(tree)


class MutantGate:
    def __init__(self) -> None:
        self._seen: set[str] = set()
        self.rejected: dict[str, int] = {}

    def _reject(self, reason: str) -> bool:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1
        return False

    def admit(self, mutant: Mutant) -> bool:
        mutated = _normalised(mutant.mutated_src)
        if mutated is None:
            return self._reject("unparseable")

        original = _normalised(mutant.original_src)
        if original is not None and mutated == original:
            return self._reject("unchanged")

        if mutant.content_hash in self._seen:
            return self._reject("duplicate")

        self._seen.add(mutant.content_hash)
        return True
