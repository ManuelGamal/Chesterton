import { AnimatePresence, motion } from "motion/react";
import type { Bundle } from "../bundle";
import type { ReplayState } from "../engine";
import { span } from "../format";
import { VERDICTS, verdictRank } from "../verdicts";

export function Lanes({ bundle, state, reduced }: { bundle: Bundle; state: ReplayState; reduced: boolean }) {
  const byId = new Map(bundle.mutants.map((m) => [m.id, m]));
  const base = (f: string) => f.split("/").pop();
  const undefendedCount = bundle.ddmin.undefended.length;
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
                  // Dark text on the slate pending fill is too low-contrast: use the light foreground there.
                  const done = s.phase === "done";
                  const v = done ? VERDICTS[m.verdict] : VERDICTS.pending;
                  return (
                    <motion.span key={s.id} layout={!reduced}
                      initial={reduced ? false : { x: -24, opacity: 0 }} animate={{ x: 0, opacity: 1 }}
                      transition={{ type: "spring", stiffness: 380, damping: 30 }}
                      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-semibold ${done ? "text-background" : "text-foreground"}`}
                      style={{ background: v.cssVar }}>
                      <span aria-hidden="true">{v.glyph}</span>{v.word}
                    </motion.span>
                  );
                })}
              </AnimatePresence>
            </div>
          </div>
        );
      })}
      {state.showDdmin && (
        <p className="px-3 py-2 text-[13px] text-muted-foreground">
          Hunk removal (ddmin), {bundle.ddmin.probes} probe{bundle.ddmin.probes === 1 ? "" : "s"}:{" "}
          {undefendedCount === 0 ? "every hunk is needed by the tests" : `${undefendedCount} hunk${undefendedCount > 1 ? "s" : ""} the tests would not miss`}
        </p>
      )}
    </div>
  );
}
