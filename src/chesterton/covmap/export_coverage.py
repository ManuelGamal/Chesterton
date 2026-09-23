"""Stream per-test coverage for named sources, one JSON record per line.

Runs INSIDE the sandbox, under the repository's own interpreter, so it uses
only the standard library and coverage's public API, and nothing newer than
Python 3.6. It is uploaded as a file; nothing here imports chesterton.

    export_coverage.py WORKDIR TARGET [TARGET ...]

Run from the repository, so the data file is found exactly as `coverage
json` finds it: the repository's own config and COVERAGE_FILE apply.

Per target file that was measured, one record with its statements, then one
record per test context with the lines that context ran. Memory is one
context's lines at a time. `coverage json --show-contexts` built the whole
line-by-test matrix and was OOM-killed on matplotlib's axes/_base.py.
"""

import json
import os
import re
import sys

import coverage


def _write(record):
    sys.stdout.write(json.dumps(record) + "\n")


def main(argv):
    workdir, targets = argv[1], set(argv[2:])
    cov = coverage.Coverage()
    cov.load()
    data = cov.get_data()
    measured = sorted(data.measured_files())
    if not measured:
        sys.stderr.write("chesterton: no coverage data: nothing was measured\n")
        return 1

    # Named relative to the repository, as `coverage json` names them.
    root = os.path.abspath(workdir)
    wanted = []
    for path in measured:
        relative = os.path.relpath(path, root).replace(os.sep, "/")
        if relative in targets:
            wanted.append((path, relative))
    contexts = sorted(data.measured_contexts())
    for path, relative in wanted:
        _write({"file": relative, "statements": sorted(cov.analysis2(path)[1])})
        for context in contexts:
            # Anchored: the patterns are regexes, and "" alone matches all.
            data.set_query_contexts(["^" + re.escape(context) + "$"])
            lines = data.lines(path) or []
            if lines:
                _write({"file": relative, "context": context, "lines": sorted(lines)})
        data.set_query_contexts(None)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
