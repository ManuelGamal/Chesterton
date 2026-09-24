import type { Verdict } from "./bundle";

export const VERDICTS: Record<Verdict | "pending", { glyph: string; word: string; cssVar: string }> = {
  survived: { glyph: "▲", word: "survived", cssVar: "var(--verdict-survived)" },
  uncovered: { glyph: "◆", word: "uncovered", cssVar: "var(--verdict-uncovered)" },
  error: { glyph: "✕", word: "error", cssVar: "var(--verdict-error)" },
  killed: { glyph: "●", word: "killed", cssVar: "var(--verdict-killed)" },
  pending: { glyph: "○", word: "pending", cssVar: "var(--verdict-pending)" },
};

const RANK: Record<Verdict, number> = { survived: 0, uncovered: 1, error: 2, killed: 3 };

export function verdictRank(v: Verdict): number {
  return RANK[v];
}
