# Chesterton

**CI proves your tests pass. Chesterton proves what they'd let through.**

A counterfactual code reviewer for AI-written pull requests. It deletes each
line of your patch in a parallel universe and reports which deletions your test
suite never noticed.

Status: implemented, measured in three pre-registered studies (see Results),
with a live demo. See [`docs/design/specs/`](docs/design/specs/) for the
current design.

## Results

**Study v3, verified tests at scale.**
- **When and where:** pre-registered 2026-09-26 and run 2026-09-27 at commit `0ee40b3`.
- **The patches:** 292 AI-written patches that had passed SWE-bench's own tests, from 16 tasks in 6 Python libraries.

What `chesterton review` produced:

- **Yield:** it wrote an execution-verified regression test (one that passes on the patch and fails on a deliberate mutant of it) for **91 of 292 patches (31%)**.
  - Wilson 95% interval: 26–37%.
  - Clustered by task: 24–39%.
- **Agreement:** **73 of those 91 tests (80%)** also pass on SWE-bench's reference fix.
  - Wilson 95% interval: 71–87%.
  - Clustered by task: 65–89%.
  - The mean of the 12 per-task rates is 65%.
  - No test failed to run on the reference fix.
- **Without matplotlib-23314,** the task the pipeline was tuned on: yield 29% and agreement 81%.

How to read it:

- **It is descriptive.** It tests no hypothesis.
- **A verified test guards behaviour the patch has and its suite does not check.** It does not detect that a patch is wrong.
- **Each patch was reviewed once, and model output varies.** The 10-patch pilot, reported separately, gave agreement 2/8.
- **With 16 unequal tasks the intervals are approximate.**

The full result, per-task table and caveats are in spec §17, under "Study v3 result, as registered".

**Studies v1 and v2: does "flagged at all" separate wrong patches from accepted ones?** No.
- v2 had 151 pairs: 80% of wrong patches and 77% of accepted ones were flagged.
- McNemar p = 0.28.
- This null result is reported as registered.

Licensed under the MIT License.

## Demo

A replay of three recorded runs, plus one live call. The URL is added after
the first deploy.

1. **Wrong patch, caught:** an agent patch that passed SWE-bench and UTBoost proved wrong. Chesterton finds the change its tests miss and writes a regression test, verified by execution, that also holds on the correct fix.
2. **The correct fix:** the fix matplotlib's developers merged: the tests catch 5 of its 6 changes, and the one they miss is judged not a real gap.
3. **Checking our own tests:** in our 13-patch study, half of Chesterton's first verified tests locked in the agent's bug; one rule cut that to 1 in 9, and this story shows the one left, and how the correct fix catches it.

## How this runs on Nebius

- **Sandboxes:** Nebius Token Factory Sandboxes (`https://api.tokenfactory.nebius.com/sandboxes/`). One seed checkpoint per pull request, forked once per mutant, 24 at a time.
- **Models** on Token Factory (`https://api.tokenfactory.nebius.com/v1/`): `nvidia/Nemotron-3_5-Lightning` proposes mutants, `nvidia/nemotron-3-super-120b-a12b` triages survivors, and `nvidia/Nemotron-3-Ultra-550b-a55b` writes the regression test. The model ids are defined in `src/chesterton/llm/client.py`.
- **The demo's live call:** `api/why.py` makes a real Nemotron Super call through `chesterton.demo.why.answer`. It is capped at 60 an hour and fails closed.
- **Deploy:** Vercel environment variables:
  - `NEBIUS_API_KEY` (server-side only);
  - `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN`, or the Upstash Vercel integration's `KV_REST_API_URL` / `KV_REST_API_TOKEN`;
  - if the counter is unreachable, the live call fails closed with a 503 rather than calling the model.
- **Run it yourself:** `chesterton seed`, `chesterton run`, `chesterton review` (needs `NEBIUS_API_KEY` and `NEBIUS_PROJECT_ID`).
- **The studies:** all three were pre-registered and are reported as registered, including v1 and v2's null results. See `docs/design/specs/2026-09-18-chesterton-design.md` §17. Study v3's driver is `scripts/study_v3.py`, and its runbook is in that file's docstring.
