import type { ReactNode } from "react";
import type { Bundle, Finding, Regression } from "../bundle";
import { lineRange } from "../format";
import { topFinding, windowDiff, type Bucket } from "../story";
import { VERDICTS } from "../verdicts";
import { AskWhy } from "./AskWhy";
import { CodeDiff } from "./CodeDiff";

export const GOLD_WARNING = "Verified, but it fails on the correct fix: it encodes the agent's bug.";

const heading = "text-[13px] font-semibold uppercase tracking-wide text-muted-foreground";

/** A hand-written verdict may set code in `backticks`. */
function withCode(text: string): ReactNode[] {
  return text.split("`").map((part, i) => (i % 2 === 1 ? <code key={i} className="font-mono">{part}</code> : part));
}

function Check({ glyph, colour, children }: { glyph: string; colour: string; children: ReactNode }) {
  return (
    <li className="flex items-baseline gap-2">
      <span aria-hidden="true" style={{ color: colour }}>{glyph}</span>
      <span>{children}</span>
    </li>
  );
}

function MissingTest({ test, bucket }: { test: Regression | null; bucket: Bucket }) {
  if (test === null) {
    return (
      <p className="mt-2 text-[15px]">
        {bucket === "headline" ? "No verified test was written for this change." : "No test needed: nothing important slipped past the tests."}
      </p>
    );
  }
  if (!test.verified) {
    return (
      <p className="mt-2 text-[14px] text-muted-foreground">
        Not verified ({test.status ?? test.note ?? "no test written"}), so it is not offered as a test.
      </p>
    );
  }
  const caught = VERDICTS.killed;
  const code = "mt-1 overflow-x-auto rounded border border-border bg-background p-2 font-mono text-[15px] leading-[1.5]";
  return (
    <>
      <p className="mt-1 text-[13px] text-muted-foreground">Verified test, written by Nemotron Ultra · {test.path}</p>
      <ul className="mt-2 space-y-1 text-[15px]">
        <Check glyph={caught.glyph} colour={caught.cssVar}>passes on the agent's fix</Check>
        <Check glyph={caught.glyph} colour={caught.cssVar}>fails on the change</Check>
        {test.gold === "passes_on_gold" && <Check glyph={caught.glyph} colour={caught.cssVar}>holds on the correct fix</Check>}
      </ul>
      {test.gold === "fails_on_gold" && (
        <p className="mt-2 rounded border p-2 text-[14px]" style={{ borderColor: "var(--verdict-uncovered)" }}>
          <span aria-hidden="true" style={{ color: "var(--verdict-uncovered)" }}>◆</span> <span>{GOLD_WARNING}</span>
        </p>
      )}
      {test.source && (
        <details className="mt-2 text-[14px]">
          <summary className="cursor-pointer text-muted-foreground">Show test</summary>
          <pre className={code}>{test.source}</pre>
        </details>
      )}
      {(test.patch_tail || test.mutant_tail) && (
        <details className="mt-1 text-[14px]">
          <summary className="cursor-pointer text-muted-foreground">Run output</summary>
          {test.patch_tail && <><p className="mt-1 text-[13px] text-muted-foreground">on the agent's fix</p><pre className={code}>{test.patch_tail}</pre></>}
          {test.mutant_tail && <><p className="mt-1 text-[13px] text-muted-foreground">on the change</p><pre className={code}>{test.mutant_tail}</pre></>}
        </details>
      )}
    </>
  );
}

/** The top of a story: its verdict, the change the tests miss, and the missing test. */
export function AnswerCard({ bundle, reduced }: { bundle: Bundle; reduced: boolean }) {
  const m = bundle.meta;
  const top = topFinding(bundle);
  const missed = VERDICTS.survived;
  const finding: Finding | undefined = top?.finding;
  const test = finding && bundle.regression?.finding_id === finding.id ? bundle.regression : null;
  return (
    <section aria-label="What Chesterton found" className="border-b border-border bg-card px-4 py-4 md:px-6">
      <p className="min-w-0 text-[13px] text-muted-foreground">
        {m.repo} · <span title={m.submission}>patch by {m.system}</span> · {m.title}
      </p>
      <p className="mt-2 max-w-5xl text-[20px] font-semibold leading-snug">{withCode(m.verdict)}</p>
      {top && finding && (
        <div className="mt-4 grid gap-6 lg:grid-cols-2">
          <div className="min-w-0">
            <h2 className={`${heading} flex flex-wrap items-baseline gap-x-3`}>
              <span>The change the tests miss</span>
              <span className="normal-case tracking-normal">
                <span aria-hidden="true" style={{ color: missed.cssVar }}>{missed.glyph}</span>{" "}
                <span className="text-foreground">{top.bucket === "headline" ? "tests still pass" : "missed, judged worth a look"}</span>
              </span>
            </h2>
            <p className="mt-1 text-[13px] text-muted-foreground">{finding.file} · {lineRange(finding.start_line, finding.end_line)}</p>
            <div className="mt-1">
              <CodeDiff key={finding.id} rows={windowDiff(finding.original, finding.mutated)} reduced={reduced} label="The change" />
            </div>
            <p className="mt-2 text-[15px]"><span className="text-muted-foreground">Nemotron: </span>{finding.explanation}</p>
          </div>
          <div className="min-w-0">
            <h2 className={heading}>The missing test</h2>
            <MissingTest test={test} bucket={top.bucket} />
            <AskWhy key={`${m.id}:${finding.id}`} storyId={m.id} finding={finding} />
          </div>
        </div>
      )}
    </section>
  );
}
