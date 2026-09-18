"""Fetch a public pull request with plain HTTPS GETs.

No Octokit, no GitHub App, no OAuth — judges must not install anything.
Set GITHUB_TOKEN in the server environment to lift the 60 req/hr anonymous
limit to 5,000; the token is never required for correctness, but the hosted
demo shares one IP across all judges and will be throttled without it.
"""

from __future__ import annotations

import asyncio
import os
import re

import httpx

from chesterton.models import PullRequest

API = "https://api.github.com"
_PR_URL = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")
_RETRY_STATUS = {403, 429, 500, 502, 503, 504}


class GitHubError(RuntimeError):
    """Any failure reaching or understanding the GitHub API."""


def parse_pr_url(url: str) -> tuple[str, str, int]:
    match = _PR_URL.search(url)
    if match is None:
        raise ValueError(f"not a GitHub pull request URL: {url}")
    owner, repo, number = match.groups()
    return owner, repo, int(number)


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _get(
    client: httpx.AsyncClient,
    url: str,
    *,
    accept: str | None = None,
    max_retries: int = 3,
    backoff_base: float = 1.0,
) -> httpx.Response:
    headers = _auth_headers()
    if accept:
        headers["Accept"] = accept

    last: httpx.Response | None = None
    for attempt in range(max_retries):
        response = await client.get(url, headers=headers)
        if response.status_code < 400:
            return response

        last = response
        if response.status_code not in _RETRY_STATUS:
            break
        if attempt < max_retries - 1:
            await asyncio.sleep(backoff_base * (2**attempt))

    assert last is not None
    remaining = last.headers.get("x-ratelimit-remaining")
    if last.status_code == 403 and remaining == "0":
        raise GitHubError(
            f"GitHub rate limit exhausted for {url}. "
            "Set GITHUB_TOKEN to raise the quota from 60/hr to 5,000/hr."
        )
    raise GitHubError(f"GitHub returned {last.status_code} for {url}")


def _dig(payload: dict, *keys: str, url: str) -> object:
    node: object = payload
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            raise GitHubError(
                f"GitHub response from {url} is missing {'.'.join(keys)}"
            )
        node = node[key]
    return node


async def fetch_pull_request(
    owner: str,
    repo: str,
    number: int,
    *,
    client: httpx.AsyncClient,
    max_retries: int = 3,
    backoff_base: float = 1.0,
) -> PullRequest:
    meta_url = f"{API}/repos/{owner}/{repo}/pulls/{number}"
    meta = (
        await _get(
            client, meta_url, max_retries=max_retries, backoff_base=backoff_base
        )
    ).json()

    base_sha = _dig(meta, "base", "sha", url=meta_url)
    head_sha = _dig(meta, "head", "sha", url=meta_url)
    clone_url = _dig(meta, "base", "repo", "clone_url", url=meta_url)
    title = _dig(meta, "title", url=meta_url)

    # GitHub computes .diff against the MERGE BASE, not base.sha. Using
    # base.sha here puts every downstream mutation on the wrong line.
    compare_url = f"{API}/repos/{owner}/{repo}/compare/{base_sha}...{head_sha}"
    compare = (
        await _get(
            client, compare_url, max_retries=max_retries, backoff_base=backoff_base
        )
    ).json()
    merge_base_sha = _dig(compare, "merge_base_commit", "sha", url=compare_url)

    # A second request to the same URL: the diff needs a different Accept
    # header, and GitHub will not return both representations at once.
    diff = (
        await _get(
            client,
            meta_url,
            accept="application/vnd.github.diff",
            max_retries=max_retries,
            backoff_base=backoff_base,
        )
    ).text

    return PullRequest(
        owner=owner,
        repo=repo,
        number=number,
        title=str(title),
        base_sha=str(base_sha),
        head_sha=str(head_sha),
        merge_base_sha=str(merge_base_sha),
        clone_url=str(clone_url),
        diff=diff,
    )
