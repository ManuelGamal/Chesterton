export type Verdict = "killed" | "survived" | "uncovered" | "error";

export interface Lane { id: string; file: string; start_line: number; end_line: number }

export interface Mutant {
  id: string; lane: string; file: string; start_line: number; end_line: number;
  operator: string; verdict: Verdict; tests: number; start_s: number; duration_s: number;
  before: string; after: string;
}

export interface Finding {
  id: string; file: string; start_line: number; end_line: number; operator: string;
  rationale: string; original: string; mutated: string; diff: string; tests: string[];
  label: string; category: string | null; confident: boolean; explanation: string;
  agreement: number | null;
}

export interface Regression {
  finding_id: string | null; path: string; source: string | null; status: string | null;
  detail: string | null; patch_tail: string; mutant_tail: string; attempts: number;
  note: string | null; verified: boolean;
  gold: "passes_on_gold" | "fails_on_gold" | "error" | null;
}

export interface Bundle {
  meta: {
    id: string; tab: string; title: string; system: string; pr_title: string; repo: string; task: string;
    submission: string; utboost: "wrong" | "correct"; chesterton_commit: string; recorded: string;
  };
  patch: { diff: string; dropped_files: string[] };
  lanes: Lane[];
  mutants: Mutant[];
  tier0: { file: string; line: number }[];
  ddmin: { undefended: { file: string; start_line: number; end_line: number }[]; probes: number };
  triage: { headline: Finding[]; worth_a_look: Finding[]; dismissed: Finding[]; model_calls: number };
  regression: Regression | null;
  counters: {
    sandbox_ops: number; lightning_calls: number; super_calls: number;
    ultra_calls: number; run_wall_s: number;
  };
  timeline: {
    generate_s: number; mutants_end_s: number; ddmin_s: number; triage_s: number;
    regression_s: number; total_s: number;
  };
}

export interface DiffLine {
  kind: "file" | "hunk" | "add" | "del" | "ctx";
  file: string | null; old: number | null; new: number | null; html: string;
}

export interface StoryIndex { stories: { id: string; tab: string }[] }

const SECTIONS = ["meta", "patch", "lanes", "mutants", "tier0", "ddmin", "triage", "counters", "timeline"] as const;

const LANE_KEYS = ["id", "file", "start_line", "end_line"] as const;

const MUTANT_KEYS = [
  "id", "lane", "file", "start_line", "end_line",
  "operator", "verdict", "tests", "start_s", "duration_s",
  "before", "after",
] as const;

const FINDING_KEYS = [
  "id", "file", "start_line", "end_line", "operator",
  "rationale", "original", "mutated", "diff", "tests",
  "label", "category", "confident", "explanation", "agreement",
] as const;

const REGRESSION_KEYS = [
  "finding_id", "path", "source", "status",
  "detail", "patch_tail", "mutant_tail", "attempts",
  "note", "verified", "gold",
] as const;

const META_KEYS = [
  "id", "tab", "title", "system", "pr_title", "repo", "task",
  "submission", "utboost", "chesterton_commit", "recorded",
] as const;

const TIMELINE_KEYS = [
  "generate_s", "mutants_end_s", "ddmin_s", "triage_s", "regression_s", "total_s",
] as const;

const COUNTER_KEYS = [
  "sandbox_ops", "lightning_calls", "super_calls", "ultra_calls", "run_wall_s",
] as const;

/** Throws if `obj` is missing any of `keys`. Uses `in` so a present-but-null field passes. */
function requireKeys(obj: unknown, keys: readonly string[], where: string): void {
  if (typeof obj !== "object" || obj === null) throw new Error(`bundle ${where} is not an object`);
  const o = obj as Record<string, unknown>;
  for (const key of keys) {
    if (!(key in o)) throw new Error(`bundle ${where} is missing ${key}`);
  }
}

/** Guards the Python exporter and this type against drifting apart. */
export function assertBundle(x: unknown): asserts x is Bundle {
  if (typeof x !== "object" || x === null) throw new Error("bundle is not an object");
  const b = x as Record<string, unknown>;
  for (const key of SECTIONS) {
    if (b[key] === undefined || b[key] === null) throw new Error(`bundle is missing ${key}`);
  }
  if (!("regression" in b)) throw new Error("bundle is missing regression");
  if (typeof (b.timeline as Record<string, unknown>).total_s !== "number") {
    throw new Error("bundle timeline has no total_s");
  }
  if (!Array.isArray(b.mutants)) throw new Error("bundle mutants is not a list");

  requireKeys(b.meta, META_KEYS, "meta");
  requireKeys(b.timeline, TIMELINE_KEYS, "timeline");
  requireKeys(b.counters, COUNTER_KEYS, "counters");

  const lanes = b.lanes as unknown[];
  lanes.forEach((lane, i) => requireKeys(lane, LANE_KEYS, `lanes[${i}]`));

  const mutants = b.mutants as unknown[];
  mutants.forEach((mutant, i) => requireKeys(mutant, MUTANT_KEYS, `mutants[${i}]`));

  const triage = b.triage as Record<string, unknown>;
  for (const bucket of ["headline", "worth_a_look", "dismissed"] as const) {
    const findings = triage[bucket] as unknown[];
    findings.forEach((finding, i) => requireKeys(finding, FINDING_KEYS, `triage.${bucket}[${i}]`));
  }

  if (b.regression !== null) {
    requireKeys(b.regression, REGRESSION_KEYS, "regression");
  }
}
