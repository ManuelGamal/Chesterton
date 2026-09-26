// @vitest-environment node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Bundle } from "./bundle";
import {
  BUCKET_WORDS, isUndefended, judgmentFor, mutantAtLine, mutantsInLaneOrder, summarise, topFinding, windowDiff,
} from "./story";
import { VERDICTS } from "./verdicts";

const golden = JSON.parse(
  readFileSync(new URL("../../tests/fixtures/demo_example_bundle.json", import.meta.url), "utf8"),
) as Bundle;

/** A window as the exporter writes it: "<n padded to 5> | <code>". */
const win = (rows: [number, string][]) => rows.map(([n, code]) => `${String(n).padStart(5)} | ${code}`).join("\n");

describe("windowDiff", () => {
  it("shows a deletion with its context", () => {
    const m0 = golden.mutants[0];
    expect(windowDiff(m0.before, m0.after)).toEqual([
      { kind: "ctx", n: 1, code: "def charge(amount):" },
      { kind: "del", n: 2, code: "    if not amount:" },
      { kind: "del", n: 3, code: '        raise ValueError("required")' },
      { kind: "ctx", n: 4, code: "    return amount" },
    ]);
  });

  it("shows a replaced line as a removed line then an added one, both numbered", () => {
    const before = win([[1156, "    # Call the base class"], [1157, "    super().set_visible(b)"], [1158, "    # hide"]]);
    const after = win([[1156, "    # Call the base class"], [1157, "    super().set_visible(False)"], [1158, "    # hide"]]);
    expect(windowDiff(before, after)).toEqual([
      { kind: "ctx", n: 1156, code: "    # Call the base class" },
      { kind: "del", n: 1157, code: "    super().set_visible(b)" },
      { kind: "add", n: 1157, code: "    super().set_visible(False)" },
      { kind: "ctx", n: 1158, code: "    # hide" },
    ]);
  });

  it("keeps only the given context around the change", () => {
    const rows: [number, string][] = Array.from({ length: 10 }, (_, i) => [i + 1, `line ${i + 1}`]);
    const changed = rows.map(([n, c]): [number, string] => [n, n === 5 ? "CHANGED" : c]);
    expect(windowDiff(win(rows), win(changed)).map((r) => [r.kind, r.n])).toEqual([
      ["ctx", 4], ["del", 5], ["add", 5], ["ctx", 6],
    ]);
  });

  it("returns nothing when the windows are the same", () => {
    expect(windowDiff(win([[1, "a"]]), win([[1, "a"]]))).toEqual([]);
  });
});

describe("the story helpers", () => {
  it("counts the changes as caught, missed and untested", () => {
    expect(summarise(golden)).toEqual({ total: 3, caught: 1, missed: 1, untested: 1, errors: 0, matter: 1 });
  });

  it("picks the first headline finding, else the first worth-a-look, else none", () => {
    expect(topFinding(golden)).toEqual({ finding: golden.triage.headline[0], bucket: "headline" });
    const quiet = { ...golden, triage: { ...golden.triage, headline: [], worth_a_look: [golden.triage.headline[0]] } };
    expect(topFinding(quiet)?.bucket).toBe("worth_a_look");
    const empty = { ...golden, triage: { ...golden.triage, headline: [], worth_a_look: [], dismissed: [] } };
    expect(topFinding(empty)).toBeNull();
  });

  it("finds Nemotron's judgment of a mutant through the finding's link", () => {
    expect(judgmentFor(golden, "m0")).toEqual({ finding: golden.triage.headline[0], bucket: "headline" });
    expect(judgmentFor(golden, "m1")).toBeNull();
    expect(BUCKET_WORDS.headline).toBe("matters");
  });

  it("orders mutants by lane, bad news first within a lane", () => {
    expect(mutantsInLaneOrder(golden).map((m) => m.id)).toEqual(["m0", "m2", "m1"]);
  });

  it("opens a missed change on a line first, else the line's first change", () => {
    expect(mutantAtLine(golden, "pay.py", 2)?.id).toBe("m0");
    expect(mutantAtLine(golden, "pay.py", 4)?.id).toBe("m1");
    expect(mutantAtLine(golden, "pay.py", 9)).toBeNull();
  });

  it("knows which mutants sit in a hunk the tests would not miss", () => {
    expect(isUndefended(golden, golden.mutants[0])).toBe(true);
    expect(isUndefended({ ...golden, ddmin: { undefended: [], probes: 1 } }, golden.mutants[0])).toBe(false);
  });
});

describe("plain words", () => {
  it("says missed and caught, and keeps the technical term for hover", () => {
    expect(VERDICTS.survived.word).toBe("missed");
    expect(VERDICTS.killed.word).toBe("caught");
    expect(VERDICTS.uncovered.word).toBe("untested line");
    expect(VERDICTS.pending.word).toBe("running");
    expect(VERDICTS.survived.term).toBe("surviving mutant: the tests still pass");
    expect(VERDICTS.killed.term).toBe("killed mutant: a test failed");
  });
});
