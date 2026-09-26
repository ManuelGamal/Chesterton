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
