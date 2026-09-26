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
