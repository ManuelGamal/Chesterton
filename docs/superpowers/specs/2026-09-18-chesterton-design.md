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
  inputs, surviving mutants.
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
6. **Triage handling** — recorded Nemotron responses as fixtures; test parsing,
   ranking, and abstention deterministically. We test our handling, not the
   model.
7. **Event-log reducer** — replay a recorded log, assert final UI state. Makes
   warm mode a test artifact rather than a special case.

## 14. Failure modes

| Failure | Response |
|---|---|
| Sandbox op fails or times out | mark `error`, exclude from statistics, show honestly; never counted as killed |
| CrossHair finds nothing / times out | expected for 70–90% of functions; fall through to tier 2 silently. Never render "equivalent" |
| Fan-out slower than expected | semaphore plus queue; warm run already on screen |
| Nebius unavailable during judging | warm runs serve everything; live button disabled with an honest message |
| Credits exhausted | hard per-run budget cap in dollars and ops; refuse to start rather than overspend |
| LLM returns malformed JSON | retry once, then fall back to deterministic mutants only |
| Nemotron Ultra absent | already the assumed path (Nano → Super → Super) |
| Checkpoint garbage-collected | tag everything; re-verify late November |
| Two judges collide on the op cap | queue with position display |
| Flaky test in the base suite | detected at seed time by running the suite 3×; flaky tests excluded from selection |

## 15. Risks

**Week-one go/no-go spike.** The architecture assumes forking a warm checkpoint
24 ways completes fast enough to feel live. This is unmeasured. Build a
checkpoint from a real prebuilt image, fork it 24 ways with `asyncio.gather`,
and time it. If fan-out takes minutes rather than seconds, the design collapses
toward the precompute-only fallback and is redesigned around a smaller finding
set.

**Load-bearing unverified facts, to confirm in week one:**

- The ~7,500 prebuilt SWE-rebench images are pullable. This claim comes from a
  HuggingFace discussion thread, not formal docs, and it mitigates the project's
  largest risk. Verify two or three specific pulls.
- Sandboxes have network egress to `api.tokenfactory.nebius.com` (undocumented;
  an open community issue asks exactly this).
- Nebius passes `chat_template_kwargs` through to Nemotron, so reasoning-budget
  control works.
- Nemotron Super responds on the account's key.
- **Content-hash checkpoint deduplication is NOT documented.** Earlier
  reporting claimed identical filesystem state yields the identical UUID.
  Verify empirically before relying on it, and never claim it on camera
  unobserved. Even if true, it applies to pre-execution state only and is not
  evidence of semantic equivalence.

**CrossHair hit rate.** If under ~10% of changed functions in the curated seeds
produce a distinguishing input, tier 1 is demo-invisible. Mitigation: select
seed PRs partly *for* pure, annotated functions, and measure hit rate on
candidate seeds in week 2 before committing them.

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

Direct dependencies and their licences: `crosshair-tool` (MIT), `libcst` (MIT),
`contree-sdk` (Apache-2.0), `coverage`/`pytest`/`pytest-cov` (MIT/Apache-2.0),
`@xyflow/react` (MIT), `motion` (MIT), `shiki` (MIT), shadcn/ui (MIT).

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
| 3 | LibCST operators, Nano mutant generation, validation gate, CrossHair tier. |
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
- **Hypothesis `ghostwriter.equivalent()`** as a tier-1 fallback for functions
  CrossHair cannot solve. ~1 day, MPL-2.0. First candidate if time appears.
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
