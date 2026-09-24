import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Finding, Regression } from "../bundle";
import { FindingPanel, FindingSide, GOLD_WARNING } from "./FindingPanel";

const FINDING: Finding = {
  id: "h0", file: "pay.py", start_line: 2, end_line: 3, operator: "semantic", rationale: "drop the guard",
  original: "    2 |     if not amount:", mutated: "    2 |     return amount", diff: "", tests: ["t.py::a"],
  label: "untested_invariant", category: "safety", confident: true, explanation: "the guard is never exercised",
  agreement: 3,
};
const VERIFIED: Regression = {
  finding_id: "h0", path: "tests/test_chesterton_regression.py", source: "def test_zero():\n    pass\n",
  status: "verified", detail: "passes on the pull request, fails on the mutant", patch_tail: "", mutant_tail: "",
  attempts: 1, note: null, verified: true, gold: "passes_on_gold",
};

/** A ten-line window, as the exporter writes it: " <n> |     <code>". */
function window10(line2: string): string {
  return Array.from({ length: 10 }, (_, i) => {
    const n = i + 1;
    return `${String(n).padStart(5)} |     ${n === 2 ? line2 : `code ${n}`}`;
  }).join("\n");
}
const WIDE: Finding = { ...FINDING, original: window10("if not amount:"), mutated: window10("return amount") };

function panel(regression: Regression | null) {
  render(
    <>
      <FindingPanel finding={FINDING} reduced />
      <FindingSide storyId="hero" finding={FINDING} regression={regression} showRegression />
    </>,
  );
}

describe("FindingPanel", () => {
  it("shows the explanation and the 3-of-3 agreement", () => {
    panel(null);
    expect(screen.getByText(/the guard is never exercised/)).toBeInTheDocument();
    expect(screen.getByText(/confirmed 3 of 3/)).toBeInTheDocument();
  });

  it("names the range in its header, in the singular for one line", () => {
    const { rerender } = render(<FindingPanel finding={FINDING} reduced />);
    expect(screen.getByRole("heading")).toHaveTextContent("SURVIVED · lines 2–3 · safety");
    rerender(<FindingPanel finding={{ ...FINDING, end_line: 2 }} reduced />);
    expect(screen.getByRole("heading")).toHaveTextContent("SURVIVED · line 2 · safety");
  });

  it("labels a verified test as verified and shows its proof and its source", () => {
    panel(VERIFIED);
    expect(screen.getByText("Verified test")).toBeInTheDocument();
    expect(screen.getByText("passes on the PR")).toBeInTheDocument();
    expect(screen.getByText("fails on the mutant")).toBeInTheDocument();
    expect(screen.getByText("holds on the correct fix")).toBeInTheDocument();
    expect(screen.getByText(/def test_zero/)).toBeInTheDocument();
  });

  it("never labels an unverified test as verified", () => {
    panel({ ...VERIFIED, verified: false, status: "fails_on_patch", gold: null });
    expect(screen.queryByText(/Verified/)).not.toBeInTheDocument();
    expect(screen.queryByText("passes on the PR")).not.toBeInTheDocument();
    expect(screen.queryByText(/def test_zero/)).not.toBeInTheDocument();
    expect(screen.getByText(/Not verified/)).toBeInTheDocument();
  });

  it("warns when a verified test fails on the correct fix", () => {
    panel({ ...VERIFIED, gold: "fails_on_gold" });
    expect(screen.getByText(GOLD_WARNING)).toBeInTheDocument();
    expect(screen.queryByText("holds on the correct fix")).not.toBeInTheDocument();
  });

  it("shows no gold row when the correct fix was not checked", () => {
    panel({ ...VERIFIED, gold: null });
    expect(screen.getByText("fails on the mutant")).toBeInTheDocument();
    expect(screen.queryByText("holds on the correct fix")).not.toBeInTheDocument();
    expect(screen.queryByText(GOLD_WARNING)).not.toBeInTheDocument();
  });

  it("offers the run output when there is some", () => {
    panel({ ...VERIFIED, patch_tail: "1 passed in 0.43s", mutant_tail: "1 failed in 0.51s" });
    expect(screen.getByText("Run output")).toBeInTheDocument();
    expect(screen.getByText("1 passed in 0.43s")).toBeInTheDocument();
    expect(screen.getByText("1 failed in 0.51s")).toBeInTheDocument();
  });

  it("offers no run output when there is none", () => {
    panel(VERIFIED);
    expect(screen.queryByText("Run output")).not.toBeInTheDocument();
  });

  it("does not show another finding's test", () => {
    panel({ ...VERIFIED, finding_id: "h1" });
    expect(screen.queryByText(/def test_zero/)).not.toBeInTheDocument();
  });

  it("keys AskWhy by finding, so a live answer never carries over to another finding", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          label: "untested_invariant",
          category: "safety",
          explanation: "LIVE ANSWER",
          elapsed_s: 2,
        }),
      }),
    );
    try {
      const { rerender } = render(
        <FindingSide storyId="hero" finding={FINDING} regression={null} showRegression />,
      );
      fireEvent.click(screen.getByRole("button", { name: /Ask Nemotron why \(live\)/ }));
      await screen.findByText("LIVE ANSWER");

      rerender(
        <FindingSide storyId="hero" finding={{ ...FINDING, id: "h1" }} regression={null} showRegression />,
      );
      expect(screen.queryByText("LIVE ANSWER")).not.toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("FindingPanel's wipe", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("opens on the PR's code, then wipes to the mutant after 600 ms", async () => {
    vi.useFakeTimers();
    render(<FindingPanel finding={FINDING} reduced={false} />);
    expect(screen.getByText(/if not amount/)).toBeInTheDocument();
    expect(screen.queryByText(/return amount/)).not.toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(600);
    });
    expect(screen.getByRole("tab", { name: "The mutant" })).toHaveAttribute("aria-selected", "true");
    // AnimatePresence mode="wait": the PR's code fades out first, then the mutant wipes in.
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText(/return amount/)).toBeInTheDocument();
  });

  it("shows the mutant at once under reduced motion", () => {
    vi.useFakeTimers();
    render(<FindingPanel finding={FINDING} reduced />);
    expect(screen.getByText(/return amount/)).toBeInTheDocument();
    expect(screen.queryByText(/if not amount/)).not.toBeInTheDocument();
  });

  it("stays on the side the viewer picked", async () => {
    vi.useFakeTimers();
    render(<FindingPanel finding={FINDING} reduced={false} />);
    fireEvent.click(screen.getByRole("tab", { name: "The PR's code" }));
    await act(async () => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByRole("tab", { name: "The PR's code" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText(/if not amount/)).toBeInTheDocument();
  });

  it("starts again on the PR's code when another finding opens", async () => {
    vi.useFakeTimers();
    const { rerender } = render(<FindingPanel finding={FINDING} reduced={false} />);
    await act(async () => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByRole("tab", { name: "The mutant" })).toHaveAttribute("aria-selected", "true");
    rerender(<FindingPanel finding={{ ...FINDING, id: "h1" }} reduced={false} />);
    expect(screen.getByRole("tab", { name: "The PR's code" })).toHaveAttribute("aria-selected", "true");
  });
});

describe("FindingPanel's code window", () => {
  it("marks the mutated lines and trims the window to 3 lines either side", () => {
    const { container } = render(<FindingPanel finding={WIDE} reduced />);
    const shown = [...container.querySelectorAll("[data-line]")].map((el) => Number(el.getAttribute("data-line")));
    expect(shown).toEqual([1, 2, 3, 4, 5, 6]);
    const marked = [...container.querySelectorAll('[data-changed="true"]')].map((el) => Number(el.getAttribute("data-line")));
    expect(marked).toEqual([2, 3]);
    const line2 = container.querySelector('[data-line="2"]')!;
    expect(line2).toHaveTextContent("return amount");
    expect(line2.querySelector('[aria-hidden="true"]')).toHaveTextContent("▲");
  });
});
