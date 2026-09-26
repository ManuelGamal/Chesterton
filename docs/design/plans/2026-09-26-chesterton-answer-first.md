# Answer-First Story View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the demo's story view so a first-time viewer reads the conclusion first (a verdict sentence, the change the tests miss, the missing test) and can click any mutant to read what it changed.

**Architecture:**
- **Exporter.** The Python exporter adds a hand-written `meta.verdict` to each story and links every triaged finding to its surviving mutant (`mutant_id`).
- **Pure story helpers.** A new module, `web/src/story.ts`, holds pure helpers: the top finding, the summary counts, the mutant order, and a line diff of the exporter's numbered windows. The components render only what those helpers compute.
- **Page structure.** Each story page becomes two parts. An `AnswerCard` sits on top. Below it, a "How Chesterton found this" section holds a summary line, the replay controls (no autoplay), the diff, clickable mutant capsules and a `MutantDetail` panel.

**Tech Stack:**
- Python 3.12 with pytest.
- React 19, TypeScript 7, Vite, Tailwind v4, motion and lucide-react.
- Vitest with jsdom, and Playwright.

**Spec:** `docs/design/specs/2026-09-26-chesterton-answer-first-design.md`. It revises the story view of `docs/design/specs/2026-09-24-chesterton-demo-ui-design.md`.

## Global Constraints

**Workspace and commits**
- Work in the main checkout `C:\Users\manue\projects\chesterton`, on branch `answer-first`. Never commit to `master`. Never push.
- Every commit message ends with a blank line and then exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No other co-author line.
- Create and edit files with the Write/Edit tools, never bash heredocs: in this shell, heredocs turn `\\` into `\`.
- Everything written to disk is UTF-8 with LF line endings.
- `git add` only the files a task names. Never `-A` or `.`.
- The data directories at the repo root are never committed: `benchmark*/`, `agent_patches*/`, `review-study*/`, `review-gold/`, `seeds/`, `runs/`, `logs/`.

**Running things**
- Python tests: `.venv/Scripts/python.exe -m pytest -q`, run from the repo root.
- Web commands run from `web/`.
- The shell's cwd resets to a dead worktree, so start every shell command with `cd "C:/Users/manue/projects/chesterton"` (or `.../web`).
- Tests that need jsdom read the golden bundle with `readFileSync(resolve(process.cwd(), "../tests/fixtures/demo_example_bundle.json"), "utf8")`. Pure tests start with `// @vitest-environment node`.
- Vitest globals are off. `web/src/test-setup.ts` already registers `afterEach(cleanup)`.

**Verdict glyphs and colours:** they don't change.
- ▲ `var(--verdict-survived)`
- ● `var(--verdict-killed)`
- ◆ `var(--verdict-uncovered)`
- ○ `var(--verdict-pending)`
- ✕ `var(--verdict-error)`

**Verdict words (spec §5):**
- survived → "missed", title "surviving mutant: the tests still pass"
- killed → "caught", title "killed mutant: a test failed"
- uncovered → "untested line", title "no test executes this line"
- pending → "running"
- error → "error"

Always show the glyph and the word together.

**Styling and motion**
- Colours are CSS variables from `web/src/styles.css`. Components never use colour literals.
- Icons come from lucide-react only. No emoji.
- Code is shown in JetBrains Mono at 15px minimum.
- Motion uses only transform, opacity and clip-path. Under `prefers-reduced-motion`, nothing moves by itself and wipes become crossfades.

**Accessibility and layout**
- Exactly one `role="status"`, with `aria-atomic="true"`, for replay progress.
- No sideways scroll at 375 px.

**Honesty rules**
- A regression test is labelled "Verified" only when `regression.verified` is true. Its source is shown only when it is verified.
- A test with `gold === "fails_on_gold"` always shows exactly: "Verified, but it fails on the correct fix: it encodes the agent's bug."

**Autoplay (spec §4):** a story opens at its final state (`t = total`, not playing). ▶ Replay plays from 0. Under reduced motion, Replay jumps to the end.

---

## File map

| File | Change | Responsibility |
|---|---|---|
| `src/chesterton/demo/export.py` | modify | `meta.verdict`; `link_findings` (finding to mutant, one to one) |
| `scripts/export_demo.py` | modify | the story order hero, gold, limit; verdicts; limit's new tab and title |
| `tests/test_demo_export.py` | modify | tests for the above; `STORY` gains `verdict` |
| `tests/fixtures/demo_example_bundle.json` | regenerate | golden fixture with `meta.verdict` and `mutant_id` |
| `web/public/stories/*.json` | re-export | committed bundles |
| `web/src/bundle.ts`, `web/src/bundle.test.ts` | modify | `Meta.verdict`, `Finding.mutant_id`, `assertBundle` |
| `web/src/verdicts.ts` | modify | plain words plus `term` |
| `web/src/story.ts`, `web/src/story.test.ts` | create | pure helpers: `topFinding`, `summarise`, `judgmentFor`, `mutantsInLaneOrder`, `mutantAtLine`, `isUndefended`, `windowDiff` |
| `web/src/components/CodeDiff.tsx` | create | `-`/`+` rows; the `+` rows wipe in |
| `web/src/components/AnswerCard.tsx`, `AnswerCard.test.tsx` | create | verdict, the change the tests miss, the missing test, Ask why; owns `GOLD_WARNING` |
| `web/src/components/SummaryLine.tsx` | create | "N small changes … caught C, missed M … H that matter", with highlight toggles |
| `web/src/components/MutantDetail.tsx` | create | the selected mutant's change, verdict, Nemotron's judgment, ddmin note |
| `web/src/components/Clickable.test.tsx` | create | tests for SummaryLine, Lanes, MutantDetail |
| `web/src/components/Lanes.tsx`, `Lanes.test.tsx` | rewrite | capsules are buttons (select, highlight); the ddmin line is removed |
| `web/src/components/DiffPane.tsx`, `DiffPane.test.tsx` | rewrite | lines with a verdict are buttons that select a mutant; plain-word labels |
| `web/src/useReplay.ts` | modify | no autoplay; reduced-motion Replay jumps to the end |
| `web/src/components/ReplayControls.tsx` | modify | "N of N changes tested · M missed"; Replay label; key hint |
| `web/src/App.tsx`, `App.test.tsx` | rewrite | the new StoryView layout and keyboard (Space, ←/→ over changes, Esc) |
| `web/src/components/AboutDialog.tsx` | modify | adds the sentence explaining a mutant |
| `web/src/components/FindingPanel.tsx`, `FindingPanel.test.tsx` | delete | replaced by AnswerCard and MutantDetail |
| `web/e2e/smoke.spec.ts` | rewrite | new smoke checks |
| `README.md` | modify | Demo section: new order and story 3 |

---

### Task 1: The exporter writes verdicts and links findings to mutants

**Files:**
- Modify: `src/chesterton/demo/export.py`
- Modify: `scripts/export_demo.py:26-54` (`STORIES`)
- Modify: `tests/test_demo_export.py`
- Modify: `web/src/bundle.ts`
- Modify: `web/src/bundle.test.ts`
- Regenerate: `tests/fixtures/demo_example_bundle.json`
- Re-export: `web/public/stories/hero.json`, `gold.json`, `limit.json`, `index.json`

**Interfaces:**
- Produces:
  - `link_findings(findings: list[dict], mutants: list[dict]) -> None`, which sets `f["mutant_id"]` on each finding in place.
  - Bundle `meta.verdict: str`.
  - Every finding gains `mutant_id: str`.
  - TS: `Bundle["meta"]["verdict"]: string` and `Finding.mutant_id: string`.

- [ ] **Step 1: Write the failing Python tests**

In `tests/test_demo_export.py`, change `STORY` (lines 18-19) to:

```python
STORY = {"id": "hero", "tab": "Wrong patch, caught", "title": "Demo story", "utboost": "wrong",
         "system": "Test System", "verdict": "The tests never check the `amount` guard."}
```

In `test_a_story_whose_inputs_are_missing_is_skipped_not_faked` (lines 172-177), add `"verdict": "v"` to both story dicts:

```python
    stories = [
        {"id": "present", "tab": "A", "title": "t", "utboost": "wrong", "system": "System A", "verdict": "v",
         "seed": "seed.json", "run": "run.json", "review": "review.json", "gold": None, "submission": "x"},
        {"id": "absent", "tab": "B", "title": "t", "utboost": "correct", "system": "System B", "verdict": "v",
         "seed": "nope.json", "run": "nope.json", "review": "nope.json", "gold": None, "submission": "y"},
    ]
```

Change the import on line 10 to:

```python
from chesterton.demo.export import CONCURRENCY, build_bundle, link_findings, schedule
```

Append these tests at the end of the file:

```python
async def test_the_bundle_carries_the_story_verdict(demo_seed):
    bundle = await a_bundle(demo_seed)

    assert bundle["meta"]["verdict"] == "The tests never check the `amount` guard."


async def test_every_finding_links_to_its_surviving_mutant(demo_seed):
    bundle = await a_bundle(demo_seed)

    [headline] = bundle["triage"]["headline"]
    assert headline["mutant_id"] == "m0"
    assert bundle["mutants"][0]["verdict"] == "survived"


WINDOW_BEFORE = "    1 | def charge(amount):\n    2 |     if not amount:\n    3 |         raise ValueError\n    4 |     return amount"
WINDOW_AFTER = "    1 | def charge(amount):\n    2 |     return amount"


def _mutant(mid, verdict="survived"):
    return {"id": mid, "file": "pay.py", "start_line": 2, "end_line": 3, "verdict": verdict,
            "before": WINDOW_BEFORE, "after": WINDOW_AFTER}


def _finding(fid):
    # A finding's windows are wider than a mutant's: the match compares changed lines only.
    return {"id": fid, "file": "pay.py", "start_line": 2, "end_line": 3,
            "original": "    0 | import os\n" + WINDOW_BEFORE, "mutated": "    0 | import os\n" + WINDOW_AFTER}


def test_two_findings_with_the_same_change_claim_two_mutants():
    findings = [_finding("h0"), _finding("w0")]

    link_findings(findings, [_mutant("m0"), _mutant("m1"), _mutant("m2", verdict="killed")])

    assert [f["mutant_id"] for f in findings] == ["m0", "m1"]


def test_a_finding_with_no_surviving_mutant_fails_loudly():
    with pytest.raises(ValueError, match="h0 matches no surviving mutant"):
        link_findings([_finding("h0")], [_mutant("m0", verdict="killed")])


def test_the_stories_run_hero_then_the_correct_fix_then_our_own_tests():
    assert [s["id"] for s in export_demo.STORIES] == ["hero", "gold", "limit"]
    assert all(s["verdict"] for s in export_demo.STORIES)
    limit = next(s for s in export_demo.STORIES if s["id"] == "limit")
    assert limit["tab"] == "Checking our own tests"


STORIES_DIR = Path(__file__).resolve().parents[1] / "web" / "public" / "stories"


@pytest.mark.parametrize("story", ["hero", "gold", "limit"])
def test_every_committed_finding_links_to_a_distinct_survivor(story):
    bundle = json.loads((STORIES_DIR / f"{story}.json").read_text(encoding="utf-8"))
    by_id = {m["id"]: m for m in bundle["mutants"]}
    findings = [f for bucket in ("headline", "worth_a_look", "dismissed") for f in bundle["triage"][bucket]]

    ids = [f["mutant_id"] for f in findings]
    assert len(ids) == len(set(ids))
    assert all(by_id[i]["verdict"] == "survived" for i in ids)


def test_the_committed_correct_fix_verdict_matches_its_bundle():
    gold = json.loads((STORIES_DIR / "gold.json").read_text(encoding="utf-8"))
    caught = sum(1 for m in gold["mutants"] if m["verdict"] == "killed")

    assert f"caught {caught} of the {len(gold['mutants'])} changes" in gold["meta"]["verdict"]


def test_the_limit_verdict_matches_the_two_review_studies():
    root = Path(__file__).resolve().parents[1]
    first, second = root / "review-study" / "summary.json", root / "review-study-2" / "summary.json"
    if not (first.exists() and second.exists()):
        pytest.skip("the review-study data directories are local only")
    def fails(path):
        rows = [r for r in json.loads(path.read_text(encoding="utf-8")) if r["verified"]]
        return sum(1 for r in rows if r["gold"] == "fails_on_gold"), len(rows)
    (f1, n1), (f2, n2) = fails(first), fails(second)
    verdict = next(s for s in export_demo.STORIES if s["id"] == "limit")["verdict"]

    assert (f1, n1, f2, n2) == (5, 10, 1, 9)
    assert f"({f1} of {n1})" in verdict and f"{f2} in {n2}" in verdict
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_demo_export.py`

Expected: this fails at import with `ImportError: cannot import name 'link_findings'`.

- [ ] **Step 3: Implement `link_findings` and `meta.verdict`**

In `src/chesterton/demo/export.py`, add `import difflib` after `from __future__ import annotations`:

```python
from __future__ import annotations

import difflib
```

Add these functions after `_finding` (after line 68):

```python
def _code(window: str) -> list[str]:
    """The code of an exporter window (" 1157 |     code" per line), numbers dropped."""
    return [line.split(" | ", 1)[1] if " | " in line else line for line in window.split("\n")]


def _change(before: str, after: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(removed lines, added lines) between two windows, by a line diff of their code."""
    a, b = _code(before), _code(after)
    removed: list[str] = []
    added: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag != "equal":
            removed += a[i1:i2]
            added += b[j1:j2]
    return tuple(removed), tuple(added)


def link_findings(findings: list[dict], mutants: list[dict]) -> None:
    """Give each finding the id of the surviving mutant it describes, one to one.

    A finding and its mutant share file and line range, and make the same
    change; their windows differ only in how much context they carry. Two
    mutants can make the identical change, so each finding claims its own.
    """
    claimed: set[str] = set()
    for f in findings:
        change = _change(f["original"], f["mutated"])
        match = next(
            (m for m in mutants
             if m["id"] not in claimed and m["verdict"] == "survived"
             and (m["file"], m["start_line"], m["end_line"]) == (f["file"], f["start_line"], f["end_line"])
             and _change(m["before"], m["after"]) == change),
            None,
        )
        if match is None:
            raise ValueError(f"finding {f['id']} matches no surviving mutant")
        claimed.add(match["id"])
        f["mutant_id"] = match["id"]
```

In `build_bundle`, replace the line `headline = [_finding("h", i, x) for i, x in enumerate(triage["headline"])]` (line 121) with:

```python
    headline = [_finding("h", i, x) for i, x in enumerate(triage["headline"])]
    worth = [_finding("w", i, x) for i, x in enumerate(triage["worth_a_look"])]
    dismissed = [_finding("d", i, x) for i, x in enumerate(triage["dismissed"])]
    link_findings(headline + worth + dismissed, mutants)
```

In the returned dict, add `"verdict": story["verdict"],` to `meta` after `"system": story["system"],`:

```python
            "system": story["system"], "verdict": story["verdict"],
```

Then replace the `"worth_a_look"` and `"dismissed"` entries of `"triage"` with:

```python
            "worth_a_look": worth,
            "dismissed": dismissed,
```

- [ ] **Step 4: Update the stories**

In `scripts/export_demo.py`, replace the whole `STORIES = [...]` list (lines 26-54) with:

```python
STORIES = [
    {"id": "hero", "tab": "Wrong patch, caught", "utboost": "wrong",
     "title": "An agent's fix passed SWE-bench. Here is what its tests let through.",
     "system": "Agentless 1.5 + Claude 3.5 Sonnet",
     "verdict": ("The agent's fix passed every test, but no test checks that `set_visible(True)` "
                 "actually shows a 3D plot. Chesterton found the gap and wrote the missing test."),
     "seed": f"benchmark-v2/seeds/{TASK}/6d83e35469d2.json",
     "run": f"benchmark-v2/runs/{TASK}/6d83e35469d2.json",
     "review": "review-study-2/6d83e35469d2.json",
     "gold": ("review-study-2/summary.json", "6d83e35469d2"),
     "submission": (SCREEN, "6d83e35469d2")},
    {"id": "gold", "tab": "The correct fix", "utboost": "correct",
     "title": "The reference fix: well defended, and a quiet review.",
     # SWE-bench's reference patch is the fix matplotlib's developers merged.
     "system": "matplotlib's developers (the merged fix)",
     "verdict": ("The fix matplotlib's developers merged is well tested: the tests caught 5 of the 6 "
                 "changes Chesterton made to its lines, and Nemotron judged the one they missed worth "
                 "a look, not a headline."),
     "seed": "seeds/matplotlib-23314.json",
     "run": "runs/matplotlib-23314.json",
     "review": "review-gold/matplotlib-23314.json",
     "gold": None,
     "submission": "The SWE-bench reference fix"},
    {"id": "limit", "tab": "Checking our own tests", "utboost": "wrong",
     "title": "Checking our own tests: a verified test can still lock in the agent's bug.",
     # This story's own submission is verified/20241202_amazon-q-developer-agent-20241202-dev
     # (checked in web/public/stories/limit.json), not the agentless-1.5 one hero uses.
     "system": "Amazon Q Developer Agent",
     # The figures are review-study (5 of 10 fail on gold) and review-study-2 (1 of 9),
     # spec §17; a test re-derives them when those local directories exist.
     "verdict": ("In our 13-patch study, half of Chesterton's first verified tests (5 of 10) locked in "
                 "the agent's bug. One rule, test through the public API, cut that to 1 in 9. This is "
                 "the one that still slips through. We catch it by running the test on the correct fix, "
                 "which SWE-bench provides and a new PR does not."),
     "seed": f"benchmark-v2/seeds/{TASK}/92beef201cfd.json",
     "run": f"benchmark-v2/runs/{TASK}/92beef201cfd.json",
     "review": "review-study-2/92beef201cfd.json",
     "gold": ("review-study-2/summary.json", "92beef201cfd"),
     "submission": (SCREEN, "92beef201cfd")},
]
```

- [ ] **Step 5: Regenerate the golden file and re-export the committed bundles**

Run:

```bash
cd "C:/Users/manue/projects/chesterton" && CHESTERTON_UPDATE_GOLDEN=1 .venv/Scripts/python.exe -m pytest -q tests/test_demo_export.py -k golden
cd "C:/Users/manue/projects/chesterton" && .venv/Scripts/python.exe scripts/export_demo.py
```

Expected: the second command prints these three lines, in this order:

```
  exported hero: 19 mutants, 3 headline
  exported gold: 6 mutants, 0 headline
  exported limit: 18 mutants, 1 headline
```

It must not raise `ValueError: finding … matches no surviving mutant`. If it does, stop and report which finding failed: the matching rule needs a ruling, not a workaround.

Then check the diff: `git diff --stat web/public/stories tests/fixtures`. Only `verdict`, `mutant_id`, `chesterton_commit` and the new order of `index.json` may change. Check with `git diff web/public/stories/hero.json | grep '^[-+] ' | grep -v mutant_id | grep -v verdict | grep -v chesterton_commit`, which must print nothing.

- [ ] **Step 6: Run the Python tests and watch them pass**

Run: `.venv/Scripts/python.exe -m pytest -q`

Expected: every test passes. The one skip allowed is `test_the_limit_verdict_matches_the_two_review_studies`, and only if the review-study directories are absent.

- [ ] **Step 7: Update the TypeScript contract**

In `web/src/bundle.ts`:
- In `Finding`, change the last line `agreement: number | null;` to `agreement: number | null; mutant_id: string;`.
- In `Bundle["meta"]`, change `id: string; tab: string; title: string; system: string;` to `id: string; tab: string; title: string; system: string; verdict: string;`.
- In `FINDING_KEYS`, change `"label", "category", "confident", "explanation", "agreement",` to `"label", "category", "confident", "explanation", "agreement", "mutant_id",`.
- In `META_KEYS`, change `"id", "tab", "title", "system", "pr_title", "repo", "task",` to `"id", "tab", "title", "system", "verdict", "pr_title", "repo", "task",`.

In `web/src/bundle.test.ts`, add inside `describe("bundle", …)`:

```ts
  it("rejects a finding with no mutant link", () => {
    const copy = structuredClone(golden);
    delete copy.triage.headline[0].mutant_id;
    expect(() => assertBundle(copy)).toThrow(/mutant_id/);
  });

  it("rejects a bundle with no verdict", () => {
    const copy = structuredClone(golden);
    delete copy.meta.verdict;
    expect(() => assertBundle(copy)).toThrow(/verdict/);
  });
```

Run: `cd "C:/Users/manue/projects/chesterton/web" && npx vitest run src/bundle.test.ts`

Expected: pass.

Some component tests build `Finding` literals and may now fail type-checking. Only `tsc` checks types, not vitest. Leave them: Tasks 3–5 rewrite those files.

- [ ] **Step 8: Commit**

```bash
cd "C:/Users/manue/projects/chesterton" && git add src/chesterton/demo/export.py scripts/export_demo.py tests/test_demo_export.py tests/fixtures/demo_example_bundle.json web/public/stories/hero.json web/public/stories/gold.json web/public/stories/limit.json web/public/stories/index.json web/src/bundle.ts web/src/bundle.test.ts
git commit -m "feat: give each demo story a verdict and link every finding to its mutant" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Plain words and the pure story helpers

**Files:**
- Modify: `web/src/verdicts.ts`
- Create: `web/src/story.ts`
- Create: `web/src/story.test.ts`

**Interfaces:**
- Consumes: `Bundle`, `Finding`, `Mutant`, `Verdict` from `web/src/bundle.ts`, including `Finding.mutant_id` (Task 1).
- Produces:
  - `VERDICTS[v]` now has `{ glyph, word, term, cssVar }`, and `verdictRank(v)` is unchanged.
  - `type Bucket = "headline" | "worth_a_look" | "dismissed"`.
  - `BUCKET_WORDS: Record<Bucket, string>`.
  - `topFinding(b: Bundle): { finding: Finding; bucket: Bucket } | null`.
  - `interface Summary { total: number; caught: number; missed: number; untested: number; errors: number; matter: number }` and `summarise(b: Bundle): Summary`.
  - `judgmentFor(b: Bundle, mutantId: string): { finding: Finding; bucket: Bucket } | null`.
  - `mutantsInLaneOrder(b: Bundle): Mutant[]`.
  - `mutantAtLine(b: Bundle, file: string, line: number): Mutant | null`.
  - `isUndefended(b: Bundle, m: Mutant): boolean`.
  - `interface DiffRow { kind: "ctx" | "del" | "add"; n: number | null; code: string }` and `windowDiff(before: string, after: string, context?: number): DiffRow[]`.

- [ ] **Step 1: Write the failing tests**

`web/src/story.test.ts`:

```ts
// @vitest-environment node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Bundle } from "./bundle";
import {
  BUCKET_WORDS, isUndefended, judgmentFor, mutantAtLine, mutantsInLaneOrder, summarise, topFinding, windowDiff,
} from "./story";
import { VERDICTS } from "./verdicts";

const golden = JSON.parse(
  readFileSync(new URL("../../tests/fixtures/demo_example_bundle.json", import.meta.url), "utf8"),
) as Bundle;

/** A window as the exporter writes it: "<n padded to 5> | <code>". */
const win = (rows: [number, string][]) => rows.map(([n, code]) => `${String(n).padStart(5)} | ${code}`).join("\n");

describe("windowDiff", () => {
  it("shows a deletion with its context", () => {
    const m0 = golden.mutants[0];
    expect(windowDiff(m0.before, m0.after)).toEqual([
      { kind: "ctx", n: 1, code: "def charge(amount):" },
      { kind: "del", n: 2, code: "    if not amount:" },
      { kind: "del", n: 3, code: '        raise ValueError("required")' },
      { kind: "ctx", n: 4, code: "    return amount" },
    ]);
  });

  it("shows a replaced line as a removed line then an added one, both numbered", () => {
    const before = win([[1156, "    # Call the base class"], [1157, "    super().set_visible(b)"], [1158, "    # hide"]]);
    const after = win([[1156, "    # Call the base class"], [1157, "    super().set_visible(False)"], [1158, "    # hide"]]);
    expect(windowDiff(before, after)).toEqual([
      { kind: "ctx", n: 1156, code: "    # Call the base class" },
      { kind: "del", n: 1157, code: "    super().set_visible(b)" },
      { kind: "add", n: 1157, code: "    super().set_visible(False)" },
      { kind: "ctx", n: 1158, code: "    # hide" },
    ]);
  });

  it("keeps only the given context around the change", () => {
    const rows: [number, string][] = Array.from({ length: 10 }, (_, i) => [i + 1, `line ${i + 1}`]);
    const changed = rows.map(([n, c]): [number, string] => [n, n === 5 ? "CHANGED" : c]);
    expect(windowDiff(win(rows), win(changed)).map((r) => [r.kind, r.n])).toEqual([
      ["ctx", 4], ["del", 5], ["add", 5], ["ctx", 6],
    ]);
  });

  it("returns nothing when the windows are the same", () => {
    expect(windowDiff(win([[1, "a"]]), win([[1, "a"]]))).toEqual([]);
  });
});

describe("the story helpers", () => {
  it("counts the changes as caught, missed and untested", () => {
    expect(summarise(golden)).toEqual({ total: 3, caught: 1, missed: 1, untested: 1, errors: 0, matter: 1 });
  });

  it("picks the first headline finding, else the first worth-a-look, else none", () => {
    expect(topFinding(golden)).toEqual({ finding: golden.triage.headline[0], bucket: "headline" });
    const quiet = { ...golden, triage: { ...golden.triage, headline: [], worth_a_look: [golden.triage.headline[0]] } };
    expect(topFinding(quiet)?.bucket).toBe("worth_a_look");
    const empty = { ...golden, triage: { ...golden.triage, headline: [], worth_a_look: [], dismissed: [] } };
    expect(topFinding(empty)).toBeNull();
  });

  it("finds Nemotron's judgment of a mutant through the finding's link", () => {
    expect(judgmentFor(golden, "m0")).toEqual({ finding: golden.triage.headline[0], bucket: "headline" });
    expect(judgmentFor(golden, "m1")).toBeNull();
    expect(BUCKET_WORDS.headline).toBe("matters");
  });

  it("orders mutants by lane, bad news first within a lane", () => {
    expect(mutantsInLaneOrder(golden).map((m) => m.id)).toEqual(["m0", "m2", "m1"]);
  });

  it("opens a missed change on a line first, else the line's first change", () => {
    expect(mutantAtLine(golden, "pay.py", 2)?.id).toBe("m0");
    expect(mutantAtLine(golden, "pay.py", 4)?.id).toBe("m1");
    expect(mutantAtLine(golden, "pay.py", 9)).toBeNull();
  });

  it("knows which mutants sit in a hunk the tests would not miss", () => {
    expect(isUndefended(golden, golden.mutants[0])).toBe(true);
    expect(isUndefended({ ...golden, ddmin: { undefended: [], probes: 1 } }, golden.mutants[0])).toBe(false);
  });
});

describe("plain words", () => {
  it("says missed and caught, and keeps the technical term for hover", () => {
    expect(VERDICTS.survived.word).toBe("missed");
    expect(VERDICTS.killed.word).toBe("caught");
    expect(VERDICTS.uncovered.word).toBe("untested line");
    expect(VERDICTS.pending.word).toBe("running");
    expect(VERDICTS.survived.term).toBe("surviving mutant: the tests still pass");
    expect(VERDICTS.killed.term).toBe("killed mutant: a test failed");
  });
});
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd "C:/Users/manue/projects/chesterton/web" && npx vitest run src/story.test.ts`

Expected: this fails to resolve `./story`.

- [ ] **Step 3: Implement**

Replace `web/src/verdicts.ts` with:

```ts
import type { Verdict } from "./bundle";

/** Glyph + plain word on screen; the technical term goes in a title (spec §5). */
export const VERDICTS: Record<Verdict | "pending", { glyph: string; word: string; term: string; cssVar: string }> = {
  survived: { glyph: "▲", word: "missed", term: "surviving mutant: the tests still pass", cssVar: "var(--verdict-survived)" },
  uncovered: { glyph: "◆", word: "untested line", term: "no test executes this line", cssVar: "var(--verdict-uncovered)" },
  error: { glyph: "✕", word: "error", term: "the run failed", cssVar: "var(--verdict-error)" },
  killed: { glyph: "●", word: "caught", term: "killed mutant: a test failed", cssVar: "var(--verdict-killed)" },
  pending: { glyph: "○", word: "running", term: "not finished yet", cssVar: "var(--verdict-pending)" },
};

const RANK: Record<Verdict, number> = { survived: 0, uncovered: 1, error: 2, killed: 3 };

export function verdictRank(v: Verdict): number {
  return RANK[v];
}
```

Create `web/src/story.ts`:

```ts
import type { Bundle, Finding, Mutant } from "./bundle";
import { verdictRank } from "./verdicts";

export type Bucket = "headline" | "worth_a_look" | "dismissed";

/** Nemotron's triage buckets in words. */
export const BUCKET_WORDS: Record<Bucket, string> = {
  headline: "matters",
  worth_a_look: "worth a look",
  dismissed: "dismissed",
};

const BUCKETS: Bucket[] = ["headline", "worth_a_look", "dismissed"];

/** The story's top finding: the first headline, else the first worth-a-look one. */
export function topFinding(b: Bundle): { finding: Finding; bucket: Bucket } | null {
  if (b.triage.headline.length > 0) return { finding: b.triage.headline[0], bucket: "headline" };
  if (b.triage.worth_a_look.length > 0) return { finding: b.triage.worth_a_look[0], bucket: "worth_a_look" };
  return null;
}

export interface Summary { total: number; caught: number; missed: number; untested: number; errors: number; matter: number }

export function summarise(b: Bundle): Summary {
  const count = (v: Mutant["verdict"]) => b.mutants.filter((m) => m.verdict === v).length;
  return {
    total: b.mutants.length,
    caught: count("killed"),
    missed: count("survived"),
    untested: count("uncovered"),
    errors: count("error"),
    matter: b.triage.headline.length,
  };
}

/** Nemotron's judgment of one mutant, through the exporter's finding → mutant link. */
export function judgmentFor(b: Bundle, mutantId: string): { finding: Finding; bucket: Bucket } | null {
  for (const bucket of BUCKETS) {
    const finding = b.triage[bucket].find((f) => f.mutant_id === mutantId);
    if (finding) return { finding, bucket };
  }
  return null;
}

/** Mutants as the lanes show them: lane by lane, bad news first within a lane. */
export function mutantsInLaneOrder(b: Bundle): Mutant[] {
  const laneIndex = new Map(b.lanes.map((lane, i) => [lane.id, i]));
  const index = new Map(b.mutants.map((m, i) => [m.id, i]));
  return [...b.mutants].sort((x, y) =>
    (laneIndex.get(x.lane)! - laneIndex.get(y.lane)!)
    || (verdictRank(x.verdict) - verdictRank(y.verdict))
    || (index.get(x.id)! - index.get(y.id)!));
}

/** The mutant a click on a diff line opens: the first one the tests missed, else the first. */
export function mutantAtLine(b: Bundle, file: string, line: number): Mutant | null {
  const here = b.mutants.filter((m) => m.file === file && line >= m.start_line && line <= m.end_line);
  return here.find((m) => m.verdict === "survived") ?? here[0] ?? null;
}

export function isUndefended(b: Bundle, m: Mutant): boolean {
  return b.ddmin.undefended.some((u) => u.file === m.file && m.start_line >= u.start_line && m.end_line <= u.end_line);
}

export interface DiffRow { kind: "ctx" | "del" | "add"; n: number | null; code: string }

interface WindowLine { n: number | null; code: string }

/** Splits an exporter window (" 1157 |     code" per line) into numbered code lines. */
function parseWindow(text: string): WindowLine[] {
  return text.split("\n").map((raw) => {
    const m = /^\s*(\d+) \|(.*)$/.exec(raw);
    return m ? { n: Number(m[1]), code: m[2].replace(/^ /, "") } : { n: null, code: raw };
  });
}

/**
 * A line diff of two exporter windows (the code before and after a mutation),
 * trimmed to `context` unchanged lines around each change. Removed lines keep
 * their old numbers, added lines their new ones, context lines their old ones.
 */
export function windowDiff(before: string, after: string, context = 1): DiffRow[] {
  const a = parseWindow(before);
  const b = parseWindow(after);
  // Longest common subsequence of the code, then walk it forwards.
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] = a[i].code === b[j].code ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i].code === b[j].code) {
      rows.push({ kind: "ctx", n: a[i].n, code: a[i].code });
      i++;
      j++;
    } else if (i < a.length && (j >= b.length || lcs[i + 1][j] >= lcs[i][j + 1])) {
      rows.push({ kind: "del", n: a[i].n, code: a[i].code });
      i++;
    } else {
      rows.push({ kind: "add", n: b[j].n, code: b[j].code });
      j++;
    }
  }
  const changed = rows.map((r, k) => (r.kind === "ctx" ? -1 : k)).filter((k) => k >= 0);
  if (changed.length === 0) return [];
  return rows.filter((r, k) => r.kind !== "ctx" || changed.some((c) => Math.abs(c - k) <= context));
}
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd "C:/Users/manue/projects/chesterton/web" && npx vitest run src/story.test.ts src/bundle.test.ts`

Expected: all pass.

`bundle.test.ts`'s "pairs every verdict with a glyph and a word" still holds.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/manue/projects/chesterton" && git add web/src/verdicts.ts web/src/story.ts web/src/story.test.ts
git commit -m "feat: plain verdict words and pure helpers for the answer-first story" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The answer card

**Files:**
- Create: `web/src/components/CodeDiff.tsx`
- Create: `web/src/components/AnswerCard.tsx`
- Create: `web/src/components/AnswerCard.test.tsx`

**Interfaces:**
- Consumes:
  - `topFinding`, `windowDiff`, `DiffRow` from `web/src/story.ts` (Task 2);
  - `VERDICTS` (Task 2);
  - `AskWhy` from `web/src/components/AskWhy.tsx` (unchanged; props `{ storyId, finding }`);
  - `lineRange` from `web/src/format.ts`.
- Produces:
  - `<CodeDiff rows={DiffRow[]} reduced={boolean} label={string} />`;
  - `<AnswerCard bundle={Bundle} reduced={boolean} />`;
  - `export const GOLD_WARNING`, now owned by `AnswerCard.tsx`. `FindingPanel.tsx` still exports its own copy until Task 5 deletes it.

- [ ] **Step 1: Write the failing tests**

`web/src/components/AnswerCard.test.tsx`:

```tsx
import { fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { Bundle, Regression } from "../bundle";
import { AnswerCard, GOLD_WARNING } from "./AnswerCard";

const golden = JSON.parse(
  readFileSync(resolve(process.cwd(), "../tests/fixtures/demo_example_bundle.json"), "utf8"),
) as Bundle;
const h0 = golden.triage.headline[0];
const verified = golden.regression as Regression;

function withRegression(regression: Regression | null): Bundle {
  return { ...golden, regression };
}

describe("AnswerCard", () => {
  it("leads with the story's verdict, with code set as code", () => {
    render(<AnswerCard bundle={golden} reduced />);
    const code = screen.getByText("amount");
    expect(code.tagName).toBe("CODE");
    expect(code.parentElement).toHaveTextContent("The tests never check the amount guard.");
  });

  it("shows the change the tests miss as removed and added lines", () => {
    const { container } = render(<AnswerCard bundle={golden} reduced />);
    const change = screen.getByRole("group", { name: "The change" });
    expect(change).toHaveTextContent("if not amount:");
    expect(container.querySelectorAll('[data-kind="del"]')).toHaveLength(2);
    expect(screen.getByText("tests still pass")).toBeInTheDocument();
    expect(screen.getByText(h0.explanation)).toBeInTheDocument();
  });

  it("proves a verified test with three checks", () => {
    render(<AnswerCard bundle={golden} reduced />);
    expect(screen.getByText("passes on the agent's fix")).toBeInTheDocument();
    expect(screen.getByText("fails on the change")).toBeInTheDocument();
    expect(screen.getByText("holds on the correct fix")).toBeInTheDocument();
    expect(screen.getByText("Show test")).toBeInTheDocument();
  });

  it("warns, in place of the third check, when the test fails on the correct fix", () => {
    render(<AnswerCard bundle={withRegression({ ...verified, gold: "fails_on_gold" })} reduced />);
    expect(screen.getByText(GOLD_WARNING)).toBeInTheDocument();
    expect(screen.queryByText("holds on the correct fix")).not.toBeInTheDocument();
  });

  it("never calls an unverified test verified, nor shows its source", () => {
    render(<AnswerCard bundle={withRegression({ ...verified, verified: false, status: "fails_on_patch", gold: null })} reduced />);
    expect(screen.queryByText(/Verified/)).not.toBeInTheDocument();
    expect(screen.queryByText("passes on the agent's fix")).not.toBeInTheDocument();
    expect(screen.queryByText("Show test")).not.toBeInTheDocument();
    expect(screen.getByText(/Not verified/)).toBeInTheDocument();
  });

  it("says no test was needed when nothing made the headline", () => {
    const quiet: Bundle = {
      ...golden,
      regression: null,
      triage: { ...golden.triage, headline: [], worth_a_look: [{ ...h0, id: "w0" }] },
    };
    render(<AnswerCard bundle={quiet} reduced />);
    expect(screen.getByText("missed, judged worth a look")).toBeInTheDocument();
    expect(screen.getByText("No test needed: nothing important slipped past the tests.")).toBeInTheDocument();
  });

  it("shows only the verdict when there is no finding at all", () => {
    const empty: Bundle = { ...golden, regression: null, triage: { ...golden.triage, headline: [], worth_a_look: [], dismissed: [] } };
    render(<AnswerCard bundle={empty} reduced />);
    expect(screen.queryByText("The change the tests miss")).not.toBeInTheDocument();
  });

  it("keys the live answer by finding, so it never carries over", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ label: "untested_invariant", category: "safety", explanation: "LIVE ANSWER", elapsed_s: 2 }),
    }));
    try {
      const { rerender } = render(<AnswerCard bundle={golden} reduced />);
      const card = screen.getByRole("region", { name: "What Chesterton found" });
      fireEvent.click(within(card).getByRole("button", { name: /Ask Nemotron why \(live\)/ }));
      await screen.findByText("LIVE ANSWER");
      const other: Bundle = { ...golden, triage: { ...golden.triage, headline: [{ ...h0, id: "h9" }] } };
      rerender(<AnswerCard bundle={other} reduced />);
      expect(screen.queryByText("LIVE ANSWER")).not.toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd "C:/Users/manue/projects/chesterton/web" && npx vitest run src/components/AnswerCard.test.tsx`

Expected: this fails to resolve `./AnswerCard`.

- [ ] **Step 3: Implement**

`web/src/components/CodeDiff.tsx`:

```tsx
import { motion } from "motion/react";
import type { DiffRow } from "../story";

const BACKGROUND = { del: "var(--diff-del)", add: "var(--diff-add)", ctx: undefined } as const;
const SIGN = { del: "−", add: "+", ctx: " " } as const;
const SPOKEN = { del: "removed: ", add: "added: ", ctx: "" } as const;

/** A mutation as a diff. Added lines wipe in (a crossfade under reduced motion). */
export function CodeDiff({ rows, reduced, label }: { rows: DiffRow[]; reduced: boolean; label: string }) {
  return (
    <div role="group" aria-label={label}
      className="overflow-x-auto rounded border border-border bg-background py-1 font-mono text-[15px] leading-[1.6]">
      {rows.map((r, i) => {
        const line = (
          <div data-kind={r.kind} className="flex whitespace-pre pr-3" style={{ background: BACKGROUND[r.kind] }}>
            <span className="w-14 shrink-0 select-none pr-2 text-right text-muted-foreground tabular">{r.n}</span>
            <span aria-hidden="true" className="w-5 shrink-0 select-none text-muted-foreground">{SIGN[r.kind]}</span>
            <span><span className="sr-only">{SPOKEN[r.kind]}</span>{r.code}</span>
          </div>
        );
        if (r.kind !== "add") return <div key={i}>{line}</div>;
        return (
          <motion.div key={i}
            initial={reduced ? { opacity: 0 } : { clipPath: "inset(0 100% 0 0)" }}
            animate={reduced ? { opacity: 1 } : { clipPath: "inset(0 0% 0 0)" }}
            transition={{ duration: reduced ? 0.15 : 0.4, delay: reduced ? 0 : 0.25, ease: "easeOut" }}>
            {line}
          </motion.div>
        );
      })}
    </div>
  );
}
```

`web/src/components/AnswerCard.tsx`:

```tsx
import type { ReactNode } from "react";
import type { Bundle, Finding, Regression } from "../bundle";
import { lineRange } from "../format";
import { topFinding, windowDiff, type Bucket } from "../story";
import { VERDICTS } from "../verdicts";
import { AskWhy } from "./AskWhy";
import { CodeDiff } from "./CodeDiff";

export const GOLD_WARNING = "Verified, but it fails on the correct fix: it encodes the agent's bug.";

const heading = "text-[13px] font-semibold uppercase tracking-wide text-muted-foreground";

/** A hand-written verdict may set code in `backticks`. */
function withCode(text: string): ReactNode[] {
  return text.split("`").map((part, i) => (i % 2 === 1 ? <code key={i} className="font-mono">{part}</code> : part));
}

function Check({ glyph, colour, children }: { glyph: string; colour: string; children: ReactNode }) {
  return (
    <li className="flex items-baseline gap-2">
      <span aria-hidden="true" style={{ color: colour }}>{glyph}</span>
      <span>{children}</span>
    </li>
  );
}

function MissingTest({ test, bucket }: { test: Regression | null; bucket: Bucket }) {
  if (test === null) {
    return (
      <p className="mt-2 text-[15px]">
        {bucket === "headline" ? "No verified test was written for this change." : "No test needed: nothing important slipped past the tests."}
      </p>
    );
  }
  if (!test.verified) {
    return (
      <p className="mt-2 text-[14px] text-muted-foreground">
        Not verified ({test.status ?? test.note ?? "no test written"}), so it is not offered as a test.
      </p>
    );
  }
  const caught = VERDICTS.killed;
  const code = "mt-1 overflow-x-auto rounded border border-border bg-background p-2 font-mono text-[15px] leading-[1.5]";
  return (
    <>
      <p className="mt-1 text-[13px] text-muted-foreground">Verified test, written by Nemotron Ultra · {test.path}</p>
      <ul className="mt-2 space-y-1 text-[15px]">
        <Check glyph={caught.glyph} colour={caught.cssVar}>passes on the agent's fix</Check>
        <Check glyph={caught.glyph} colour={caught.cssVar}>fails on the change</Check>
        {test.gold === "passes_on_gold" && <Check glyph={caught.glyph} colour={caught.cssVar}>holds on the correct fix</Check>}
      </ul>
      {test.gold === "fails_on_gold" && (
        <p className="mt-2 rounded border p-2 text-[14px]" style={{ borderColor: "var(--verdict-uncovered)" }}>
          <span aria-hidden="true" style={{ color: "var(--verdict-uncovered)" }}>◆</span> <span>{GOLD_WARNING}</span>
        </p>
      )}
      {test.source && (
        <details className="mt-2 text-[14px]">
          <summary className="cursor-pointer text-muted-foreground">Show test</summary>
          <pre className={code}>{test.source}</pre>
        </details>
      )}
      {(test.patch_tail || test.mutant_tail) && (
        <details className="mt-1 text-[14px]">
          <summary className="cursor-pointer text-muted-foreground">Run output</summary>
          {test.patch_tail && <><p className="mt-1 text-[13px] text-muted-foreground">on the agent's fix</p><pre className={code}>{test.patch_tail}</pre></>}
          {test.mutant_tail && <><p className="mt-1 text-[13px] text-muted-foreground">on the change</p><pre className={code}>{test.mutant_tail}</pre></>}
        </details>
      )}
    </>
  );
}

/** The top of a story: its verdict, the change the tests miss, and the missing test. */
export function AnswerCard({ bundle, reduced }: { bundle: Bundle; reduced: boolean }) {
  const m = bundle.meta;
  const top = topFinding(bundle);
  const missed = VERDICTS.survived;
  const finding: Finding | undefined = top?.finding;
  const test = finding && bundle.regression?.finding_id === finding.id ? bundle.regression : null;
  return (
    <section aria-label="What Chesterton found" className="border-b border-border bg-card px-4 py-4 md:px-6">
      <p className="min-w-0 text-[13px] text-muted-foreground">
        {m.repo} · <span title={m.submission}>patch by {m.system}</span> · {m.title}
      </p>
      <p className="mt-2 max-w-5xl text-[20px] font-semibold leading-snug">{withCode(m.verdict)}</p>
      {top && finding && (
        <div className="mt-4 grid gap-6 lg:grid-cols-2">
          <div className="min-w-0">
            <h2 className={`${heading} flex flex-wrap items-baseline gap-x-3`}>
              <span>The change the tests miss</span>
              <span className="normal-case tracking-normal">
                <span aria-hidden="true" style={{ color: missed.cssVar }}>{missed.glyph}</span>{" "}
                <span className="text-foreground">{top.bucket === "headline" ? "tests still pass" : "missed, judged worth a look"}</span>
              </span>
            </h2>
            <p className="mt-1 text-[13px] text-muted-foreground">{finding.file} · {lineRange(finding.start_line, finding.end_line)}</p>
            <div className="mt-1">
              <CodeDiff key={finding.id} rows={windowDiff(finding.original, finding.mutated)} reduced={reduced} label="The change" />
            </div>
            <p className="mt-2 text-[15px]"><span className="text-muted-foreground">Nemotron: </span>{finding.explanation}</p>
          </div>
          <div className="min-w-0">
            <h2 className={heading}>The missing test</h2>
            <MissingTest test={test} bucket={top.bucket} />
            <AskWhy key={`${m.id}:${finding.id}`} storyId={m.id} finding={finding} />
          </div>
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd "C:/Users/manue/projects/chesterton/web" && npx vitest run src/components/AnswerCard.test.tsx`

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/manue/projects/chesterton" && git add web/src/components/CodeDiff.tsx web/src/components/AnswerCard.tsx web/src/components/AnswerCard.test.tsx
git commit -m "feat: the answer card: verdict, the change the tests miss, and the missing test" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Mutants you can click: summary line, lanes, diff lines, detail panel

**Files:**
- Create: `web/src/components/SummaryLine.tsx`
- Create: `web/src/components/MutantDetail.tsx`
- Create: `web/src/components/Clickable.test.tsx`
- Rewrite: `web/src/components/Lanes.tsx`, `web/src/components/Lanes.test.tsx`
- Rewrite: `web/src/components/DiffPane.tsx`, `web/src/components/DiffPane.test.tsx`

**Interfaces:**
- Consumes: from `story.ts`, `summarise`, `judgmentFor`, `BUCKET_WORDS`, `isUndefended` and `windowDiff`; `CodeDiff` (Task 3); `VERDICTS` (Task 2); `span` from `format.ts`.
- Produces:
  - `<SummaryLine bundle={Bundle} highlight={Verdict | null} onHighlight={(v: Verdict | null) => void} />`;
  - `<Lanes bundle={Bundle} state={ReplayState} reduced={boolean} selected={string | null} highlight={Verdict | null} onSelect={(id: string) => void} />`;
  - `<DiffPane lines={DiffLine[]} bundle={Bundle} state={ReplayState} selected={Mutant | null} onSelectLine={(file: string, line: number) => void} reduced={boolean} />`;
  - `<MutantDetail bundle={Bundle} mutant={Mutant} reduced={boolean} onClose={() => void} onStep={(dir: 1 | -1) => void} />`.

- [ ] **Step 1: Write the failing tests**

`web/src/components/Clickable.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { Bundle } from "../bundle";
import { stateAt } from "../engine";
import { Lanes } from "./Lanes";
import { MutantDetail } from "./MutantDetail";
import { SummaryLine } from "./SummaryLine";

const golden = JSON.parse(
  readFileSync(resolve(process.cwd(), "../tests/fixtures/demo_example_bundle.json"), "utf8"),
) as Bundle;
const end = stateAt(golden, golden.timeline.total_s);

describe("SummaryLine", () => {
  it("tells the whole run in one sentence", () => {
    render(<SummaryLine bundle={golden} highlight={null} onHighlight={() => {}} />);
    expect(screen.getByText(/3 small changes to the lines the patch changed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "caught 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "missed 1" })).toBeInTheDocument();
    expect(screen.getByText(/1 on lines no test runs/)).toBeInTheDocument();
    expect(screen.getByText(/Nemotron picked the 1 that matters/)).toBeInTheDocument();
  });

  it("says Nemotron found none when nothing made the headline", () => {
    const quiet = { ...golden, triage: { ...golden.triage, headline: [] } };
    render(<SummaryLine bundle={quiet} highlight={null} onHighlight={() => {}} />);
    expect(screen.getByText(/Nemotron found none that matter/)).toBeInTheDocument();
  });

  it("toggles a highlight on and off", () => {
    const onHighlight = vi.fn();
    const { rerender } = render(<SummaryLine bundle={golden} highlight={null} onHighlight={onHighlight} />);
    fireEvent.click(screen.getByRole("button", { name: "missed 1" }));
    expect(onHighlight).toHaveBeenLastCalledWith("survived");
    rerender(<SummaryLine bundle={golden} highlight="survived" onHighlight={onHighlight} />);
    expect(screen.getByRole("button", { name: "missed 1" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "missed 1" }));
    expect(onHighlight).toHaveBeenLastCalledWith(null);
  });
});

describe("Lanes", () => {
  it("makes every finished capsule a button in plain words, with the term on hover", () => {
    const onSelect = vi.fn();
    render(<Lanes bundle={golden} state={end} reduced selected={null} highlight={null} onSelect={onSelect} />);
    const missed = screen.getByRole("button", { name: /missed/ });
    expect(missed).toHaveAttribute("title", "surviving mutant: the tests still pass");
    fireEvent.click(missed);
    expect(onSelect).toHaveBeenCalledWith("m0");
    expect(screen.getByRole("button", { name: /caught/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /untested line/ })).toBeInTheDocument();
  });

  it("marks the selected capsule and dims the others under a highlight", () => {
    render(<Lanes bundle={golden} state={end} reduced selected="m0" highlight="killed" onSelect={() => {}} />);
    expect(screen.getByRole("button", { name: /missed/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /missed/ })).toHaveAttribute("data-dimmed", "true");
    expect(screen.getByRole("button", { name: /caught/ })).toHaveAttribute("data-dimmed", "false");
  });
});

describe("MutantDetail", () => {
  it("shows the change, the verdict and Nemotron's judgment", () => {
    render(<MutantDetail bundle={golden} mutant={golden.mutants[0]} reduced onClose={() => {}} onStep={() => {}} />);
    const panel = screen.getByRole("region", { name: "The selected change" });
    expect(panel).toHaveTextContent("if not amount:");
    expect(panel).toHaveTextContent("missed: the 1 test that runs this line still passes");
    expect(panel).toHaveTextContent("Nemotron: matters");
    expect(panel).toHaveTextContent("Removing this whole hunk still passes the tests.");
  });

  it("says a caught change was caught, with no judgment", () => {
    render(<MutantDetail bundle={golden} mutant={golden.mutants[1]} reduced onClose={() => {}} onStep={() => {}} />);
    const panel = screen.getByRole("region", { name: "The selected change" });
    expect(panel).toHaveTextContent("caught: a test failed");
    expect(panel).not.toHaveTextContent("Nemotron:");
  });

  it("steps and closes from its buttons", () => {
    const onStep = vi.fn();
    const onClose = vi.fn();
    render(<MutantDetail bundle={golden} mutant={golden.mutants[0]} reduced onClose={onClose} onStep={onStep} />);
    fireEvent.click(screen.getByRole("button", { name: "Next change" }));
    fireEvent.click(screen.getByRole("button", { name: "Previous change" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onStep.mock.calls).toEqual([[1], [-1]]);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
```

Replace `web/src/components/Lanes.test.tsx` with:

```tsx
import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { Bundle } from "../bundle";
import { stateAt } from "../engine";
import { Lanes } from "./Lanes";

const golden = JSON.parse(
  readFileSync(resolve(process.cwd(), "../tests/fixtures/demo_example_bundle.json"), "utf8"),
) as Bundle;
const end = stateAt(golden, golden.timeline.total_s);

describe("Lanes", () => {
  it("labels a one-line hunk with one number and a range with an en dash", () => {
    render(<Lanes bundle={golden} state={end} reduced selected={null} highlight={null} onSelect={() => {}} />);
    expect(screen.getByText("pay.py:4")).toBeInTheDocument();
    expect(screen.getByText("pay.py:2–3")).toBeInTheDocument();
  });

  it("shows nothing but pending lanes before any mutant runs", () => {
    render(<Lanes bundle={golden} state={stateAt(golden, 0)} reduced selected={null} highlight={null} onSelect={() => {}} />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });
});
```

Replace `web/src/components/DiffPane.test.tsx` with:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Bundle, DiffLine } from "../bundle";
import { stateAt } from "../engine";
import { DiffPane } from "./DiffPane";

const golden = JSON.parse(
  readFileSync(resolve(process.cwd(), "../tests/fixtures/demo_example_bundle.json"), "utf8"),
) as Bundle;
const LINES: DiffLine[] = [
  { kind: "add", file: "pay.py", old: null, new: 2, html: "if not amount:" },
  { kind: "add", file: "pay.py", old: null, new: 3, html: "raise" },
  { kind: "add", file: "pay.py", old: null, new: 4, html: "return amount" },
];
const end = stateAt(golden, golden.timeline.total_s);

function pane(props: Partial<Parameters<typeof DiffPane>[0]> = {}) {
  return render(<DiffPane lines={LINES} bundle={golden} state={end} selected={null} onSelectLine={() => {}} {...props} />);
}

describe("DiffPane", () => {
  it("labels a line the tests missed in plain words", () => {
    pane();
    expect(screen.getByRole("img", { name: "line 2: the tests missed 1 of 1 changes" })).toBeInTheDocument();
  });

  it("labels a line no test runs", () => {
    pane({ state: stateAt(golden, 0) });
    expect(screen.getByLabelText(/no test runs this line/)).toBeInTheDocument();
  });

  it("opens a line's changes on click, with one tab stop per hunk", () => {
    const onSelectLine = vi.fn();
    pane({ onSelectLine });
    fireEvent.click(screen.getByRole("button", { name: "Show the changes on line 3" }));
    expect(onSelectLine).toHaveBeenCalledWith("pay.py", 3);
    expect(screen.getByRole("button", { name: "Show the changes on line 2" })).not.toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("button", { name: "Show the changes on line 3" })).toHaveAttribute("tabindex", "-1");
  });

  it("labels the hunk the tests would not miss, once, when ddmin shows", () => {
    const { rerender } = pane({ state: stateAt(golden, 0) });
    expect(screen.queryByText("the tests would not miss this hunk")).not.toBeInTheDocument();
    rerender(<DiffPane lines={LINES} bundle={golden} state={end} selected={null} onSelectLine={() => {}} />);
    expect(screen.getAllByText("the tests would not miss this hunk")).toHaveLength(1);
  });

  describe("scrolling to the selected change", () => {
    const scroll = vi.fn();
    beforeEach(() => {
      scroll.mockClear();
      Element.prototype.scrollIntoView = scroll;
    });
    afterEach(() => {
      delete (Element.prototype as Partial<Element>).scrollIntoView;
    });

    it("centres the selected change's first line, smoothly", () => {
      pane({ selected: golden.mutants[0] });
      expect(scroll).toHaveBeenCalledWith({ block: "center", behavior: "smooth" });
      expect(scroll.mock.contexts[0]).toHaveTextContent("if not amount:");
    });

    it("jumps without smoothing under reduced motion", () => {
      pane({ selected: golden.mutants[0], reduced: true });
      expect(scroll).toHaveBeenCalledWith({ block: "center", behavior: "auto" });
    });
  });

  it("does not throw where scrollIntoView is missing", () => {
    expect(() => pane({ selected: golden.mutants[0] })).not.toThrow();
  });
});
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd "C:/Users/manue/projects/chesterton/web" && npx vitest run src/components/Clickable.test.tsx src/components/Lanes.test.tsx src/components/DiffPane.test.tsx`

Expected: the run fails. `./SummaryLine` and `./MutantDetail` don't resolve, and the Lanes and DiffPane tests fail on the missing buttons and labels.

- [ ] **Step 3: Implement**

`web/src/components/SummaryLine.tsx`:

```tsx
import type { Bundle, Verdict } from "../bundle";
import { summarise } from "../story";
import { VERDICTS } from "../verdicts";

interface Props { bundle: Bundle; highlight: Verdict | null; onHighlight: (v: Verdict | null) => void }

/** The run in one sentence; "caught" and "missed" highlight their capsules. */
export function SummaryLine({ bundle, highlight, onHighlight }: Props) {
  const s = summarise(bundle);
  const toggle = (v: Verdict, word: string, n: number) => (
    <button type="button" aria-pressed={highlight === v} onClick={() => onHighlight(highlight === v ? null : v)}
      className="cursor-pointer rounded px-1 font-semibold underline decoration-dotted underline-offset-4 aria-pressed:bg-muted">
      <span aria-hidden="true" style={{ color: VERDICTS[v].cssVar }}>{VERDICTS[v].glyph}</span>{" "}
      {word} {n}
    </button>
  );
  return (
    <p className="px-4 py-2 text-[15px] tabular">
      {s.total} small changes to the lines the patch changed → the tests {toggle("killed", "caught", s.caught)},{" "}
      {toggle("survived", "missed", s.missed)}
      {s.untested > 0 && <span className="text-muted-foreground"> · {s.untested} on lines no test runs</span>}
      {" → "}
      {s.matter === 0
        ? "Nemotron found none that matter"
        : `Nemotron picked the ${s.matter} that ${s.matter === 1 ? "matters" : "matter"}`}
    </p>
  );
}
```

Note that each toggle's accessible name is "caught 1" or "missed 1": the glyph is `aria-hidden`.

`web/src/components/MutantDetail.tsx`:

```tsx
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import type { Bundle, Mutant } from "../bundle";
import { span } from "../format";
import { BUCKET_WORDS, isUndefended, judgmentFor, windowDiff } from "../story";
import { VERDICTS } from "../verdicts";
import { CodeDiff } from "./CodeDiff";

function verdictSentence(m: Mutant): string {
  switch (m.verdict) {
    case "survived":
      return m.tests === 1
        ? "missed: the 1 test that runs this line still passes"
        : `missed: the ${m.tests} tests that run this line still pass`;
    case "killed":
      return "caught: a test failed";
    case "uncovered":
      return "untested line: no test runs this line";
    case "error":
      return "error: the run failed";
  }
}

interface Props {
  bundle: Bundle;
  mutant: Mutant;
  reduced: boolean;
  onClose: () => void;
  onStep: (dir: 1 | -1) => void;
}

/** One mutant, readable: what it changed, what the tests did, what Nemotron made of it. */
export function MutantDetail({ bundle, mutant, reduced, onClose, onStep }: Props) {
  const v = VERDICTS[mutant.verdict];
  const judged = judgmentFor(bundle, mutant.id);
  const icon = "inline-flex cursor-pointer items-center rounded p-1 text-muted-foreground hover:bg-muted";
  return (
    <section aria-label="The selected change" className="border-t border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <h3 className="font-mono text-[14px]">{mutant.file.split("/").pop()}:{span(mutant.start_line, mutant.end_line)}</h3>
        <span className="text-[13px] text-muted-foreground">{mutant.operator}</span>
        <span className="ml-auto flex gap-1">
          <button type="button" className={icon} aria-label="Previous change" onClick={() => onStep(-1)}><ChevronLeft size={18} aria-hidden="true" /></button>
          <button type="button" className={icon} aria-label="Next change" onClick={() => onStep(1)}><ChevronRight size={18} aria-hidden="true" /></button>
          <button type="button" className={icon} aria-label="Close" onClick={onClose}><X size={18} aria-hidden="true" /></button>
        </span>
      </div>
      <div className="mt-2">
        <CodeDiff key={mutant.id} rows={windowDiff(mutant.before, mutant.after)} reduced={reduced} label="The change" />
      </div>
      <p className="mt-2 text-[15px]" title={v.term}>
        <span aria-hidden="true" style={{ color: v.cssVar }}>{v.glyph}</span> {verdictSentence(mutant)}
      </p>
      {judged && (
        <p className="mt-1 text-[15px]">
          <span className="text-muted-foreground">Nemotron: </span>
          <b>{BUCKET_WORDS[judged.bucket]}</b>{judged.finding.category ? ` · ${judged.finding.category}` : ""}. {judged.finding.explanation}
        </p>
      )}
      {isUndefended(bundle, mutant) && (
        <p className="mt-1 text-[14px] text-muted-foreground">Removing this whole hunk still passes the tests.</p>
      )}
    </section>
  );
}
```

Replace `web/src/components/Lanes.tsx` with:

```tsx
import { AnimatePresence, motion } from "motion/react";
import type { Bundle, Verdict } from "../bundle";
import type { ReplayState } from "../engine";
import { span } from "../format";
import { VERDICTS, verdictRank } from "../verdicts";

interface Props {
  bundle: Bundle;
  state: ReplayState;
  reduced: boolean;
  selected: string | null;
  highlight: Verdict | null;
  onSelect: (id: string) => void;
}

/** One lane per changed hunk; every finished mutant is a capsule you can open. */
export function Lanes({ bundle, state, reduced, selected, highlight, onSelect }: Props) {
  const byId = new Map(bundle.mutants.map((m) => [m.id, m]));
  const base = (f: string) => f.split("/").pop();
  return (
    <div role="region" aria-label="Mutants by hunk">
      {bundle.lanes.map((lane) => {
        const live = state.mutants
          .filter((s) => s.lane === lane.id && s.phase !== "pending")
          .sort((a, b) => {
            const ra = a.phase === "done" ? verdictRank(byId.get(a.id)!.verdict) : 9;
            const rb = b.phase === "done" ? verdictRank(byId.get(b.id)!.verdict) : 9;
            return ra - rb;
          });
        const undefended = state.showDdmin && bundle.ddmin.undefended.some(
          (u) => u.file === lane.file && lane.start_line >= u.start_line && lane.end_line <= u.end_line);
        return (
          <div key={lane.id}
            className="flex items-center gap-2 border-b border-border px-3 py-2"
            style={undefended ? { outline: "1px dashed var(--verdict-uncovered)", outlineOffset: "-2px" } : undefined}>
            <span className="w-36 shrink-0 overflow-hidden text-ellipsis whitespace-nowrap font-mono text-[12px] text-muted-foreground tabular"
              title={`${lane.file}:${span(lane.start_line, lane.end_line)}`}>
              {base(lane.file)}:{span(lane.start_line, lane.end_line)}
            </span>
            <div className="flex flex-wrap gap-1.5">
              <AnimatePresence initial={false}>
                {live.map((s) => {
                  const m = byId.get(s.id)!;
                  const done = s.phase === "done";
                  const v = done ? VERDICTS[m.verdict] : VERDICTS.pending;
                  const dimmed = done && highlight !== null && m.verdict !== highlight;
                  const pill = `inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-semibold ${done ? "text-background" : "text-foreground"}`;
                  const motionProps = {
                    layout: !reduced,
                    initial: reduced ? false : { x: -24, opacity: 0 },
                    animate: { x: 0, opacity: dimmed ? 0.35 : 1 },
                    transition: { type: "spring" as const, stiffness: 380, damping: 30 },
                  };
                  if (!done) {
                    return (
                      <motion.span key={s.id} {...motionProps} className={pill} style={{ background: v.cssVar }} title={v.term}>
                        <span aria-hidden="true">{v.glyph}</span>{v.word}
                      </motion.span>
                    );
                  }
                  return (
                    <motion.button key={s.id} type="button" {...motionProps}
                      aria-pressed={selected === s.id} data-dimmed={dimmed} title={v.term}
                      onClick={() => onSelect(s.id)}
                      className={`${pill} cursor-pointer aria-pressed:outline-2 aria-pressed:outline-offset-2 aria-pressed:outline-accent`}
                      style={{ background: v.cssVar }}>
                      <span aria-hidden="true">{v.glyph}</span>{v.word}
                    </motion.button>
                  );
                })}
              </AnimatePresence>
            </div>
          </div>
        );
      })}
    </div>
  );
}
```

Replace `web/src/components/DiffPane.tsx` with:

```tsx
import { useEffect, useRef } from "react";
import type { Bundle, DiffLine, Mutant } from "../bundle";
import { lineKey, type ReplayState } from "../engine";
import { VERDICTS } from "../verdicts";

interface Props {
  lines: DiffLine[];
  bundle: Bundle;
  state: ReplayState;
  selected: Mutant | null;
  onSelectLine: (file: string, line: number) => void;
  /** Reduced motion: jump to the selected change instead of scrolling smoothly. */
  reduced?: boolean;
}

function gutter(line: DiffLine, bundle: Bundle, state: ReplayState) {
  if (line.kind !== "add" || line.new === null || line.file === null) return null;
  if (state.showTier0 && bundle.tier0.some((z) => z.file === line.file && z.line === line.new)) {
    return { verdict: VERDICTS.uncovered, label: `line ${line.new}: no test runs this line`, tint: 18 };
  }
  const meter = state.meters[lineKey(line.file, line.new)];
  if (!meter) return null;
  if (meter.survived > 0) {
    return {
      verdict: VERDICTS.survived,
      label: `line ${line.new}: the tests missed ${meter.survived} of ${meter.done} changes`,
      tint: Math.min(28, 8 + 6 * meter.survived),
    };
  }
  return { verdict: VERDICTS.killed, label: `line ${line.new}: the tests caught all ${meter.done} changes`, tint: 0 };
}

const BASE = { add: "var(--diff-add)", del: "var(--diff-del)", ctx: "transparent" } as const;

interface Range { file: string; start_line: number; end_line: number }

const within = (r: Range, file: string | null, n: number | null) =>
  n !== null && r.file === file && n >= r.start_line && n <= r.end_line;

export function DiffPane({ lines, bundle, state, selected, onSelectLine, reduced = false }: Props) {
  const laneAt = (file: string | null, n: number | null) => bundle.lanes.find((l) => within(l, file, n));
  const undefendedAt = (file: string | null, n: number | null) =>
    state.showDdmin ? bundle.ddmin.undefended.find((u) => within(u, file, n)) : undefined;

  // The first diff line of each lane (one tab stop per hunk) and of each undefended hunk (its label).
  const firstOf = new Map<unknown, number>();
  lines.forEach((line, i) => {
    for (const r of [laneAt(line.file, line.new), undefendedAt(line.file, line.new)]) {
      if (r && !firstOf.has(r)) firstOf.set(r, i);
    }
  });
  const selectedFirst = selected === null ? -1 : lines.findIndex((line) => within(selected, line.file, line.new));

  const selectedRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    selectedRef.current?.scrollIntoView?.({ block: "center", behavior: reduced ? "auto" : "smooth" });
    // Only when another change is selected, not on every replay tick.
  }, [selected?.id]);

  return (
    <div className="font-mono text-[15px] leading-[1.6]" role="region" aria-label="The pull request's diff">
      {lines.map((line, i) => {
        if (line.kind === "file") {
          return <div key={i} className="border-y border-border bg-card px-3 py-1 text-muted-foreground">{line.file}</div>;
        }
        if (line.kind === "hunk") {
          return <div key={i} className="px-3 text-muted-foreground" dangerouslySetInnerHTML={{ __html: line.html }} />;
        }
        const g = gutter(line, bundle, state);
        const lane = laneAt(line.file, line.new);
        const undefended = undefendedAt(line.file, line.new);
        const isSelected = selected !== null && within(selected, line.file, line.new);
        const base = BASE[line.kind];
        const background = g && g.tint > 0
          ? `color-mix(in srgb, ${g.verdict.cssVar} ${g.tint}%, ${base === "transparent" ? "var(--background)" : base})`
          : base;
        const borderLeft = undefended ? "2px dashed var(--verdict-uncovered)" : "2px solid transparent";
        const clickable = g !== null && line.file !== null && line.new !== null;
        return (
          <div key={i} ref={i === selectedFirst ? selectedRef : undefined}
            className={`flex ${isSelected ? "outline-2 outline-accent -outline-offset-2 outline" : ""}`} style={{ background, borderLeft }}>
            <span className="w-14 shrink-0 select-none pr-2 text-right text-muted-foreground tabular">{line.new ?? line.old}</span>
            <span className="w-6 shrink-0 select-none text-center" style={{ color: g?.verdict.cssVar }}>
              {g ? <span role="img" aria-label={g.label} title={g.label}>{g.verdict.glyph}</span> : null}
            </span>
            <span className="w-4 shrink-0 select-none text-muted-foreground">{line.kind === "add" ? "+" : line.kind === "del" ? "−" : " "}</span>
            {clickable ? (
              <button type="button" className="cursor-pointer whitespace-pre text-left"
                onClick={() => onSelectLine(line.file!, line.new!)}
                tabIndex={lane && firstOf.get(lane) === i ? undefined : -1}
                aria-label={`Show the changes on line ${line.new}`}>
                <span dangerouslySetInnerHTML={{ __html: line.html }} />
              </button>
            ) : (
              <span className="whitespace-pre" dangerouslySetInnerHTML={{ __html: line.html }} />
            )}
            {undefended && firstOf.get(undefended) === i && (
              <span className="ml-6 select-none whitespace-nowrap font-sans text-[13px] text-muted-foreground">
                the tests would not miss this hunk
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd "C:/Users/manue/projects/chesterton/web" && npx vitest run src/components/Clickable.test.tsx src/components/Lanes.test.tsx src/components/DiffPane.test.tsx`

Expected: all pass.

`App.test.tsx` and `FindingPanel.test.tsx` may fail now, because App still uses the old `Lanes`/`DiffPane` props. Task 5 rewrites them. Don't touch them here.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/manue/projects/chesterton" && git add web/src/components/SummaryLine.tsx web/src/components/MutantDetail.tsx web/src/components/Clickable.test.tsx web/src/components/Lanes.tsx web/src/components/Lanes.test.tsx web/src/components/DiffPane.tsx web/src/components/DiffPane.test.tsx
git commit -m "feat: every mutant can be opened: clickable capsules and diff lines, a detail panel, a summary line" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The page: answer first, replay below, no autoplay

**Files:**
- Modify: `web/src/useReplay.ts`
- Modify: `web/src/components/ReplayControls.tsx`
- Modify: `web/src/components/AboutDialog.tsx`
- Rewrite: `web/src/App.tsx`, `web/src/App.test.tsx`
- Delete: `web/src/components/FindingPanel.tsx`, `web/src/components/FindingPanel.test.tsx`

**Interfaces:**
- Consumes: everything from Tasks 2–4. `AnswerCard` (Task 3). `SummaryLine`, `Lanes`, `DiffPane` and `MutantDetail` (Task 4). `mutantsInLaneOrder` and `mutantAtLine` (Task 2).
- Produces:
  - the app;
  - `statusLine(state, bundle)`, which now returns `"N of N changes tested · M missed"`;
  - `useReplay(total)`, which now starts at `t = total`, not playing.

- [ ] **Step 1: Write the failing tests**

Replace `web/src/App.test.tsx` with:

```tsx
import { fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { Bundle, DiffLine } from "./bundle";
import { ReplayControls, statusLine } from "./components/ReplayControls";
import { stateAt, type ReplayState } from "./engine";
import type { useReplay } from "./useReplay";

const golden = JSON.parse(
  readFileSync(resolve(process.cwd(), "../tests/fixtures/demo_example_bundle.json"), "utf8"),
) as Bundle;

describe("statusLine", () => {
  it("reads as a sentence in plain words", () => {
    expect(statusLine(stateAt(golden, golden.timeline.total_s), golden)).toBe("3 of 3 changes tested · 1 missed");
  });
});

function stubClock(t: number): ReturnType<typeof useReplay> {
  return { t, playing: false, speed: 1, reduced: true, setSpeed: () => {}, play: () => {}, pause: () => {}, seek: () => {}, skip: () => {} };
}

function makeState(overrides: Partial<ReplayState>): ReplayState {
  return {
    t: 0, phase: "mutants", mutants: [], finished: 0, survived: 0, killed: 0, uncovered: 0, errors: 0, meters: {},
    showTier0: true, showDdmin: false, showTriage: false, showRegression: false, ...overrides,
  };
}

describe("ReplayControls' status announcement", () => {
  const total = golden.timeline.total_s;
  const n = golden.mutants.length;

  it("does not re-announce for an extra miss within the same quarter, but does at the end", () => {
    const clock = stubClock(0);
    const { rerender } = render(<ReplayControls clock={clock} total={total} state={makeState({ finished: 1, survived: 0 })} bundle={golden} />);
    const before = screen.getByRole("status").textContent;
    rerender(<ReplayControls clock={clock} total={total} state={makeState({ finished: 1, survived: 1 })} bundle={golden} />);
    expect(screen.getByRole("status").textContent).toBe(before);
    rerender(<ReplayControls clock={clock} total={total} state={makeState({ phase: "done", finished: n, survived: 3 })} bundle={golden} />);
    expect(screen.getByRole("status")).toHaveTextContent(`${n} of ${n} changes tested`);
  });

  it("offers Replay at the end and Play partway through", () => {
    const { rerender } = render(<ReplayControls clock={stubClock(total)} total={total} state={makeState({ phase: "done" })} bundle={golden} />);
    expect(screen.getByRole("button", { name: /^Replay/ })).toBeInTheDocument();
    rerender(<ReplayControls clock={stubClock(1)} total={total} state={makeState({})} bundle={golden} />);
    expect(screen.getByRole("button", { name: /^Play/ })).toBeInTheDocument();
  });
});

describe("App's load errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a message instead of loading forever when the story index fails to load", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) })));
    render(<App />);
    await screen.findByText("Could not load the stories.");
  });

  it("shows a message instead of loading forever when a story fails to load", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => (url.includes("index.json")
      ? { ok: true, json: async () => ({ stories: [{ id: "hero", tab: "Hero" }] }) }
      : { ok: false, status: 500, json: async () => ({}) })));
    render(<App />);
    await screen.findByText("Could not load this story.");
  });
});

const LINES: DiffLine[] = [2, 3, 4].map((n) => ({ kind: "add", file: "pay.py", old: null, new: n, html: `line ${n}` }));

function serve(bundle: Bundle) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const body = url.includes("index.json") ? { stories: [{ id: "hero", tab: "Hero" }] }
      : url.includes(".lines.json") ? LINES
      : bundle;
    return { ok: true, json: async () => body };
  }));
}

async function openStory() {
  render(<App />);
  return screen.findByRole("region", { name: "What Chesterton found" });
}

const detail = () => screen.queryByRole("region", { name: "The selected change" });
// The summary line's "missed 1"/"caught 1" toggles also match /missed/ and /caught/: scope capsules to the lanes.
const capsule = (name: RegExp) => within(screen.getByRole("region", { name: "Mutants by hunk" })).getByRole("button", { name });

describe("the story page", () => {
  beforeEach(() => {
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens on the answer, with the replay finished and not playing", async () => {
    serve(golden);
    const card = await openStory();
    expect(within(card).getByText(/The tests never check the/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "How Chesterton found this" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("3 of 3 changes tested · 1 missed");
    expect(screen.getByRole("button", { name: /^Replay/ })).toBeInTheDocument();
  });

  it("replays from the start when asked", async () => {
    serve(golden);
    await openStory();
    fireEvent.click(screen.getByRole("button", { name: /^Replay/ }));
    expect(screen.getByRole("slider", { name: "Replay position" })).toHaveValue("0");
    expect(screen.getByRole("button", { name: /^Pause/ })).toBeInTheDocument();
  });

  it("opens a capsule's change, steps with the arrow keys and closes with Escape", async () => {
    serve(golden);
    await openStory();
    fireEvent.click(capsule(/missed/));
    expect(detail()).toHaveTextContent("Nemotron: matters");
    const next = within(detail()!).getByRole("button", { name: "Next change" });
    next.focus();
    fireEvent.keyDown(next, { key: "ArrowRight" });
    expect(detail()).toHaveTextContent("untested line: no test runs this line");
    fireEvent.keyDown(document.body, { key: "ArrowRight", altKey: true });
    expect(detail()).toHaveTextContent("untested line: no test runs this line");
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(detail()).not.toBeInTheDocument();
  });

  it("opens a diff line's missed change first", async () => {
    serve(golden);
    await openStory();
    fireEvent.click(screen.getByRole("button", { name: "Show the changes on line 2" }));
    expect(detail()).toHaveTextContent("missed: the 1 test that runs this line still passes");
  });

  it("highlights missed changes from the summary line", async () => {
    serve(golden);
    await openStory();
    fireEvent.click(screen.getByRole("button", { name: "missed 1" }));
    expect(capsule(/caught/)).toHaveAttribute("data-dimmed", "true");
  });

  it("pauses a running replay when a change is opened", async () => {
    serve(golden);
    await openStory();
    fireEvent.click(screen.getByRole("button", { name: /^Replay/ }));
    expect(screen.getByRole("button", { name: /^Pause/ })).toBeInTheDocument();
    // At t = 0 no mutant has finished, but line 3 is a tier-0 line and already clickable.
    fireEvent.click(screen.getByRole("button", { name: "Show the changes on line 3" }));
    expect(screen.getByRole("button", { name: /^Play/ })).toBeInTheDocument();
    expect(detail()).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd "C:/Users/manue/projects/chesterton/web" && npx vitest run src/App.test.tsx`

Expected: fails. The status still reads "mutants finished", there is no "What Chesterton found" region, and there is no Replay button.

- [ ] **Step 3: Implement**

In `web/src/useReplay.ts`:

1. Replace the doc comment on `useReplay` and the first three state lines:

```ts
/** Replay clock. Remount (key by story) to reset. Opens at the final state, not playing (spec §4). */
export function useReplay(total: number) {
  const reduced = usePrefersReducedMotion();
  const [t, setT] = useState(total);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(() => defaultSpeed(total));
```

2. Replace `play`:

```ts
    play: () => {
      // Reduced motion: nothing animates, so Replay shows the end.
      if (reduced) {
        setT(total);
        return;
      }
      if (t >= total) setT(0);
      setPlaying(true);
    },
```

In `web/src/components/ReplayControls.tsx`:

- Replace `statusLine`:

```ts
export function statusLine(state: ReplayState, bundle: Bundle): string {
  return `${state.finished} of ${bundle.mutants.length} changes tested · ${state.survived} missed`;
}
```

- Replace the play/pause block (the `{clock.playing ? (...) : (...)}` expression) with:

```tsx
      {clock.playing ? (
        <button type="button" className={primary} onClick={clock.pause}>
          <Pause size={16} aria-hidden="true" /> Pause
        </button>
      ) : (
        <button type="button" className={primary} onClick={clock.play}>
          <Play size={16} aria-hidden="true" /> {clock.t >= total ? "Replay" : "Play"}
        </button>
      )}
```

- Replace the hint span's text `{"Space pause · ←/→ findings"}` with `{"Space play or pause · ←/→ changes · Esc close"}`.

In `web/src/components/AboutDialog.tsx`, insert this as the first `<li>` of the list:

```tsx
        <li>A mutant is a small deliberate change to a line the agent wrote. If every test still passes, the tests missed it.</li>
```

Replace `web/src/App.tsx` with:

```tsx
import * as Tabs from "@radix-ui/react-tabs";
import { Info } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { assertBundle, type Bundle, type DiffLine, type StoryIndex, type Verdict } from "./bundle";
import { AboutDialog } from "./components/AboutDialog";
import { AnswerCard } from "./components/AnswerCard";
import { DiffPane } from "./components/DiffPane";
import { Lanes } from "./components/Lanes";
import { MutantDetail } from "./components/MutantDetail";
import { ReplayControls } from "./components/ReplayControls";
import { SummaryLine } from "./components/SummaryLine";
import { stateAt } from "./engine";
import { mutantAtLine, mutantsInLaneOrder } from "./story";
import { useReplay } from "./useReplay";

async function fetchJson(url: string): Promise<unknown> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

export default function App() {
  const [index, setIndex] = useState<StoryIndex | null>(null);
  const [indexError, setIndexError] = useState(false);
  const [active, setActive] = useState<string>("");
  const [about, setAbout] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchJson("/stories/index.json")
      .then((ix) => {
        if (cancelled) return;
        setIndex(ix as StoryIndex);
        setActive((ix as StoryIndex).stories[0]?.id ?? "");
      })
      .catch(() => {
        if (!cancelled) setIndexError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (indexError) return <main className="p-6 text-muted-foreground">Could not load the stories.</main>;
  if (!index) return <main className="p-6 text-muted-foreground">Loading…</main>;
  return (
    <Tabs.Root value={active} onValueChange={setActive} className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-border bg-card px-4 py-2">
        <span className="font-semibold">Chesterton</span>
        <Tabs.List aria-label="Stories" className="flex flex-wrap gap-1">
          {index.stories.map((s, i) => (
            <Tabs.Trigger key={s.id} value={s.id}
              className="cursor-pointer rounded-md px-3 py-1 text-[14px] text-muted-foreground data-[state=active]:bg-muted data-[state=active]:text-foreground">
              {i + 1} · {s.tab}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        <button type="button" onClick={() => setAbout(true)}
          className="ml-auto inline-flex cursor-pointer items-center gap-1.5 text-[14px] text-muted-foreground">
          <Info size={16} aria-hidden="true" /> About · how it runs on Nebius
        </button>
      </header>
      {index.stories.map((s) => (
        // Radix puts the panel itself in the tab order; ours always has focusable content.
        <Tabs.Content key={s.id} value={s.id} tabIndex={-1} className="min-h-0 flex-1 overflow-auto">
          {active === s.id && <Story key={s.id} id={s.id} />}
        </Tabs.Content>
      ))}
      <AboutDialog open={about} onClose={() => setAbout(false)} />
    </Tabs.Root>
  );
}

function Story({ id }: { id: string }) {
  const [data, setData] = useState<{ bundle: Bundle; lines: DiffLine[] } | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(false);
    Promise.all([fetchJson(`/stories/${id}.json`), fetchJson(`/stories/${id}.lines.json`)])
      .then(([bundle, lines]) => {
        assertBundle(bundle);
        if (!cancelled) setData({ bundle, lines: lines as DiffLine[] });
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);
  if (error) return <p className="p-6 text-muted-foreground">Could not load this story.</p>;
  if (!data) return <p className="p-6 text-muted-foreground">Loading story…</p>;
  return <StoryView bundle={data.bundle} lines={data.lines} />;
}

function StoryView({ bundle, lines }: { bundle: Bundle; lines: DiffLine[] }) {
  const total = bundle.timeline.total_s;
  const clock = useReplay(total);
  const state = useMemo(() => stateAt(bundle, clock.t), [bundle, clock.t]);
  const order = useMemo(() => mutantsInLaneOrder(bundle), [bundle]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<Verdict | null>(null);
  const selected = order.find((m) => m.id === selectedId) ?? null;

  const select = (id: string) => {
    clock.pause();
    setSelectedId(id);
  };
  const step = (dir: 1 | -1) => {
    if (order.length === 0) return;
    const i = selected ? order.indexOf(selected) : -1;
    const next = i === -1 ? (dir === 1 ? 0 : order.length - 1) : Math.min(Math.max(i + dir, 0), order.length - 1);
    select(order[next].id);
  };
  const selectLine = (file: string, line: number) => {
    const m = mutantAtLine(bundle, file, line);
    if (m) select(m.id);
  };

  // `clock` is a fresh object every render; keep the latest handler in a ref and
  // register the window listener once.
  const onKeyRef = useRef<(e: KeyboardEvent) => void>(() => {});
  onKeyRef.current = (e: KeyboardEvent) => {
    if (document.querySelector("dialog[open]")) return;
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const el = e.target instanceof Element ? e.target : null;
    const tag = el?.tagName ?? "";
    if (e.key === " ") {
      // Space activates a focused button, so leave it to the button.
      if (["INPUT", "SELECT", "BUTTON", "TEXTAREA", "SUMMARY"].includes(tag)) return;
      e.preventDefault();
      if (clock.playing) clock.pause();
      else clock.play();
      return;
    }
    if (e.key === "Escape") {
      setSelectedId(null);
      return;
    }
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      // Arrows belong to form fields and to tab lists.
      if (["INPUT", "SELECT", "TEXTAREA"].includes(tag)) return;
      if (el?.closest("[role=tab], [role=tablist]")) return;
      step(e.key === "ArrowRight" ? 1 : -1);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => onKeyRef.current(e);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const c = bundle.counters;
  return (
    <div className="flex flex-col">
      <AnswerCard bundle={bundle} reduced={clock.reduced} />
      <section aria-labelledby="how-found" className="flex flex-col">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 pt-4">
          <h2 id="how-found" className="text-[17px] font-semibold">How Chesterton found this</h2>
          <span className="text-[13px] text-muted-foreground tabular md:ml-auto">
            run totals: {c.sandbox_ops} sandboxes · {c.lightning_calls} Lightning · {c.super_calls} Super · {c.ultra_calls} Ultra · {Math.round(c.run_wall_s)} s
          </span>
        </div>
        <SummaryLine bundle={bundle} highlight={highlight} onHighlight={setHighlight} />
        <ReplayControls clock={clock} total={total} state={state} bundle={bundle} />
        <div className="flex flex-col md:h-[75vh] md:flex-row">
          <div className="max-h-[75vh] min-w-0 overflow-auto border-b border-border md:max-h-none md:w-[60%] md:border-b-0 md:border-r">
            <DiffPane lines={lines} bundle={bundle} state={state} selected={selected} onSelectLine={selectLine} reduced={clock.reduced} />
          </div>
          <div className="min-w-0 overflow-auto md:w-[40%]">
            <Lanes bundle={bundle} state={state} reduced={clock.reduced} selected={selectedId} highlight={highlight} onSelect={select} />
            {selected ? (
              <MutantDetail bundle={bundle} mutant={selected} reduced={clock.reduced}
                onClose={() => setSelectedId(null)} onStep={step} />
            ) : (
              <p className="px-3 py-3 text-[14px] text-muted-foreground">Click a change, or a marked line in the diff, to see what it did.</p>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
```

Delete the old panel:

```bash
cd "C:/Users/manue/projects/chesterton" && git rm -q web/src/components/FindingPanel.tsx web/src/components/FindingPanel.test.tsx
```

- [ ] **Step 4: Run all web tests, the type check and the build**

Run: `cd "C:/Users/manue/projects/chesterton/web" && npx vitest run && npm run build`

Expected: every vitest file passes, and the build succeeds. The build runs `tsc` and fails on any type error, including stale `Finding` literals in `AskWhy.test.tsx`. If `AskWhy.test.tsx` builds a `Finding` without `mutant_id`, add `mutant_id: "m0"` to that literal. That is the only change allowed in that file.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/manue/projects/chesterton" && git add web/src/useReplay.ts web/src/components/ReplayControls.tsx web/src/components/AboutDialog.tsx web/src/App.tsx web/src/App.test.tsx
git add web/src/components/AskWhy.test.tsx 2>/dev/null; git status --short web/src
git commit -m "feat: open each story on its answer, with the replay below and no autoplay" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Stage `AskWhy.test.tsx` only if Step 4 changed it. The `git rm` in Step 3 has already staged both deletions.

---

### Task 6: Smoke test, README, and the layout check

**Files:**
- Rewrite: `web/e2e/smoke.spec.ts`
- Modify: `README.md` (the Demo section's numbered list)

**Interfaces:**
- Consumes: the built site.
- Produces: a passing smoke test, a README that matches the demo, and screenshots for review.

- [ ] **Step 1: Rewrite the smoke test**

`web/e2e/smoke.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

const storyTabs = (page: import("@playwright/test").Page) =>
  page.getByRole("tablist", { name: "Stories" }).getByRole("tab");

test("every story opens on its answer, finished, and can replay", async ({ page }) => {
  await page.goto("/");
  await expect(storyTabs(page)).toHaveText([/Wrong patch, caught/, /The correct fix/, /Checking our own tests/]);
  for (let i = 0; i < 3; i++) {
    await storyTabs(page).nth(i).click();
    const card = page.getByRole("region", { name: "What Chesterton found" });
    await expect(card).toBeVisible();
    await expect(page.getByRole("status")).toHaveText(/(\d+) of \1 changes tested/);
    await page.getByRole("button", { name: /^Replay/ }).click();
    await page.getByRole("button", { name: /Skip to results/ }).click();
    await expect(page.getByRole("status")).toHaveText(/(\d+) of \1 changes tested/);
  }
});

test("a capsule opens its change, and Escape closes it", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("region", { name: "Mutants by hunk" }).getByRole("button", { name: /missed/ }).first().click();
  const detail = page.getByRole("region", { name: "The selected change" });
  await expect(detail).toContainText(/missed: the \d+ tests? that runs? this line still pass/);
  await page.keyboard.press("Escape");
  await expect(detail).toHaveCount(0);
});

test.describe("reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("nothing moves until the viewer acts", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: /^Replay/ })).toBeVisible();
    const before = await page.getByRole("status").textContent();
    await page.waitForTimeout(800);
    await expect(page.getByRole("status")).toHaveText(before ?? "");
  });
});
```

- [ ] **Step 2: Run the smoke test**

Run: `cd "C:/Users/manue/projects/chesterton/web" && npm run e2e`

Expected: 3 passed. Afterwards, confirm nothing is listening on port 4173.

- [ ] **Step 3: Update the README's Demo list**

In `README.md`, replace the three numbered items under `## Demo` with:

```markdown
1. **Wrong patch, caught:** an agent patch that passed SWE-bench and UTBoost proved wrong. Chesterton finds the change its tests miss and writes a regression test, verified by execution, that also holds on the correct fix.
2. **The correct fix:** the fix matplotlib's developers merged: the tests catch 5 of its 6 changes, and the one they miss is judged not worth a headline.
3. **Checking our own tests:** in our 13-patch study, half of Chesterton's first verified tests locked in the agent's bug; one rule cut that to 1 in 9, and this story shows the one left, and how the correct fix catches it.
```

- [ ] **Step 4: The layout check (scripted, not committed)**

Write a throwaway Playwright spec and config in `web/.tmp-layout/`. Playwright must resolve from `web/`, so the files live there. Delete the directory afterwards and never commit it.

The config serves `npm run preview` on port 4173, like `web/playwright.config.ts`, and uses `testDir: "."`. The spec must:

- **At 1600×900, for each of the three tabs:**
  - Check that these are fully inside the viewport (`boundingBox().y + height <= 900`):
    - the verdict paragraph (the first `p.text-\[20px\]` in the "What Chesterton found" region);
    - the "The change" group inside that region;
    - the first check item ("passes on the agent's fix") or, on the correct fix, the "No test needed" line;
    - the "Ask Nemotron why (live)" button.
  - Save a screenshot to `C:/Users/manue/projects/chesterton/.superpowers/sdd/2026-09-26-chesterton-answer-first/scratch/answer-<id>-1600.png`, where `<id>` is hero, gold or limit.
- **At 375×800, for the hero:** check that `document.documentElement.scrollWidth <= 375`, and save `answer-hero-375.png` in the same folder.

Run it with `npx playwright test --config .tmp-layout/<config>`, then run `rm -rf .tmp-layout test-results`. Report every check's result. If a check fails, fix the layout in `AnswerCard.tsx` or `App.tsx` (spacing and sizes only), re-run the checks, and report what changed.

- [ ] **Step 5: Run everything once more**

Run:

```bash
cd "C:/Users/manue/projects/chesterton" && .venv/Scripts/python.exe -m pytest -q
cd "C:/Users/manue/projects/chesterton/web" && npx vitest run && npm run build
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/manue/projects/chesterton" && git add web/e2e/smoke.spec.ts README.md
git commit -m "test: smoke-test the answer-first stories; describe the new story order" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

If Step 4 changed `AnswerCard.tsx` or `App.tsx`, name those files in the `git add` too.
