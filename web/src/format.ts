/** "1157" for one line, "1157–1160" for several. */
export function span(start: number, end: number): string {
  return start === end ? `${start}` : `${start}–${end}`;
}

/** "line 1157" for one line, "lines 1157–1160" for several. */
export function lineRange(start: number, end: number): string {
  return `${start === end ? "line" : "lines"} ${span(start, end)}`;
}

/** A triage label as words: "untested_invariant" → "untested invariant". */
export function labelWords(label: string): string {
  return label.replaceAll("_", " ");
}
