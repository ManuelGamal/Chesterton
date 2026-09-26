import { fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { Bundle, Regression } from "../bundle";
import { AnswerCard, GOLD_WARNING } from "./AnswerCard";

const golden = JSON.parse(
  readFileSync(resolve(process.cwd(), "../tests/fixtures/demo_example_bundle.json"), "utf8"),
) as Bundle;
const h0 = golden.triage.headline[0];
const verified = golden.regression as Regression;

function withRegression(regression: Regression | null): Bundle {
  return { ...golden, regression };
}

describe("AnswerCard", () => {
  it("leads with the story's verdict, with code set as code", () => {
    render(<AnswerCard bundle={golden} reduced />);
    const code = screen.getByText("amount");
    expect(code.tagName).toBe("CODE");
    expect(code.parentElement).toHaveTextContent("The tests never check the amount guard.");
  });

  it("says the change was made on purpose, headline wording", () => {
    render(<AnswerCard bundle={golden} reduced />);
    const caption = screen.getByText(/Chesterton changed this line on purpose/);
    expect(caption).toHaveTextContent("Chesterton changed this line on purpose (a mutant). Every test still passed.");
    expect(caption.querySelector("em")).toHaveTextContent("mutant");
    expect(caption).toHaveAttribute(
      "title",
      "A mutant is a small deliberate change to a line of the patch; if every test still passes, the tests missed it.",
    );
  });

  it("says the change was made on purpose, worth-a-look wording", () => {
    const quiet: Bundle = {
      ...golden,
      regression: null,
      triage: { ...golden.triage, headline: [], worth_a_look: [{ ...h0, id: "w0" }] },
    };
    render(<AnswerCard bundle={quiet} reduced />);
    expect(screen.getByText(/Chesterton changed this line on purpose/)).toHaveTextContent(
      "Chesterton changed this line on purpose (a mutant). The tests still passed; Nemotron judged it worth a look.",
    );
  });

  it("shows the change the tests miss as removed and added lines", () => {
    const { container } = render(<AnswerCard bundle={golden} reduced />);
    const change = screen.getByRole("group", { name: "The change" });
    expect(change).toHaveTextContent("if not amount:");
    expect(container.querySelectorAll('[data-kind="del"]')).toHaveLength(2);
    expect(screen.getByText("tests still pass")).toBeInTheDocument();
    expect(screen.getByText(h0.explanation)).toBeInTheDocument();
  });

  it("proves a verified test with three checks", () => {
    render(<AnswerCard bundle={golden} reduced />);
    expect(screen.getByText("passes on the agent's fix")).toBeInTheDocument();
    expect(screen.getByText("fails on the change")).toBeInTheDocument();
    expect(screen.getByText("holds on the correct fix")).toBeInTheDocument();
    expect(screen.getByText("Show test")).toBeInTheDocument();
  });

  it("warns, in place of the third check, when the test fails on the correct fix", () => {
    render(<AnswerCard bundle={withRegression({ ...verified, gold: "fails_on_gold" })} reduced />);
    expect(screen.getByText(GOLD_WARNING)).toBeInTheDocument();
    expect(screen.queryByText("holds on the correct fix")).not.toBeInTheDocument();
  });

  it("never calls an unverified test verified, nor shows its source", () => {
    render(<AnswerCard bundle={withRegression({ ...verified, verified: false, status: "fails_on_patch", gold: null })} reduced />);
    expect(screen.queryByText(/Verified/)).not.toBeInTheDocument();
    expect(screen.queryByText("passes on the agent's fix")).not.toBeInTheDocument();
    expect(screen.queryByText("Show test")).not.toBeInTheDocument();
    expect(screen.getByText(/Not verified/)).toBeInTheDocument();
  });

  it("says no test was needed when nothing made the headline", () => {
    const quiet: Bundle = {
      ...golden,
      regression: null,
      triage: { ...golden.triage, headline: [], worth_a_look: [{ ...h0, id: "w0" }] },
    };
    render(<AnswerCard bundle={quiet} reduced />);
    expect(screen.getByText("missed, judged worth a look")).toBeInTheDocument();
    expect(screen.getByText("No test needed: nothing important slipped past the tests.")).toBeInTheDocument();
  });

  it("headings: the verdict is an h1, and the change heading's name excludes the badge", () => {
    render(<AnswerCard bundle={golden} reduced />);
    const verdict = screen.getByRole("heading", { level: 1 });
    expect(verdict).toHaveTextContent("The tests never check the amount guard.");
    const changeHeading = screen.getByRole("heading", { level: 2, name: "The change the tests miss" });
    expect(changeHeading).not.toHaveTextContent("tests still pass");
    expect(screen.getByText("tests still pass")).toBeInTheDocument();
  });

  it("labels the right-hand heading by whether a test was written", () => {
    render(<AnswerCard bundle={golden} reduced />);
    expect(screen.getByRole("heading", { name: "The test Chesterton wrote" })).toBeInTheDocument();
  });

  it("labels the right-hand heading 'Regression test' when none was written for the top finding", () => {
    const quiet: Bundle = {
      ...golden,
      regression: null,
      triage: { ...golden.triage, headline: [], worth_a_look: [{ ...h0, id: "w0" }] },
    };
    render(<AnswerCard bundle={quiet} reduced />);
    expect(screen.getByRole("heading", { name: "Regression test" })).toBeInTheDocument();
  });

  it("shows only the verdict when there is no finding at all", () => {
    const empty: Bundle = { ...golden, regression: null, triage: { ...golden.triage, headline: [], worth_a_look: [], dismissed: [] } };
    render(<AnswerCard bundle={empty} reduced />);
    expect(screen.queryByText("The change the tests miss")).not.toBeInTheDocument();
  });

  it("keys the live answer by finding, so it never carries over", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ label: "untested_invariant", category: "safety", explanation: "LIVE ANSWER", elapsed_s: 2 }),
    }));
    try {
      const { rerender } = render(<AnswerCard bundle={golden} reduced />);
      const card = screen.getByRole("region", { name: "What Chesterton found" });
      fireEvent.click(within(card).getByRole("button", { name: /Ask Nemotron why \(live\)/ }));
      await screen.findByText("LIVE ANSWER");
      const other: Bundle = { ...golden, triage: { ...golden.triage, headline: [{ ...h0, id: "h9" }] } };
      rerender(<AnswerCard bundle={other} reduced />);
      expect(screen.queryByText("LIVE ANSWER")).not.toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
