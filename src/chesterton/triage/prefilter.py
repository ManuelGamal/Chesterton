"""Survivors that are obvious equivalents, dropped before any model call.

Spec §9's first stage. Only rules that are right by construction belong
here: a survivor dropped here is never shown to anyone, so a wrong rule
would hide a real finding. Anything uncertain goes to the model instead.

One rule so far: every line the mutation changed is a logging, print or
warnings call. What those emit is output, not behaviour the program acts on.
"""

from __future__ import annotations

import re

from chesterton.triage.evidence import Evidence

LOGGING_ONLY = "logging_only"

#: `log.debug(...)`, `self.logger.warning(...)`, `logging.info(...)`,
#: `print(...)`, `warnings.warn(...)`: one whole call on one line.
_LOGGING = re.compile(
    r"^\s*(?:(?:self|cls)\.)?(?:_?log(?:ger)?|logging|LOG|LOGGER)\.\w+\(.*\)\s*$"
    r"|^\s*print\(.*\)\s*$"
    r"|^\s*warnings\.warn\(.*\)\s*$"
)


def _changed(diff: str) -> list[str]:
    return [
        line[1:]
        for line in diff.splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]


def prefilter(ev: Evidence) -> str | None:
    changed = [line for line in _changed(ev.diff) if line.strip()]
    if changed and all(_LOGGING.match(line) for line in changed):
        return LOGGING_ONLY
    return None
