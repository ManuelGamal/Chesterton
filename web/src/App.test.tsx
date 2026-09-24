import { fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { Bundle, DiffLine } from "./bundle";
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

// The golden bundle has one headline finding; the keyboard needs two to move between,
// and the lists need something in them.
const h0 = golden.triage.headline[0];
const STORY: Bundle = {
  ...golden,
  triage: {
    ...golden.triage,
    headline: [h0, { ...h0, id: "h1", start_line: 4, end_line: 4, explanation: "SECOND FINDING" }],
    worth_a_look: [{ ...h0, id: "w0", category: "functional", explanation: "WORTH A LOOK" }],
    dismissed: [{ ...h0, id: "d0", label: "dead_code", category: null, explanation: "DISMISSED" }],
  },
};
const STORY_LINES: DiffLine[] = [1, 2, 3, 4].map((n) => ({ kind: "add", file: "pay.py", old: null, new: n, html: `line ${n}` }));

function serve(bundle: Bundle) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = url.includes("index.json") ? { stories: [{ id: "hero", tab: "Hero" }] }
        : url.includes(".lines.json") ? STORY_LINES
        : bundle;
      return { ok: true, json: async () => body };
    }),
  );
}

async function skipToResults() {
  render(<App />);
  const skip = await screen.findByRole("button", { name: /Skip to results/ });
  fireEvent.click(skip);
  return skip;
}

const focused = () => screen.getByRole("region", { name: "Focused finding" });

describe("the story view", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("moves between findings with the arrow keys, even from a focused button", async () => {
    serve(STORY);
    const skip = await skipToResults();
    expect(focused()).toHaveTextContent(h0.explanation);
    skip.focus();
    fireEvent.keyDown(skip, { key: "ArrowRight" });
    expect(focused()).toHaveTextContent("SECOND FINDING");
    fireEvent.keyDown(skip, { key: "ArrowLeft" });
    expect(focused()).toHaveTextContent(h0.explanation);
  });

  it("ignores arrow keys with a modifier, or in the story tabs", async () => {
    serve(STORY);
    const skip = await skipToResults();
    skip.focus();
    fireEvent.keyDown(skip, { key: "ArrowRight", altKey: true });
    fireEvent.keyDown(document.body, { key: "ArrowRight", ctrlKey: true });
    fireEvent.keyDown(document.body, { key: "ArrowRight", metaKey: true });
    fireEvent.keyDown(screen.getByRole("tab", { name: /Hero/ }), { key: "ArrowRight" });
    expect(focused()).toHaveTextContent(h0.explanation);
  });

  it("puts the verified test and the live call beside the lanes, and hints at the keys", async () => {
    serve(STORY);
    await skipToResults();
    const side = screen.getByRole("region", { name: "Mutants by hunk" }).parentElement!;
    expect(side).toHaveTextContent("Verified test");
    expect(side).toContainElement(screen.getByRole("button", { name: /Ask Nemotron why \(live\)/ }));
    expect(screen.getByText("Space pause · ←/→ findings")).toBeInTheDocument();
  });

  it("lists worth-a-look and dismissed findings, and opens a worth-a-look one", async () => {
    serve(STORY);
    await skipToResults();
    expect(screen.getByText("Worth a look (1)")).toBeInTheDocument();
    expect(screen.getByText("Dismissed (1)")).toBeInTheDocument();
    expect(screen.getByText("pay.py:2–3 · dead code")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "pay.py:2–3 · untested invariant · functional" }));
    expect(focused()).toHaveTextContent("WORTH A LOOK");
  });

  it("says who wrote the patch, and that the counters are run totals", async () => {
    serve(STORY);
    await skipToResults();
    const by = screen.getByText(`patch by ${golden.meta.system}`);
    expect(by).toHaveAttribute("title", golden.meta.submission);
    expect(screen.getByText(/^run totals: /)).toBeInTheDocument();
  });

  it("says so when there is no headline finding", async () => {
    serve({ ...STORY, triage: { ...STORY.triage, headline: [] } });
    await skipToResults();
    expect(screen.getByText("No headline findings: every survivor was dismissed or judged minor.")).toBeInTheDocument();
  });
});
