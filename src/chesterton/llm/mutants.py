"""Ask Nemotron for mutations the deterministic operators cannot name.

Runs on the execution tier: called once per hunk across every seed, high
volume, low judgement. Thinking is disabled, so the reply should be JSON with
no preamble — but `parse_mutants` tolerates one anyway, because a single stray
sentence must not cost a whole batch.

A malformed reply yields no mutants rather than raising. The deterministic
operators are the floor; the model is upside.
"""

from __future__ import annotations

import json

from chesterton.llm.client import EXECUTION_MODEL
from chesterton.mutation.model import Mutant

_PROMPT = """\
You are helping audit a pull request by proposing small, plausible mutations \
to changed code. A good mutation removes or weakens a protection an author \
might delete by accident: a guard clause, a bounds check, an await, a cleanup \
call, a narrow exception.

File: {file}
Lines {start}-{end}:

```python
{source}
```

Propose up to {limit} mutations. Each must be the FULL replacement text for \
those lines, valid Python, and differ from the original in exactly one way.

Reply with JSON only, no prose:
{{"mutants": [{{"mutated_src": "...", "rationale": "...", \
"operator": "semantic"}}]}}
"""


def build_prompt(
    file: str, source: str, start_line: int, end_line: int, limit: int = 4
) -> str:
    return _PROMPT.format(
        file=file, source=source, start=start_line, end=end_line, limit=limit
    )


def _extract_json(reply: str) -> dict | None:
    start = reply.find("{")
    end = reply.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(reply[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_mutants(
    reply: str, *, file: str, start_line: int, end_line: int, original_src: str
) -> list[Mutant]:
    parsed = _extract_json(reply)
    if parsed is None:
        return []

    entries = parsed.get("mutants")
    if not isinstance(entries, list):
        # A model with nothing to propose may send `"mutants": null`. Iterating
        # that raises, which would abort a run over hundreds of hunks for a
        # reply that simply said "nothing here".
        return []

    mutants: list[Mutant] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        mutated = entry.get("mutated_src")
        if not isinstance(mutated, str) or not mutated:
            continue
        mutants.append(
            Mutant(
                file=file,
                start_line=start_line,
                end_line=end_line,
                operator=str(entry.get("operator", "semantic")),
                original_src=original_src,
                mutated_src=mutated,
                rationale=str(entry.get("rationale", "")),
                source="llm",
            )
        )
    return mutants


async def propose(
    client, *, file: str, source: str, start_line: int, end_line: int
) -> list[Mutant]:
    reply = await client.complete(
        build_prompt(file, source, start_line, end_line),
        model=EXECUTION_MODEL,
        max_tokens=2048,
    )
    return parse_mutants(
        reply,
        file=file,
        start_line=start_line,
        end_line=end_line,
        original_src=source,
    )
