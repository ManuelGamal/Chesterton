import { fireEvent, render, screen } from "@testing-library/react";
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
  { kind: "add", file: "pay.py", old: null, new: 4, html: "return amount" },
];
const end = stateAt(golden, golden.timeline.total_s);

function pane(props: Partial<Parameters<typeof DiffPane>[0]> = {}) {
  return render(<DiffPane lines={LINES} bundle={golden} state={end} selected={null} onSelectLine={() => {}} {...props} />);
}

describe("DiffPane", () => {
  it("labels a line the tests missed in plain words", () => {
    pane();
    expect(screen.getByRole("img", { name: "line 2: the tests missed 1 of 1 changes" })).toBeInTheDocument();
  });

  it("labels a line no test runs", () => {
    pane({ state: stateAt(golden, 0) });
    expect(screen.getByLabelText(/no test runs this line/)).toBeInTheDocument();
  });

  it("opens a line's changes on click, with one tab stop per hunk", () => {
    const onSelectLine = vi.fn();
    pane({ onSelectLine });
    fireEvent.click(screen.getByRole("button", { name: "Show the changes on line 3" }));
    expect(onSelectLine).toHaveBeenCalledWith("pay.py", 3);
    expect(screen.getByRole("button", { name: "Show the changes on line 2" })).not.toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("button", { name: "Show the changes on line 3" })).toHaveAttribute("tabindex", "-1");
  });

  it("does not make a line with no mutant a button, even when no test runs it", () => {
    const bundle = { ...golden, tier0: [...golden.tier0, { file: "pay.py", line: 9 }] };
    const lines = [...LINES, { kind: "add" as const, file: "pay.py", old: null, new: 9, html: "extra" }];
    render(<DiffPane lines={lines} bundle={bundle} state={end} selected={null} onSelectLine={() => {}} />);
    expect(screen.getByLabelText("line 9: no test runs this line")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show the changes on line 9" })).not.toBeInTheDocument();
  });

  it("labels the hunk the tests still pass without, once, when ddmin shows", () => {
    const { rerender } = pane({ state: stateAt(golden, 0) });
    expect(screen.queryByText("the tests still pass without this hunk")).not.toBeInTheDocument();
    rerender(<DiffPane lines={LINES} bundle={golden} state={end} selected={null} onSelectLine={() => {}} />);
    expect(screen.getAllByText("the tests still pass without this hunk")).toHaveLength(1);
  });

  describe("scrolling to the selected change", () => {
    const scrollTo = vi.fn();

    function mountThenSelect(overflowing: boolean, props: Partial<Parameters<typeof DiffPane>[0]> = {}) {
      const { container, rerender } = render(
        <div style={{ overflowY: "auto" }}>
          <DiffPane lines={LINES} bundle={golden} state={end} selected={null} onSelectLine={() => {}} {...props} />
        </div>,
      );
      const box = container.firstElementChild as HTMLElement;
      Object.defineProperty(box, "scrollHeight", { value: overflowing ? 1000 : 200, configurable: true });
      Object.defineProperty(box, "clientHeight", { value: 200, configurable: true });
      box.scrollTo = scrollTo;
      rerender(
        <div style={{ overflowY: "auto" }}>
          <DiffPane lines={LINES} bundle={golden} state={end} selected={golden.mutants[0]} onSelectLine={() => {}} {...props} />
        </div>,
      );
      return box;
    }

    beforeEach(() => {
      scrollTo.mockClear();
    });

    it("scrolls only its own scrollable ancestor, smoothly", () => {
      mountThenSelect(true);
      expect(scrollTo).toHaveBeenCalledTimes(1);
      expect(scrollTo.mock.calls[0][0]).toMatchObject({ behavior: "smooth" });
    });

    it("jumps without smoothing under reduced motion", () => {
      mountThenSelect(true, { reduced: true });
      expect(scrollTo).toHaveBeenCalledTimes(1);
      expect(scrollTo.mock.calls[0][0]).toMatchObject({ behavior: "auto" });
    });

    it("does nothing when the box does not overflow", () => {
      mountThenSelect(false);
      expect(scrollTo).not.toHaveBeenCalled();
    });
  });

  it("does not throw where scrollTo is missing", () => {
    expect(() => pane({ selected: golden.mutants[0] })).not.toThrow();
  });
});
