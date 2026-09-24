import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Finding, Regression } from "../bundle";
import { FindingPanel, GOLD_WARNING } from "./FindingPanel";

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

function panel(regression: Regression | null) {
  render(<FindingPanel storyId="hero" finding={FINDING} regression={regression} showRegression reduced />);
}

describe("FindingPanel", () => {
  it("shows the explanation and the 3-of-3 agreement", () => {
    panel(null);
    expect(screen.getByText(/the guard is never exercised/)).toBeInTheDocument();
    expect(screen.getByText(/confirmed 3 of 3/)).toBeInTheDocument();
  });

  it("labels a verified test as verified and shows its source", () => {
    panel(VERIFIED);
    expect(screen.getByText(/Verified: passes on the PR/)).toBeInTheDocument();
    expect(screen.getByText(/def test_zero/)).toBeInTheDocument();
  });

  it("never labels an unverified test as verified", () => {
    panel({ ...VERIFIED, verified: false, status: "fails_on_patch", gold: null });
    expect(screen.queryByText(/Verified: passes on the PR/)).not.toBeInTheDocument();
    expect(screen.queryByText(/def test_zero/)).not.toBeInTheDocument();
    expect(screen.getByText(/Not verified/)).toBeInTheDocument();
  });

  it("warns when a verified test fails on the correct fix", () => {
    panel({ ...VERIFIED, gold: "fails_on_gold" });
    expect(screen.getByText(GOLD_WARNING)).toBeInTheDocument();
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
        <FindingPanel storyId="hero" finding={FINDING} regression={null} showRegression reduced />,
      );
      fireEvent.click(screen.getByRole("button", { name: /Ask Nemotron why \(live\)/ }));
      await screen.findByText("LIVE ANSWER");

      rerender(
        <FindingPanel storyId="hero" finding={{ ...FINDING, id: "h1" }} regression={null} showRegression reduced />,
      );
      expect(screen.queryByText("LIVE ANSWER")).not.toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
