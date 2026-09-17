# Chesterton — Design

**Date:** 2026-09-18
**Status:** Approved, pre-implementation
**Target:** Nebius × NVIDIA Global AI Hackathon, Coding and Agentic Engineering track
**Deadline:** 2026-10-30 10:00 PT · **Judging:** 2026-12-01 to 2026-12-15

---

## 1. Thesis

> CI proves your tests pass. Chesterton proves what they'd let through.

Chesterton is a counterfactual reviewer for AI-authored pull requests. For each
changed hunk it generates semantic mutations, executes the test suite against
every mutant in a forked microVM, and reports the mutations that **survived** —
lines the test suite does not defend.

The failure mode it targets is documented and specific: a coding agent
refactors a file and quietly removes a null check, a rate limiter, or an
offline fallback that was there for a reason. Tests pass. Review misses it.

Every tool in the AI-code-review category is a static reader inferring "this
looks wrong" from text. Chesterton makes an empirical, falsifiable claim:
*"I deleted your rate-limit guard, ran your tests, and they went green."*

## 2. Honest novelty claim

Mutation testing on AI-generated code is **not** novel in 2026. It runs in
production at Meta (ACH, with an LLM equivalence-detector agent), Google
(~2M mutants surfaced during code review), and Atlassian.

What is unbuilt in the open, and what this project claims:

**Mutation testing scoped to a PR diff, fanned out over forked filesystem
checkpoints, and delivered as a reviewer-legible review with a verified
regression test.**

Rough novelty split: sandbox fan-out ~0%, coverage-based selection ~0%,
mutation testing ~0%, LLM-generated mutants ~10%, **survivor triage rendered as
a PR review ~60%**, framing ~80%.

Overclaiming the general idea would be detected and would cost credibility on
everything else. The README must state this split.

## 3. Scope

### In scope

- A curated set of ~6-10 seeded pull requests, each backed by a Nebius
  prebuilt SWE-rebench Docker image.
- Python repositories only.
- A hosted web demo requiring no signup and no installation.
- A benchmark run against UTBoost / SWE-bench Verified producing one headline
  number.

### Explicit non-goals (stated in the README)

- Arbitrary "paste any public PR" support. Getting an arbitrary repo to a green
  test suite inside a microVM is the problem SWE-bench spent years and ~7,500
  prebuilt images solving. A solo builder will not beat it in six weeks.
- JavaScript/TypeScript repositories.
- Posting reviews back to GitHub (requires OAuth; zero judge-visible value).
- User accounts, authentication, persistence across sessions.

## 4. Architecture

A single FastAPI service owns run state in SQLite, drives Token Factory
Sandboxes directly via `asyncio.gather` behind a semaphore, and streams state
transitions to a React front end over SSE. The UTBoost benchmark sweep runs
separately as a **Nebius Serverless Job** — a natural batch fit and a second,
honest Nebius touchpoint for the Stage One gate.

Rejected alternatives:

- **Job-queue for interactive runs.** Nebius rates serverless startup latency
  only "Moderate"; endpoint creation takes ~5 minutes. Putting that in front of
  a judge trades the demo's best 40 seconds for an architecture diagram.
- **Precompute-only static site.** Zero runtime risk, but it is a recording,
  not a product. Retained only as the fallback if the week-one fan-out spike
  comes back slow.

### Phases

**Build time (ahead of the demo), per curated PR:**

1. Resolve base SHA and diff from GitHub.
2. Select the matching Nebius prebuilt SWE-rebench image.
3. Build the baseline checkpoint: install dependencies, run the full suite with
   `--cov-context=test_function`, snapshot.
4. Run the base suite **three times** and exclude any non-deterministic test
   from later selection.
5. **Tag the checkpoint.** Untagged images may be garbage-collected, and
   judging is six weeks after submission.
6. Store checkpoint UUID, inverted coverage map, and diff.

**Run time (judge clicks):**

baseline load → mutant generation → test selection → fan-out execution →
survivor triage → review synthesis → regression-test verification.

### Data model (SQLite)

- `repo_seed` — slug, pr_url, base_sha, head_sha, oci_image, checkpoint_uuid,
  checkpoint_tag, coverage_map, flaky_tests, status
- `run` — seed_id, mode (`live` | `warm`), status, started_at, finished_at
- `mutant` — run_id, file, start_line, end_line, operator, original_src,
  mutated_src, source (`llm` | `deterministic`), rationale, content_hash
- `mutant_result` — mutant_id, verdict (`killed` | `survived` | `uncovered` |
  `error`), tests_run, duration_ms, sandbox_uuid, stdout_tail
- `triage` — mutant_id, classification, invariant_kind, risk_score,
  confidence, reasoning, model
- `review` — run_id, markdown, generated_test, test_verified, model
- `event` — run_id, seq, ts, type, payload

`event` is the single source of truth for both run modes. Live runs append
while streaming; warm runs replay the identical log with original timing. One
rendering path; the warm run is a genuine recording rather than a mock.

## 5. Mutation generation

**Two sources.** Deterministic LibCST operators guarantee mutants exist even if
the LLM flakes; Nemotron Nano proposes the semantic ones. Nano is correct here
— high-volume, cheap calls, which makes the model tiering structurally honest
rather than decorative.

**Operator catalogue, biased toward safety invariants:**

- delete a guard clause or early return
- remove a branch that raises
- invert a boolean condition
- drop an `await`
- widen an `except` from specific to bare
- remove a `finally` or context-manager cleanup
- off-by-one on comparison operators
- **strip a decorator** (`@requires_auth`, `@rate_limit`, `@retry`)

The decorator operator maps most directly onto the documented failure mode and
is given prominence in the UI and the demo.

**Mutations are scoped to lines inside the PR diff hunks only**, never the whole
file. This is the precise claim in section 2, and it keeps runs small enough to
fan out.

**Validation gate, before any mutant costs a sandbox op.** Every mutant must
round-trip to parseable Python, differ from the original, apply cleanly at the
correct line, and survive content-hash dedup. Invalid mutants are dropped
silently. This is not optional: a mutant that fails to compile makes tests
error, which reads as *killed* — a silent false negative.

**Line-mapping hazard.** GitHub's `.diff` is computed against the merge base,
not `base.sha`. Confusing them puts every mutation on the wrong lines. This gets
a dedicated golden test.

**Budget.** 30-40 mutants per run, ranked by operator risk weight, executed
behind `asyncio.Semaphore(24)`.

## 6. Test selection

Baseline coverage is captured with `pytest --cov --cov-context=test_function`
and inverted into `{file: {line: [test_ids]}}`. Each mutant runs only the tests
that execute its mutated lines.

**A third verdict falls out for free.** A mutated line with zero covering tests
is `uncovered` — undefended without running anything. No sandbox op, no
credits, and it is the most damning finding available.

**Known constraint:** `--cov-context=test_function` is unreliable under
pytest-xdist. The baseline pass runs single-threaded. This is a one-time
build-time cost.

## 7. Triage and review synthesis

The highest-value and highest-risk component. Expect **25-30% of survivors to
be equivalent mutants**; weak triage means a judge clicks a red node, gets
noise, and credibility collapses in one click.

**Classifications:** `equivalent` (behaviour unchanged — false positive),
`dead_code` (honest, low value), `untested_invariant` (the finding). Within the
third, flag `safety` (auth, rate limit, resource cleanup, bounds check) versus
`functional`.

**Evidence, not just code.** The prompt receives original and mutated source,
the operator, surrounding context, the PR title, and **which tests executed and
passed**. "Seventeen tests exercised this line and all stayed green after the
guard was deleted" is grounding a static reviewer structurally cannot have.

**Two stages.** A deterministic pre-filter catches obvious equivalents
(mutations inside logging-only statements, code unreachable after a return,
constants never compared). Only survivors of that reach Nemotron Super with
thinking enabled at a ~1024 reasoning budget — the published sweet spot, since
higher budgets inflate latency up to 4× for little gain. Structured output via
`json_schema`, with the schema also restated in the prompt text.

**Abstention is required.** Uncertain items go to a secondary "worth a look"
list, never the headline. Three confident findings beat eleven noisy ones. The
two or three findings shown prominently are sampled three times and must agree.

**Regression test, verified by execution.** One test is generated for the top
finding, then verified in two fresh forks: it **must fail on the mutant and
pass on the base checkpoint**. If it does not verify both ways it is never
rendered. This answers Trail of Bits' warning — that an uncritical agent
writing a test from a surviving mutant may encode a bug as correct behaviour —
with execution rather than a disclaimer. Costs two extra sandbox ops.

## 8. Model routing

| Tier | Role | Volume |
|---|---|---|
| Nemotron Nano | semantic mutant generation, log triage | thousands of calls |
| Nemotron Super | survivor classification, review synthesis | tens of calls |

**Nemotron Ultra is not assumed.** Its availability on Token Factory is
unconfirmed. The architecture is Nano → Super → Super; if Ultra is live it
takes the final write-up, but nothing depends on it.

Routing is made **legible** in the UI via a live counter: "412 Nano calls ·
9 Super · $0.04 · 24 sandboxes forked from 1 checkpoint." Judges reward smart
routing only if they can see it.

## 9. Nebius touchpoints

1. **Token Factory inference API** — all Nemotron calls, OpenAI-compatible at
   `https://api.tokenfactory.nebius.com/v1/`.
2. **Token Factory Sandboxes** — checkpoint and fan-out; the core mechanic.
   Free during beta.
3. **Prebuilt SWE-rebench images** via `images.oci("docker://...")`.
4. **Serverless Job** — the UTBoost benchmark sweep.

The README opens with a "How this runs on Nebius" section giving the base URL,
exact model IDs, the file and line of the runtime call, and the
`nebius ai job create` command. The demo video shows a Nebius call in the first
30 seconds.

## 10. User interface

One screen: a fan-out graph centre, a ranked findings panel right, one
secondary tab rendering the standard Stryker `mutation-testing-report-schema`.

**Graph.** React Flow (`@xyflow/react`, MIT). A root node — repo, PR title,
"suite green, N tests" — with mutants radiating outward on a hand-computed
radial layout. No layout engine: one root with N children is trigonometry, not
a graph-layout problem, and dagre has been unmaintained since ~2018.

Node states: dim `pending` → pulsing `running` → green `killed` (then dims and
shrinks so survivors dominate) → red `survived` → amber `uncovered`. Each node
is a small React card showing its operator and a one-line code fragment.

**Motion is the payload.** Emission staggered over ~1.5s, radius interpolated
from zero, colour transitioned on verdict. Amber `uncovered` nodes appear
instantly at t=0 — findings on screen before the sweep begins.

**Findings panel** ranks by risk × confidence. Each entry: severity chip,
one-sentence claim, the actual mutation diff, the test evidence, the
classification. The top finding shows the verified regression test and its
two-way proof. All evidence is inspectable rather than asserted.

**Never empty.** The warm run renders on load; "Run live" re-executes; a failed
live run leaves the warm result intact. A judge arriving while another holds
the op budget sees a queue position.

**Performance traps designed around:** `onlyRenderVisibleElements` stays off
(it inverts exactly on zoom-to-fit, the money shot); `nodeTypes` and
`edgeTypes` are memoized outside the component; handlers use `useCallback`.

## 11. Testing strategy

**The enabling decision: ConTree sits behind a `SandboxRunner` protocol with a
fake in-memory implementation.** Iterating a pipeline against a beta API with a
50-op cap and finite credits is not viable. With a fake runner the whole
pipeline runs offline in milliseconds; the real implementation is one thin
adapter exercised deliberately.

In priority order:

1. **Diff-to-line mapping**, against a recorded fixture from a known public PR.
   The merge-base hazard silently corrupts everything downstream.
2. **Coverage-map inversion** — pure function over a recorded `coverage.json`.
3. **Each mutation operator** — fixture in, expected mutant out — plus the
   validation gate dropping unparseable, identical, and non-applying mutants.
4. **Triage handling** — recorded Nemotron responses as fixtures; test parsing,
   ranking, and abstention deterministically. We test our handling, not the
   model.
5. **Event-log reducer** — replay a recorded log, assert final UI state. Makes
   warm mode a test artifact rather than a special case.

## 12. Failure modes

| Failure | Response |
|---|---|
| Sandbox op fails or times out | mark `error`, exclude from statistics, show honestly; never counted as killed |
| Fan-out slower than expected | semaphore plus queue; warm run already on screen |
| Nebius unavailable during judging | warm runs serve everything; live button disabled with an honest message |
| Credits exhausted | hard per-run budget cap in dollars and ops; refuse to start rather than overspend |
| LLM returns malformed JSON | retry once, then fall back to deterministic mutants only |
| Nemotron Ultra absent | already the assumed path (Nano → Super → Super) |
| Checkpoint garbage-collected | tag everything; re-verify late November |
| Two judges collide on the op cap | queue with position display |
| Flaky test in the base suite | detected at seed time by running the suite 3×; flaky tests excluded from selection |

## 13. Risks

**Week-one go/no-go spike.** The architecture assumes forking a warm checkpoint
24 ways completes fast enough to feel live. This is unmeasured. Build a
checkpoint from a real prebuilt image, fork it 24 ways with `asyncio.gather`,
and time it. If fan-out takes minutes rather than seconds, the design collapses
toward the precompute-only fallback and is redesigned around a smaller mutant
set chosen by the triage model rather than a wide sweep.

**Load-bearing unverified facts, to confirm in week one:**

- The ~7,500 prebuilt SWE-rebench images are pullable. This claim comes from a
  HuggingFace discussion thread, not formal docs, and it mitigates the project's
  largest risk. Verify two or three specific pulls.
- Sandboxes have network egress to `api.tokenfactory.nebius.com` (undocumented;
  an open community issue asks exactly this).
- Nebius passes `chat_template_kwargs` through to Nemotron, so reasoning-budget
  control works.
- Nemotron Super responds on the account's key.

**Second risk: survivor noise.** Triage deserves more of the six weeks than the
visualization does, even though the visualization is what judges remember.

**Third risk: the 50-op beta cap.** Request an increase from Nebius support in
week one. Semaphore at 24 regardless.

**Dependency volatility.** `contree-sdk` is Apache-2.0 and days-to-weeks old
with a handful of stars. Call `contree_get_guide` via its MCP server for ground
truth before writing sandbox code, and keep the raw REST path as a fallback.

## 14. Licensing constraints

The repository ships under MIT. Two traps to avoid:

- **Mutahunter is AGPL-3.0.** The nearest LLM-mutation cousin and completely
  unusable — do not vendor, copy, or depend on it.
- **Semgrep's maintained rulesets** are under a licence restricted to internal,
  non-competing, non-SaaS use. A hosted demo is arguably SaaS. Static rules are
  not used anyway; they would undercut the "we execute, they merely read"
  differentiation.

Safe to learn from: cosmic-ray (MIT) for its two-phase init/exec split,
mutmut's `node_mutation.py` (BSD-3) for the operator catalogue, LLMorpheus
(MIT) for its PLACEHOLDER-marker mutant-generation prompt pattern, PR-Agent
(MIT) for diff-context compression prompts.

## 15. Benchmark claim

UTBoost (ACL 2025, MIT) is a validated corpus of AI patches that pass weak test
suites: **15.7% of SWE-bench Verified patches are erroneous despite passing**,
with 169 scored PASS by the original harness. Running Chesterton against the
instances UTBoost identified as having test gaps yields a headline number with
external ground truth, which is far stronger than a self-reported mutation
score.

## 16. Schedule

| Week | Focus |
|---|---|
| 1 | Fan-out spike (go/no-go). Credit codes, op-cap request, image-pull verification. |
| 2 | Coverage contexts, diff-to-line mapping, GitHub ingest, seed pipeline. |
| 3 | LibCST operators, Nano mutant generation, validation gate. |
| 4 | Triage and regression-test verification. **Most time here.** |
| 5 | React Flow UI, SSE streaming, hosted deploy. |
| 6 | UTBoost benchmark run, video (two full days), README. |

Judging runs six weeks after submission. The demo URL, checkpoints, credits,
and PAT must all be re-verified in late November.
