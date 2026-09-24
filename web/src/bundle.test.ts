// @vitest-environment node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { assertBundle } from "./bundle";
import { VERDICTS, verdictRank } from "./verdicts";

const golden = JSON.parse(
  readFileSync(new URL("../../tests/fixtures/demo_example_bundle.json", import.meta.url), "utf8"),
);

describe("bundle", () => {
  it("accepts the exporter's golden bundle", () => {
    expect(() => assertBundle(golden)).not.toThrow();
  });

  it("rejects a bundle missing a required section", () => {
    const broken = { ...golden, timeline: undefined };
    expect(() => assertBundle(broken)).toThrow(/timeline/);
  });

  it("rejects a mutant missing a field", () => {
    const copy = structuredClone(golden);
    delete copy.mutants[0].verdict;
    expect(() => assertBundle(copy)).toThrow(/verdict/);
  });

  it("rejects a finding missing a field", () => {
    const copy = structuredClone(golden);
    delete copy.triage.headline[0].agreement;
    expect(() => assertBundle(copy)).toThrow(/agreement/);
  });

  it("accepts a null regression", () => {
    const copy = structuredClone(golden);
    copy.regression = null;
    expect(() => assertBundle(copy)).not.toThrow();
  });
});

describe("verdicts", () => {
  it("pairs every verdict with a glyph and a word", () => {
    for (const v of Object.values(VERDICTS)) {
      expect(v.glyph.length).toBeGreaterThan(0);
      expect(v.word.length).toBeGreaterThan(0);
    }
  });

  it("sorts bad news first", () => {
    const sorted = (["killed", "survived", "error", "uncovered"] as const)
      .slice().sort((a, b) => verdictRank(a) - verdictRank(b));
    expect(sorted).toEqual(["survived", "uncovered", "error", "killed"]);
  });
});
