import httpx
import pytest

from chesterton.diffing.parse import changed_lines
from chesterton.github.swebench import (
    SWEBenchError,
    fetch_swebench_row,
    fetch_swebench_rows,
    fetch_swebench_task,
    image_for,
    task_from_row,
    with_patch,
)

GOLD = (
    "diff --git a/xarray/core/indexing.py b/xarray/core/indexing.py\n"
    "--- a/xarray/core/indexing.py\n"
    "+++ b/xarray/core/indexing.py\n"
    "@@ -1,2 +1,4 @@\n"
    " def f(dtype):\n"
    "+    if dtype is None:\n"
    "+        return 1\n"
    "     return 2\n"
)

TESTS = (
    "diff --git a/xarray/tests/test_indexes.py b/xarray/tests/test_indexes.py\n"
    "--- a/xarray/tests/test_indexes.py\n"
    "+++ b/xarray/tests/test_indexes.py\n"
    "@@ -1 +1,4 @@\n"
    " import xarray\n"
    "+\n"
    "+def test_stack_keeps_dtype():\n"
    "+    assert True\n"
)

ROW = {
    "repo": "pydata/xarray",
    "instance_id": "pydata__xarray-7393",
    "base_commit": "41fef6f1352be994cd90056d47440fe9aa4c068f",
    "patch": GOLD,
    "test_patch": TESTS,
    "problem_statement": "\n  stack casts int32 dtype coordinate to int64\nMore detail.",
}


def test_the_pr_is_the_gold_patch_plus_the_original_test_patch():
    task = task_from_row(ROW)
    pr = task.pr

    assert (pr.owner, pr.repo, pr.number) == ("pydata", "xarray", 7393)
    assert pr.base_sha == pr.merge_base_sha == ROW["base_commit"]
    assert set(changed_lines(pr.diff)) == {
        "xarray/core/indexing.py",
        "xarray/tests/test_indexes.py",
    }
    assert "stack casts int32" in pr.title


def test_the_default_scope_is_the_test_files_swebench_runs():
    assert task_from_row(ROW).test_paths == ("xarray/tests/test_indexes.py",)


def test_a_gold_patch_without_a_final_newline_still_joins_into_one_diff():
    row = {**ROW, "patch": GOLD.rstrip("\n")}

    assert set(changed_lines(task_from_row(row).pr.diff)) == {
        "xarray/core/indexing.py",
        "xarray/tests/test_indexes.py",
    }


AGENT = (
    "diff --git a/xarray/core/indexing.py b/xarray/core/indexing.py\n"
    "--- a/xarray/core/indexing.py\n"
    "+++ b/xarray/core/indexing.py\n"
    "@@ -1,2 +1,3 @@\n"
    " def f(dtype):\n"
    "+    dtype = dtype or 1\n"
    "     return 2\n"
    # Agents often write tests too. SWE-bench's harness restores the files
    # the test_patch touches before applying it, so these edits never count.
    "diff --git a/xarray/tests/test_indexes.py b/xarray/tests/test_indexes.py\n"
    "--- a/xarray/tests/test_indexes.py\n"
    "+++ b/xarray/tests/test_indexes.py\n"
    "@@ -1 +1,2 @@\n"
    " import xarray\n"
    "+import pytest\n"
)


def test_an_agent_patch_replaces_the_gold_patch():
    task = with_patch(task_from_row(ROW), AGENT, label="agent-x")

    assert "dtype = dtype or 1" in task.pr.diff
    assert "if dtype is None" not in task.pr.diff
    assert "agent-x" in task.pr.title


def test_the_original_test_patch_stays_the_oracle():
    task = with_patch(task_from_row(ROW), AGENT, label="agent-x")

    assert "def test_stack_keeps_dtype" in task.pr.diff
    assert task.test_paths == ("xarray/tests/test_indexes.py",)


def test_agent_edits_to_the_tasks_test_files_are_dropped_as_the_harness_does():
    task = with_patch(task_from_row(ROW), AGENT, label="agent-x")

    assert "+import pytest" not in task.pr.diff
    # One edit per file, so the combined diff applies cleanly.
    assert task.pr.diff.count("+++ b/xarray/tests/test_indexes.py") == 1
    assert set(changed_lines(task.pr.diff)) == {
        "xarray/core/indexing.py",
        "xarray/tests/test_indexes.py",
    }


def test_an_agent_patch_with_no_source_change_is_refused():
    only_tests = AGENT[AGENT.index("diff --git a/xarray/tests"):]

    with pytest.raises(ValueError, match="no source"):
        with_patch(task_from_row(ROW), only_tests, label="agent-x")


def test_the_image_follows_swebenchs_naming():
    assert image_for("pydata__xarray-7393") == (
        "docker://swebench/sweb.eval.x86_64.pydata_1776_xarray-7393"
    )
    assert image_for("scikit-learn__scikit-learn-14894") == (
        "docker://swebench/sweb.eval.x86_64.scikit-learn_1776_scikit-learn-14894"
    )


def filler(n: int) -> list[dict]:
    return [{**ROW, "instance_id": f"acme__other-{i}"} for i in range(n)]


def a_client(found_in: dict[str, list[dict]], *, fail=None) -> httpx.AsyncClient:
    """Serves the paged /rows API. `fail` makes every request fail that way."""

    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(fail, Exception):
            raise fail
        if fail is not None:
            return httpx.Response(fail, text="server trouble")
        rows = found_in.get(request.url.params["dataset"], [])
        offset = int(request.url.params["offset"])
        length = int(request.url.params["length"])
        page = rows[offset : offset + length]
        return httpx.Response(200, json={
            "rows": [{"row": r} for r in page], "num_rows_total": len(rows),
        })

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_an_instance_is_found_in_verified():
    async with a_client({"princeton-nlp/SWE-bench_Verified": [ROW]}) as http:
        task = await fetch_swebench_task("pydata__xarray-7393", client=http)
    assert task.pr.number == 7393


async def test_an_instance_on_a_later_page_is_found():
    rows = filler(150) + [ROW]
    async with a_client({"princeton-nlp/SWE-bench_Verified": rows}) as http:
        task = await fetch_swebench_task("pydata__xarray-7393", client=http)
    assert task.pr.number == 7393


async def test_an_instance_only_in_lite_is_still_found():
    # Live 2026-09-19: matplotlib-23314 is in Lite, and a Verified lookup
    # that failed stopped the search before Lite was ever asked.
    async with a_client({
        "princeton-nlp/SWE-bench_Verified": filler(120),
        "princeton-nlp/SWE-bench_Lite": [ROW],
    }) as http:
        task = await fetch_swebench_task("pydata__xarray-7393", client=http)
    assert task.pr.number == 7393


async def test_an_unknown_instance_is_a_legible_error():
    async with a_client({"princeton-nlp/SWE-bench_Verified": filler(3)}) as http:
        with pytest.raises(SWEBenchError, match="not found"):
            await fetch_swebench_task("pydata__xarray-7393", client=http)


async def no_sleep(seconds):
    """The backoff, without the waiting: a test must not spend 7 s retrying."""


async def test_a_failing_dataset_api_is_a_legible_error():
    async with a_client({}, fail=500) as http:
        with pytest.raises(SWEBenchError, match="500"):
            await fetch_swebench_task("pydata__xarray-7393", client=http, sleep=no_sleep)


async def test_a_network_timeout_is_a_legible_error_not_a_traceback():
    # Live 2026-09-19: an httpx.ReadTimeout escaped the CLI as a traceback.
    async with a_client({}, fail=httpx.ReadTimeout("slow")) as http:
        with pytest.raises(SWEBenchError, match="ReadTimeout"):
            await fetch_swebench_task("pydata__xarray-7393", client=http, sleep=no_sleep)


async def test_a_failed_page_is_retried_once():
    attempts = []

    def handler(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(500, text="transient")
        return httpx.Response(200, json={"rows": [{"row": ROW}], "num_rows_total": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        task = await fetch_swebench_task("pydata__xarray-7393", client=http, sleep=no_sleep)

    assert task.pr.number == 7393
    assert len(attempts) == 2


async def test_many_instances_are_found_in_one_scan():
    # Live 2026-09-20: scanning once per instance for 22 tasks sent ~170
    # requests in a burst and the dataset API answered HTTP 429.
    rows = filler(150) + [ROW, {**ROW, "instance_id": "acme__other-7"}]
    requests = []

    def handler(request):
        requests.append(request)
        offset = int(request.url.params["offset"])
        page = rows[offset : offset + 100]
        return httpx.Response(200, json={"rows": [{"row": r} for r in page],
                                         "num_rows_total": len(rows)})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        found = await fetch_swebench_rows(
            ["pydata__xarray-7393", "acme__other-7"], client=http,
            datasets=("princeton-nlp/SWE-bench_Verified",),
        )

    assert set(found) == {"pydata__xarray-7393", "acme__other-7"}
    assert len(requests) == 2  # two pages, not two scans


async def test_a_rate_limited_page_waits_before_retrying():
    attempts, waits = [], []

    def handler(request):
        attempts.append(request)
        if len(attempts) < 3:
            return httpx.Response(429, text="slow down", headers={"Retry-After": "7"})
        return httpx.Response(200, json={"rows": [{"row": ROW}], "num_rows_total": 1})

    async def sleep(seconds):
        waits.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        task = await fetch_swebench_task("pydata__xarray-7393", client=http, sleep=sleep)

    assert task.pr.number == 7393
    assert waits == [7.0, 7.0]  # Retry-After honoured, not a bare retry


async def test_backoff_grows_when_no_retry_after_is_given():
    attempts, waits = [], []

    def handler(request):
        attempts.append(request)
        if len(attempts) < 4:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json={"rows": [{"row": ROW}], "num_rows_total": 1})

    async def sleep(seconds):
        waits.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await fetch_swebench_task("pydata__xarray-7393", client=http, sleep=sleep)

    assert waits == [1.0, 2.0, 4.0]


async def test_a_raw_row_can_be_read_from_any_dataset():
    # The agent-patch screen needs UTBoost's rows (augmented tests and their
    # FAIL_TO_PASS lists), not just a task built from SWE-bench's.
    boosted = {**ROW, "FAIL_TO_PASS": '["xarray/tests/test_indexes.py::test_x"]'}
    async with a_client({"Bertsekas/SWE-Bench_Verified_UTBoost": [boosted]}) as http:
        row = await fetch_swebench_row(
            "pydata__xarray-7393", client=http,
            datasets=("Bertsekas/SWE-Bench_Verified_UTBoost",),
        )
    assert row["FAIL_TO_PASS"] == boosted["FAIL_TO_PASS"]


async def test_a_malformed_instance_id_is_refused_before_any_request():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"rows": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ValueError, match="instance id"):
            await fetch_swebench_task("x' OR '1'='1", client=http)

    assert calls == []
