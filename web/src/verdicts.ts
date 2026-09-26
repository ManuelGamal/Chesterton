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
