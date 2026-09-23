"""Obvious equivalents are dropped before any model call (spec §9)."""

from chesterton.triage.evidence import evidence_for
from chesterton.triage.prefilter import LOGGING_ONLY, prefilter

from conftest import NO_GUARD, a_survivor

LOGGED = (
    "import logging\n"
    "log = logging.getLogger(__name__)\n"
    "\n"
    "def charge(amount):\n"
    '    log.debug("charging %s", amount)\n'
    "    return amount\n"
)


def ev(result):
    return evidence_for(result, "t")


def test_a_mutation_inside_a_logging_call_is_dropped():
    mutated = LOGGED.replace('log.debug("charging %s", amount)', 'log.debug("charging")')

    assert prefilter(ev(a_survivor(mutated, start=5, end=5, original=LOGGED))) == LOGGING_ONLY


def test_print_and_warnings_count_as_logging():
    printed = LOGGED.replace('log.debug("charging %s", amount)', 'print("charging", amount)')
    quiet = printed.replace('print("charging", amount)', 'print("charging")')

    assert prefilter(ev(a_survivor(quiet, start=5, end=5, original=printed))) == LOGGING_ONLY


def test_a_deleted_guard_is_kept_for_the_model():
    assert prefilter(ev(a_survivor(NO_GUARD))) is None


def test_a_change_that_also_touches_real_code_is_kept():
    mutated = LOGGED.replace(
        '    log.debug("charging %s", amount)\n    return amount\n',
        '    log.debug("charging")\n    return 0\n',
    )

    assert prefilter(ev(a_survivor(mutated, start=5, end=6, original=LOGGED))) is None


def test_logging_call_with_real_logic_on_same_line_is_kept():
    """log.debug(...) if verbose else validate(...) has real behavior."""
    guarded = (
        "import logging\n"
        "log = logging.getLogger(__name__)\n"
        "\n"
        "def charge(amount):\n"
        '    log.debug("checking") if verbose else validate(amount)\n'
        "    return amount\n"
    )
    mutated = guarded.replace("verbose", "not verbose")

    assert prefilter(ev(a_survivor(mutated, start=5, end=5, original=guarded))) is None


def test_print_with_side_effect_is_kept():
    """print(x) or side_effect(y) has real behavior."""
    with_side_effect = (
        "def charge(amount):\n"
        '    print(x) or dangerous_side_effect(y)\n'
        "    return amount\n"
    )
    mutated = with_side_effect.replace("dangerous_side_effect", "other_side_effect")

    assert prefilter(ev(a_survivor(mutated, start=2, end=2, original=with_side_effect))) is None


def test_logging_with_call_in_arguments_is_kept():
    """log.debug with queue.pop() argument has real behavior."""
    with_call_arg = (
        "import logging\n"
        "log = logging.getLogger(__name__)\n"
        "\n"
        "def charge(amount):\n"
        '    log.debug("%s", queue.pop())\n'
        "    return amount\n"
    )
    mutated = with_call_arg.replace('log.debug("%s", queue.pop())', 'log.debug("%s")')

    assert prefilter(ev(a_survivor(mutated, start=5, end=5, original=with_call_arg))) is None


def test_non_logging_method_on_log_object_is_kept():
    """log.append(item) is not a logging method."""
    audit_log = (
        "def charge(amount):\n"
        "    log.append(item)\n"
        "    return amount\n"
    )
    mutated = audit_log.replace("log.append(item)", "log.append(None)")

    assert prefilter(ev(a_survivor(mutated, start=2, end=2, original=audit_log))) is None
