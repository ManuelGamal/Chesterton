// @vitest-environment node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Bundle } from "./bundle";
import { defaultSpeed, lineKey, stateAt } from "./engine";

const golden = JSON.parse(
  readFileSync(new URL("../../tests/fixtures/demo_example_bundle.json", import.meta.url), "utf8"),
) as Bundle;

describe("stateAt", () => {
  it("shows no verdict at the start", () => {
    const s = stateAt(golden, 0);
    expect(s.phase).toBe("generate");
    expect(s.mutants.every((m) => m.phase === "pending")).toBe(true);
    expect(s.finished).toBe(0);
    expect(s.showTier0).toBe(true);
    expect(s.showTriage).toBe(false);
  });

  it("gives every mutant its recorded verdict at the end", () => {
    const s = stateAt(golden, golden.timeline.total_s);
    expect(s.phase).toBe("done");
    expect(s.mutants.every((m) => m.phase === "done")).toBe(true);
    expect(s.survived).toBe(golden.mutants.filter((m) => m.verdict === "survived").length);
    expect(s.killed).toBe(golden.mutants.filter((m) => m.verdict === "killed").length);
    expect(s.showRegression).toBe(true);
  });

  it("never lets a counter go backwards", () => {
    let last = -1;
    for (let t = 0; t <= golden.timeline.total_s; t += 0.5) {
      const f = stateAt(golden, t).finished;
      expect(f).toBeGreaterThanOrEqual(last);
      last = f;
    }
  });

  it("clamps time outside the timeline", () => {
    expect(stateAt(golden, -5).finished).toBe(0);
    expect(stateAt(golden, 1e9).phase).toBe("done");
  });

  it("fills each survived line's meter", () => {
    const s = stateAt(golden, golden.timeline.total_s);
    const survivor = golden.mutants.find((m) => m.verdict === "survived")!;
    expect(s.meters[lineKey(survivor.file, survivor.start_line)].survived).toBeGreaterThan(0);
  });
});

describe("defaultSpeed", () => {
  it("fits the replay to about 15 seconds", () => {
    expect(defaultSpeed(120)).toBe(8);
    expect(defaultSpeed(5)).toBe(1);
  });
});
