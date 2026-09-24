import { cleanup, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

  it("gives a multi-line finding one tab stop, on its first line", () => {
    render(<DiffPane lines={LINES} bundle={golden} state={stateAt(golden, golden.timeline.total_s)}
                     focus={null} onPick={() => {}} />);
    expect(screen.getByRole("button", { name: "Open finding on line 2" })).not.toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("button", { name: "Open finding on line 3" })).toHaveAttribute("tabindex", "-1");
  });

  it("gives each gutter mark an image role, so its label is read", () => {
    render(<DiffPane lines={LINES} bundle={golden} state={stateAt(golden, golden.timeline.total_s)}
                     focus={null} onPick={() => {}} />);
    expect(screen.getByRole("img", { name: /line 2: 1 of 1 mutants survived/ })).toBeInTheDocument();
  });

  it("labels the hunk the tests would not miss, once, when ddmin shows", () => {
    const { rerender } = render(<DiffPane lines={LINES} bundle={golden} state={stateAt(golden, 0)}
                                          focus={null} onPick={() => {}} />);
    expect(screen.queryByText("the tests would not miss this hunk")).not.toBeInTheDocument();
    rerender(<DiffPane lines={LINES} bundle={golden} state={stateAt(golden, golden.timeline.total_s)}
                       focus={null} onPick={() => {}} />);
    expect(screen.getAllByText("the tests would not miss this hunk")).toHaveLength(1);
  });

  describe("scrolling to the focused finding", () => {
    const scroll = vi.fn();
    beforeEach(() => {
      scroll.mockClear();
      Element.prototype.scrollIntoView = scroll;
    });
    afterEach(() => {
      delete (Element.prototype as Partial<Element>).scrollIntoView;
    });

    it("centres the focused finding's first line, smoothly", () => {
      const end = stateAt(golden, golden.timeline.total_s);
      render(<DiffPane lines={LINES} bundle={golden} state={end} focus={golden.triage.headline[0]} onPick={() => {}} />);
      expect(scroll).toHaveBeenCalledTimes(1);
      expect(scroll).toHaveBeenCalledWith({ block: "center", behavior: "smooth" });
      expect(scroll.mock.contexts[0]).toHaveTextContent("if not amount:");
    });

    it("jumps without smoothing under reduced motion", () => {
      const end = stateAt(golden, golden.timeline.total_s);
      render(<DiffPane lines={LINES} bundle={golden} state={end} focus={golden.triage.headline[0]} onPick={() => {}} reduced />);
      expect(scroll).toHaveBeenCalledWith({ block: "center", behavior: "auto" });
    });
  });

  it("does not throw where scrollIntoView is missing", () => {
    const end = stateAt(golden, golden.timeline.total_s);
    expect(() => render(<DiffPane lines={LINES} bundle={golden} state={end} focus={golden.triage.headline[0]}
                                  onPick={() => {}} />)).not.toThrow();
  });
});
