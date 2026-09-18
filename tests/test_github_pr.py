import json
from pathlib import Path

import httpx
import pytest

from chesterton.github.pr import GitHubError, fetch_pull_request, parse_pr_url

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_pr_url_extracts_owner_repo_and_number():
    assert parse_pr_url("https://github.com/acme/widgets/pull/42") == (
        "acme",
        "widgets",
        42,
    )


def test_parse_pr_url_rejects_a_non_pr_url():
    with pytest.raises(ValueError):
        parse_pr_url("https://github.com/acme/widgets")


def _ok_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/pulls/42") and "diff" in request.headers.get("accept", ""):
        return httpx.Response(200, text=(FIXTURES / "pr.diff").read_text())
    if path.endswith("/pulls/42"):
        return httpx.Response(
            200, json=json.loads((FIXTURES / "pr_meta.json").read_text())
        )
    if "/compare/" in path:
        return httpx.Response(
            200, json=json.loads((FIXTURES / "pr_compare.json").read_text())
        )
    return httpx.Response(404)


async def test_fetch_uses_merge_base_not_base_sha():
    async with httpx.AsyncClient(transport=httpx.MockTransport(_ok_handler)) as c:
        pr = await fetch_pull_request("acme", "widgets", 42, client=c)

    assert pr.base_sha == "a" * 40
    assert pr.merge_base_sha == "c" * 40
    assert pr.merge_base_sha != pr.base_sha


async def test_fetch_returns_title_clone_url_and_diff():
    async with httpx.AsyncClient(transport=httpx.MockTransport(_ok_handler)) as c:
        pr = await fetch_pull_request("acme", "widgets", 42, client=c)

    assert pr.title == "Speed up user lookup"
    assert pr.clone_url == "https://github.com/acme/widgets.git"
    assert "def get_user" in pr.diff


async def test_a_missing_pull_request_raises_github_error():
    def handler(request):
        return httpx.Response(404, json={"message": "Not Found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(GitHubError, match="404"):
            await fetch_pull_request("acme", "ghost", 1, client=c)


async def test_rate_limit_is_retried_then_surfaces_as_github_error():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0"},
            json={"message": "API rate limit exceeded"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(GitHubError, match="rate limit"):
            await fetch_pull_request("acme", "widgets", 42, client=c, max_retries=2)

    assert calls["n"] == 2


async def test_a_missing_merge_base_field_raises_a_clear_error():
    def handler(request):
        path = request.url.path
        if "/compare/" in path:
            return httpx.Response(200, json={})
        return httpx.Response(
            200, json=json.loads((FIXTURES / "pr_meta.json").read_text())
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(GitHubError, match="merge_base_commit"):
            await fetch_pull_request("acme", "widgets", 42, client=c)
