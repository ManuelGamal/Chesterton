import { cleanup, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import type { Bundle, DiffLine } from "../bundle";
import { stateAt } from "../engine";
import { DiffPane } from "./DiffPane";

const golden = JSON.parse(
  readFileSync(resolve(process.cwd(), "../tests/fixtures/demo_example_bundle.json"), "utf8"),
) as Bundle;
const LINES: DiffLine[] = [
  { kind: "add", file: "pay.py", old: null, new: 2, html: "if not amount:" },
  { kind: "add", file: "pay.py", old: null, new: 3, html: "raise" },
];

// RTL's auto-cleanup needs a global `afterEach`, which this project's vitest config
// (no `globals: true`) doesn't provide, so we register it explicitly.
afterEach(cleanup);

describe("DiffPane", () => {
  it("marks a survived line with the glyph and the word", () => {
    render(<DiffPane lines={LINES} bundle={golden} state={stateAt(golden, golden.timeline.total_s)}
                     focus={null} onPick={() => {}} />);
    expect(screen.getByLabelText(/line 2: 1 of 1 mutants survived/)).toBeInTheDocument();
  });

  it("marks a tier-0 line as uncovered from the start", () => {
    render(<DiffPane lines={LINES} bundle={golden} state={stateAt(golden, 0)} focus={null} onPick={() => {}} />);
    expect(screen.getByLabelText(/no test runs this line/)).toBeInTheDocument();
  });
});
