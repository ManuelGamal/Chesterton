# Chesterton Demo UI — Design

**Date:** 2026-09-24
**Status:** Approved in brainstorming, pending written-spec review
**Parent spec:** `2026-09-18-chesterton-design.md` (§12 UI, §18 video, §20 hosting)
**Serves:** the hackathon's **Design** criterion ("a complete, coherent product experience, not just a technical proof of concept") and the submission requirement of a working demo URL.

---

## 1. Purpose and success criteria

A judge opens one URL and, within 10 seconds, watches Chesterton take apart an agent-written patch that passed SWE-bench and was later proven wrong. Within a minute they can click the finding, see the exact line the suite fails to defend, see an execution-verified regression test, and ask Nemotron live why the finding matters.

**Success means:**
- The demo URL works, unattended, from submission (2026-10-30) through the close of judging (2026-12-15) at zero standing cost.
- Every number and verdict on screen comes from a real recorded run; nothing is mocked or pretends to be live.
- One interaction is genuinely live and makes a real Nemotron call on Nebius Token Factory.
- The screen reads correctly in grayscale and after 1080p video compression (parent §12).

## 2. Decisions

| Decision | Choice | Why |
|---|---|---|
| Hosting | Static site plus **one** serverless function on Vercel (Hobby, free) | No always-on backend to pay for or keep alive; the function covers the runtime-call requirement |
| Live element | "Ask Nemotron why": a live re-triage of one finding | Seconds, a fraction of a cent, no sandbox needed |
| Content | Three curated stories (§4) | Tight enough to polish in five weeks; tells the true story, limits included |
| Build | Vite + React + TypeScript; Python function | The function reuses the tool's own triage code, so live answers come from the real code path |
| Layout | Parent §12 layout: diff 60 % left, lanes 40 % right, focused finding and test beneath the diff | Chosen over a three-column layout: the code stays large and each finding sits next to its lines |
| Design system | Derived with the UI/UX Pro Max skill and reconciled with parent §12 (§7) | |

## 3. Architecture

```
seed + run + review JSON (existing, from the CLI and studies)
        │  scripts/export_demo.py          (Python, offline, no network)
        ▼
web/public/stories/<id>.json               (committed replay bundles)
        │  web/scripts/highlight.mjs       (Shiki, at build time)
        ▼
web/dist  ──(static, Vercel)──►  browser: React app, replay engine
                                     │  POST {story, finding}
                                     ▼
                                 api/why.py (Vercel Python function)
                                     │  build_triage_prompt → Nemotron Super → parse_classification
                                     ▼
                                 Nebius Token Factory
```

## 4. Stories

| # | Tab label | Source | What it shows |
|---|---|---|---|
| 1 | Wrong patch, caught | matplotlib-23314 `6d83e35469d2` (Agentless 1.5 + Claude 3.5 Sonnet); seed and run in `benchmark-v2/`, review in `review-study-2/` | UTBoost proved it wrong. Survivors name the defect (`set_visible` can ignore its argument); tier 0 flags the line that hides children; the regression test is verified and holds on the gold fix |
| 2 | The honest limit | matplotlib-23314 `92beef201cfd`; same sources | Its verified test encodes the agent's own bug (an axes hidden then shown stays hidden) and fails on the gold fix |
| 3 | The correct fix | matplotlib-23314 gold patch; `seeds/` and `runs/matplotlib-23314.json`, review to be produced | Well defended: few survivors, quiet review |

**Prerequisite:** story 3 has no review yet. The human runs, once:
`chesterton review seeds/matplotlib-23314.json runs/matplotlib-23314.json --out review-gold/matplotlib-23314.json`

## 5. The replay bundle

`scripts/export_demo.py` reads existing artifacts and writes one JSON bundle per story. It computes nothing new and calls no service.

Contents:
- **meta:** id, tab label, title, repository, task id, agent submission, UTBoost verdict (`wrong` or `correct`), the Chesterton commit that produced the run, recorded date.
- **patch:** the unified diff of changed **mutable source** files only. Test files and unexercised new files are dropped and counted (`dropped_files`).
- **lanes:** one per semantic hunk: id, file, line range.
- **mutants:** id, lane, line range, operator, verdict, number of tests run, measured duration, and the before/after code window used by the wipe. Never whole modules.
- **tier0:** changed lines no test executes. **ddmin:** undefended hunks.
- **triage:** headline, worth a look, dismissed. Each carries its evidence window, label, category, explanation and agreement.
- **regression:** path, source, verification status, both run tails, attempts, note, and for stories 1–2 the gold check (`passes_on_gold` or `fails_on_gold`).
- **counters:** sandbox ops, model calls per tier, wall time.
- **schedule:** for each mutant a start time, computed by placing the recorded durations greedily onto 24 parallel slots in execution order, the real run's concurrency. The UI labels the playback "replay · durations as measured".

Bundles stay under a few hundred KB. A TypeScript type in `web/src/bundle.ts` mirrors the schema; a Python test and a TypeScript test both check a checked-in example bundle, so the two sides cannot drift silently.

## 6. Screens and interaction

- **No landing page.** The site opens on story 1 with its replay playing (parent §18: product on screen within 10 seconds).
- **Top bar:** product name; three story tabs; the counters (e.g. "20 sandboxes · 9 Super · 1 Ultra · 124 s"); the replay badge; an "About · how it runs on Nebius" link to a short panel covering architecture, model ids, the benchmark's honest result, and the CLI.
- **Left 60 %: the diff.** Shiki-highlighted, JetBrains Mono at 15px minimum. Each changed line has a gutter glyph and a survival tint that fills as verdicts arrive.
- **Right 40 %: lanes.** One flat row per hunk. Mutant capsules leave their line's gutter, slide into their lane, and snap to a verdict (glyph plus word).
- **Beneath the diff: the focused finding.** Clicking a headline finding (or pressing ←/→ to step through them):
  1. wipes the line between the PR's code and the mutant's (the parent spec's money shot), captioned "every test still passes";
  2. shows the explanation, category and agreement;
  3. reveals the regression test with three checks: passes on the PR, fails on the mutant, and for stories 1–2 holds on (or fails on) the gold fix;
  4. offers **"Ask Nemotron why (live)"** (§9).
- **Story 2's test** carries a plain warning: "Verified, but it fails on the correct fix: it encodes the agent's bug." The warning is part of the story, not an error state.
- "Worth a look" and "dismissed" collapse under the headline with their counts.
- **Replay controls:** Pause/Play (first in tab order), a scrubber, "Skip to results", and a speed control (default ×8).

## 7. Design system

From the UI/UX Pro Max skill, reconciled with parent §12:

- **Style:** dark developer tool. No gradients, no glassmorphism, no glow.
- **Type:** IBM Plex Sans for UI; JetBrains Mono for code, 15px minimum in the diff. `font-variant-numeric: tabular-nums` on every number.
- **Colour tokens:** semantic CSS variables exposed to Tailwind v4 through `@theme inline`, following shadcn theming. Components never use raw hex.
  - Surfaces: background `#0F172A`, card `#1B2336`, muted `#272F42`, border `#334155`, foreground `#F8FAFC`, muted text `#94A3B8`.
  - Verdicts (Okabe-Ito): survived `#D55E00` ▲, killed `#009E73` ●, uncovered `#E69F00` ◆, pending slate ○. Always glyph plus word, bad news sorted first (parent §12's three redundant channels).
  - **One UI accent: sky blue `#56B4E9`**, for primary buttons and focus rings only. The skill's proposed green accent was rejected because green means "killed".
- **Icons:** Lucide (shadcn's set). No emoji.
- **Motion:** Motion (`motion.dev`). Only mutant capsules and gutter meters animate during the replay; counters update without bounce. Transform and opacity only. Every animation is interruptible.
- **Accessibility:**
  - Text contrast ≥ 4.5:1 and visible focus rings.
  - Full keyboard use: space for play/pause, ←/→ for findings.
  - One `role="status"`, `aria-atomic` line announces progress as a sentence at milestones ("12 of 19 mutants finished · 7 survived"), not per tick.
  - Autoplay counts as moving content: a visible pause, pausing on interaction, and **no autoplay under `prefers-reduced-motion`**, which shows the final state and replaces the wipe with a crossfade.

## 8. The replay engine

`stateAt(bundle, t)` is a pure function from a bundle and a time to the complete screen state: each mutant's phase (pending, running, done), its lane position, verdicts, gutter meters, counters, and which findings are revealed. Components only render that state. Play, pause, scrub and skip set `t`.

Timeline, in replay seconds at ×1:
1. `t = 0`: tier-0 lines light up (free in the real run, too).
2. Mutants run on the bundle's schedule and snap to their recorded verdicts.
3. ddmin's undefended hunks are outlined.
4. Triage headline findings rise; worth a look and dismissed collapse beneath.
5. The regression test appears for the first headline finding.

At the default ×8 the hero replay lasts about 15 seconds.

## 9. The live function: `api/why.py`

- **Request:** `POST {"story": "<id>", "finding": "<id>"}`. Any other field is ignored. An unknown id returns 404.
- **Evidence:** looked up server-side in the deployed bundle. The browser never supplies code or prompt text, so the endpoint cannot be used as a general LLM proxy.
- **Call:** `build_triage_prompt` → `REASONING_MODEL` with thinking on → `parse_classification`, all imported from `src/chesterton`. This is the same code path as the recorded triage.
- **Response:** label, category, confidence, explanation, elapsed seconds, model id. The UI shows it beside the recorded classification and says plainly when they differ.
- **Secrets:** `NEBIUS_API_KEY` lives in Vercel environment variables and never reaches the browser.
- **Limits:**
  - A global cap of 60 calls per hour, counted in Upstash Redis (free tier, via Vercel's integration).
  - The function **fails closed**: if the counter is unreachable or the cap is reached, it makes no model call and the UI shows the recorded answer with the reason.
  - A spend limit set in the Token Factory console is the final backstop.
  - Function time limit 55 s (Hobby maximum 60 s).
- **Failure display:** a live elapsed-time indicator while waiting ("Nemotron Super is thinking… 12 s"). Timeout, outage and truncation each give a one-line honest message plus the recorded answer. The UI never shows an endless spinner.

## 10. Repository layout and deployment

```
scripts/export_demo.py         story bundles (Python)
web/                           Vite + React + TypeScript app
web/public/stories/*.json      committed bundles
web/scripts/highlight.mjs      Shiki, run in the build
api/why.py                     the live function
vercel.json                    build command, output dir, function config, includeFiles for src/chesterton
requirements.txt               the function's dependencies (openai, upstash-redis)
```

- **Build:** `cd web && npm ci && npm run build`, which runs highlighting, then outputs `web/dist`.
- **Source control:** a public GitHub repository is required by the submission rules. The repo has no remote today; creating it and pushing is a one-time human step.
- **Deploy:** connect the GitHub repo to Vercel. Every push to the default branch redeploys. Two secrets: `NEBIUS_API_KEY` and the Upstash connection.
- **Longevity:** static files on Vercel do not sleep; the function has a 1–3 s cold start. The parent spec's late-November re-check also covers the Upstash database, the key and the Token Factory spend limit.

## 11. Testing

- **Python (existing pytest suite):**
  - The exporter, on fixtures: no whole modules; the schedule never exceeds 24 concurrent slots; every mutant keeps its recorded verdict; dropped files are counted; the example bundle matches.
  - The function handler, with the scripted fake model: id validation, extra body fields ignored, rate-limit logic against a fake counter, fail-closed when the counter is unreachable, and each failure message.
- **Web (Vitest):**
  - `stateAt`: nothing has a verdict at `t = 0`; every mutant has its recorded verdict at the end; counters are monotonic; the example bundle type-checks.
  - Components: an unverified test is never labelled verified; a gold-failing test always shows the warning.
- **Playwright smoke test on the built site:** the three tabs load, "Skip to results" shows the final state, and under reduced motion nothing autoplays.
- **Manual acceptance before the video:** the grayscale screenshot check (parent §12) and a keyboard-only pass.

## 12. Out of scope

- Live sandbox runs from the web. They remain a CLI feature, documented in the README.
- The parent spec's radial topology panel. The counters bar carries the platform story more legibly.
- User accounts, uploads, "paste any PR".
- Tier 1 (distinguishing inputs), already cut.
- Mobile layout beyond "readable and not broken" at 375px. The demo is a desktop and video experience.

## 13. Risks

| Risk | Mitigation |
|---|---|
| Super with thinking is slow (10–40 s) | Elapsed-time indicator; 55 s limit; recorded answer shown on timeout |
| Upstash archives an idle free database | Fail closed (no spend); late-November re-check |
| The live answer disagrees with the recorded one | Shown honestly, with a one-line note that triage confirms each headline 3 of 3 times for this reason |
| Stage One reads the static demo as "not working" | The live call is real; the About panel states plainly what is replayed and what is live; the README documents the CLI |
| Gold review not yet produced | Named prerequisite (§4) |

## 14. Effort

Exporter and bundles: 2 days. Web app: 6–8 days. Live function: 1 day. Deployment: 1 day. This leaves about two weeks before 2026-10-30 for polish and the video.
