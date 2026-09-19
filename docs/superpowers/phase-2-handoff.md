# Phase 2 handoff

**Completed:** 2026-09-19 · **Branch:** `worktree-chesterton-phase-2` · **Suite:** 184 passed, no network

Phase 2 built mutation generation. It has seven LibCST operators with two-pass
candidate identity, a validation gate, a Nemotron client, model-proposed
semantic mutants spliced back into the full module, and an orchestrator that
gates, ranks and budgets mutants. It also ran a measurement that decided
whether the CrossHair tier is worth building. See
`docs/superpowers/plans/2026-09-18-chesterton-phase-2-mutation.md` for the task
breakdown and the spec for the design.

---

## Blocked on you

**Nothing.** The one live question this phase raised, whether a non-zero exit
puts a sandbox image in `FAILED`, was settled against the real service on
2026-09-19 and is recorded in spec §15.

## What the review process caught

All nine tasks passed their per-task reviews. The whole-branch review then
found **4 critical and 9 important defects**, every one of them where one
task's code hands off to another's. Four of them could have made the tool
report evidence that was false:

- Mutated source was passed to the sandbox SDK as a *filename*, so the one
  artifact Phase 2 produces never reached its one destination.
- `mutated_src` meant "whole module" for the operators and "just the hunk" for
  the model, so correct model output was rejected and incorrect output
  overwrote whole files.
- The gate admitted no-op mutants whenever the original did not parse. A no-op
  survives every test, so it would be reported as a behaviour change the tests
  let through.
- Tier-0 still reported "no test defends this" on README lines, despite the
  filter written to prevent exactly that.

The suite was green through all of it. A scoped re-review then found one
pre-existing crash (a `try` with two handlers aborted the whole run) and two
regressions the fix wave introduced. All are fixed, and every test added in the
two fix rounds was shown to fail with its fix disabled.

## Measured this phase

| What | Result |
|---|---|
| CrossHair eligibility, `IAMconsortium/nomenclature` @ `a0408e5` | 77/256 = **30%**, an **upper bound**; the purity screen is a name heuristic that overstates |
| `crosshair diffbehavior`, `>` vs `>=` | distinguishing input `(amount=0, balance=0)` in **0.38 s** on Python 3.13 |
| Non-zero exit in a sandbox | ordinary `SUCCEEDED` result with `exit_code=1`; only operation failures raise |
| `crosshair-tool` 0.0.110 | MIT, installs on 3.13; the CLI has no `--version`, so read `crosshair.__version__` |

**Phase 2b is justified.** 170 of 256 functions are ruled out by missing
annotations alone, which is exact. Some unknown share of the remaining 86 is
impure.

## Required in Phase 3 (not optional)

- **Check `RunResult.error` before `exit_code`.** `exit_code` is `None` exactly
  when `error` is set. An errored run is excluded from statistics and never
  counted as killed (ruling P20).
- **Pass `proposal.mutants` to `generate()`**, and carry `proposal.failure`
  counts (`truncated` / `malformed`) into the run summary. Otherwise a total
  model outage reads as "the model had nothing to say" (P20).
- **Exercise `ConTreeSandboxRunner.run` live.** Its body is still executed by no
  test. The fake enforces "disposable run has no checkpoint" and "persisted run
  must be tagged", but the real adapter's behaviour is unproven (P15).
- **Wire the semaphore.** `asyncio.Semaphore(24)` appears nowhere in `src/` yet.
  `MUTANT_BUDGET` is 32, per spec §6, and the semaphore is what keeps that to
  one short second round.

## Required in Phase 4 (not optional)

- **Carry `Candidate.line` / `.column` onto the finding.** They exist for
  attribution (ruling P3) but are dropped at the `Candidate → Mutant` boundary,
  so a mutant currently records only its hunk bounds. Phase 4 renders findings,
  and that is where the exact line has to come from (P16).

## Deferred minors

- `_extract_json` spans the first `{` to the last `}`, so prose containing a
  brace degrades to "malformed". It is now counted rather than silent.
- `reply.choices[0]` is indexed unguarded in the Nemotron client.
- A hunk that yields no candidates is dropped without a counter.
- Ranking ties fall back to insertion order.
- The probe's impurity screen over-matches `self.<x>.get` on dicts. This errs
  conservative.

## Rulings

P1–P24 and their costs-if-wrong are in the execution ledger. The ledger is not
committed, so the ones Phase 3 and 4 depend on are copied above.
