"""What a mutant is.

`content_hash` deliberately covers only the file, the line range and the
mutated code. Two generators proposing the same edit for different stated
reasons are one mutant, and paying for both would waste a sandbox operation
to learn the same thing twice.

`original_src` and `mutated_src` are ALWAYS the complete module text, never a
fragment, whichever generator built the mutant. `mutated_src` is exactly what
gets written over the file in the sandbox, and the gate parses both as whole
modules. Once these fields meant a whole file to one generator and a hunk to
the other; a fragment written as a file destroys it, its tests error, and an
error reads as "killed". `start_line`/`end_line` are the hunk the mutant came
from, not the mutated file's extent.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

MutantSource = Literal["deterministic", "llm"]


@dataclass(frozen=True)
class Mutant:
    file: str
    start_line: int
    end_line: int
    operator: str
    original_src: str
    mutated_src: str
    rationale: str
    source: MutantSource

    @property
    def content_hash(self) -> str:
        payload = f"{self.file}:{self.start_line}-{self.end_line}:{self.mutated_src}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
