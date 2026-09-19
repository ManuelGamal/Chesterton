"""Seed from a SWE-bench task instead of a GitHub pull request.

A SWE-bench task stands for a real merged PR: its gold `patch` plus its
original `test_patch`. Seeding from the dataset row rather than the GitHub PR
matters for two reasons.

- It is the thing actually under test. UTBoost (ACL'25) proved SWE-bench's
  test_patch insufficient for 36 tasks. That test_patch, not whatever else
  the GitHub PR carried, is what Chesterton should find the gap in.
- It applies. GitHub's .diff renders binary files as "Binary files differ"
  with no content, which `git apply` rejects, and matplotlib PRs routinely
  add baseline images.

The default test scope is the files the test_patch touches, which is what
SWE-bench's own harness runs. The default image follows SWE-bench's naming
on Docker Hub.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

import httpx
from unidiff import PatchSet

from chesterton.filters import is_mutable_source
from chesterton.models import PullRequest
from chesterton.paths import normalise_path

#: The paged /rows endpoint, scanned. The /filter endpoint looks like the
#: obvious fit and was rejected on live evidence (2026-09-19): 20-60 s per
#: call, a ReadTimeout, and an HTTP 500 for an id that is simply in the other
#: dataset. /rows answered every time. Both datasets are 800 rows in 8 pages.
ROWS_API = "https://datasets-server.huggingface.co/rows"
PAGE = 100
DATASETS = ("princeton-nlp/SWE-bench_Verified", "princeton-nlp/SWE-bench_Lite")

#: owner__repo-NUMBER.
_INSTANCE_ID = re.compile(r"^[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-\d+$")


class SWEBenchError(RuntimeError):
    """The task could not be fetched; the message says why."""


@dataclass(frozen=True)
class SWEBenchTask:
    instance_id: str
    pr: PullRequest
    test_paths: tuple[str, ...]
    image: str
    #: The task's original tests: the oracle, whatever patch is under review.
    test_patch: str = ""


def image_for(instance_id: str) -> str:
    return "docker://swebench/sweb.eval.x86_64." + instance_id.replace(
        "__", "_1776_"
    ).lower()


def _files(patch: str) -> tuple[str, ...]:
    return tuple(normalise_path(f.path) for f in PatchSet(patch))


def _title(problem_statement: str) -> str:
    first = next((line.strip() for line in problem_statement.splitlines() if line.strip()), "")
    return first[:100]


def task_from_row(row: dict) -> SWEBenchTask:
    instance_id = row["instance_id"]
    owner, repo = row["repo"].split("/", 1)
    gold = row["patch"] if row["patch"].endswith("\n") else row["patch"] + "\n"
    pr = PullRequest(
        owner=owner,
        repo=repo,
        number=int(instance_id.rsplit("-", 1)[1]),
        title=_title(row.get("problem_statement", "")),
        base_sha=row["base_commit"],
        # A SWE-bench row records the base only. Nothing downstream reads the
        # head; the gold patch applied to the base IS the head.
        head_sha="",
        merge_base_sha=row["base_commit"],
        clone_url=f"https://github.com/{row['repo']}.git",
        diff=gold + row["test_patch"],
    )
    return SWEBenchTask(
        instance_id=instance_id,
        pr=pr,
        test_paths=_files(row["test_patch"]),
        image=image_for(instance_id),
        test_patch=row["test_patch"],
    )


def with_patch(task: SWEBenchTask, patch: str, *, label: str) -> SWEBenchTask:
    """The same task, reviewing a different patch, typically an agent's.

    This is the thesis case: UTBoost found 345 agent patches that passed
    SWE-bench's tests and were wrong. The task's ORIGINAL test_patch stays
    the oracle, because it is the suite those patches passed.

    Edits the patch makes to the files test_patch touches are dropped.
    SWE-bench's harness restores those files before applying test_patch, so
    such edits never counted there. Keeping both would give `git apply` two
    conflicting edits of one file.
    """
    oracle = set(task.test_paths)
    kept = [pf for pf in PatchSet(patch) if normalise_path(pf.path) not in oracle]
    if not any(is_mutable_source(normalise_path(pf.path)) for pf in kept):
        raise ValueError(
            f"the patch has no source change to review once the task's test "
            f"files are set aside ({label})"
        )
    body = "".join(str(pf) for pf in kept)
    if not body.endswith("\n"):
        body += "\n"
    pr = replace(task.pr, title=f"{task.instance_id}: {label}", diff=body + task.test_patch)
    return replace(task, pr=pr)


async def _page(client: httpx.AsyncClient, dataset: str, offset: int) -> dict:
    """One page of rows, retried once. Network errors become SWEBenchError."""
    problem = ""
    for _ in range(2):
        try:
            response = await client.get(
                ROWS_API,
                params={
                    "dataset": dataset,
                    "config": "default",
                    "split": "test",
                    "offset": offset,
                    "length": PAGE,
                },
            )
        except httpx.HTTPError as exc:
            problem = f"{type(exc).__name__}: {exc}"
            continue
        if response.status_code == 200:
            return response.json()
        problem = f"HTTP {response.status_code}: {response.text[:200]}"
    raise SWEBenchError(
        f"the dataset API failed twice for {dataset} at offset {offset} ({problem})"
    )


async def fetch_swebench_row(
    instance_id: str,
    *,
    client: httpx.AsyncClient,
    datasets: Sequence[str] = DATASETS,
) -> dict:
    """The raw dataset row for one instance, from the first dataset holding it."""
    if not _INSTANCE_ID.match(instance_id):
        raise ValueError(f"not a SWE-bench instance id: {instance_id!r}")

    for dataset in datasets:
        offset = 0
        while True:
            page = await _page(client, dataset, offset)
            rows = page.get("rows", [])
            for item in rows:
                if item["row"]["instance_id"] == instance_id:
                    return item["row"]
            offset += PAGE
            if not rows or offset >= page.get("num_rows_total", 0):
                break

    raise SWEBenchError(f"{instance_id} not found in {', '.join(datasets)}")


async def fetch_swebench_task(
    instance_id: str,
    *,
    client: httpx.AsyncClient,
    datasets: Sequence[str] = DATASETS,
) -> SWEBenchTask:
    row = await fetch_swebench_row(instance_id, client=client, datasets=datasets)
    return task_from_row(row)
