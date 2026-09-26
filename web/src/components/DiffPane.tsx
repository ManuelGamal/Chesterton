import { useEffect, useRef } from "react";
import type { Bundle, DiffLine, Mutant } from "../bundle";
import { lineKey, type ReplayState } from "../engine";
import { mutantAtLine } from "../story";
import { VERDICTS } from "../verdicts";

interface Props {
  lines: DiffLine[];
  bundle: Bundle;
  state: ReplayState;
  selected: Mutant | null;
  onSelectLine: (file: string, line: number) => void;
  /** Reduced motion: jump to the selected change instead of scrolling smoothly. */
  reduced?: boolean;
}

function gutter(line: DiffLine, bundle: Bundle, state: ReplayState) {
  if (line.kind !== "add" || line.new === null || line.file === null) return null;
  if (state.showTier0 && bundle.tier0.some((z) => z.file === line.file && z.line === line.new)) {
    return { verdict: VERDICTS.uncovered, label: `line ${line.new}: no test runs this line`, tint: 18 };
  }
  const meter = state.meters[lineKey(line.file, line.new)];
  if (!meter) return null;
  if (meter.survived > 0) {
    return {
      verdict: VERDICTS.survived,
      label: `line ${line.new}: the tests missed ${meter.survived} of ${meter.done} changes`,
      tint: Math.min(28, 8 + 6 * meter.survived),
    };
  }
  return { verdict: VERDICTS.killed, label: `line ${line.new}: the tests caught all ${meter.done} changes`, tint: 0 };
}

const BASE = { add: "var(--diff-add)", del: "var(--diff-del)", ctx: "transparent" } as const;

interface Range { file: string; start_line: number; end_line: number }

const within = (r: Range, file: string | null, n: number | null) =>
  n !== null && r.file === file && n >= r.start_line && n <= r.end_line;

export function DiffPane({ lines, bundle, state, selected, onSelectLine, reduced = false }: Props) {
  const laneAt = (file: string | null, n: number | null) => bundle.lanes.find((l) => within(l, file, n));
  const undefendedAt = (file: string | null, n: number | null) =>
    state.showDdmin ? bundle.ddmin.undefended.find((u) => within(u, file, n)) : undefined;

  // The first diff line of each lane (one tab stop per hunk) and of each undefended hunk (its label).
  const firstOf = new Map<unknown, number>();
  lines.forEach((line, i) => {
    for (const r of [laneAt(line.file, line.new), undefendedAt(line.file, line.new)]) {
      if (r && !firstOf.has(r)) firstOf.set(r, i);
    }
  });
  const selectedFirst = selected === null ? -1 : lines.findIndex((line) => within(selected, line.file, line.new));

  const selectedRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    selectedRef.current?.scrollIntoView?.({ block: "center", behavior: reduced ? "auto" : "smooth" });
    // Only when another change is selected, not on every replay tick.
  }, [selected?.id]);

  return (
    <div className="font-mono text-[15px] leading-[1.6]" role="region" aria-label="The pull request's diff">
      {lines.map((line, i) => {
        if (line.kind === "file") {
          return <div key={i} className="border-y border-border bg-card px-3 py-1 text-muted-foreground">{line.file}</div>;
        }
        if (line.kind === "hunk") {
          return <div key={i} className="px-3 text-muted-foreground" dangerouslySetInnerHTML={{ __html: line.html }} />;
        }
        const g = gutter(line, bundle, state);
        const lane = laneAt(line.file, line.new);
        const undefended = undefendedAt(line.file, line.new);
        const isSelected = selected !== null && within(selected, line.file, line.new);
        const base = BASE[line.kind];
        const background = g && g.tint > 0
          ? `color-mix(in srgb, ${g.verdict.cssVar} ${g.tint}%, ${base === "transparent" ? "var(--background)" : base})`
          : base;
        const borderLeft = undefended ? "2px dashed var(--verdict-uncovered)" : "2px solid transparent";
        const clickable = g !== null && line.file !== null && line.new !== null
          && mutantAtLine(bundle, line.file, line.new) !== null;
        return (
          <div key={i} ref={i === selectedFirst ? selectedRef : undefined}
            className={`flex ${isSelected ? "outline-2 outline-accent -outline-offset-2 outline" : ""}`} style={{ background, borderLeft }}>
            <span className="w-14 shrink-0 select-none pr-2 text-right text-muted-foreground tabular">{line.new ?? line.old}</span>
            <span className="w-6 shrink-0 select-none text-center" style={{ color: g?.verdict.cssVar }}>
              {g ? <span role="img" aria-label={g.label} title={g.label}>{g.verdict.glyph}</span> : null}
            </span>
            <span className="w-4 shrink-0 select-none text-muted-foreground">{line.kind === "add" ? "+" : line.kind === "del" ? "−" : " "}</span>
            {clickable ? (
              <button type="button" className="cursor-pointer whitespace-pre text-left"
                onClick={() => onSelectLine(line.file!, line.new!)}
                tabIndex={lane && firstOf.get(lane) === i ? undefined : -1}
                aria-label={`Show the changes on line ${line.new}`}>
                <span dangerouslySetInnerHTML={{ __html: line.html }} />
              </button>
            ) : (
              <span className="whitespace-pre" dangerouslySetInnerHTML={{ __html: line.html }} />
            )}
            {undefended && firstOf.get(undefended) === i && (
              <span className="ml-6 select-none whitespace-nowrap font-sans text-[13px] text-muted-foreground">
                the tests would not miss this hunk
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
