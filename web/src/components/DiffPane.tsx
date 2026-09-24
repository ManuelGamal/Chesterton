import type { Bundle, DiffLine, Finding } from "../bundle";
import { lineKey, type ReplayState } from "../engine";
import { VERDICTS } from "../verdicts";

interface Props {
  lines: DiffLine[];
  bundle: Bundle;
  state: ReplayState;
  focus: Finding | null;
  onPick: (f: Finding) => void;
}

function gutter(line: DiffLine, bundle: Bundle, state: ReplayState) {
  if (line.kind !== "add" || line.new === null || line.file === null) return null;
  if (state.showTier0 && bundle.tier0.some((z) => z.file === line.file && z.line === line.new)) {
    return { verdict: VERDICTS.uncovered, label: `line ${line.new}: uncovered, no test runs this line`, tint: 18 };
  }
  const meter = state.meters[lineKey(line.file, line.new)];
  if (!meter) return null;
  if (meter.survived > 0) {
    return {
      verdict: VERDICTS.survived,
      label: `line ${line.new}: ${meter.survived} of ${meter.done} mutants survived`,
      tint: Math.min(28, 8 + 6 * meter.survived),
    };
  }
  return { verdict: VERDICTS.killed, label: `line ${line.new}: ${meter.done} mutants killed`, tint: 0 };
}

const BASE = { add: "var(--diff-add)", del: "var(--diff-del)", ctx: "transparent" } as const;

export function DiffPane({ lines, bundle, state, focus, onPick }: Props) {
  const headlineAt = (file: string | null, n: number | null) =>
    state.showTriage && n !== null
      ? bundle.triage.headline.find((f) => f.file === file && n >= f.start_line && n <= f.end_line)
      : undefined;

  return (
    <div className="font-mono text-[15px] leading-[1.6]" role="region" aria-label="The pull request's diff">
      {lines.map((line, i) => {
        if (line.kind === "file") {
          return <div key={i} className="border-y border-border bg-card px-3 py-1 text-muted-foreground">{line.file}</div>;
        }
        if (line.kind === "hunk") {
          return <div key={i} className="px-3 text-[13px] text-muted-foreground" dangerouslySetInnerHTML={{ __html: line.html }} />;
        }
        const g = gutter(line, bundle, state);
        const finding = headlineAt(line.file, line.new);
        const focused = focus !== null && finding?.id === focus.id;
        const base = BASE[line.kind];
        const background = g && g.tint > 0
          ? `color-mix(in srgb, ${g.verdict.cssVar} ${g.tint}%, ${base === "transparent" ? "var(--background)" : base})`
          : base;
        return (
          <div key={i} className={`flex ${focused ? "outline-2 outline-accent -outline-offset-2 outline" : ""}`} style={{ background }}>
            <span className="w-14 shrink-0 select-none pr-2 text-right text-muted-foreground tabular">{line.new ?? line.old}</span>
            <span className="w-6 shrink-0 select-none text-center" style={{ color: g?.verdict.cssVar }}>
              {g ? <span aria-label={g.label} title={g.label}>{g.verdict.glyph}</span> : null}
            </span>
            <span className="w-4 shrink-0 select-none text-muted-foreground">{line.kind === "add" ? "+" : line.kind === "del" ? "−" : " "}</span>
            {finding ? (
              <button type="button" className="cursor-pointer whitespace-pre text-left" onClick={() => onPick(finding)}
                      aria-label={`Open finding on line ${line.new}`}>
                <span dangerouslySetInnerHTML={{ __html: line.html }} />
              </button>
            ) : (
              <span className="whitespace-pre" dangerouslySetInnerHTML={{ __html: line.html }} />
            )}
          </div>
        );
      })}
    </div>
  );
}
