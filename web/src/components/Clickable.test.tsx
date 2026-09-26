import { fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { Bundle } from "../bundle";
import { stateAt } from "../engine";
import { Lanes } from "./Lanes";
import { MutantDetail } from "./MutantDetail";
import { SummaryLine } from "./SummaryLine";

const golden = JSON.parse(
  readFileSync(resolve(process.cwd(), "../tests/fixtures/demo_example_bundle.json"), "utf8"),
) as Bundle;
const end = stateAt(golden, golden.timeline.total_s);

describe("SummaryLine", () => {
  it("tells the whole run in one sentence", () => {
    render(<SummaryLine bundle={golden} highlight={null} onHighlight={() => {}} />);
    expect(screen.getByText(/3 small changes to the lines the patch changed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "caught 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "missed 1" })).toBeInTheDocument();
    expect(screen.getByText(/1 on lines no test runs/)).toBeInTheDocument();
    expect(screen.getByText(/Nemotron picked the 1 that matters/)).toBeInTheDocument();
  });

  it("says Nemotron found none when nothing made the headline", () => {
    const quiet = { ...golden, triage: { ...golden.triage, headline: [] } };
    render(<SummaryLine bundle={quiet} highlight={null} onHighlight={() => {}} />);
    expect(screen.getByText(/Nemotron found none that matter/)).toBeInTheDocument();
  });

  it("toggles a highlight on and off", () => {
    const onHighlight = vi.fn();
    const { rerender } = render(<SummaryLine bundle={golden} highlight={null} onHighlight={onHighlight} />);
    fireEvent.click(screen.getByRole("button", { name: "missed 1" }));
    expect(onHighlight).toHaveBeenLastCalledWith("survived");
    rerender(<SummaryLine bundle={golden} highlight="survived" onHighlight={onHighlight} />);
    expect(screen.getByRole("button", { name: "missed 1" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "missed 1" }));
    expect(onHighlight).toHaveBeenLastCalledWith(null);
  });
});

describe("Lanes", () => {
  it("makes every finished capsule a button in plain words, with the term on hover", () => {
    const onSelect = vi.fn();
    render(<Lanes bundle={golden} state={end} reduced selected={null} highlight={null} onSelect={onSelect} />);
    const missed = screen.getByRole("button", { name: /missed/ });
    expect(missed).toHaveAttribute("title", "surviving mutant: the tests still pass");
    fireEvent.click(missed);
    expect(onSelect).toHaveBeenCalledWith("m0");
    expect(screen.getByRole("button", { name: /caught/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /untested line/ })).toBeInTheDocument();
  });

  it("marks the selected capsule and dims the others under a highlight", () => {
    render(<Lanes bundle={golden} state={end} reduced selected="m0" highlight="killed" onSelect={() => {}} />);
    expect(screen.getByRole("button", { name: /missed/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /missed/ })).toHaveAttribute("data-dimmed", "true");
    expect(screen.getByRole("button", { name: /caught/ })).toHaveAttribute("data-dimmed", "false");
  });
});

describe("MutantDetail", () => {
  it("shows the change, the verdict and Nemotron's judgment", () => {
    render(<MutantDetail bundle={golden} mutant={golden.mutants[0]} reduced onClose={() => {}} onStep={() => {}} />);
    const panel = screen.getByRole("region", { name: "The selected change" });
    expect(panel).toHaveTextContent("if not amount:");
    expect(panel).toHaveTextContent("missed: the 1 test that runs this line still passes");
    expect(panel).toHaveTextContent("Nemotron: matters");
    expect(panel).toHaveTextContent("Removing this whole hunk still passes the tests.");
  });

  it("says a caught change was caught, with no judgment", () => {
    render(<MutantDetail bundle={golden} mutant={golden.mutants[1]} reduced onClose={() => {}} onStep={() => {}} />);
    const panel = screen.getByRole("region", { name: "The selected change" });
    expect(panel).toHaveTextContent("caught: a test failed");
    expect(panel).not.toHaveTextContent("Nemotron:");
  });

  it("steps and closes from its buttons", () => {
    const onStep = vi.fn();
    const onClose = vi.fn();
    render(<MutantDetail bundle={golden} mutant={golden.mutants[0]} reduced onClose={onClose} onStep={onStep} />);
    fireEvent.click(screen.getByRole("button", { name: "Next change" }));
    fireEvent.click(screen.getByRole("button", { name: "Previous change" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onStep.mock.calls).toEqual([[1], [-1]]);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
