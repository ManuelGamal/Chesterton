import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { Bundle } from "./bundle";
import { ReplayControls, statusLine } from "./components/ReplayControls";
import { stateAt, type ReplayState } from "./engine";
import type { useReplay } from "./useReplay";

const golden = JSON.parse(
  readFileSync(resolve(process.cwd(), "../tests/fixtures/demo_example_bundle.json"), "utf8"),
) as Bundle;

describe("statusLine", () => {
  it("reads as a sentence, not a bare number", () => {
    const line = statusLine(stateAt(golden, golden.timeline.total_s), golden);
    expect(line).toMatch(/^\d+ of \d+ mutants finished · \d+ survived$/);
  });

  it("renders in a status region", () => {
    render(<p role="status" aria-atomic="true">{statusLine(stateAt(golden, 0), golden)}</p>);
    expect(screen.getByRole("status")).toHaveTextContent("0 of");
  });
});

function stubClock(t: number): ReturnType<typeof useReplay> {
  return {
    t,
    playing: false,
    speed: 1,
    reduced: true,
    setSpeed: () => {},
    play: () => {},
    pause: () => {},
    seek: () => {},
    skip: () => {},
  };
}

function makeState(overrides: Partial<ReplayState>): ReplayState {
  return {
    t: 0,
    phase: "mutants",
    mutants: [],
    finished: 0,
    survived: 0,
    killed: 0,
    uncovered: 0,
    errors: 0,
    meters: {},
    showTier0: true,
    showDdmin: false,
    showTriage: false,
    showRegression: false,
    ...overrides,
  };
}

describe("ReplayControls' status announcement", () => {
  const total = golden.timeline.total_s;
  const n = golden.mutants.length;

  it("does not re-announce for an extra survivor within the same quarter, but does at the end", () => {
    const clock = stubClock(0);
    const { rerender } = render(
      <ReplayControls clock={clock} total={total} state={makeState({ finished: 1, survived: 0 })} bundle={golden} />,
    );
    const before = screen.getByRole("status").textContent;

    rerender(
      <ReplayControls clock={clock} total={total} state={makeState({ finished: 1, survived: 1 })} bundle={golden} />,
    );
    expect(screen.getByRole("status").textContent).toBe(before);

    rerender(
      <ReplayControls clock={clock} total={total} state={makeState({ phase: "done", finished: n, survived: 3 })} bundle={golden} />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(`${n} of ${n} mutants finished`);
  });
});

describe("App's load errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a message instead of loading forever when the story index fails to load", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) })),
    );
    render(<App />);
    await screen.findByText("Could not load the stories.");
  });

  it("shows a message instead of loading forever when a story fails to load", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.includes("index.json")) {
          return { ok: true, json: async () => ({ stories: [{ id: "hero", tab: "Hero" }] }) };
        }
        return { ok: false, status: 500, json: async () => ({}) };
      }),
    );
    render(<App />);
    await screen.findByText("Could not load this story.");
  });
});
