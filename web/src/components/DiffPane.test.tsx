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

  it("labels the hunk the tests would not miss, once, when ddmin shows", () => {
    const { rerender } = pane({ state: stateAt(golden, 0) });
    expect(screen.queryByText("the tests would not miss this hunk")).not.toBeInTheDocument();
    rerender(<DiffPane lines={LINES} bundle={golden} state={end} selected={null} onSelectLine={() => {}} />);
    expect(screen.getAllByText("the tests would not miss this hunk")).toHaveLength(1);
  });

  describe("scrolling to the selected change", () => {
    const scroll = vi.fn();
    beforeEach(() => {
      scroll.mockClear();
      Element.prototype.scrollIntoView = scroll;
    });
    afterEach(() => {
      delete (Element.prototype as Partial<Element>).scrollIntoView;
    });

    it("centres the selected change's first line, smoothly", () => {
      pane({ selected: golden.mutants[0] });
      expect(scroll).toHaveBeenCalledWith({ block: "center", behavior: "smooth" });
      expect(scroll.mock.contexts[0]).toHaveTextContent("if not amount:");
    });

    it("jumps without smoothing under reduced motion", () => {
      pane({ selected: golden.mutants[0], reduced: true });
      expect(scroll).toHaveBeenCalledWith({ block: "center", behavior: "auto" });
    });
  });

  it("does not throw where scrollIntoView is missing", () => {
    expect(() => pane({ selected: golden.mutants[0] })).not.toThrow();
  });
});
