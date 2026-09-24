import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import type { Finding, Regression } from "../bundle";
import { lineRange } from "../format";
import { VERDICTS } from "../verdicts";
import { AskWhy } from "./AskWhy";

export const GOLD_WARNING = "Verified, but it fails on the correct fix: it encodes the agent's bug.";

/** How long the PR's code shows before the wipe reveals the mutant. */
export const WIPE_DELAY_MS = 600;
/** Lines of context kept on either side of the mutated range. */
const CONTEXT = 3;

type Side = "pr" | "mutant";

interface CodeLine { n: number | null; code: string }

/** Splits an exporter window (" 1157 |     code" per line) and keeps CONTEXT lines around the range. */
function windowLines(text: string, start: number, end: number): CodeLine[] {
  let last: number | null = null;
  const parsed = text.split("\n").map((raw): CodeLine => {
    const m = /^\s*(\d+) \|/.exec(raw);
    if (!m) return { n: last, code: raw };
    last = Number(m[1]);
    return { n: last, code: raw.slice(m[0].length).replace(/^ /, "") };
  });
  return parsed.filter((l) => l.n === null || (l.n >= start - CONTEXT && l.n <= end + CONTEXT));
}

/** The focused finding: its header, explanation, agreement and the PR↔mutant wipe. */
export function FindingPanel({ finding, reduced }: { finding: Finding; reduced: boolean }) {
  const first: Side = reduced ? "mutant" : "pr";
  const [side, setSide] = useState<Side>(first);
  // Start over on the PR's code whenever another finding opens (reset during render, no flash).
  const [shownId, setShownId] = useState(finding.id);
  if (shownId !== finding.id) {
    setShownId(finding.id);
    setSide(first);
  }

  const timer = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (reduced) return;
    timer.current = window.setTimeout(() => setSide("mutant"), WIPE_DELAY_MS);
    return () => window.clearTimeout(timer.current);
  }, [finding.id, reduced]);

  const pickSide = (s: Side) => {
    window.clearTimeout(timer.current);
    setSide(s);
  };

  const v = VERDICTS.survived;
  const lines = windowLines(side === "pr" ? finding.original : finding.mutated, finding.start_line, finding.end_line);
  const changedTint = "color-mix(in srgb, var(--verdict-survived) 18%, var(--background))";
  return (
    <section className="bg-card p-4" aria-label="Focused finding">
      <h2 className="text-[15px] font-semibold">
        <span aria-hidden="true" style={{ color: v.cssVar }}>{v.glyph}</span> {v.word.toUpperCase()}
        <span className="text-muted-foreground"> · {lineRange(finding.start_line, finding.end_line)}{finding.category ? ` · ${finding.category}` : ""}</span>
        {finding.agreement !== null && (
          <span className="text-[13px] font-normal text-muted-foreground"> · confirmed {finding.agreement} of 3</span>
        )}
      </h2>
      <p className="mt-1 text-[15px]">{finding.explanation}</p>

      <div className="mt-2">
        <div className="flex flex-wrap items-baseline gap-x-2 text-[13px]">
          <div role="tablist" aria-label="Code shown" className="flex gap-2">
            {(["pr", "mutant"] as const).map((s) => (
              <button key={s} type="button" role="tab" aria-selected={side === s} onClick={() => pickSide(s)}
                className={`cursor-pointer rounded px-2 py-0.5 ${side === s ? "bg-muted text-foreground" : "text-muted-foreground"}`}>
                {s === "pr" ? "The PR's code" : "The mutant"}
              </button>
            ))}
          </div>
          <p className="ml-auto text-muted-foreground">Every selected test still passes on the mutant.</p>
        </div>
        <div className="relative mt-1 overflow-x-auto rounded border border-border bg-background">
          <AnimatePresence mode="wait">
            <motion.pre key={`${finding.id}:${side}`} className="py-1 font-mono text-[15px] leading-[1.5]"
              initial={reduced ? { opacity: 0 } : { clipPath: "inset(0 100% 0 0)" }}
              animate={reduced ? { opacity: 1 } : { clipPath: "inset(0 0% 0 0)" }}
              exit={{ opacity: 0 }} transition={{ duration: reduced ? 0.15 : 0.45, ease: "easeOut" }}>
              {lines.map((l, i) => {
                const changed = l.n !== null && l.n >= finding.start_line && l.n <= finding.end_line;
                return (
                  <div key={i} data-line={l.n ?? undefined} data-changed={changed}
                    className="flex whitespace-pre pr-3" style={changed ? { background: changedTint } : undefined}>
                    <span aria-hidden="true" className="w-6 shrink-0 select-none text-center" style={{ color: v.cssVar }}>
                      {changed ? v.glyph : ""}
                    </span>
                    <span className="w-12 shrink-0 select-none pr-3 text-right text-muted-foreground tabular">{l.n}</span>
                    <span>{l.code}</span>
                  </div>
                );
              })}
            </motion.pre>
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}

interface SideProps {
  storyId: string;
  finding: Finding;
  regression: Regression | null;
  showRegression: boolean;
}

/** The focused finding's regression test (when it has one) and the live "why" call. */
export function FindingSide({ storyId, finding, regression, showRegression }: SideProps) {
  const test = showRegression && regression && regression.finding_id === finding.id ? regression : null;
  return (
    <>
      {test && <RegressionTest test={test} />}
      <AskWhy key={`${storyId}:${finding.id}`} storyId={storyId} finding={finding} />
    </>
  );
}

function Check({ glyph, colour, children }: { glyph: string; colour: string; children: string }) {
  return (
    <li className="flex items-baseline gap-2">
      <span aria-hidden="true" style={{ color: colour }}>{glyph}</span>
      <span>{children}</span>
    </li>
  );
}

export function RegressionTest({ test }: { test: Regression }) {
  if (!test.verified) {
    return (
      <div className="mt-3">
        <p className="text-[14px] text-muted-foreground">Not verified ({test.status ?? test.note ?? "no test written"}), so it is not offered as a test.</p>
        <p className="mt-1 text-[12px] text-muted-foreground">{test.path}</p>
      </div>
    );
  }
  const killed = VERDICTS.killed;
  const code = "mt-1 overflow-x-auto rounded border border-border bg-background p-2 font-mono text-[15px] leading-[1.5]";
  return (
    <div className="mt-3">
      <h3 className="text-[15px] font-semibold">Verified test</h3>
      <ul className="mt-1 space-y-0.5 text-[14px]">
        <Check glyph={killed.glyph} colour={killed.cssVar}>passes on the PR</Check>
        <Check glyph={killed.glyph} colour={killed.cssVar}>fails on the mutant</Check>
        {test.gold === "passes_on_gold" && <Check glyph={killed.glyph} colour={killed.cssVar}>holds on the correct fix</Check>}
      </ul>
      {test.gold === "fails_on_gold" && (
        <p className="mt-2 rounded border p-2 text-[14px]" style={{ borderColor: "var(--verdict-uncovered)" }}>
          <span aria-hidden="true" style={{ color: "var(--verdict-uncovered)" }}>◆</span> <span>{GOLD_WARNING}</span>
        </p>
      )}
      {test.source && (
        <details className="mt-2 text-[14px]">
          <summary className="cursor-pointer text-muted-foreground">Test source · {test.path}</summary>
          <pre className={code}>{test.source}</pre>
        </details>
      )}
      {(test.patch_tail || test.mutant_tail) && (
        <details className="mt-1 text-[14px]">
          <summary className="cursor-pointer text-muted-foreground">Run output</summary>
          {test.patch_tail && (
            <>
              <p className="mt-1 text-[13px] text-muted-foreground">on the PR</p>
              <pre className={code}>{test.patch_tail}</pre>
            </>
          )}
          {test.mutant_tail && (
            <>
              <p className="mt-1 text-[13px] text-muted-foreground">on the mutant</p>
              <pre className={code}>{test.mutant_tail}</pre>
            </>
          )}
        </details>
      )}
    </div>
  );
}
