from chesterton.llm.mutants import build_prompt, parse_mutants

HUNK = 'def charge(amount):\n    if amount > 100:\n        raise ValueError("no")\n'


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
    mutants = parse_mutants(
        reply, file="pay.py", start_line=1, end_line=3, original_src=HUNK
    )
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
                             original_src="y = 2\n")) == 1


def test_malformed_json_yields_no_mutants_rather_than_raising():
    # One bad reply must not abort a run over hundreds of hunks.
    assert parse_mutants("not json at all", file="a.py", start_line=1,
                         end_line=1, original_src="x = 1\n") == []


def test_entries_missing_mutated_src_are_skipped():
    reply = '{"mutants": [{"rationale": "no code"}, {"mutated_src": "x = 9\\n"}]}'
    mutants = parse_mutants(reply, file="a.py", start_line=1, end_line=1,
                            original_src="x = 1\n")
    assert len(mutants) == 1
    assert mutants[0].mutated_src == "x = 9\n"
