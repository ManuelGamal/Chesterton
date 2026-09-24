"""The demo's one live call: re-triage a recorded finding (demo spec §9).

The browser names a story and a finding, nothing else. The evidence comes
from the deployed bundle, so this can never be used as a general LLM proxy.
The prompt, model and parser are the tool's own (classify_survivor), so a
live answer takes exactly the recorded triage's code path. It fails
closed: no counter, or over the cap, means no model call.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from chesterton.llm.client import REASONING_MODEL
from chesterton.triage.classify import classify_survivor
from chesterton.triage.evidence import Evidence

HOURLY_CAP = 60
MODEL_TIMEOUT_S = 50.0
_ID = re.compile(r"^[a-z0-9-]{1,40}$")


@dataclass(frozen=True)
class WhyResult:
    status: int
    body: dict


def _error(status: int, error: str, message: str, recorded: dict | None = None) -> WhyResult:
    return WhyResult(status, {"error": error, "message": message, "recorded": recorded})


def _find(stories_dir: Path, story: str, finding: str) -> tuple[dict, dict] | None:
    index = json.loads((stories_dir / "index.json").read_text(encoding="utf-8"))
    if story not in {s["id"] for s in index["stories"]}:
        return None
    bundle = json.loads((stories_dir / f"{story}.json").read_text(encoding="utf-8"))
    triage = bundle["triage"]
    for item in triage["headline"] + triage["worth_a_look"] + triage["dismissed"]:
        if item["id"] == finding:
            return bundle, item
    return None


def _evidence(bundle: dict, f: dict) -> Evidence:
    return Evidence(
        file=f["file"], start_line=f["start_line"], end_line=f["end_line"], operator=f["operator"],
        rationale=f["rationale"], original=f["original"], mutated=f["mutated"], diff=f["diff"],
        tests=tuple(f["tests"]), pr_title=bundle["meta"]["pr_title"], mutant=None,
    )


async def answer(payload, *, stories_dir: Path, client, counter) -> WhyResult:
    if not isinstance(payload, dict):
        return _error(400, "bad_request", "send a JSON object with story and finding")
    story, finding = payload.get("story"), payload.get("finding")
    if not (isinstance(story, str) and isinstance(finding, str)
            and _ID.match(story) and _ID.match(finding)):
        return _error(404, "not_found", "unknown story or finding")
    try:
        found = _find(stories_dir, story, finding)
    except (OSError, ValueError, KeyError, TypeError):
        return _error(503, "stories_unavailable", "the demo's story data could not be read")
    if found is None:
        return _error(404, "not_found", "unknown story or finding")
    bundle, item = found
    recorded = {"label": item["label"], "category": item["category"], "explanation": item["explanation"]}

    count = counter.hit()
    if count is None:
        return _error(503, "rate_limit_unavailable",
                      "the live-call counter is unreachable, so no call was made", recorded)
    if count > HOURLY_CAP:
        return _error(429, "capped",
                      f"live calls are capped at {HOURLY_CAP} an hour to keep this demo free", recorded)

    started = time.perf_counter()
    try:
        c = await asyncio.wait_for(classify_survivor(client, _evidence(bundle, item)), MODEL_TIMEOUT_S)
    except asyncio.TimeoutError:
        return _error(504, "timeout", f"Nemotron did not answer within {MODEL_TIMEOUT_S:.0f} s", recorded)
    if c.failure in ("unavailable", "truncated"):
        return _error(502, c.failure, c.explanation, recorded)
    return WhyResult(200, {
        "label": c.label, "category": c.category, "confident": c.confident,
        "explanation": c.explanation, "failure": c.failure,
        "elapsed_s": round(time.perf_counter() - started, 1), "model": REASONING_MODEL,
        "recorded": recorded,
    })


class UpstashCounter:
    """Hourly INCR in Upstash Redis; None on any failure, so callers fail closed."""

    def __init__(self, redis):
        self._redis = redis

    @classmethod
    def from_env(cls) -> "UpstashCounter":
        try:
            from upstash_redis import Redis

            return cls(Redis(url=os.environ["UPSTASH_REDIS_REST_URL"],
                             token=os.environ["UPSTASH_REDIS_REST_TOKEN"]))
        except Exception:  # missing package or env: the counter is unreachable
            return cls(None)

    def hit(self) -> int | None:
        if self._redis is None:
            return None
        key = f"why:{int(time.time() // 3600)}"
        try:
            value = self._redis.incr(key)
            if value == 1:
                self._redis.expire(key, 3600)
            return int(value)
        except Exception:
            return None
