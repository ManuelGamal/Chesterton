import ast

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
    # The spec's headline operator is the quiet removal of a guard. Under a
    # tight budget that must survive and the cheaper mutations must not.
    mutants, _ = generate([Hunk("pay.py", 1, 5)], {"pay.py": GUARDED}, budget=1)
    assert mutants[0].operator in {"delete_guard", "strip_decorator"}


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
