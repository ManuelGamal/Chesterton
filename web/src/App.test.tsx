import { fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { Bundle, DiffLine } from "./bundle";
import { ReplayControls, statusLine } from "./components/ReplayControls";
import { stateAt, type ReplayState } from "./engine";
import type { useReplay } from "./useReplay";

const golden = JSON.parse(
  readFileSync(resolve(process.cwd(), "../tests/fixtures/demo_example_bundle.json"), "utf8"),
) as Bundle;

describe("statusLine", () => {
  it("reads as a sentence in plain words", () => {
    expect(statusLine(stateAt(golden, golden.timeline.total_s), golden)).toBe("3 of 3 changes tested · 1 missed");
  });
});

function stubClock(t: number): ReturnType<typeof useReplay> {
  return { t, playing: false, speed: 1, reduced: true, setSpeed: () => {}, play: () => {}, pause: () => {}, seek: () => {}, skip: () => {} };
}

function makeState(overrides: Partial<ReplayState>): ReplayState {
  return {
    t: 0, phase: "mutants", mutants: [], finished: 0, survived: 0, killed: 0, uncovered: 0, errors: 0, meters: {},
    showTier0: true, showDdmin: false, showTriage: false, showRegression: false, ...overrides,
  };
}

describe("ReplayControls' status announcement", () => {
  const total = golden.timeline.total_s;
  const n = golden.mutants.length;

  it("does not re-announce for an extra miss within the same quarter, but does at the end", () => {
    const clock = stubClock(0);
    const { rerender } = render(<ReplayControls clock={clock} total={total} state={makeState({ finished: 1, survived: 0 })} bundle={golden} />);
    const before = screen.getByRole("status").textContent;
    rerender(<ReplayControls clock={clock} total={total} state={makeState({ finished: 1, survived: 1 })} bundle={golden} />);
    expect(screen.getByRole("status").textContent).toBe(before);
    rerender(<ReplayControls clock={clock} total={total} state={makeState({ phase: "done", finished: n, survived: 3 })} bundle={golden} />);
    expect(screen.getByRole("status")).toHaveTextContent(`${n} of ${n} changes tested`);
  });

  it("offers Replay at the end and Play partway through", () => {
    const { rerender } = render(<ReplayControls clock={stubClock(total)} total={total} state={makeState({ phase: "done" })} bundle={golden} />);
    expect(screen.getByRole("button", { name: /^Replay/ })).toBeInTheDocument();
    rerender(<ReplayControls clock={stubClock(1)} total={total} state={makeState({})} bundle={golden} />);
    expect(screen.getByRole("button", { name: /^Play/ })).toBeInTheDocument();
  });
});

describe("App's load errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a message instead of loading forever when the story index fails to load", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) })));
    render(<App />);
    await screen.findByText("Could not load the stories.");
  });

  it("shows a message instead of loading forever when a story fails to load", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => (url.includes("index.json")
      ? { ok: true, json: async () => ({ stories: [{ id: "hero", tab: "Hero" }] }) }
      : { ok: false, status: 500, json: async () => ({}) })));
    render(<App />);
    await screen.findByText("Could not load this story.");
  });
});

const LINES: DiffLine[] = [2, 3, 4].map((n) => ({ kind: "add", file: "pay.py", old: null, new: n, html: `line ${n}` }));

function serve(bundle: Bundle) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const body = url.includes("index.json") ? { stories: [{ id: "hero", tab: "Hero" }] }
      : url.includes(".lines.json") ? LINES
      : bundle;
    return { ok: true, json: async () => body };
  }));
}

async function openStory() {
  render(<App />);
  return screen.findByRole("region", { name: "What Chesterton found" });
}

const detail = () => screen.queryByRole("region", { name: "The selected change" });
// The summary line's "missed 1"/"caught 1" toggles also match /missed/ and /caught/: scope capsules to the lanes.
const capsule = (name: RegExp) => within(screen.getByRole("region", { name: "Mutants by hunk" })).getByRole("button", { name });

describe("the story page", () => {
  beforeEach(() => {
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens on the answer, with the replay finished and not playing", async () => {
    serve(golden);
    const card = await openStory();
    expect(within(card).getByText(/The tests never check the/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "How Chesterton found this" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("3 of 3 changes tested · 1 missed");
    expect(screen.getByRole("button", { name: /^Replay/ })).toBeInTheDocument();
  });

  it("replays from the start when asked", async () => {
    serve(golden);
    await openStory();
    fireEvent.click(screen.getByRole("button", { name: /^Replay/ }));
    expect(screen.getByRole("slider", { name: "Replay position" })).toHaveValue("0");
    expect(screen.getByRole("button", { name: /^Pause/ })).toBeInTheDocument();
  });

  it("opens a capsule's change, steps with the arrow keys and closes with Escape", async () => {
    serve(golden);
    await openStory();
    fireEvent.click(capsule(/missed/));
    expect(detail()).toHaveTextContent("Nemotron: matters");
    const next = within(detail()!).getByRole("button", { name: "Next change" });
    next.focus();
    fireEvent.keyDown(next, { key: "ArrowRight" });
    expect(detail()).toHaveTextContent("untested line: no test runs this line");
    fireEvent.keyDown(document.body, { key: "ArrowRight", altKey: true });
    expect(detail()).toHaveTextContent("untested line: no test runs this line");
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(detail()).not.toBeInTheDocument();
  });

  it("opens a diff line's missed change first", async () => {
    serve(golden);
    await openStory();
    fireEvent.click(screen.getByRole("button", { name: "Show the changes on line 2" }));
    expect(detail()).toHaveTextContent("missed: the 1 test that runs this line still passes");
  });

  it("highlights missed changes from the summary line", async () => {
    serve(golden);
    await openStory();
    fireEvent.click(screen.getByRole("button", { name: "missed 1" }));
    expect(capsule(/caught/)).toHaveAttribute("data-dimmed", "true");
  });

  it("pauses a running replay when a change is opened", async () => {
    serve(golden);
    await openStory();
    fireEvent.click(screen.getByRole("button", { name: /^Replay/ }));
    expect(screen.getByRole("button", { name: /^Pause/ })).toBeInTheDocument();
    // At t = 0 no mutant has finished, but line 3 is a tier-0 line and already clickable.
    fireEvent.click(screen.getByRole("button", { name: "Show the changes on line 3" }));
    expect(screen.getByRole("button", { name: /^Play/ })).toBeInTheDocument();
    expect(detail()).toBeInTheDocument();
  });
});
