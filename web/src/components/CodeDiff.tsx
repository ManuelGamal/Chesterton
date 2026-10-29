import { motion } from "motion/react";
import type { DiffRow } from "../story";

const BACKGROUND = { del: "var(--diff-del)", add: "var(--diff-add)", ctx: undefined } as const;
const SIGN = { del: "−", add: "+", ctx: " " } as const;
const SPOKEN = { del: "removed: ", add: "added: ", ctx: "" } as const;

/** A mutation as a diff. Added lines wipe in (a crossfade under reduced motion).
 *  `missed`: the tests let this change through, so its added line is marked in the missed colour. */
export function CodeDiff({ rows, reduced, label, missed = false }: { rows: DiffRow[]; reduced: boolean; label: string; missed?: boolean }) {
  return (
    <div role="group" aria-label={label}
      className="overflow-x-auto rounded-md border border-border bg-background py-1 font-mono text-[15px] leading-[1.6]">
      {rows.map((r, i) => {
        const flagged = missed && r.kind === "add";
        const line = (
          <div data-kind={r.kind} className="flex whitespace-pre pr-3"
            style={{ background: flagged ? "var(--diff-missed)" : BACKGROUND[r.kind] }}>
            <span className="w-14 shrink-0 select-none pr-2 text-right text-muted-foreground tabular">{r.n}</span>
            <span aria-hidden="true" className="w-5 shrink-0 select-none text-muted-foreground">{SIGN[r.kind]}</span>
            <span style={flagged ? { color: "var(--verdict-survived)" } : undefined}><span className="sr-only">{SPOKEN[r.kind]}</span>{r.code}</span>
            {flagged && <span className="ml-4 select-none font-sans text-[13px]" style={{ color: "var(--verdict-survived)" }}>← no test notices</span>}
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
