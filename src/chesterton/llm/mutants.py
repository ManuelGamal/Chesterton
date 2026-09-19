"""Ask Nemotron for mutations the deterministic operators cannot name.

Runs on the execution tier: called once per hunk across every seed, high
volume, low judgement. Thinking is disabled, so the reply should be JSON with
no preamble — but `parse_mutants` tolerates one anyway, because a single stray
sentence must not cost a whole batch.

A malformed reply yields no mutants rather than raising. The deterministic
operators are the floor; the model is upside.

`Mutant.mutated_src` is ALWAYS the complete module, from every generator. The
model is shown only the hunk and replies with replacement text for those
lines — asking it to echo back a whole file would be unaffordable on a large
module — so its reply is spliced back into the module here, before a `Mutant`
is ever built. That is what lets the gate parse a mutant as the file it will
become: a correctly indented reply for a hunk inside a function parses once
spliced, and a dedented one is caught as unparseable rather than written to
the sandbox as a two-line file whose tests all error and read as "killed".
Parameters named `module_src` are the whole file; `hunk_src` is the fragment.
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
lines {start}-{end} exactly as they should appear in the file — at the same \
indentation as shown, valid Python in place, and differing from the original \
in exactly one way.

Reply with JSON only, no prose:
{{"mutants": [{{"mutated_src": "...", "rationale": "..."}}]}}
"""


def build_prompt(
    file: str, hunk_src: str, start_line: int, end_line: int, limit: int = 4
) -> str:
    return _PROMPT.format(
        file=file, source=hunk_src, start=start_line, end=end_line, limit=limit
    )


def _physical_lines(text: str) -> list[str]:
    """Lines as `ast` and unified diffs number them, each keeping its ending.

    Split on "\\n" only. `str.splitlines` also breaks on form feeds and
    Unicode separators, which are legal inside Python source and would shift
    every line number after them — splicing a reply onto the wrong lines.
    """
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _check_range(lines: list[str], start_line: int, end_line: int) -> None:
    if not 1 <= start_line <= end_line <= len(lines):
        raise ValueError(
            f"lines {start_line}-{end_line} fall outside a {len(lines)}-line "
            "module; the hunk and the module are probably from different trees"
        )


def _hunk(module_src: str, start_line: int, end_line: int) -> str:
    """The hunk's own text, at its real indentation, for the prompt."""
    lines = _physical_lines(module_src)
    _check_range(lines, start_line, end_line)
    return "".join(lines[start_line - 1 : end_line]).rstrip("\r\n")


def _splice(module_src: str, start_line: int, end_line: int, reply: str) -> str:
    """The whole module with lines start..end replaced by the model's text.

    The module's line-ending convention wins over whatever the model sent, and
    the result ends in a newline exactly when the input did.
    """
    lines = _physical_lines(module_src)
    _check_range(lines, start_line, end_line)
    newline = "\r\n" if "\r\n" in module_src else "\n"

    body = reply.replace("\r\n", "\n").split("\n")
    if body and body[-1] == "":
        body.pop()  # the reply's own trailing newline, not an extra blank line

    after = lines[end_line:]
    replaced_ended_a_line = lines[end_line - 1].endswith("\n")
    block = newline.join(body)
    if body and (after or replaced_ended_a_line):
        block += newline

    return "".join(lines[: start_line - 1]) + block + "".join(after)


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
    reply: str, *, file: str, start_line: int, end_line: int, module_src: str
) -> list[Mutant]:
    """Turn a model reply for lines start..end into whole-module mutants."""
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
        replacement = entry.get("mutated_src")
        if not isinstance(replacement, str) or not replacement:
            continue
        mutants.append(
            Mutant(
                file=file,
                start_line=start_line,
                end_line=end_line,
                operator=str(entry.get("operator", "semantic")),
                original_src=module_src,
                mutated_src=_splice(module_src, start_line, end_line, replacement),
                rationale=str(entry.get("rationale", "")),
                source="llm",
            )
        )
    return mutants


async def propose(
    client, *, file: str, module_src: str, start_line: int, end_line: int
) -> list[Mutant]:
    reply = await client.complete(
        build_prompt(file, _hunk(module_src, start_line, end_line), start_line, end_line),
        model=EXECUTION_MODEL,
        max_tokens=2048,
    )
    return parse_mutants(
        reply,
        file=file,
        start_line=start_line,
        end_line=end_line,
        module_src=module_src,
    )
