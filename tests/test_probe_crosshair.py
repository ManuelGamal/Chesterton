"""The CrossHair probe is a script, not library code, so it is loaded by path.

Its purity screen is what spec §15's eligibility figure rests on, and a
narrower version of it reported four plainly impure functions as eligible.
"""

import ast
import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_crosshair.py"
_spec = importlib.util.spec_from_file_location("probe_crosshair", _SCRIPT)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)


def verdict(source: str) -> tuple[bool, str]:
    [fn] = ast.parse(source).body
    return probe._eligible(fn)


@pytest.mark.parametrize(
    "source",
    [
        "def fetch(self, url: str) -> str:\n    return self.session.get(url)\n",
        "def read_it(p: Path) -> str:\n    return p.read_text()\n",
        "def env(name: str) -> str:\n    return os.environ[name]\n",
        "def clock(x: float) -> float:\n    return x + time.time()\n",
    ],
    ids=["self.session.get", "Path.read_text", "os.environ", "time.time"],
)
def test_impurity_the_old_screen_missed_is_now_caught(source):
    eligible, reason = verdict(source)
    assert eligible is False, reason


def test_a_pure_annotated_function_is_still_eligible():
    # The widened screen must not simply reject everything.
    assert verdict("def total(a: int, b: int) -> int:\n    return a + b\n") == (
        True,
        "eligible",
    )


def test_the_output_says_the_purity_screen_overstates_eligibility(tmp_path, capsys):
    target = tmp_path / "pure.py"
    target.write_text("def total(a: int, b: int) -> int:\n    return a + b\n")

    probe.main([str(target)])

    out = capsys.readouterr().out
    assert "name heuristic" in out
    assert "OVERSTATES eligibility" in out
    assert "annotation checks are exact" in out
