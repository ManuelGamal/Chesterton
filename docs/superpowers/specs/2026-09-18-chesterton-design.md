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

### As built — 2026-09-23

`chesterton review SEED RUN` reads an existing run, so runs and the benchmark
never change. Decisions the section above left open:

- **Pre-filter:** one rule, right by construction, decided from an `ast`
  check on the diff between the mutant's WHOLE original and mutated modules
  (never the display window, which an operator can edit past): every changed
  line is a single whole-line call to `print` (with no `file=` keyword) or to
  a logger method (`debug`/`info`/`warning`/`warn`/`error`/`exception`/
  `critical`/`log` on a logger-named receiver), with no call or other side
  effect in its arguments. `warnings.warn` is deliberately NOT dismissed - a
  warning's category is observable (`pytest.warns`, `-W error`, a project's
  own `filterwarnings = error`) - so it goes to the model like anything else
  uncertain.
- **Headline:** confident `untested_invariant`, ranked safety first, then by
  how many tests ran it and still passed; at most one per hunk and three per
  run; each confirmed 3 of 3 times, or it is only "worth a look".
- **A total model outage is an error, not "0 findings".** A bad key or a
  denied model must not read as a clean review: if every survivor sent to
  the model came back unavailable, `chesterton review` exits 2 naming the
  cause instead of writing a report that looks like nothing was found.
- **Regression test:** for the first headline with a covering test, written
  by Ultra beside the covering test (`test_chesterton_regression.py`),
  verified in two forks (exit 0 on the PR, exit 1 on the mutant; any other
  code proves nothing), repaired once with the failing output. At most 4
  sandbox ops per review.
- **The ~1024 reasoning budget above is not enforced.** The code sizes
  `max_tokens` at 8192 (thinking plus a short JSON answer) and has no way to
  cap thinking tokens separately from the reply.
- **Measured before it is pitched:** `scripts/review_study.py` runs it on
  matplotlib-23314's 13 wrong agent patches and checks each verified test
  against the gold fix. A test that fails on gold encoded the agent's bug and
  is reported as such. Exploratory, not a benchmark.
- **First live result — 2026-09-23, exploratory (13 patches, one task).**
  12 of 13 wrong patches got a headline finding and 10 a verified test. 5
  of those passed on the gold fix and asserted only public behaviour
  (`ax.get_visible()`); 5 failed on gold, and every one of them pinned the
  agent's implementation: `ax._axis3don`, `ax._axis_map`, or a fake `zaxis`
  swapped in. They are hardening tests for the agent's design, not for the
  intended behaviour. A verified test passes on the patch by construction,
  so it can never catch that patch's own bug: the catch is the finding, and
  the test is the regression guard.
- **Response:** a generated test that reads or writes a private attribute
  or imports a private name (a leading underscore; dunders and a test
  class's own `self._x` / `cls._x` exempt) is rejected before verification,
  at no sandbox cost, and the repair prompt names the attributes. On the 10
  study tests it flags 4 of the 5 that failed on gold and none of the 5 that
  passed; the fake-`zaxis` case is invisible to a static rule.
- **Second live result, with the rule — 2026-09-24, exploratory (same 13
  patches, one run each; `review-study-2/`).** 12 of 13 got a headline
  finding and 9 a verified test; 8 of the 9 pass on the gold fix, against 5
  of 10 before. The 3 unverified tests failed on the PR's own code on both
  attempts and were refused. The one left, `92beef201cfd`, uses only public
  API: an image comparison asserting that an axes hidden and shown again
  still renders as hidden, which is the agent's real bug (its
  `_axis3don = b and self._axis3don` never restores the axes). The model
  wrote the bug down as the expected behaviour; no static rule can see
  that, only an oracle such as the gold fix. Model output varies between
  runs (`9b606524fdb2` had a headline in the first run and none in the
  second), so 5 → 1 is a strong signal from the rule's mechanism, not a
  controlled measurement.

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

### Re-measured against a real suite (2026-09-18) — INVALID, see correction

> **CORRECTION 2026-09-19. This measurement did not run a test suite.** In a
> SWE-rebench image the `python` on PATH is conda *base*
> (`/opt/conda/bin/python`), which has no pytest; the repository's
> dependencies live in `/opt/conda/envs/testbed/bin/python`. Measured by
> `scripts/probe_interpreter.py`: plain `python -m pytest` there exits **1**
> with `No module named pytest`. The spike counted exit 1 as "tests ran and
> failed", so every one of the 72 "runs" below was an interpreter failing to
> import pytest. The table measures fork + interpreter start + an ImportError.
> The fork *mechanics* still stand (the synthetic `sleep 2` column is
> unaffected), but **"the 20s target holds with real work" is unproven** until
> a real run under the testbed interpreter. The spike's classification is the
> defect: exit 1 is a test failure only when pytest actually started.

`spike_fanout.py docker://swerebench/…nomenclature-284 "python -m pytest -q -x" 3`
— intended as a real prebuilt image running a real pytest invocation in every
fork; see the correction above for what it actually ran.

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

### Phase 3 live end-to-end — MEASURED 2026-09-19

`python -m chesterton seed` then `run` on nomenclature PR #284 ("Raise error
for unknown region"), image `…iamconsortium_1776_nomenclature-284`, interpreter
`/opt/conda/envs/testbed/bin/python`. This is the first measurement that ran a
real test suite (see the correction above).

| | |
|---|---|
| seed | checkpoint tagged `chesterton:seed-nomenclature-284`; **137 selectable**, 2 flaky, 3 failing tests after three baseline runs |
| **per-mutant duration** | **median 3.96 s, worst 4.16 s** (19 coverage-selected tests, n=5 across both runs) |
| run, deterministic only | 2 hunks, 1 mutant (killed), 4 sandbox ops of 160, **22.9 s** wall incl. ddmin |
| run, with Lightning | 8 mutants: 3 killed, 1 survived, 4 uncovered, 0 error; 7 ops; **28.2 s** wall |
| model | 3 calls for 2 hunks, 1 retried, 0 final failures; the gate rejected 1 no-op |
| ddmin | 2 hunks, **3 probes**, 0 undefended, which is correct: reverting either hunk breaks the PR's new test |

**The 20 s per-mutant target holds with real work, at ~4 s.** This replaces
the invalid 4.7 s figure above.

**Found live and fixed the same day:** the seed build ran conda *base*
(`--python` now required in practice); a failed build hid its cause
(`stderr or stdout`); `-rA` captured-log lines were parsed as failing tests;
and Phase 1's dropping of the empty coverage context turned a changed
**import line** into a false tier-0 finding. Import time now counts as
executed.

**Open, from this run, with the evidence:**
- **The one survivor is dead code.** Lightning added `pass` *after* the
  `raise`, which is unreachable, and its rationale ("making the raise
  unreachable") is false. The score reads 75% when every catchable mutant was
  caught. This is live justification for Phase 4's deterministic equivalence
  pre-filter; dead code after `raise`/`return` is the first case it should
  handle.
- ~~**`delete_guard` did not fire on the PR's own guard.**~~ **RESOLVED
  2026-09-19.** A guard may now make bare calls, such as logging, before its
  final `raise`/`return`; assignments are still excluded. Re-run live
  (`runs/nomenclature-284-v2.json`): `delete_guard` fired first on the PR's
  guard, removing the condition, the `log_error` and the `raise`, and was
  **killed** by the PR's new test.
- ~~**Mutants on import-only lines are unselectable.**~~ **RESOLVED
  2026-09-19.** They now run the whole selectable suite, and the budget check
  counts them. Live: of four model mutants on the import line, the two alias
  renames were **killed** (`NameError` at the call site), and the two
  importing a name that does not exist exited pytest 4 and are **error, not
  kill**, per the rule that a mutant stopping a module importing is never
  counted as caught.

**Re-run after both fixes:** 8 mutants, **5 killed, 1 survived, 0 uncovered, 2
error**, 11 ops, 25.5 s wall, per-mutant median 3.86 s and worst 4.77 s (a
whole-suite run). This time the survivor is a genuine gap, not dead code:
`raise ValueError("Validation error.")` drops the "check the log for
details" text, and the PR's test uses `pytest.raises(ValueError)` without
`match=`. Nothing pins the user-facing message. The dead-code survivor did
not recur this run; model proposals vary, and the Phase 4 pre-filter is
still needed.
- **This seed is well defended, so it does not show the demo's moment.** A
  demo seed needs a PR with an undefended hunk (spec §20: curated selection).

**Load-bearing unverified facts, to confirm in week one:**

- ~~The ~7,500 prebuilt SWE-rebench images are pullable.~~ **RESOLVED
  2026-09-18 by `scripts/probe_images.py`: 4/4 candidates pulled, each with a
  repository checked out at `/testbed` and a working interpreter.** *Narrowed
  2026-09-19:* "working interpreter" meant only that `python --version`
  answered. That `python` is conda base and cannot run the repository's tests;
  use `/opt/conda/envs/testbed/bin/python` (`--python` on `chesterton seed`),
  and check a new image with `scripts/probe_interpreter.py`. The images
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

**MEASURED 2026-09-19 (Phase 2, Task 9).** Eligibility on a real seed —
`IAMconsortium/nomenclature` @ `a0408e52fc6b2402c448c174802c16441326b80c`,
source tree only — is **77/256 functions = 30%**, the top of the estimate above
and well clear of the ~10% floor. `scripts/probe_crosshair.py` reproduces it.
Of the 179 ineligible, 90 take no arguments, 52 have unannotated arguments and
28 lack a return annotation. Those three are exact AST facts and account for
the bulk of the ceiling. **The purity figure is not a fact and must not be
quoted.** Only 9 functions were rejected as impure, but the probe tests a
six-name heuristic against the root of a call: it reports `self.session.get(url)`,
`p.read_text()`, `os.environ[name]` and `x + time.time()` as *eligible*. The
impurity screen therefore **overstates** eligibility, unlike the probe's other
gaps, which all undercount. Read 30% strictly as an upper bound: 170 of 256
functions are disqualified on annotations alone, and some unknown share of the
remaining 86 is impure. This codebase scores 45/71 = 63% and is not
representative — we annotate more heavily than the seeds do.

Eligibility is a ceiling, not a hit rate. But the acceptance bar is also met in
principle: `crosshair diffbehavior` on Python 3.13.14 distinguished
`if amount > balance` from `if amount >= balance` — our own `off_by_one`
operator — in **0.38s**, reporting `Given: (amount=0, balance=0)` with one
function returning `0` and the other raising. That is the demo moment, proved
on the real interpreter rather than assumed.

`crosshair-tool` 0.0.110 is MIT and installs on Python 3.13.14. Note its CLI
has no top-level `--version` flag (`python -m crosshair --version` exits 2);
read `crosshair.__version__` instead. **Phase 2b is justified on these
numbers.**

**Non-zero exit vs failed operation — MEASURED 2026-09-19.** Raw
`contree_sdk` against `ubuntu:latest`: `exit 0` and `exit 1` both return an
image in state `SUCCEEDED`, with `exit_code` 0 and 1 respectively and stdout and
stderr readable. `sleep 60` under a 5 s timeout **raises**
`OperationTimedOutError` after 5.6 s. So a killed mutant — tests fail, command
exits non-zero — is an ordinary result, and an *exception* from `run()` is what
marks a sandbox `error`. `run()` re-raises on a failed operation rather than
returning a `FAILED` image, so the adapter must catch the SDK's `ContreeError`
family around the call; a post-hoc state check on the returned image can never
fire.

### Seed screening on UTBoost instances — MEASURED 2026-09-19

UTBoost's 36 augmented instances were recovered by diffing
`Bertsekas/SWE-Bench_{Verified,Lite}_UTBoost` against
`princeton-nlp/SWE-bench_{Verified,Lite}` on `test_patch`. That gives exactly
36, matching the paper. 14 are Django, whose suite is not pytest, so they are
out. All 7 shortlisted images exist on Docker Hub under `swebench/`, and their
interpreter is `/opt/miniconda3/envs/testbed/bin/python` (SWE-rebench images
use `/opt/conda/...`). Seeded with `chesterton seed --swebench ID`, which uses
the gold patch plus the original test_patch, scoped to its test files.

| seed | scope | mutants | killed / survived | tier 0 | ddmin | per-mutant |
|---|---|---|---|---|---|---|
| xarray-7393 | 73 tests | 10 | 9 / 1 | 0 | 1 of 1 hunks needed | ~2 s |
| matplotlib-23314 | 864 tests | 6 | 5 / 1 | 0 | 1 of 1 hunks needed | **median 23.3 s, over the 20 s target** |

**Negative result, and it matters for §17.** On both instances, mutating the
*gold* patch does not rediscover the gap UTBoost found. The PRs' own tests
kill the gold patch's mutants, including `delete_guard` on matplotlib's
`if not self.get_visible(): return`. UTBoost's gaps are gaps against
*alternative* implementations. Its matplotlib test adds drawn content, which
a fix that hides only the background would fail. Small mutations of the
correct fix rarely reach those. Both survivors were also effectively no-op
mutants (`dtype is None` to `== None`; `not x` to `x is False` on a bool),
more live cases for the Phase 4 equivalence pre-filter.

**Implication:** a SWE-bench *gold* patch is defended by construction, since
its test_patch was written for it, so it is a poor demo seed. The thesis
target is the *agent* patch: UTBoost found 345 agent patches that passed
SWE-bench's tests and were wrong. That list is not published, but it is
reconstructible from SWE-bench's `experiments` submissions: resolved patches
that fail UTBoost's augmented test.

### Known-wrong agent patches — MEASURED 2026-09-19

**This is the first evidence for the §17 benchmark claim.** Resolved agent
patches for matplotlib-23314 were collected from SWE-bench's public
submissions (`scripts/collect_agent_patches.py`): 131 resolving submissions,
75 distinct patches, of which only 20 submissions match gold. Each was screened
in one sandbox op (`scripts/screen_agent_patches.py`): pass SWE-bench's
original FAIL_TO_PASS, then UTBoost's augmented FAIL_TO_PASS. **13 distinct
patches, from 14 leaderboard submissions, passed SWE-bench and fail
UTBoost.** Every applied patch reproduced "resolved" in our sandbox
(`fails_original` = 0), so the environment is faithful. xarray-7393 yielded 0
wrong patches under FAIL_TO_PASS alone, a lower bound, and 10 of its patches
failed `git apply` (open).

All 13 share one mistake. Instead of the gold fix (a guard in `draw()`:
don't draw when invisible), they override `set_visible()` to push visibility
into parts of the axes. The original test hides an *empty* 3D axes, so that
passes. UTBoost's test draws scatter points first, and they still render.

Chesterton on three of them, against the same task's original tests:

| patch | UTBoost | killed / survived | what the survivors say |
|---|---|---|---|
| gold | correct | 5 / 1 | the one survivor can never be caught (`not x` to `x is False`) |
| deepswerl r2eagent | **wrong** | 4 / 10 | `super().set_visible(visible)` to `(True)` survives |
| RepoGraph + GPT-4o | **wrong** | 9 / 9 | the same, plus `spine.set_visible(b)` to `pass` survives |
| Agentless 1.5 + Claude 3.5 Sonnet | **wrong** | 6 / 13 | the same, plus **tier 0: line 1160 `artist.set_visible(b)`, executed by no test** |

**What this establishes.** On all three wrong patches, Chesterton reports
that the axes' own visibility flag has no observable effect: the patch can
ignore its argument and no test fails. That is precisely the defect. On
Agentless, tier 0 names the exact line that hides drawn content and says no
test runs it; UTBoost's added test is the one that would. The gold patch
shows none of this. An earlier prediction in this project, that mutation
could not surface a *missing*-behaviour bug, was wrong: it surfaces it as an
argument or line whose effect nothing observes.

**Honest limits.** n = 3 wrong patches, one task. Some survivors are noise:
the `stale` redraw flag (real but low-risk) and uncatchable mutants
(`stale = 1`). The score gap (83% gold against 29-50% wrong) is partly
volume, because agent patches add more code and so more mutants. The claim to
make is the *content* of the survivors, not the score. Changed comment and
blank lines produced model mutants of `# Call the base class`, now fixed by
building hunks only from executable lines (Agentless: 10 hunks to 5).

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

### Pre-registered protocol — REGISTERED 2026-09-20, before any run

Written and committed before the study, so the metric cannot be fitted to the
data. The analysis is code, not prose: `chesterton/benchmark/analysis.py`,
with its tests. Changing any of this after a run begins makes a NEW study,
and the change must be recorded here as one.

**Question.** Among agent patches that all passed SWE-bench's tests, does
Chesterton flag the ones UTBoost proves wrong more often than matched ones
UTBoost's tests accept?

**Population.** The 22 non-Django UTBoost instances (Django's suite is not
pytest). For each, every patch SWE-bench's public submissions resolved,
deduplicated by edit (`scripts/collect_agent_patches.py`), then screened in
one sandbox op each (`scripts/screen_agent_patches.py`):
- **wrong**: passes SWE-bench's original FAIL_TO_PASS, fails UTBoost's;
- **control**: passes both.
A patch whose original tests do not pass in our sandbox is excluded, not
counted either way.

**Pairing.** Each wrong patch is matched to a control from the SAME task,
nearest by changed source lines, without replacement, ties by name
(`match_controls`). Unmatched wrong patches are reported and excluded.

**Chesterton configuration.** Identical for both arms: default mutant budget,
Lightning proposals on, ddmin on, scope = the task's own test files, one run
per patch.

**Outcomes.**
- FLAGGED: at least one surviving mutant or tier-0 finding. Provable no-ops
  never get this far; the gate rejects them (two sound rules only — an added
  `pass`, and inert unreachable code — everything else stays a survivor).
- RATE: (survivors + tier-0) per changed executable line, since agent patches
  add code and raw counts partly measure volume.

**Hypotheses, one-sided, alpha 0.05.**
- **H1 (primary):** wrong patches are flagged more often than their controls.
  Exact McNemar on discordant pairs.
- **H2 (secondary):** within a pair, the wrong patch's rate is higher. Exact
  sign test, ties dropped.

**Reported whatever the result**, including a null or a reversal, with the
per-task breakdown, the unmatched and excluded counts, and every survivor
that is noise rather than a real gap.

**Known limits, stated in advance.** Controls are "correct" only against
UTBoost's FAIL_TO_PASS, so some are probably wrong too, which biases towards
the null. Model proposals vary between runs and each patch is run once.
Tasks contribute unequally. `-k` selection for sympy-style tasks can pull in
extra tests.

### Study v1 result, as registered (run 2026-09-20)

32 analysed pairs, from 7 tasks. Flagged: wrong 100%, control 88%. **H1: 4
wrong-only against 0 control-only discordant pairs, exact McNemar p =
0.0625, not significant at alpha 0.05.** H2: 19 wins, 12 losses, 1 tie,
exact sign test p = 0.14. This is the v1 result and it stands as reported.
Outputs: `benchmark/`.

### Study v2 — a NEW study, REGISTERED 2026-09-22, before any v2 run

**Why a second study.** A review of v1's outputs on 2026-09-22 found
defects in the pipeline, not in the protocol. v2 was designed AFTER seeing
v1's data, and that is disclosed here: v1 re-scored with defect 1's files
removed gives H1 p = 0.033. Every change below is a defect fix justified by
its mechanism, not by its effect on the result. Nothing else changes.

**Defects found in v1, and the fix for each.**

1. **Agent scratch scripts were analysed as source.** 23 of 78 patches
   created files such as `reproduce_issue.py` and `debug_where2.py` that no
   test imports. Tier 0 reported every line of them, which alone flagged 8
   patches (6 controls, 2 wrong) that were clean on the real change. Their
   hunks also used up the 32-mutant budget: in 8 runs no mutant touched the
   actual fix. **Fix:** a file the patch CREATED that NO baseline run
   executed, not even at import, is left out of tier 0, mutation and ddmin
   (`SeedRecord.unexercised_new_files`). A new module the tests import is
   executed, so it stays. Excluded files are listed in each run report.
2. **The rate's denominator counted every line of those files**, because a
   file with no coverage record fell back to "all changed lines" (one
   control: 650 against a real 17). **Fix:** the same files are left out of
   the denominator.
3. **12 of the 22 tasks screened to nothing usable.** 8 read
   `apply_failed:augmented`: UTBoost's test patches end without a final
   newline and `git apply` rejects them as corrupt. 5 sympy tasks read
   `fails_original` for every patch: "No module named pytest", since
   SWE-bench runs sympy with `bin/test`. **Fix:** every patch is given a
   final newline, UTBoost's patch gets the same fuzzy `patch` fallback as
   the agent patch (checked dry first), and pytest is installed when the
   image lacks it, in screening and in the seed build.
4. **Seed-build failure reasons were only printed.** All 21
   matplotlib-14623 patches touching `axes/_base.py` failed to seed, all 16
   wrong ones among them, and the reason was lost. **Fix:** each reason is
   saved as `seeds/<task>/<patch>.error.txt`. This fix is diagnostic only;
   it changes no outcome.

**Amendment 1 — 2026-09-22, during v2's seeding, before any v2 run.**
Fix 4 did its job on the first builds. Every matplotlib-14623 patch that
touches `axes/_base.py` passed its baseline run (401 passed, 180 failed, the
same as the task's other seeds), and then `coverage json --show-contexts`
was OOM-killed ("Killed") exporting that one file: nearly all ~580 tests run
nearly every line of it, and the reporter builds the whole line-by-test
matrix at once. The exclusion is systematic, not random, because all 16 of
the task's wrong patches touch that file. **Fix:** coverage is exported in
the sandbox as one record per (file, test) and assembled outside it
(`covmap/export_coverage.py`, `read_streamed_coverage`). A test runs real
pytest and coverage, in line and in branch mode, and asserts the streamed
path gives exactly the coverage map and executable lines the JSON report
gave, so seeds reused from v1 and seeds built now are comparable. It is an
infrastructure fix under **Retries** below and changes no outcome
definition. The first v2 invocation had already started with the old
exporter, so the affected seeds fail there and are rebuilt when the driver
is re-invoked; their runs then follow. Completed runs are not rerun.

**Amendment 2 — 2026-09-22, during v2's seeding, before any v2 run.** The
first invocation stopped partway through seeding: the driver fetched the
SWE-bench dataset once per seed, drew HTTP 429, and that error was raised
outside the per-seed guard. The driver now reads every task's row in one
scan before seeding, and anything that fails inside one seed's build is
recorded for that seed. A driver fix only; no outcome definition changes.
Three wrong patches cannot be parsed, and are excluded with their reasons,
as **Retries** requires: seaborn-3010 `0070ff86f94b` (its first line fuses
the `diff --git` and `---` headers) and sympy-22714 `62e5a55b2038` and
`b6e976a792bc` (truncated: a hunk promises more lines than its body
carries). SWE-bench applied them with fuzzy `patch`, but a truncated hunk
cannot place its changed lines in post-patch coordinates with certainty,
and mutating the wrong lines would fail silently. Each exclusion drops its
whole pair, so the paired tests stay balanced: 151 of 154 pairs remain.

### Study v2 result, as registered (run 2026-09-22 to 23)

151 analysed pairs, from 16 tasks; 3 pairs excluded (above). Flagged: wrong
80%, control 77%. **H1: 26 wrong-only against 21 control-only discordant
pairs, exact McNemar p = 0.28. H2: 65 wins, 68 losses, 18 ties, exact sign
test p = 0.64. Neither hypothesis is supported.** Outputs: `benchmark-v2/`;
the result reproduces exactly from the run files. Run health: 5 of 302 runs
executed no mutant, 12 mutant verdicts were errors, 5 model proposals
failed, and 55 runs left out scratch files under fix 1.

| task | pairs | wrong flagged | control flagged | wrong-only | control-only |
|---|---|---|---|---|---|
| matplotlib-14623 | 16 | 15 | 16 | 0 | 1 |
| matplotlib-23314 | 13 | 13 | 8 | 5 | 0 |
| seaborn-3010 | 4 | 2 | 3 | 0 | 1 |
| requests-863 | 2 | 2 | 1 | 1 | 0 |
| xarray-3305 | 3 | 3 | 3 | 0 | 0 |
| xarray-4687 | 12 | 12 | 12 | 0 | 0 |
| pylint-5859 | 4 | 4 | 4 | 0 | 0 |
| pylint-7080 | 1 | 1 | 1 | 0 | 0 |
| scikit-learn-14087 | 5 | 5 | 5 | 0 | 0 |
| scikit-learn-14894 | 1 | 1 | 1 | 0 | 0 |
| sympy-16450 | 6 | 3 | 1 | 3 | 1 |
| sympy-17655 | 32 | 21 | 31 | 1 | 11 |
| sympy-18621 | 3 | 3 | 3 | 0 | 0 |
| sympy-20154 | 1 | 0 | 1 | 0 | 1 |
| sympy-21847 | 16 | 16 | 13 | 3 | 0 |
| sympy-22714 | 32 | 20 | 13 | 13 | 6 |

sympy-23117's screen marked all 38 of its patches wrong and none correct,
so UTBoost's augmented test there most likely fails on any fix. With no
control it formed no pair and does not enter the result.

**Exploratory, not confirmatory.** No patch in either arm was flagged by
tier 0 alone, so every flag came from a surviving mutant, and the flag is
in effect "the suite leaves some mutant of the patch alive". That holds for
about four in five agent patches whether UTBoost accepts them or not, which
is the §2 critique measured on our own data: survival alone does not
separate wrong patches from accepted ones. Effects vary by task, from
matplotlib-23314 (13 of 13 rate wins) to sympy-17655 (28 of 32 losses).
Any claim built on a per-task pattern would need its own pre-registration
and fresh data.

**Unchanged from v1:** the question, the population (the 22 non-Django
UTBoost instances), the wrong and control definitions, the pairing rule,
the Chesterton configuration, the FLAGGED and RATE outcomes, H1 and H2,
their tests, one-sidedness and alpha 0.05, and reporting whatever the
result.

**Procedure.** All 22 tasks are re-screened with the fixed screener into a
fresh copy of the patch directory; no v1 verdict is reused, because fix 3
can also let a previously unappliable agent patch apply. Pairing is
recomputed and written once. A seed is keyed by (task, patch), and a v1
seed is reused for the same patch, since no fix changes anything a seed
records (the pytest install is a no-op where pytest exists). **Every run is
new.** Outputs: `benchmark-v2/`.

**Retries.** A seed build or run that fails for an infrastructure reason
may be retried by re-invoking the resumable driver. A run that completed is
never rerun, whatever it shows. The report lists every excluded patch and
the reason for each.

**Known limits, in addition to v1's.** The fixes were chosen knowing the
direction of their effect on v1's data, so v2's p-values should be read as
a replication with repaired tooling, not as an untouched confirmatory test.
Newly screened tasks may change the mix of tasks, and sympy's `-k`
selection applies to more of the sample.

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
