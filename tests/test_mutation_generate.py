import ast
from dataclasses import replace

from chesterton.models import Hunk
from chesterton.mutation.generate import MUTANT_BUDGET, generate
from chesterton.mutation.model import Mutant

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


def test_the_budget_is_respected():
    mutants, _ = generate([Hunk("pay.py", 1, 5)], {"pay.py": GUARDED}, budget=2)
    assert len(mutants) == 2


def test_guard_deletion_outranks_a_boundary_shift():
    # Asserting the exact operator, not a set: find_candidates' insertion order
    # puts strip_decorator first, so a set-based assertion would pass even with
    # the ranking removed entirely.
    mutants, _ = generate([Hunk("pay.py", 1, 5)], {"pay.py": GUARDED}, budget=1)
    assert mutants[0].operator == "delete_guard"


def test_the_default_budget_fits_the_measured_concurrency_cap():
    # 24 concurrent operations was measured safe. A budget far above it queues.
    assert MUTANT_BUDGET <= 24


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


def test_the_same_edit_with_different_separators_deduplicates():
    # Two spellings of one file are one mutant, not two — otherwise we pay for
    # the same sandbox operation twice to learn the same thing.
    forward = replace(an_llm_mutant("x = 1\n", "a"), file="widgets/pay.py")
    backward = replace(an_llm_mutant("x = 1\n", "b"), file="widgets\\pay.py")

    mutants, rejected = generate([], {}, llm_mutants=[forward, backward])

    assert len(mutants) == 1
    assert rejected["duplicate"] == 1
