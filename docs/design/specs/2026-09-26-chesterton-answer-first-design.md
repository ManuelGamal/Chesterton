# Chesterton demo: answer first

**Date:** 2026-09-26.
**Revises:** `docs/design/specs/2026-09-24-chesterton-demo-ui-design.md`, the story view (§2, §6).
**Status:** approved in conversation, section by section.

## 1. Why

A first-time viewer couldn't tell what Chesterton does from the demo. The story view shows the machinery: the patch, lanes of capsules, "killed" and "survived", ddmin, triage counts. It never states the question ("is this fix really tested?") or the answer ("this behaviour isn't, and here is the test that fixes it"). The mutants themselves can't be read, either: the capsules don't respond to clicks, and only the 3 headline findings can be opened at all.

**Goal:** a hackathon judge who has never heard of mutation testing understands the idea within 30 seconds, and can point at a mutant and read what it changed.

## 2. Story order and copy

The tabs, in this order:

| # | id | Tab | Verdict (the page's first sentence) |
|---|---|---|---|
| 1 | `hero` | Wrong patch, caught | The agent's fix passed every test, but no test checks that `set_visible(True)` actually shows a 3D plot. Chesterton found the gap and wrote the missing test. |
| 2 | `gold` | The correct fix | The fix matplotlib's developers merged is well tested: the tests caught 5 of the 6 changes Chesterton made to its lines, and Nemotron judged the one they missed worth a look, not a headline. |
| 3 | `limit` | Checking our own tests | In our 13-patch study, half of Chesterton's first verified tests (5 of 10) locked in the agent's bug. One rule, test through the public API, cut that to 1 in 9. This is the one that still slips through. We catch it by running the test on the correct fix, which SWE-bench provides and a new PR does not. |

Where the copy lives:

- Verdicts are written by us, not generated. They live in the exporter's story config as a new `verdict` field and reach the page as `meta.verdict`.
- Each verdict's numbers match its bundle. A test in `tests/test_demo_export.py` checks the counts it can: caught, missed and total mutants.
- The story titles change to match. `limit`'s title becomes "Checking our own tests: a verified test can still lock in the agent's bug."
- The 5/10 and 1/9 figures come from `review-study/summary.json` and `review-study-2/summary.json`, as spec §17 already reports.

## 3. The answer card (top of every story)

At 1600×900, the whole card fits in about 420 px:

1. **Verdict.** The §2 sentence, at 20px.
2. **The change the tests miss.** The story's top finding: the first headline, or the first worth-a-look finding when there are no headlines.
   - It is shown as a diff of the mutated lines only: `- <original>` / `+ <mutated>`, with line numbers, at 15px mono.
   - A badge reads "▲ tests still pass".
   - Below it, Nemotron's explanation, labelled "Nemotron:".
   - With no headline (story 2), the badge reads "▲ missed, judged worth a look".
3. **The missing test.** Present only when `regression.finding_id` is the top finding's id.
   - Three checks, each with a glyph and a word:
     - "● passes on the agent's fix";
     - "● fails on the change";
     - "● holds on the correct fix".
   - When `gold === "fails_on_gold"`, the third check is replaced by the exact `GOLD_WARNING` row.
   - Two buttons: [Show test], which expands the source at 15px mono, and [Ask Nemotron why ✦ live], the existing `AskWhy`.
   - With no regression (story 2): "No test needed: nothing important slipped past the tests."
   - All existing rules hold: the word "Verified" appears only when `verified` is true, and the source is shown only when verified.

The answer card doesn't move with the replay. It always shows the final result.

## 4. "How Chesterton found this" (below the card)

1. **Summary line**, built from the bundle:
   "N small changes to the lines the patch changed → the tests **caught** C, **missed** M → Nemotron picked the **H** that matter".
   - It says "the patch", not "the agent", because story 2's patch was written by matplotlib's developers.
   - With H = 1 it reads "the 1 that matters". Story 2 ends "… → Nemotron found none that matter".
   - When some changes sit on lines no test runs, it adds "· U on lines no test runs".
   - "caught C" and "missed M" are buttons. Each highlights its capsules and toggles off on a second click.
2. **Replay controls**, with no autoplay:
   - The section opens at the final state (`t = total`).
   - ▶ **Replay** plays from 0.
   - While playing: Pause, Skip to results, the scrubber and the speed control, as now.
   - Reduced motion works as before: Replay jumps to the end instead of animating.
   - The single `role="status"` line stays in this row.
3. **Diff and lanes**, as now, but with plain words and clickable elements:
   - Every capsule is a button.
   - Every diff line that carries a verdict glyph is a button.
   - Each opens the detail panel for its mutant. On a diff line with several mutants, it opens the first one that the tests missed, or the first one otherwise.
4. **Detail panel**, under the lanes, for the selected mutant:
   - **The change:** a diff of the lines that differ between `before` and `after`. These are the bundle's existing mutant windows, trimmed to the changed lines ±1.
     - The `+` line wipes in with a `clip-path` animation of about 0.4 s.
     - Under reduced motion it crossfades instead.
   - **Verdict:**
     - "▲ missed: the N tests that run this line still pass";
     - "● caught: a test failed";
     - "◆ no test runs this line";
     - "✕ error".
   - **Nemotron's judgment**, when a finding links to this mutant: "matters", "worth a look" or "dismissed", its explanation, and its category.
   - **ddmin note:** when the mutant's hunk is undefended, the panel says "Removing this whole hunk still passes the tests."
   - **Navigation:** ←/→ step through the mutants in lane order, and Esc closes the panel.

## 5. Plain words

The glyphs and colours don't change. Only the words do. The technical term goes in `title`.

| Glyph | Old word | New word | `title` |
|---|---|---|---|
| ▲ | survived | missed | "surviving mutant: the tests still pass" |
| ● | killed | caught | "killed mutant: a test failed" |
| ◆ | uncovered | untested line | "no test executes this line" |
| ○ | pending | running | |
| ✕ | error | error | |

- The lookup lives once, in `web/src/verdicts.ts`, and the capsules, gutter, detail panel and status line all read it.
- The status line becomes "N of N changes tested · M missed".
- The About dialog gains one sentence: "A mutant is a small deliberate change to a line the agent wrote. If every test still passes, the tests missed it."

## 6. Exporter changes

These are in `src/chesterton/demo/export.py` and `scripts/export_demo.py`:

- **Story config:**
  - add `verdict`, emitted as `meta.verdict`;
  - update `limit`'s `tab` and `title`;
  - reorder `STORIES` to hero, gold, limit, which also sets the order in `index.json`.
- **Finding to mutant link:** every triaged finding (headline, worth a look and dismissed) gains `mutant_id`.
  - It is found by matching a surviving mutant with the same file, `start_line` and `end_line` whose changed lines (removed and added code, from a line diff of its windows) equal the finding's.
  - Matching is one-to-one: each finding claims its own mutant, because two mutants can make the identical change. The export fails loudly if a finding has no unclaimed match. A test asserts that every finding in the committed bundles and in the golden fixture links to a distinct surviving mutant.
- **Contract:** `web/src/bundle.ts` gains `Meta.verdict` and `Finding.mutant_id`, and `assertBundle` checks both. The golden fixture is regenerated, and the committed bundles are re-exported.

## 7. What goes away

- The PR/mutant tab switcher in the finding panel. Its job moves to the answer card's diff and the detail panel's wipe.
- The standalone "Hunk removal (ddmin), …" line. It becomes the detail panel's note on undefended hunks.
- The "No headline findings: …" empty-state line. Story 2's answer card covers it.
- The worth-a-look and dismissed lists and the triage counts line. Every judged change is reachable from its capsule, and the detail panel shows Nemotron's judgment.
- Autoplay, and the "Pause first in tab order" rule that existed because of autoplay. The replay controls stay keyboard reachable.

## 8. Unchanged

- The live function and its contract, the rate limit, and the About dialog's honesty copy.
- The verdict colours, the tokens-only styling, lucide icons, 15px minimum code, and one `role="status"`.
- Reduced motion: nothing animates on its own, and wipes become crossfades.
- No sideways scroll at 375 px.

## 9. Testing

**Python:**
- `meta.verdict` is present.
- The finding–mutant link is exact, and a mismatch raises.
- The story order is right.
- The verdict counts match the bundle.

**Unit (vitest):**
- The answer card, on each of the three stories: the verdict text, the diff's `-` and `+` lines, the three checks, `GOLD_WARNING` on story 3, "No test needed" on story 2, and "Verified" never shown on an unverified test.
- The summary line counts, and the highlight toggle.
- The detail panel:
  - clicking a capsule shows that mutant's change and verdict;
  - a linked finding shows Nemotron's judgment;
  - ←/→ and Esc work.
- The plain-words map.
- No autoplay: the section starts at the final state, and Replay starts at 0.

**Playwright smoke test:**
- Each tab shows its verdict.
- Replay, then Skip, reaches "N of N".
- Clicking a capsule opens the detail panel.
- Reduced motion: nothing moves until the viewer acts.

**Layout (a scripted check):**
- At 1600×900 on every story, the verdict, the change, the three checks (or the story 2 message) and the Ask button are above the fold.
- At 375 px, there is no sideways scroll.
- Screenshots of all three stories for review.

## 10. Out of scope

- Naming the tests that caught each mutant. The bundle carries only a count, and exporting names is a separate change.
- A guided caption walkthrough. The answer card plus the summary line carry the idea. Revisit only if a first-time viewer still gets lost.
