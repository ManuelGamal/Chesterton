from chesterton.mutation.gate import MutantGate
from chesterton.mutation.model import Mutant


def a_mutant(**overrides) -> Mutant:
    fields = {
        "file": "users.py",
        "start_line": 2,
        "end_line": 3,
        "operator": "strip_decorator",
        "original_src": "x = 1\n",
        "mutated_src": "x = 2\n",
        "rationale": "changed the constant",
        "source": "deterministic",
    }
    fields.update(overrides)
    return Mutant(**fields)


def test_a_well_formed_mutant_is_admitted():
    assert MutantGate().admit(a_mutant()) is True


def test_unparseable_python_is_rejected():
    # A mutant that will not compile makes its tests ERROR, which reads as
    # "killed" — a silent false negative, and the worst outcome available.
    gate = MutantGate()
    assert gate.admit(a_mutant(mutated_src="def broken(:\n")) is False
    assert gate.rejected["unparseable"] == 1


def test_code_that_parses_but_will_not_compile_is_rejected():
    # ast.parse accepts a `return` at module level; only the compiler rejects
    # it. It is the shape a reply spliced one indentation level too shallow
    # takes, and the file would fail to import — every test errors.
    gate = MutantGate()
    assert gate.admit(a_mutant(mutated_src="x = 1\nreturn x\n")) is False
    assert gate.rejected["unparseable"] == 1


def test_a_mutant_identical_to_the_original_is_rejected():
    gate = MutantGate()
    assert gate.admit(a_mutant(mutated_src="x = 1\n")) is False
    assert gate.rejected["unchanged"] == 1


def test_a_whitespace_only_change_is_rejected():
    # Reformatting is not a mutation; it would burn a sandbox op to prove
    # nothing.
    gate = MutantGate()
    assert gate.admit(a_mutant(mutated_src="x  =  1\n")) is False
    assert gate.rejected["unchanged"] == 1


def test_a_no_op_is_rejected_even_when_the_original_will_not_parse():
    # The controller's reproduction. With no tree for the original, the
    # unchanged check used to be skipped and this no-op was admitted — and a
    # no-op survives every suite, so it would be reported as a permitted
    # behaviour change that does not exist.
    gate = MutantGate()
    mutant = a_mutant(original_src="    return a\n", mutated_src="return a\n")

    assert gate.admit(mutant) is False
    assert gate.rejected == {"unchanged": 1}


def test_a_compiling_no_op_of_an_unparseable_original_is_not_admitted():
    # The same hole, in the shape that still gets through once the gate also
    # compiles: here the mutant compiles, so only the unchanged check stands
    # between this no-op and a fabricated finding.
    gate = MutantGate()
    mutant = a_mutant(original_src="    x = a\n", mutated_src="x = a\n")

    assert gate.admit(mutant) is False
    assert gate.rejected == {"unchanged": 1}


def test_a_comment_only_change_to_an_unparseable_original_is_rejected():
    gate = MutantGate()
    mutant = a_mutant(
        original_src="    return a\n", mutated_src="return a  # shifted\n"
    )

    assert gate.admit(mutant) is False
    assert gate.rejected == {"unchanged": 1}


def test_a_real_change_to_an_unparseable_original_is_still_admitted():
    # The fallback must reject only what it cannot tell apart, not everything.
    gate = MutantGate()
    mutant = a_mutant(original_src="    x = a\n", mutated_src="x = b\n")

    assert gate.admit(mutant) is True
    assert gate.rejected == {}


def test_a_duplicate_mutant_is_rejected_once_seen():
    gate = MutantGate()
    assert gate.admit(a_mutant()) is True
    assert gate.admit(a_mutant(rationale="different words, same code")) is False
    assert gate.rejected["duplicate"] == 1


def test_two_different_mutants_are_both_admitted():
    gate = MutantGate()
    assert gate.admit(a_mutant(mutated_src="x = 2\n")) is True
    assert gate.admit(a_mutant(mutated_src="x = 3\n")) is True
    assert gate.rejected == {}


def test_content_hash_ignores_rationale_and_source():
    # Two generators proposing the same edit are one mutant, not two.
    left = a_mutant(source="deterministic", rationale="a")
    right = a_mutant(source="llm", rationale="b")
    assert left.content_hash == right.content_hash
