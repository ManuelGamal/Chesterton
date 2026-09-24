import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Finding } from "../bundle";
import { AskWhy } from "./AskWhy";

const FINDING: Finding = {
  id: "h0", file: "pay.py", start_line: 2, end_line: 3, operator: "semantic", rationale: "drop the guard",
  original: "    2 |     if not amount:", mutated: "    2 |     return amount", diff: "", tests: ["t.py::a"],
  label: "untested_invariant", category: "safety", confident: true, explanation: "the guard is never exercised",
  agreement: 3,
};

function answer(body: Record<string, unknown>) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => body }));
}

describe("AskWhy", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("announces the wait once, without the ticking seconds", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<AskWhy storyId="hero" finding={FINDING} />);
    fireEvent.click(screen.getByRole("button", { name: /Ask Nemotron why \(live\)/ }));
    const line = await screen.findByText("Asking Nemotron Super…");
    expect(line.querySelector('[aria-hidden="true"]')).toHaveTextContent(/\d+ s/);
  });

  it("shows the model, the time and the labels in words", async () => {
    answer({
      label: "untested_invariant", category: "safety", confident: true, explanation: "LIVE",
      elapsed_s: 2.4, model: "nvidia/nemotron-3-super-120b",
    });
    render(<AskWhy storyId="hero" finding={FINDING} />);
    fireEvent.click(screen.getByRole("button", { name: /Ask Nemotron why \(live\)/ }));
    await screen.findByText("LIVE");
    expect(screen.getByText("live · nemotron-3-super-120b · 2.4 s:")).toBeInTheDocument();
    expect(screen.queryByText(/not confident/)).not.toBeInTheDocument();
    expect(screen.queryByText(/untested_invariant/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/untested invariant · safety/)).toHaveLength(2);
  });

  it("says when the live answer is not confident", async () => {
    answer({
      label: "equivalent", category: null, confident: false, explanation: "LIVE",
      elapsed_s: 3, model: "nvidia/nemotron-3-super-120b",
    });
    render(<AskWhy storyId="hero" finding={FINDING} />);
    fireEvent.click(screen.getByRole("button", { name: /Ask Nemotron why \(live\)/ }));
    await screen.findByText("LIVE");
    expect(screen.getByText("live · nemotron-3-super-120b · 3 s · not confident:")).toBeInTheDocument();
  });
});
