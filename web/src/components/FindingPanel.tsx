import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import type { Finding, Regression } from "../bundle";
import { VERDICTS } from "../verdicts";
import { AskWhy } from "./AskWhy";

export const GOLD_WARNING = "Verified, but it fails on the correct fix: it encodes the agent's bug.";

interface Props {
  storyId: string;
  finding: Finding;
  regression: Regression | null;
  showRegression: boolean;
  reduced: boolean;
}

export function FindingPanel({ storyId, finding, regression, showRegression, reduced }: Props) {
  const [side, setSide] = useState<"pr" | "mutant">("mutant");
  const v = VERDICTS.survived;
  const test = showRegression && regression && regression.finding_id === finding.id ? regression : null;
  return (
    <section className="border-t border-border bg-card p-4" aria-label="Focused finding">
      <h2 className="text-[15px] font-semibold">
        <span style={{ color: v.cssVar }}><span aria-hidden="true">{v.glyph}</span> {v.word.toUpperCase()}</span>
        <span className="text-muted-foreground"> · lines {finding.start_line}–{finding.end_line}{finding.category ? ` · ${finding.category}` : ""}</span>
      </h2>
      <p className="mt-1 text-[15px]">{finding.explanation}</p>
      {finding.agreement !== null && <p className="text-[13px] text-muted-foreground">confirmed {finding.agreement} of 3</p>}

      <div className="mt-3">
        <div role="tablist" aria-label="Code shown" className="flex gap-2 text-[13px]">
          {(["pr", "mutant"] as const).map((s) => (
            <button key={s} type="button" role="tab" aria-selected={side === s} onClick={() => setSide(s)}
              className={`cursor-pointer rounded px-2 py-0.5 ${side === s ? "bg-muted text-foreground" : "text-muted-foreground"}`}>
              {s === "pr" ? "The PR's code" : "The mutant"}
            </button>
          ))}
        </div>
        <div className="relative mt-1 overflow-hidden rounded border border-border bg-background">
          <AnimatePresence mode="wait" initial={false}>
            <motion.pre key={side} className="whitespace-pre p-2 font-mono text-[15px] leading-[1.6]"
              initial={reduced ? { opacity: 0 } : { clipPath: "inset(0 100% 0 0)" }}
              animate={reduced ? { opacity: 1 } : { clipPath: "inset(0 0% 0 0)" }}
              exit={{ opacity: 0 }} transition={{ duration: reduced ? 0.15 : 0.45, ease: "easeOut" }}>
              {side === "pr" ? finding.original : finding.mutated}
            </motion.pre>
          </AnimatePresence>
        </div>
        <p className="mt-1 text-[13px] text-muted-foreground">Every selected test still passes on the mutant.</p>
      </div>

      {test && <RegressionTest test={test} />}
      <AskWhy key={`${storyId}:${finding.id}`} storyId={storyId} finding={finding} />
    </section>
  );
}

function RegressionTest({ test }: { test: Regression }) {
  return (
    <div className="mt-4">
      {test.verified ? (
        <p className="text-[14px]">
          <span aria-hidden="true" style={{ color: "var(--verdict-killed)" }}>●</span>{" "}
          <span>Verified: passes on the PR, fails on the mutant{test.gold === "passes_on_gold" ? ", holds on the correct fix" : ""}</span>
        </p>
      ) : (
        <p className="text-[14px] text-muted-foreground">Not verified ({test.status ?? test.note ?? "no test written"}), so it is not offered as a test.</p>
      )}
      {test.verified && test.gold === "fails_on_gold" && (
        <p className="mt-2 rounded border p-2 text-[14px]" style={{ borderColor: "var(--verdict-uncovered)" }}>
          <span aria-hidden="true" style={{ color: "var(--verdict-uncovered)" }}>◆</span> <span>{GOLD_WARNING}</span>
        </p>
      )}
      {test.verified && test.source && (
        <pre className="mt-2 max-h-72 overflow-auto rounded border border-border bg-background p-2 font-mono text-[13px]">{test.source}</pre>
      )}
      <p className="mt-1 text-[12px] text-muted-foreground">{test.path}</p>
    </div>
  );
}
