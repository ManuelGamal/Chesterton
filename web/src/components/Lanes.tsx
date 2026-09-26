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
                      aria-pressed={selected === s.id} data-dimmed={dimmed} data-capsule={s.id} title={v.term}
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
