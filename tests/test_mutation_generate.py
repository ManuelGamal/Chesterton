import ast
from dataclasses import replace

from chesterton.models import Hunk
from chesterton.mutation.generate import MUTANT_BUDGET, generate
from chesterton.mutation.model import Mutant
from chesterton.mutation.operators import apply_candidate, find_candidates

GUARDED = '''\
@rate_limit(10)
def charge(amount):
    if not amount:
        raise ValueError("required")
    return amount > 100
'''


def an_llm_mutant(mutated_src: str, rationale: str) -> Mutant:
    return Mutant(
        file="pay.py",
        start_line=1,
        end_line=5,
        operator="semantic",
        original_src=GUARDED,
        mutated_src=mutated_src,
        rationale=rationale,
        source="llm",
    )


def test_mutants_are_generated_for_a_python_hunk():
    mutants, _ = generate([Hunk("pay.py", 1, 5)], {"pay.py": GUARDED})
    assert mutants
    assert all(m.file == "pay.py" for m in mutants)


def test_non_python_files_are_skipped_entirely():
    mutants, rejected = generate([Hunk("README.md", 1, 2)], {"README.md": "# hi\n"})
    assert mutants == []
    assert rejected["not_mutable_source"] == 1


def test_a_hunk_with_no_source_available_is_skipped():
    mutants, rejected = generate([Hunk("gone.py", 1, 2)], {})
    assert mutants == []
    assert rejected["no_source"] == 1


def test_every_generated_mutant_passed_the_gate():
    # The gate rejects unparseable output, so anything returned must compile.
    mutants, _ = generate([Hunk("pay.py", 1, 5)], {"pay.py": GUARDED})
    for mutant in mutants:
        ast.parse(mutant.mutated_src)


def test_a_deterministic_no_op_is_gated_out():
    # remove_cleanup on an already-empty finally renders a byte-identical
    # file. Ungated, that is a guaranteed survivor — a fabricated finding —
    # and every other deterministic fixture happens to mutate for real.
    source = "try:\n    f()\nfinally:\n    pass\n"
    [candidate] = find_candidates(source, [1, 2, 3, 4])
    assert candidate.operator == "remove_cleanup"
    assert apply_candidate(source, candidate) == source  # the premise

    mutants, rejected = generate([Hunk("cleanup.py", 1, 4)], {"cleanup.py": source})

    assert mutants == []
    assert rejected == {"unchanged": 1}


def test_the_budget_is_respected():
    mutants, _ = generate([Hunk("pay.py", 1, 5)], {"pay.py": GUARDED}, budget=2)
    assert len(mutants) == 2


def test_guard_deletion_outranks_a_boundary_shift():
    # Asserting the exact operator, not a set: find_candidates' insertion order
    # puts strip_decorator first, so a set-based assertion would pass even with
    # the ranking removed entirely.
    mutants, _ = generate([Hunk("pay.py", 1, 5)], {"pay.py": GUARDED}, budget=1)
    assert mutants[0].operator == "delete_guard"


def test_the_default_budget_sits_in_the_specs_range():
    # Ruling P14: the spec binds — 30-40 mutants per run. The Semaphore(24)
    # concurrency cap is a separate limit; a second short round is its job.
    assert 30 <= MUTANT_BUDGET <= 40


def test_supplied_llm_mutants_are_gated_alongside_deterministic_ones():
    # Ruling P1: the model's proposals are not privileged. One parses and is
    # kept; one does not and is rejected exactly as a broken operator would be.
    good = an_llm_mutant("x = 1\n", "from the model")
    broken = an_llm_mutant("def broken(:\n", "unparseable")

    mutants, rejected = generate([], {"pay.py": GUARDED}, llm_mutants=[good, broken])

    assert [m.rationale for m in mutants] == ["from the model"]
    assert rejected["unparseable"] == 1


def test_a_model_supplied_path_is_normalised():
    windows = replace(an_llm_mutant("x = 1\n", "from the model"),
                      file="widgets\\pay.py")

    mutants, _ = generate([], {}, llm_mutants=[windows])

    assert mutants[0].file == "widgets/pay.py"


def test_sources_keyed_with_backslashes_still_match_a_forward_slash_hunk():
    # A sources map built from a Windows filesystem walk. Unnormalised, this
    # produced zero mutants and a misleading {"no_source": 1}.
    mutants, rejected = generate(
        [Hunk("widgets/pay.py", 1, 5)], {"widgets\\pay.py": GUARDED}
    )

    assert mutants
    assert "no_source" not in rejected
    assert {m.file for m in mutants} == {"widgets/pay.py"}


def test_a_backslash_hunk_still_matches_forward_slash_sources():
    mutants, rejected = generate(
        [Hunk("widgets\\pay.py", 1, 5)], {"widgets/pay.py": GUARDED}
    )

    assert mutants
    assert "no_source" not in rejected
    assert {m.file for m in mutants} == {"widgets/pay.py"}


TWO_TYPED_HANDLERS = (
    "def load(key):\n"
    "    try:\n"
    "        return cache[key]\n"
    "    except ValueError:\n"
    "        return None\n"
    "    except KeyError:\n"
    "        return default\n"
)


def test_widen_except_on_a_non_last_handler_does_not_abort_the_run():
    # The controller's reproduction (ruling P22). Before the fix this raised
    # CSTValidationError out of generate() and produced zero mutants for the
    # whole file, not just this candidate.
    mutants, rejected = generate(
        [Hunk("svc.py", 1, 7)], {"svc.py": TWO_TYPED_HANDLERS}
    )

    widened = {m.rationale: m.mutated_src for m in mutants if m.operator == "widen_except"}
    assert len(widened) == 2
    non_last = next(src for rationale, src in widened.items() if "ValueError" in rationale)
    last = next(src for rationale, src in widened.items() if "KeyError" in rationale)
    assert "except Exception:\n        return None\n" in non_last
    assert "except:\n        return default\n" in last
    assert "operator_error" not in rejected


def test_a_candidate_that_fails_to_apply_costs_one_mutant_not_the_run(monkeypatch):
    # Ruling P22 part 2. LibCST's validation can reject a shape we did not
    # foresee; one bad candidate must never abort the run.
    import chesterton.mutation.generate as generate_module

    real_apply_candidate = generate_module.apply_candidate
    calls = {"n": 0}

    def flaky(source, candidate):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("simulated operator crash")
        return real_apply_candidate(source, candidate)

    monkeypatch.setattr(generate_module, "apply_candidate", flaky)

    mutants, rejected = generate([Hunk("pay.py", 1, 5)], {"pay.py": GUARDED})

    assert rejected["operator_error"] == 1
    assert mutants  # the other candidates still made it through


def test_the_same_edit_with_different_separators_deduplicates():
    # Two spellings of one file are one mutant, not two — otherwise we pay for
    # the same sandbox operation twice to learn the same thing.
    forward = replace(an_llm_mutant("x = 1\n", "a"), file="widgets/pay.py")
    backward = replace(an_llm_mutant("x = 1\n", "b"), file="widgets\\pay.py")

    mutants, rejected = generate([], {}, llm_mutants=[forward, backward])

    assert len(mutants) == 1
    assert rejected["duplicate"] == 1
