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
