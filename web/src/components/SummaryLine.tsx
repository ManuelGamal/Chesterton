import type { Bundle, Verdict } from "../bundle";
import { summarise } from "../story";
import { VERDICTS } from "../verdicts";

interface Props { bundle: Bundle; highlight: Verdict | null; onHighlight: (v: Verdict | null) => void }

/** The run in one sentence; "caught" and "missed" highlight their capsules. */
export function SummaryLine({ bundle, highlight, onHighlight }: Props) {
  const s = summarise(bundle);
  const toggle = (v: Verdict, word: string, n: number) => (
    <button type="button" aria-pressed={highlight === v} onClick={() => onHighlight(highlight === v ? null : v)}
      className="cursor-pointer rounded px-1 font-semibold underline decoration-dotted underline-offset-4 aria-pressed:bg-muted">
      <span aria-hidden="true" style={{ color: VERDICTS[v].cssVar }}>{VERDICTS[v].glyph}</span>{" "}
      {word} {n}
    </button>
  );
  return (
    <p className="px-4 py-2 text-[15px] tabular">
      {s.total} small changes to the lines the patch changed → the tests {toggle("killed", "caught", s.caught)},{" "}
      {toggle("survived", "missed", s.missed)}
      {s.untested > 0 && <span className="text-muted-foreground"> · {s.untested} on lines no test runs</span>}
      {" → "}
      {s.matter === 0
        ? "Nemotron found none that matter"
        : `Nemotron picked the ${s.matter} that ${s.matter === 1 ? "matters" : "matter"}`}
    </p>
  );
}
