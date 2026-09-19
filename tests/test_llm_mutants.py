import ast
from collections import Counter

import pytest

from chesterton.llm.client import TruncatedResponse
from chesterton.llm.mutants import (
    MALFORMED,
    TRUNCATED,
    build_prompt,
    parse_mutants,
    propose,
)
from chesterton.mutation.gate import MutantGate
from chesterton.mutation.generate import generate

HUNK = 'def charge(amount):\n    if amount > 100:\n        raise ValueError("no")\n'

#: The normal case: a guard indented inside a function, not at module level.
#: Every earlier fixture was a dedented module-level snippet, which is exactly
#: why a fragment-versus-file confusion went unseen.
MODULE = '''\
import logging

log = logging.getLogger(__name__)


def charge(amount, balance):
    log.info("charging %s", amount)
    if amount > balance:
        raise ValueError("insufficient")
    return balance - amount


def refund(amount):
    return -amount
'''

#: Lines 8-9 of MODULE: the guard, at its real indentation.
GUARD_START, GUARD_END = 8, 9

INDENTED_REPLY = (
    '{"mutants": [{"mutated_src": "    if amount >= balance:\\n'
    '        raise ValueError(\\"insufficient\\")\\n",'
    ' "rationale": "shift the boundary"}]}'
)

DEDENTED_REPLY = (
    '{"mutants": [{"mutated_src": "if amount >= balance:\\n'
    '    raise ValueError(\\"insufficient\\")\\n",'
    ' "rationale": "shift the boundary"}]}'
)


class _ScriptedClient:
    """Stands in for NemotronClient; no network in unit tests."""

    def __init__(self, reply: str | Exception):
        self.reply = reply
        self.prompts: list[str] = []

    async def complete(self, prompt: str, *, model: str, max_tokens: int) -> str:
        self.prompts.append(prompt)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_the_prompt_carries_the_code_and_the_line_range():
    prompt = build_prompt("pay.py", HUNK, 1, 3)
    assert "pay.py" in prompt
    assert "raise ValueError" in prompt
    assert "1" in prompt and "3" in prompt


def test_the_prompt_asks_for_json_only():
    # The client disables thinking for this call, so the reply should be JSON
    # with no preamble. Saying so in the prompt as well is cheap insurance.
    prompt = build_prompt("pay.py", HUNK, 1, 3)
    assert "JSON" in prompt


def test_well_formed_mutants_are_parsed():
    reply = (
        '{"mutants": [{"mutated_src": "def charge(amount):\\n    pass\\n",'
        ' "rationale": "removed the guard", "operator": "semantic"}]}'
    )
    proposal = parse_mutants(
        reply, file="pay.py", start_line=1, end_line=3, module_src=HUNK
    )
    mutants = proposal.mutants
    assert proposal.failure is None
    assert len(mutants) == 1
    assert mutants[0].source == "llm"
    assert mutants[0].file == "pay.py"
    assert mutants[0].rationale == "removed the guard"


def test_a_reply_with_leading_prose_still_parses():
    # Belt and braces: thinking is disabled, but a stray preamble must not
    # cost us the whole batch.
    reply = 'Here you go:\n{"mutants": [{"mutated_src": "x = 1\\n",'
    reply += ' "rationale": "r", "operator": "semantic"}]}'
    assert len(parse_mutants(reply, file="a.py", start_line=1, end_line=1,
                             module_src="y = 2\n").mutants) == 1


def test_malformed_json_yields_no_mutants_rather_than_raising():
    # One bad reply must not abort a run over hundreds of hunks — but it must
    # say so, or a run of failures reads like a run of silence.
    proposal = parse_mutants("not json at all", file="a.py", start_line=1,
                             end_line=1, module_src="x = 1\n")
    assert proposal.mutants == []
    assert proposal.failure == MALFORMED


def test_entries_missing_mutated_src_are_skipped():
    reply = '{"mutants": [{"rationale": "no code"}, {"mutated_src": "x = 9\\n"}]}'
    proposal = parse_mutants(reply, file="a.py", start_line=1, end_line=1,
                             module_src="x = 1\n")
    assert [m.mutated_src for m in proposal.mutants] == ["x = 9\n"]
    assert proposal.failure is None


def test_a_reply_whose_every_entry_is_unusable_is_a_failure():
    reply = '{"mutants": [{"rationale": "no code"}, "stray"]}'
    proposal = parse_mutants(reply, file="a.py", start_line=1, end_line=1,
                             module_src="x = 1\n")
    assert proposal.mutants == []
    assert proposal.failure == MALFORMED


@pytest.mark.parametrize("reply", ['{"mutants": null}', '{"mutants": []}'])
def test_an_explicit_nothing_to_propose_is_an_answer_not_a_failure(reply):
    # A model with nothing to propose may legitimately send either.
    proposal = parse_mutants(reply, file="a.py", start_line=1, end_line=1,
                             module_src="x = 1\n")
    assert proposal.mutants == []
    assert proposal.failure is None


@pytest.mark.parametrize("reply", ['{"mutants": 5}', '{"proposals": []}'])
def test_a_reply_without_a_mutants_list_is_malformed_not_raised(reply):
    proposal = parse_mutants(reply, file="a.py", start_line=1, end_line=1,
                             module_src="x = 1\n")
    assert proposal.mutants == []
    assert proposal.failure == MALFORMED


def test_the_model_cannot_name_its_own_operator():
    # Ruling P13. delete_guard is the top-weighted operator; a model claiming
    # it would outrank every deterministic mutant under a tight budget and
    # label a finding with a detection that never happened.
    reply = (
        '{"mutants": [{"mutated_src": "x = 2\\n", "rationale": "r",'
        ' "operator": "delete_guard"}]}'
    )

    [mutant] = parse_mutants(
        reply, file="a.py", start_line=1, end_line=1, module_src="x = 1\n"
    ).mutants

    assert mutant.operator == "semantic"


def test_an_indented_reply_is_spliced_into_the_whole_module_and_admitted():
    # Ruling P12: mutated_src is the complete file. The model answers for
    # lines 8-9 only, at their real indentation; the splice puts that back
    # into the module, so the gate parses what the sandbox will actually run.
    [mutant] = parse_mutants(
        INDENTED_REPLY, file="pay.py", start_line=GUARD_START,
        end_line=GUARD_END, module_src=MODULE,
    ).mutants

    assert MutantGate().admit(mutant) is True
    ast.parse(mutant.mutated_src)
    assert mutant.original_src == MODULE

    before, after = MODULE.splitlines(), mutant.mutated_src.splitlines()
    assert len(after) == len(before)
    assert after[: GUARD_START - 1] == before[: GUARD_START - 1]
    assert after[GUARD_END:] == before[GUARD_END:]
    assert after[GUARD_START - 1] == "    if amount >= balance:"
    assert mutant.mutated_src.endswith("return -amount\n")


def test_a_dedented_reply_is_rejected_not_admitted():
    # Written as a file, a dedented fragment would replace the module with two
    # lines; every test would error, and an error reads as "killed". Spliced
    # into place it no longer parses, so the gate stops it before it costs a
    # sandbox operation.
    [mutant] = parse_mutants(
        DEDENTED_REPLY, file="pay.py", start_line=GUARD_START,
        end_line=GUARD_END, module_src=MODULE,
    ).mutants

    gate = MutantGate()
    assert gate.admit(mutant) is False
    assert gate.rejected == {"unparseable": 1}


def test_the_splice_keeps_the_modules_crlf_line_endings():
    crlf = MODULE.replace("\n", "\r\n")

    [mutant] = parse_mutants(
        INDENTED_REPLY, file="pay.py", start_line=GUARD_START,
        end_line=GUARD_END, module_src=crlf,
    ).mutants

    assert "\n" not in mutant.mutated_src.replace("\r\n", "")
    assert mutant.mutated_src.count("\r\n") == crlf.count("\r\n")


def test_the_splice_keeps_a_missing_final_newline_missing():
    module = "def f(x):\n    return x + 1"
    reply = '{"mutants": [{"mutated_src": "    return x - 1\\n"}]}'

    [mutant] = parse_mutants(
        reply, file="f.py", start_line=2, end_line=2, module_src=module
    ).mutants

    assert mutant.mutated_src == "def f(x):\n    return x - 1"


async def test_propose_shows_the_hunk_indented_and_its_mutants_survive_generate():
    # The seam no execution path crossed before: a recorded reply through
    # propose() and into generate(), alongside the deterministic operators.
    client = _ScriptedClient(INDENTED_REPLY)

    proposed = await propose(
        client, file="pay.py", module_src=MODULE,
        start_line=GUARD_START, end_line=GUARD_END,
    )
    mutants, rejected = generate(
        [], {"pay.py": MODULE}, llm_mutants=proposed.mutants
    )

    [prompt] = client.prompts
    assert "\n    if amount > balance:\n" in prompt
    assert "def refund" not in prompt  # the hunk, not the whole file
    assert [m.source for m in mutants] == ["llm"]
    assert mutants[0].mutated_src.startswith("import logging\n")
    assert rejected == {}


async def test_a_dedented_proposal_is_rejected_by_generate():
    proposed = await propose(
        _ScriptedClient(DEDENTED_REPLY), file="pay.py", module_src=MODULE,
        start_line=GUARD_START, end_line=GUARD_END,
    )

    mutants, rejected = generate([], {}, llm_mutants=proposed.mutants)

    assert mutants == []
    assert rejected == {"unparseable": 1}


async def test_a_truncated_reply_yields_nothing_and_does_not_raise():
    # With max_tokens fixed and up to four replacement blocks requested,
    # truncation is ordinary. Raising here aborted a fan-out over every hunk.
    client = _ScriptedClient(TruncatedResponse("hit max_tokens"))

    proposal = await propose(
        client, file="pay.py", module_src=MODULE,
        start_line=GUARD_START, end_line=GUARD_END,
    )

    assert proposal.mutants == []
    assert proposal.failure == TRUNCATED


async def test_propose_swallows_only_truncation():
    # Anything else the client raises is not a bad reply; hiding it would
    # turn a broken client into a quiet run with no model mutants.
    client = _ScriptedClient(RuntimeError("connection refused"))

    with pytest.raises(RuntimeError, match="connection refused"):
        await propose(
            client, file="pay.py", module_src=MODULE,
            start_line=GUARD_START, end_line=GUARD_END,
        )


async def test_a_run_of_failed_replies_is_distinguishable_from_a_run_of_silence():
    # Before, both of these runs produced no mutants and an empty rejected
    # dict: a model tier that failed on every call looked exactly like one
    # that had nothing to say.
    async def run(reply: str) -> Counter:
        client = _ScriptedClient(reply)
        proposals = [
            await propose(client, file="pay.py", module_src=MODULE,
                          start_line=line, end_line=line)
            for line in (7, 8, 10)
        ]
        assert all(p.mutants == [] for p in proposals)
        return Counter(p.failure for p in proposals)

    assert await run("I could not produce JSON, sorry.") == Counter({MALFORMED: 3})
    assert await run('{"mutants": []}') == Counter({None: 3})
