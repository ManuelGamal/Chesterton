// @vitest-environment node
import { createHighlighter } from "shiki";
import { describe, expect, it } from "vitest";
import { highlightDiff, parseDiff, THEME } from "./highlight.mjs";

const DIFF = [
  "diff --git a/pay.py b/pay.py",
  "--- a/pay.py",
  "+++ b/pay.py",
  "@@ -1,2 +1,4 @@",
  " def charge(amount):",
  "+    if not amount:",
  '+        raise ValueError("required")',
  "     return amount",
  "",
].join("\n");

describe("parseDiff", () => {
  it("numbers lines on both sides", () => {
    const lines = parseDiff(DIFF);
    expect(lines.map((l) => [l.kind, l.old, l.new])).toEqual([
      ["file", null, null], ["hunk", null, null],
      ["ctx", 1, 1], ["add", null, 2], ["add", null, 3], ["ctx", 2, 4],
    ]);
    expect(lines[0].file).toBe("pay.py");
  });
});

describe("highlightDiff", () => {
  it("returns escaped, coloured html for every code line", async () => {
    const hl = await createHighlighter({ themes: [THEME], langs: ["python"] });
    const lines = await highlightDiff(DIFF, hl);
    const raise = lines.find((l) => l.new === 3);
    expect(raise.html).toContain("raise");
    expect(raise.html).toContain('style="color:');
    const hunk = lines.find((l) => l.kind === "hunk");
    expect(hunk.html).toBe("@@ -1,2 +1,4 @@");
  });
});
