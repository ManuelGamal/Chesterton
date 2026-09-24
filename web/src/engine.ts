import type { Bundle } from "./bundle";

export type Phase = "generate" | "mutants" | "ddmin" | "triage" | "regression" | "done";

export interface MutantState {
  id: string;
  lane: string;
  phase: "pending" | "running" | "done";
  progress: number;
}

export interface ReplayState {
  t: number;
  phase: Phase;
  mutants: MutantState[];
  finished: number;
  survived: number;
  killed: number;
  uncovered: number;
  errors: number;
  meters: Record<string, { survived: number; done: number }>;
  showTier0: boolean;
  showDdmin: boolean;
  showTriage: boolean;
  showRegression: boolean;
}

export const TARGET_SECONDS = 15;

/** The replay speeds the menu offers. defaultSpeed only ever returns one of these. */
export const SPEEDS = [1, 2, 4, 8, 16, 32] as const;

/** The offered speed nearest to fitting the replay into TARGET_SECONDS (lower on a tie). */
export function defaultSpeed(total: number): number {
  const ideal = total / TARGET_SECONDS;
  let best: number = SPEEDS[0];
  for (const s of SPEEDS) {
    if (Math.abs(s - ideal) < Math.abs(best - ideal)) best = s;
  }
  return best;
}

export function lineKey(file: string, line: number): string {
  return `${file}:${line}`;
}

/** The whole screen state at replay time t. Pure: the UI only renders this. */
export function stateAt(b: Bundle, tIn: number): ReplayState {
  const tl = b.timeline;
  const t = Math.min(Math.max(tIn, 0), tl.total_s);
  const mutantsFrom = tl.generate_s;
  const ddminFrom = mutantsFrom + tl.mutants_end_s;
  const triageFrom = ddminFrom + tl.ddmin_s;
  const regressionFrom = triageFrom + tl.triage_s;
  const local = t - mutantsFrom;

  const counts = { survived: 0, killed: 0, uncovered: 0, error: 0 };
  const meters: ReplayState["meters"] = {};
  const mutants = b.mutants.map((m): MutantState => {
    const end = m.start_s + m.duration_s;
    if (local < m.start_s) return { id: m.id, lane: m.lane, phase: "pending", progress: 0 };
    if (local < end) {
      return { id: m.id, lane: m.lane, phase: "running", progress: (local - m.start_s) / m.duration_s };
    }
    counts[m.verdict] += 1;
    for (let line = m.start_line; line <= m.end_line; line++) {
      const key = lineKey(m.file, line);
      const meter = (meters[key] ??= { survived: 0, done: 0 });
      meter.done += 1;
      if (m.verdict === "survived") meter.survived += 1;
    }
    return { id: m.id, lane: m.lane, phase: "done", progress: 1 };
  });

  const phase: Phase =
    t >= tl.total_s ? "done"
    : t >= regressionFrom ? "regression"
    : t >= triageFrom ? "triage"
    : t >= ddminFrom ? "ddmin"
    : t >= mutantsFrom ? "mutants"
    : "generate";

  return {
    t, phase, mutants,
    finished: counts.survived + counts.killed + counts.uncovered + counts.error,
    survived: counts.survived, killed: counts.killed, uncovered: counts.uncovered, errors: counts.error,
    meters,
    showTier0: true,
    showDdmin: t >= ddminFrom,
    showTriage: t >= triageFrom,
    showRegression: t >= regressionFrom,
  };
}
