# Chesterton — Design

**Date:** 2026-09-18
**Status:** Approved, pre-implementation (revised same day — see §2 and §5)
**Target:** Nebius × NVIDIA Global AI Hackathon, Coding and Agentic Engineering track
**Deadline:** 2026-10-30 10:00 PT · **Judging:** 2026-12-01 to 2026-12-15

---

## 1. Thesis

> CI proves your tests pass. Chesterton proves what they'd let through.

Chesterton is a counterfactual reviewer for AI-authored pull requests. It
attacks a patch from three directions and reports what the test suite fails to
defend — then **synthesizes the oracle the suite is missing**: a concrete input
on which the patch and main disagree, the minimal subset of the patch nothing
defends, and a regression test verified by execution to catch it.

The failure mode it targets is documented and specific: a coding agent
refactors a file and quietly removes a null check, a rate limiter, or an
offline fallback that was there for a reason. Tests pass. Review misses it. The
problem compounds when the same agent writes both the code and its tests — the
tests then agree with the agent's own bug (arXiv 2607.22883).

Every tool in the AI-code-review category is a static reader inferring "this
looks wrong" from text. PR-Agent's own README states it does not execute code
or run tests. Chesterton makes an empirical, falsifiable claim instead:
*"On input `x=[], k=0`, main returns `None` and your patch raises `IndexError`.
No test in your suite exercises this. Here is the test."*

## 2. Prior art and the honest novelty claim

### The critique we must answer

**arXiv 2609.09315** (Sep 2026; 5 LLMs, 4 benchmarks, 6,000+ faulty instances)
finds that fault detection rates on LLM-generated code remain **near zero
because test oracles fail to capture faulty behaviour**, and that **mutation
testing only marginally outperforms traditional coverage criteria**, raising
questions about whether its higher cost is justified.

This is correct, and it is why mutation survival alone is not the product. The
oracle is the bottleneck, not the mutant. Mutation identifies *where* the suite
is blind; the distinguishing-input tier (§5) supplies *what it is blind to*.

### The framing we adopt

**Harden and Catch** (Meta, arXiv 2504.16472) distinguishes *hardening* tests,
which prevent future regressions and can be generated any time, from *catching*
tests, which catch a fault in one specific change — and names the **Catching
Just-in-Time (JiTTest) Challenge** as an open research problem.

Chesterton's execution-verified regression test — scoped to one PR, required to
fail on the mutant and pass on base — **is a JiTTest**. Meta named the
challenge; this is a solo-built, open-source attempt at it. That is the claim.

### What is and is not novel

Mutation testing on AI-generated code is **not** novel in 2026. It runs in
production at Meta (ACH, with an LLM equivalence-detector agent), Google (~2M
mutants surfaced during code review), and Atlassian.

Novelty split: sandbox fan-out ~0%, coverage-based selection ~0%, mutation
testing ~0%, LLM-generated mutants ~10%, **distinguishing-input synthesis
scoped to a PR diff ~50%**, **ddmin over hunks on cheap forks ~60%**,
**survivor triage rendered as a PR review ~60%**, framing ~80%.

Overclaiming would be detected and would cost credibility on everything else.
The README states this split.

### Adjacent work, not competing

- **arXiv 2608.01715** — coding agents auditing online-judge suites found 589
  verified buggy-but-accepted submissions among 20,375. Independent evidence
  that official suites systematically miss real bugs; no PR-diff workflow.
- **sandforge** (a hackathon neighbour) is an autonomous *repair* loop: it
  patches code until the suite passes. It runs the suite to validate a fix and
  never interrogates the suite's sensitivity. Opposite direction. Shared
  surface is only "forks checkpoints, two Nemotron tiers, draws a tree" — which
  is one reason the tree is demoted in §12.

## 3. Scope

### In scope

- Three analysis tiers over a PR diff (§5): uncovered lines, distinguishing
  inputs (solver-backed, with a property-based fallback), surviving mutants.
- Minimal undefended subset via ddmin over hunks (§8).
- Survivor triage and an execution-verified regression test (§9).
- A curated set of ~6-10 seeded pull requests, each backed by a Nebius prebuilt
  SWE-rebench Docker image.
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
- Stryker-schema report tab, adaptive fork-budget allocation, and invariant
  mining — all cut to pay for §5 and §8. Recorded in §19.

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

baseline load → tier 0 uncovered lines → tier 1 distinguishing inputs → tier 2
mutation fan-out → ddmin minimal subset → survivor triage → review synthesis →
regression-test verification.

### Data model (SQLite)

- `repo_seed` — slug, pr_url, base_sha, head_sha, oci_image, checkpoint_uuid,
  checkpoint_tag, coverage_map, flaky_tests, status
- `run` — seed_id, mode (`live` | `warm`), status, started_at, finished_at
- `hunk` — run_id, file, start_line, end_line, semantic_unit, in_minimal_subset
- `finding` — run_id, hunk_id, tier (`uncovered` | `distinguishing` |
  `mutation`), strength, file, line_range, payload, mutant_id (nullable)

  `finding` is the single surface the UI and triage read from. Each tier writes
  into it: tier 0 directly from the coverage map, tier 1 from parsed CrossHair
  output, tier 2 from each `survived` row in `mutant_result` (linked by
  `mutant_id`). `mutant`/`mutant_result` remain the execution record;
  `finding` is the reviewer-facing projection. `strength` orders the ladder
  and is derived from `tier`, not stored independently.
- `mutant` — run_id, hunk_id, file, start_line, end_line, operator,
  original_src, mutated_src, source (`llm` | `deterministic`), rationale,
  content_hash
- `mutant_result` — mutant_id, verdict (`killed` | `survived` | `uncovered` |
  `error`), tests_run, duration_ms, sandbox_uuid, stdout_tail
- `triage` — mutant_id, classification, invariant_kind, risk_score,
  confidence, reasoning, model
- `review` — run_id, markdown, generated_test, test_verified, model
- `event` — run_id, seq, ts, type, payload

`event` is the single source of truth for both run modes. Live runs append
while streaming; warm runs replay the identical log with original timing. One
rendering path; the warm run is a genuine recording rather than a mock.

## 5. Analysis tiers — the evidence ladder

Findings are ranked by **strength of evidence**, and the ladder is itself a
design asset: it gives the UI a natural sort order and gives the pitch a
defensible answer to the mutation-testing critique in §2.

### Tier 0 — uncovered lines (free)

A changed line with zero covering tests in the baseline coverage map is
undefended without running anything. No sandbox op, no credits. Weakest
evidence, but instant — these render before the sweep begins.

### Tier 1 — distinguishing input (strongest)

**CrossHair `diffbehavior`** (MIT, v0.0.110, released 2026-08-16, actively
maintained) uses concolic execution plus an SMT solver to find a concrete input
on which two versions of a function behave differently, printing the input and
both results.

Implementation: fork the base checkpoint, lay base at `/base` and patched at
`/patch`, put both on `sys.path` under aliased module names, and run
`crosshair diffbehavior base_x.fn patch_x.fn --per_condition_timeout=N`. One
fork per changed function — the fan-out we already have.

**Honest limits, stated in the UI and README.** Arguments need type
annotations and must be deep-copyable and equality-comparable. Functions must
be deterministic and self-contained — no I/O, no external state. Complex code
will not solve. Expected hit rate is **10–30% of changed functions**, and the
design assumes that: tier 1 runs first, tier 2 is the fallback when it times
out or cannot apply.

**Never print "equivalent."** Absence of a reported difference is not a proof
of equivalence. The UI says "no difference found within budget."

### Tier 1b — property-based distinguishing input (fallback within tier 1)

When CrossHair cannot apply — unannotated arguments, impure functions, or a
solver timeout — fall back to **Hypothesis `ghostwriter.equivalent()`**
(MPL-2.0, very mature). It emits source for a property test asserting two
functions return equal values; the Hypothesis docs name differential testing,
where neither function is trusted and any difference indicates a bug, as an
explicit use case. Ghostwrite a differential test between base and patch, then
run it in a fork.

This is random search rather than SMT, so it proves less per run but applies to
far more functions. It exists specifically to keep tier 1 populated when the
CrossHair hit rate is low (§15) — without it, tier 1 depends entirely on the
curated seeds happening to contain pure, annotated code.

Findings from this tier carry the same evidence weight as tier 1 in the UI but
are labelled by method, since a randomly-found counterexample and a
solver-proved one are not the same claim. **Known gap:** ghostwriter does not
handle functions that mutate their arguments (Hypothesis issue 4113); those
fall through to tier 2.

### Tier 2 — surviving mutant (fallback)

Mutation generation and fan-out, per §6. Applies to every changed line
regardless of annotation or purity, which is why it remains the workhorse even
though tier 1 outranks it.

## 6. Mutation generation

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
file — and hunk boundaries are **semantic, not textual**: Python's `ast` module
groups changed lines into whole statements and function bodies, so we mutate
meaningful units and spend no forks on reformatting-only hunks. Half a day,
no dependency.

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

## 7. Test selection

Baseline coverage is captured with `pytest --cov --cov-context=test_function`
and inverted into `{file: {line: [test_ids]}}`. Each mutant runs only the tests
that execute its mutated lines.

**Known constraint:** `--cov-context=test_function` is unreliable under
pytest-xdist. The baseline pass runs single-threaded. This is a one-time
build-time cost.

## 8. Minimal undefended subset (ddmin)

Given a patch whose findings are spread across many hunks, classic **delta
debugging** (`ddmin`) isolates the minimal subset of hunks the test suite fails
to defend. Each probe is one fork from the base checkpoint.

**This is the design's answer to "creative, non-obvious use of the platform."**
`ddmin` is O(n²) in the worst case, which is why it is rarely used
interactively — and cheap, content-addressed filesystem forking is exactly what
makes that cost affordable. Without this, ConTree is being used as a parallel
`for` loop.

The output is reviewer-actionable in a way a mutation score is not:
*"Of 11 hunks, these 2 are the entire undefended surface."*

Probes run inside the same semaphore budget as the mutation sweep. Reference
implementation to read (not depend on): the Debugging Book's `DeltaDebugger`.

## 9. Triage and review synthesis

The highest-value and highest-risk component. Expect **25-30% of survivors to
be equivalent mutants**; weak triage means a judge clicks a finding, gets
noise, and credibility collapses in one click.

**Classifications:** `equivalent` (behaviour unchanged — false positive),
`dead_code` (honest, low value), `untested_invariant` (the finding). Within the
third, flag `safety` (auth, rate limit, resource cleanup, bounds check) versus
`functional`.

**Evidence, not just code.** The prompt receives original and mutated source,
the operator, surrounding context, the PR title, and **which tests executed and
passed**. "Seventeen tests exercised this line and all stayed green after the
guard was deleted" is grounding a static reviewer structurally cannot have.
Tier 1 findings additionally carry the concrete distinguishing input, which
makes triage nearly trivial for them.

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
with execution rather than a disclaimer. Costs two extra sandbox ops. This
artifact is the JiTTest of §2.

## 10. Model routing

**Model IDs confirmed live on Token Factory (2026-09-18, via
`GET /v1/models?verbose=true`).** Casing is inconsistent between them — copy
these exactly, and do not infer any of them from a third-party catalogue.

| Tier | Model ID | Context | Role | Volume |
|---|---|---|---|---|
| execution | `nvidia/Nemotron-3_5-Lightning` | 1,048,576 | semantic mutant generation, log triage | thousands of calls |
| fallback | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | 262,144 | same, if Lightning underperforms | thousands of calls |
| reasoning | `nvidia/nemotron-3-super-120b-a12b` | 262,144 | survivor classification | tens of calls |
| synthesis | `nvidia/Nemotron-3-Ultra-550b-a55b` | 1,048,576 | review write-up, regression-test generation | one or two calls |

**Nemotron Ultra is available**, contrary to the earlier assumption in this
document, so the routing is a genuine three-tier funnel rather than a degraded
Nano → Super → Super.

**Throughput, not context, is the binding limit on the synthesis call.** Ultra
is `$1.00/1M` input and `$3.00/1M` output, served fp4 from `us-central1` only,
with `tools` and `reasoning` both supported — and a per-request ceiling of
**200,000 tokens/minute and 300 requests/minute**. Its context window is
1,048,576, so the window and the throughput budget are off by roughly 5×: a
full-context call would spend five minutes of allowance. Size the synthesis
prompt against the 200K/min ceiling, not the context window. Pre-summarise
mutant results on the execution tier rather than shipping raw logs to Ultra.

**Lightning over Nano for the execution tier.** Both are cheap; Lightning is
newer, carries a 1M context against Nano's 262K, and is built for the
high-volume always-on case this tier is. Nano stays as the fallback if
measurement disagrees. Pick between them on measured latency and output
quality, not on the reasoning here.

**Nemotron 3 Nano Omni is NOT served** — it does not appear in the live model
list. Nothing in this design needs it.

### Reasoning control works, and truncation is the real hazard (verified 2026-09-18)

**`chat_template_kwargs` IS honoured.** Two Super calls with an identical
prompt asking only for `{"ok": true}`:

| Call | `chat_template_kwargs` | `reasoning_tokens` | `content` |
|---|---|---|---|
| A | `{"enable_thinking": false}` | **0** | `{"ok": true}` |
| B | *(omitted)* | **64** | `\n\n{"ok": true}` |

Three things follow.

1. **Thinking is ON by default and costs real tokens** — 64 of them for a
   trivial reply. Across thousands of execution-tier calls that is a straight
   multiplier on both latency and spend. Disable it for mechanical extraction;
   keep it for the judgment calls in §9.
2. **On a complete response, reasoning does not appear in `content`.** B
   returned clean JSON with leading whitespace, not prose. `json.loads` on a
   stripped `content` is safe *when the call finishes*.
3. **The hazard is truncation, not contamination.** A call cut off by
   `max_tokens` mid-reasoning returns the partial thought as `content` — an
   Ultra call with `max_tokens: 5` returned `"The user wants a single"`.
   That parses as neither JSON nor an answer, and nothing in the response
   flags it except `finish_reason`.

**Engineering rule:** treat `finish_reason == "length"` as an error and never
parse that response. Size `max_tokens` for thinking plus answer whenever
thinking is on, and set `enable_thinking: false` on every call whose output is
consumed by a parser rather than a human.

**Prompt caching exists** (`prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`
are reported per call). The fan-out sends near-identical prompts thousands of
times per run, so holding the shared prefix stable is worth real money — order
prompts so the invariant part comes first.

Inference is served through **vLLM** (`system_fingerprint: vllm-…-tp8`).

Routing is made **legible** in the UI via a live counter: "412 Nano calls ·
9 Super · $0.04 · 24 sandboxes forked from 1 checkpoint." Judges reward smart
routing only if they can see it.

## 11. Nebius touchpoints

1. **Token Factory inference API** — all Nemotron calls, OpenAI-compatible at
   `https://api.tokenfactory.nebius.com/v1/`.
2. **Token Factory Sandboxes** — checkpoint, fan-out, CrossHair tier, and ddmin
   probes. Free during beta.
3. **Prebuilt SWE-rebench images** via `images.oci("docker://...")`.
4. **Serverless Job** — the UTBoost benchmark sweep.

The README opens with a "How this runs on Nebius" section giving the base URL,
exact model IDs, the file and line of the runtime call, and the
`nebius ai job create` command. The demo video shows a Nebius call in the first
30 seconds.

## 12. User interface

**The diff is the hero. The graph is not.**

A radial fan-out graph was the original hero and is demoted, for three reasons:
it is semantically empty (a viewer cannot name what a dot *is* twenty seconds
in); it is the single element that makes this look like sandforge, which
already ships a checkpoint branch tree; and 40 small circles with thin edges
dissolve under video compression at 1080p. Stryker's own mutation report puts
mutants **inline in source** rather than in a graph — independent evidence for
the same call.

**Left 60% — the patch, rendered large.** Shiki-highlighted real diff, mono
type at 15–16px minimum (12px does not survive video). Each changed line
carries a **gutter survival meter** that fills as findings accumulate against
it, with the line background tinting toward the survived colour.

**Right 40% — swimlanes.** One flat row per hunk; no nested span trees. Mutants
are wide capsules that slide along their lane as they execute, then snap to a
verdict colour. This is how 24 concurrent microVMs become legible; every trace
UI in the industry converged on horizontal lanes for concurrency.

**Connective tissue.** A mutant animates *out of its source line's gutter* into
its lane, which makes the two panels one idea rather than two widgets. Motion's
`layoutId` handles this.

**The money shot** (built deliberately for the video): focusing a survived
finding **wipes** the left panel between base and mutant source, showing the
exact one-token change — a deleted `if not user:` guard — with the suite still
green. The verified regression test then types in below and goes red on the
mutant, green on base. That wipe explains the product without narration.

**The radial graph survives** as a small always-on topology panel and a
four-second establishing shot. It earns the platform points; it must not be on
screen when the thesis is spoken.

### Stack

- **Shiki** for diff rendering — real TextMate grammars and VS Code themes, so
  output looks like VS Code for free, and every line is a plain DOM node we can
  decorate and animate. Highlight **server-side** and stream HTML over the
  existing SSE channel: zero browser highlighting cost. Not Monaco (2–5MB), not
  CodeMirror (we need no editing).
- **Motion** (`motion.dev`, MIT) for all animation — `AnimatePresence`,
  `layoutId`, staggered variants, and spring-driven number counters. **No
  GSAP**; two animation systems on one canvas is a hackathon-eating yak-shave.
  **Keep Motion layout animations outside the React Flow canvas** — Motion
  animates in page coordinates while React Flow nodes live in a transformed
  viewport, and mixing them costs hours.
- **shadcn/ui + Tailwind v4**, one dark palette, one sans (Inter or Geist) and
  one mono (JetBrains Mono or Geist Mono). Adopt, don't design. Restraint is
  the polish: one accent colour, generous whitespace, no gradients, no
  glassmorphism.
- `font-variant-numeric: tabular-nums` on every counter so digits don't jitter
  while animating.

### Verdict encoding — accessible and compression-proof

Red/green alone fails ~8% of male viewers **and** desaturates toward itself
under low-bitrate chroma-subsampled video. Colours are drawn from the Okabe-Ito
colourblind-safe palette, with redundancy mandatory.

| Verdict | Colour | Glyph | Meaning |
|---|---|---|---|
| Distinguishing input found | Blue `#0072B2` | ★ | tier 1 — strongest evidence |
| Survived | Vermillion `#D55E00` | ▲ | tests missed it |
| Uncovered | Orange `#E69F00` | ◆ | line never executed |
| Killed | Bluish green `#009E73` | ● | tests caught it |
| Pending | Neutral gray | ○ pulsing | — |

Three redundant channels, always: **shape** (the glyph), **position** (bad news
sorts to the top of every lane and list), and **text** (a literal word on every
chip). Acceptance test: screenshot the UI, desaturate to grayscale, and confirm
every verdict is still readable. If it is, video compression cannot hurt it
either.

### Behaviour

**Never empty.** The warm run renders on load; "Run live" re-executes; a failed
live run leaves the warm result intact. A judge arriving while another holds
the op budget sees a queue position.

**Performance:** `onlyRenderVisibleElements` stays off in the topology panel (it
inverts exactly on zoom-to-fit); `nodeTypes` and `edgeTypes` are memoized
outside the component; handlers use `useCallback`.

## 13. Testing strategy

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
4. **ddmin** — against a synthetic hunk set with a known minimal subset. Pure
   function over a predicate; no sandbox needed.
5. **CrossHair output parsing** — recorded `diffbehavior` output as fixtures,
   including the no-difference-found and timeout cases.
6. **Tier-1 fallback routing** — given a function signature, assert the correct
   tier is selected (CrossHair for annotated/pure, ghostwriter for the rest,
   tier 2 for argument-mutating functions). Pure function over metadata; no
   sandbox needed.
6. **Triage handling** — recorded Nemotron responses as fixtures; test parsing,
   ranking, and abstention deterministically. We test our handling, not the
   model.
7. **Event-log reducer** — replay a recorded log, assert final UI state. Makes
   warm mode a test artifact rather than a special case.

## 14. Failure modes

| Failure | Response |
|---|---|
| Sandbox op fails or times out | mark `error`, exclude from statistics, show honestly; never counted as killed |
| CrossHair finds nothing / times out | expected for 70–90% of functions; fall through to tier 1b, then tier 2, silently. Never render "equivalent" |
| Ghostwriter test errors or is inapplicable | fall through to tier 2; argument-mutating functions skip 1b entirely |
| Fan-out slower than expected | semaphore plus queue; warm run already on screen |
| Nebius unavailable during judging | warm runs serve everything; live button disabled with an honest message |
| Credits exhausted | hard per-run budget cap in dollars and ops; refuse to start rather than overspend |
| LLM returns malformed JSON | retry once, then fall back to deterministic mutants only |
| Nemotron Ultra absent | already the assumed path (Nano → Super → Super) |
| Checkpoint garbage-collected | tag everything; re-verify late November |
| Two judges collide on the op cap | queue with position display |
| Flaky test in the base suite | detected at seed time by running the suite 3×; flaky tests excluded from selection |

## 15. Risks

**Week-one go/no-go spike — MEASURED 2026-09-18. VERDICT: GO.**

`scripts/spike_fanout.py python:3.12-slim "sleep 2" 3` — 24-way fan-out from a
tagged checkpoint, three rounds, each fork doing a known 2s of work.

| | |
|---|---|
| baseline build (one-time, cached) | **3.3s** |
| worst-case wall clock, 24 forks | **4.1s** |
| median individual fork | **3.48s** |
| round-to-round spread | **0.2s** |
| outcomes | **72/72 ran**, 0 command failures, 0 infrastructure errors |

Two derived facts the design should be planned against:

**Per-fork overhead is ~1.5s** (3.48s median minus the 2s of known work). So a
fan-out costs roughly *slowest-selected-test-duration + 1.5s*, not the sum of
its parts. A mutant whose selected tests take 5s lands around 6.5s — an order
of magnitude inside the 20s target.

**Parallelism is real, at ~85% efficiency.** Serialised, 24 × 3.48s would be
83s; actual wall was 4.1s, a ~20× speedup across 24 slots. The forks genuinely
run side by side rather than queueing, which is the assumption the entire
fan-out architecture rests on.

The 0.2s spread over three rounds matters as much as the speed: a live demo
needs the *worst* case to be fast, not the median.

### Re-measured against a real suite (2026-09-18)

`spike_fanout.py docker://swerebench/…nomenclature-284 "python -m pytest -q -x" 3`
— a real prebuilt image running a real pytest invocation in every fork.

| | synthetic `sleep 2` | real `pytest` |
|---|---|---|
| baseline build | 3.3s | **1.2s** (image already cached) |
| worst-case wall, 24 forks | 4.1s | **4.7s** |
| median individual fork | 3.48s | **1.75s** |
| round-to-round spread | 0.2s | **1.5s** |
| outcomes | 72/72 | **72/72**, 0 failures, 0 errors |

**The 20s target holds with real work: 4.7s worst case.** The spread widening
from 0.2s to 1.5s is the expected signature of real CPU and I/O contention —
worth knowing, and still far inside budget.

**Two honest caveats.** `-x` stops at the first failure, and a SWE-bench image
sits at the pre-fix commit, so some forks likely exited early rather than
running a suite to completion — this measures fork plus interpreter start plus
*partial* execution, not a full green suite. And a real mutant run executes
coverage-selected tests against a *patched* tree, which may run longer. The
fork mechanics are proven; the per-mutant duration is not yet pinned. Re-measure
once the seed pipeline produces a genuinely green baseline.

**Load-bearing unverified facts, to confirm in week one:**

- ~~The ~7,500 prebuilt SWE-rebench images are pullable.~~ **RESOLVED
  2026-09-18 by `scripts/probe_images.py`: 4/4 candidates pulled, each with a
  repository checked out at `/testbed` and a working interpreter.** The images
  live on Docker Hub under `swerebench/`, named
  `sweb.eval.x86_64.<owner>_<pr>_<repo>-<n>`, and the reference for any instance
  is in the `docker_image` field of the SWE-rebench dataset on HuggingFace.
  The curated-seed scoping decision holds.

  **Pulls are slow: 88s–225s each, median ~114s.** That is a *build-time* cost
  and must never appear in a judge's path — which is a second, independent
  argument for the curated-seed scoping in §3, beyond environment reliability.
  Ten seeds is 20–40 minutes of one-time setup. Do it well before the October 30
  deadline, tag every resulting checkpoint (untagged images can be collected,
  and judging runs six weeks later), and re-verify the tags in late November.
- ~~Sandboxes have network egress to `api.tokenfactory.nebius.com`.~~
  **RESOLVED 2026-09-18 by `scripts/smoke_sandbox.py`: they do.** DNS resolves
  inside a sandbox (`195.242.11.3`) and TCP:443 connects. Model calls from
  inside a sandbox are therefore possible — an option the design had assumed
  away. Nothing in Phase 1 depends on it, but Phase 2's analysis tiers may.

**Also verified live on 2026-09-18, all by the same smoke test:**

- **Forks inherit parent filesystem state.** A tagged non-disposable run wrote
  a sentinel file; two concurrent forks of that checkpoint both read it back.
  This is the checkpoint-and-fork mechanic §4 rests on, and it works.
- **Tagging works**, so checkpoints can be protected from garbage collection
  across the six-week gap between submission and judging.
- **`disposable=True` really does yield no reusable checkpoint**, matching the
  Global Constraint the fake enforces offline.
- **Eight sandbox operations, including two concurrent forks, in 5.7s total.**
  Not the fan-out measurement — that is still §15's open item — but the first
  real evidence that per-operation latency is small.

**Sandboxes authorise on a `Project` header as well as a bearer token.** A key
that works against `/v1/chat/completions` is rejected here with a bare
`ForbiddenError` if `NEBIUS_PROJECT_ID` is unset. That error reads as a missing
entitlement and is not one; `sandbox/contree.py` now refuses up front with a
legible message instead.
- ~~Nebius passes `chat_template_kwargs` through to Nemotron.~~
  **RESOLVED 2026-09-18:** it does. `enable_thinking: false` yields 0 reasoning
  tokens against 64 for the same prompt without it. See §10.
- ~~Nemotron Super responds on the account's key.~~ **RESOLVED 2026-09-18:**
  all four Nemotron models are served and Super and Ultra both answer real
  completions. Exact IDs, prices and per-request limits are in §10.

**Every model-side unknown in this document is now closed.** What remains
unverified is entirely sandbox-side: the three items below.
- **Content-hash checkpoint deduplication is NOT documented.** Earlier
  reporting claimed identical filesystem state yields the identical UUID.
  Verify empirically before relying on it, and never claim it on camera
  unobserved. Even if true, it applies to pre-execution state only and is not
  evidence of semantic equivalence.

**CrossHair hit rate.** If under ~10% of changed functions in the curated seeds
produce a distinguishing input, tier 1 is demo-invisible. Two mitigations, both
in scope: the tier 1b ghostwriter fallback (§5) covers functions CrossHair
cannot solve, and seed PRs are selected partly *for* pure, annotated functions.
Measure combined tier-1 hit rate on candidate seeds in week 2, before
committing them. **Acceptance bar: at least one curated seed must produce a
solver-proved distinguishing input**, since that is the demo's strongest
single moment and random search cannot substitute for it on camera.

**Survivor noise.** Triage deserves more of the six weeks than the
visualization does, even though the visualization is what judges remember.

**The 50-op beta cap.** Request an increase from Nebius support in week one.
Semaphore at 24 regardless. ddmin probes share the same budget.

**Dependency volatility.** `contree-sdk` is Apache-2.0 and days-to-weeks old
with a handful of stars. Call `contree_get_guide` via its MCP server for ground
truth before writing sandbox code, and keep the raw REST path as a fallback.

## 16. Licensing constraints

The repository ships under MIT. Traps to avoid:

- **Mutahunter is AGPL-3.0.** The nearest LLM-mutation cousin and completely
  unusable — do not vendor, copy, or depend on it.
- **Semgrep's maintained rulesets** are under a licence restricted to internal,
  non-competing, non-SaaS use. Static rules are not used anyway; they would
  undercut the "we execute, they merely read" differentiation.
- **elkjs is EPL-2.0** — safe as an unmodified dependency, copyleft if patched.
  Not used; the topology panel's layout is hand-computed.

Direct dependencies and their licences: `crosshair-tool` (MIT), `hypothesis`
(MPL-2.0), `libcst` (MIT), `contree-sdk` (Apache-2.0),
`coverage`/`pytest`/`pytest-cov` (MIT/Apache-2.0), `@xyflow/react` (MIT),
`motion` (MIT), `shiki` (MIT), shadcn/ui (MIT).

**MPL-2.0 note:** Hypothesis is file-level copyleft. Using it as an unmodified
dependency imposes no obligation on this MIT codebase. If any Hypothesis source
file were modified, that file — and only that file — would have to stay
MPL-2.0. We do not modify it.

Safe to learn from: cosmic-ray (MIT) for its two-phase init/exec split,
mutmut's `node_mutation.py` (BSD-3) for the operator catalogue, LLMorpheus
(MIT) for its PLACEHOLDER-marker mutant-generation prompt pattern, PR-Agent
(MIT) for diff-context compression prompts, the Debugging Book for `ddmin`.

## 17. Benchmark claim

UTBoost (ACL 2025, MIT) is a validated corpus of AI patches that pass weak test
suites: **15.7% of SWE-bench Verified patches are erroneous despite passing**,
with 169 scored PASS by the original harness. Running Chesterton against the
instances UTBoost identified as having test gaps yields a headline number with
external ground truth, which is far stronger than a self-reported mutation
score.

## 18. Schedule

| Week | Focus |
|---|---|
| 1 | Fan-out spike (go/no-go). Credit codes, op-cap request, image-pull verification. |
| 2 | Coverage contexts, diff-to-line mapping, GitHub ingest, seed pipeline. Measure CrossHair hit rate on candidate seeds. |
| 3 | LibCST operators, Nano mutant generation, validation gate, CrossHair tier, ghostwriter fallback. |
| 4 | Triage, regression-test verification, ddmin. **Most time here.** |
| 5 | Diff-hero UI, swimlanes, SSE streaming, hosted deploy. |
| 6 | UTBoost benchmark run, video (two full days), README. |

Judging runs six weeks after submission. The demo URL, checkpoints, credits,
and PAT must all be re-verified in late November.

### Video structure

Show the product working in the first 10–15 seconds. No title card, no logo
animation, no team intro. Start already logged in, on a pre-warmed backend with
results cached — never let a judge watch a spinner. Record at 2560×1440 and
export 1080p; downscaling is the cheapest sharpness available.

- **0:00–0:03** — a green CI check on a PR labelled "authored by an agent."
  *"This pull request passes every test."*
- **0:03–0:08** — the diff wipes to the mutant: a deleted `if not user:` guard,
  suite still green. *"Here it is with the authorization check deleted. Still
  green."*
- **0:08–0:15** — cut wide; survival meters light up, lanes fill. *"CI proves
  your tests pass. Chesterton proves what they'd let through."*
- 0:15–1:00 distinguishing input · 1:00–1:40 verified regression test ·
  1:40–2:10 minimal undefended subset · 2:10–2:45 platform, cost, architecture ·
  2:45–3:00 MIT and close.

## 19. Deferred — recorded, not built

Cut to pay for §5 and §8, or judged not worth the cost. Listed so the decisions
are not silently re-litigated:

- **Stryker-schema report tab.** Free credible rendering, but redundant once
  the diff is the hero.
- **Adaptive fork budget** (bandit over hunks). Genuine engineering answer to
  the op cap; revisit only if the cap is not raised.
- **Invariant mining** (`sys.monitoring` + Daikon-style templates). The best
  remaining reframe — "your patch silently broke an invariant nothing tested" —
  at 3–4 days. Daikon itself is a trap: Java-only, no maintained Python front
  end.
- **Agent-provenance detection** (`Co-Authored-By` trailers, bot accounts,
  branch prefixes). ~2 hours and a good product moment, but a regex over commit
  trailers is not a research contribution and must not be presented as one.
- **Metamorphic testing, Atheris fuzzing, SymDiff.** Traps — domain-specific,
  harness-per-target, or no Python front end.

## 20. Open decisions

**Hosting (decide by week 5).** Not yet chosen. The binding constraint is that
the demo URL, its backing checkpoints, and its credits must all remain live and
funded from submission on 2026-10-30 through the close of judging on
2026-12-15. A free tier that lapses in November is a self-inflicted zero.
Requirements: persistent process for SSE, a small disk for SQLite, an outbound
path to Nebius, and a stable public URL.

**Curated PR selection (decide by week 2).** The specific ~6-10 pull requests
are not yet chosen. Selection criteria: each must have a matching Nebius
prebuilt image, a deterministic suite, at least one hunk where a safety
invariant is plausibly undefended, and — new — enough pure, type-annotated
functions for the CrossHair tier to land. At least one seed should be drawn
from the UTBoost-identified set so the demo and the benchmark claim reinforce
each other.
