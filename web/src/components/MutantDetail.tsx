import { ChevronLeft, ChevronRight, X } from "lucide-react";
import type { Bundle, Mutant } from "../bundle";
import { span } from "../format";
import { BUCKET_WORDS, isUndefended, judgmentFor, windowDiff } from "../story";
import { VERDICTS } from "../verdicts";
import { CodeDiff } from "./CodeDiff";

function verdictSentence(m: Mutant): string {
  switch (m.verdict) {
    case "survived":
      return m.tests === 1
        ? "missed: the 1 test that runs this line still passes"
        : `missed: the ${m.tests} tests that run this line still pass`;
    case "killed":
      return "caught: a test failed";
    case "uncovered":
      return "untested line: no test runs this line";
    case "error":
      return "error: the run failed";
  }
}

interface Props {
  bundle: Bundle;
  mutant: Mutant;
  reduced: boolean;
  onClose: () => void;
  onStep: (dir: 1 | -1) => void;
}

/** One mutant, readable: what it changed, what the tests did, what Nemotron made of it. */
export function MutantDetail({ bundle, mutant, reduced, onClose, onStep }: Props) {
  const v = VERDICTS[mutant.verdict];
  const judged = judgmentFor(bundle, mutant.id);
  const icon = "inline-flex cursor-pointer items-center rounded p-1 text-muted-foreground hover:bg-muted";
  return (
    <section aria-label="The selected change" className="border-t border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <h3 className="font-mono text-[14px]">{mutant.file.split("/").pop()}:{span(mutant.start_line, mutant.end_line)}</h3>
        <span className="text-[13px] text-muted-foreground">{mutant.operator}</span>
        <span className="ml-auto flex gap-1">
          <button type="button" className={icon} aria-label="Previous change" onClick={() => onStep(-1)}><ChevronLeft size={18} aria-hidden="true" /></button>
          <button type="button" className={icon} aria-label="Next change" onClick={() => onStep(1)}><ChevronRight size={18} aria-hidden="true" /></button>
          <button type="button" className={icon} aria-label="Close" onClick={onClose}><X size={18} aria-hidden="true" /></button>
        </span>
      </div>
      <div className="mt-2">
        <CodeDiff key={mutant.id} rows={windowDiff(mutant.before, mutant.after)} reduced={reduced} label="The selected change's code" />
      </div>
      <p className="mt-2 text-[15px]" title={v.term}>
        <span aria-hidden="true" style={{ color: v.cssVar }}>{v.glyph}</span> {verdictSentence(mutant)}
      </p>
      {judged && (
        <p className="mt-1 text-[15px]">
          <span className="text-muted-foreground">Nemotron: </span>
          <b>{BUCKET_WORDS[judged.bucket]}</b>{judged.finding.category ? ` · ${judged.finding.category}` : ""}. {judged.finding.explanation}
        </p>
      )}
      {isUndefended(bundle, mutant) && (
        <p className="mt-1 text-[14px] text-muted-foreground">Removing this whole hunk still passes the tests.</p>
      )}
    </section>
  );
}
