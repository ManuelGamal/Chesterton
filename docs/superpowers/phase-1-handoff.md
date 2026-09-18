# Phase 1 handoff

**Completed:** 2026-09-18 · **Merged:** `112bfd2` · **Suite:** 54 passed, 0.17s, no network

Phase 1 built the offline-testable foundation: a sandbox abstraction behind a
protocol, GitHub PR ingest with correct merge-base handling, diff parsing,
semantic hunk grouping, coverage inversion, and the join that produces tier-0
findings. See `docs/superpowers/plans/2026-09-18-chesterton-phase-1-foundations.md`
for the task breakdown and `docs/superpowers/specs/2026-09-18-chesterton-design.md`
for the design it implements.

---

## Blocked on you

1. **Run the fan-out spike.** `scripts/spike_fanout.py` is written and parses but
   has never run — it needs `NEBIUS_API_KEY` in the session environment. It
   measures whether forking one checkpoint 24 ways *and running a test suite in
   each* completes fast enough to feel live. **This is the go/no-go gate for the
   whole architecture.** Record all four numbers it prints into spec §15,
   replacing "This is unmeasured."

2. **Verify the prebuilt SWE-rebench images actually pull.** The plan's scoping
   decision — curated seeds only, no arbitrary repos — rests entirely on Nebius
   publishing ~7,500 prebuilt images loadable via `images.oci("docker://…")`.
   That claim comes from a HuggingFace discussion thread, not formal docs. Pull
   two or three specific images before designing Phase 3 around them.

3. **Call `contree_get_guide` before writing more sandbox code.** The
   `contree-sdk` surface used in `sandbox/contree.py` (`images.oci`,
   `images.use`, `image.run(shell=, files=, disposable=, tag=)`, `result.uuid`)
   is entirely unverified against the live service. All five adapter tests pass
   regardless, because they test shape only.

---

## Decisions made during execution

| | Decision | Cost if wrong |
|---|---|---|
| R1 | venv built with `py -3.13`; `requires-python` stays `>=3.12`. The machine's default `python` is 3.10.6, below the floor. | Recreate the venv |
| R2 | `SandboxRunner` is `@runtime_checkable`. **Caveat: that checks method *names* only** — a signature divergence passed its test undetected (see I2 below). | Treat the adapter's protocol test as a smoke check, not conformance |
| R3 | Live spike deferred — no API key was visible to the executing session. | The go/no-go answer is still unknown |
| R4 | SDD helper scripts replicated by hand; the worktree sandbox refused to execute them. | None to the product |
| R5 | `.gitignore`: scoped `coverage.json` to `/coverage.json` (the bare pattern matches at any depth and would have silently ignored `tests/fixtures/coverage.json`), and ignored the tooling scratch dirs. | None — verified |
| R6 | `contree-sdk` not installed; the lazy import means tests pass without it. | The SDK surface stays unverified — see item 3 above |
| R7 | The `pr.diff` fixture's hunk **headers** were wrong, not its bodies. Corrected the headers and restored the two-line guard-clause deletion, which an earlier repair had mutilated into invalid Python. | The fixture would stop representing a guard-clause deletion |
| R8 | `tests_for_hunk` renamed to `covering_tests`. pytest's default `python_functions` glob is `test*`, so a public function starting with `test` gets collected as a test case the moment a test module imports it. | None — mechanical |

**Naming rule this established:** no public symbol a test module imports may
begin with `test`.

---

## Deferred to Phase 2

Raised by the final whole-branch review and deliberately not fixed in Phase 1.
Ordered by how much damage each can do.

**I4 — the coverage map's tree provenance is unpinned.** *(Partially closed —
see "Merged from the parallel branch" below.)* `defended.py` joins **post-patch**
line numbers into a map whose origin nothing states. Spec §4 builds the baseline
checkpoint from the base SHA; if the coverage map is captured on the base tree,
every added line indexes into unrelated content — added lines reported as
"defended" by tests that never ran them, or the whole PR reported undefended.
`semantic_hunks` now documents its coordinate contract and rejects lines outside
its source, but **`CoverageMap` still carries no such contract**, and a mismatch
that happens to land in range still passes silently. **Settle the coverage-map
side before writing the seed pipeline** — it remains the most likely source of a
confidently wrong answer.

**I3 — no Python-file filter anywhere in the pipeline.** A README, YAML, or
lockfile hunk flows straight through (`semantic_hunks` falls back to per-line
hunks on a SyntaxError) and produces confident undefended-line findings on
prose. Same for files under `tests/`, where a test file "covers itself". Add a
`.py` plus non-test predicate before any finding reaches a UI.

**I2 — the protocol lacks `tag`.** `ConTreeSandboxRunner.run` takes a `tag`
parameter; `SandboxRunner` and `FakeSandboxRunner` do not. `spike_fanout.py`
already calls it. So "every persisted checkpoint must be tagged" is the one
constraint the offline fake cannot exercise. Widen the protocol before N call
sites exist — and it likely needs a timeout and an explicit error verdict too.

**I5 — the capture command does not enforce its own constraints.**
`COVERAGE_CAPTURE_COMMANDS` does not prevent a target repo's `addopts = -n auto`
from running the baseline under xdist, where dynamic contexts are unreliable and
degrade silently to "uncovered". It also does not set `relative_files`, so a
capture whose cwd is not the repo root emits keys like `/testbed/widgets/x.py`
that `normalise_path` cannot fix. Consider `-o addopts=` and a coverage config.

**I6 — the spec's mandated golden test does not exist.** Spec §6 and §13.1 both
require a dedicated merge-base line-mapping test against a recorded fixture from
a real public PR. `tests/fixtures/pr.diff` is hand-written, and
`test_fetch_uses_merge_base_not_base_sha` only asserts the two SHAs differ —
nothing verifies a line number derived from a real merge-base diff lands where
the head tree actually has that content.

**Minor:** `github/pr.py` retries a `403` with `x-ratelimit-remaining: 0` three
times, burning requests against a quota that resets hourly. `parse_pr_url` uses
`re.search`, so any URL merely *containing* a PR path parses.
`changed_lines` lets `unidiff.UnidiffParseError` escape unwrapped. `RunResult`
carries neither duration nor sandbox uuid, both of which the spec's
`mutant_result` table needs. `Hunk` has no `semantic_unit` field although the
spec's `hunk` table does.

---

## What the review process actually caught

Worth recording, because it is the argument for the project itself. Three
defects reached implementation and were caught only by review, each producing
**green tests while being wrong**:

- A diff fixture with inconsistent hunk arithmetic, "repaired" by editing the
  bodies to match bad headers — which deleted an `if not user_id:` while keeping
  its `raise`, yielding invalid Python.
- Widest-first span selection, introduced to fix guard clauses, which made any
  line inside a large `try` swallow the entire block.
- `uncovered_findings` emitting findings for lines the PR never touched: one
  changed line produced three fabricated claims on statement continuation lines
  that coverage.py cannot even record.

The last one is the project's own thesis turned on itself — a tool whose pitch
is *executed proof, not opinion* was fabricating evidence.

---

## Merged from the parallel branch

A second branch, `phase-1-foundations`, executed this plan independently —
but from the **pre-critique** version, before the seven-agent task review
revised it. It was compared file by file against this work.

**Superseded by this branch** (the critique fixed these before implementation):
the hand-rolled diff parser with its `+++ /dev/null` and no-newline defects;
widest-first span selection, which lets any line inside a large `try` swallow
the whole block; no `paths.py` and so no path normalisation anywhere; a GitHub
client with `raise_for_status` but no retries, no rate-limit handling and raw
`meta["base"]["sha"]` indexing; no `aclose` on the protocol; no `tag` on the
adapter; and 33 tests that are a strict subset of this branch's 57.

**Adopted from it** (commit `10518cb`) — two things it genuinely did better:

1. **The coordinate contract**, documented in `semantic.py`'s module docstring.
   This branch had left it implicit, and the final review named it the most
   likely source of a confidently wrong answer.
2. **A bounds guard** on `semantic_hunks`. That branch rejected `line < 1`;
   this version also rejects lines past the end of the source, which is the
   detectable half of a wrong-tree mismatch and the likelier one in practice.

The lesson worth keeping: the parallel run's only wins were a *docstring* and a
*guard clause* — the two things a plan tends not to specify and a reviewer tends
not to demand. Everything the critique process caught, it caught better.
