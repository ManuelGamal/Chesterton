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

  it("highlights each hunk on its own", async () => {
    const hl = await createHighlighter({ themes: [THEME], langs: ["python"] });
    const TWO_HUNK = [
      "diff --git a/mod.py b/mod.py",
      "--- a/mod.py",
      "+++ b/mod.py",
      "@@ -1,2 +1,2 @@",
      " def foo():",
      '     """',
      "@@ -10,3 +10,3 @@",
      " def get_test_data():",
      "     X, Y, Z = 1, 2, 3",
      "     return X, Y, Z",
    ].join("\n");
    const ONE_HUNK = [
      "diff --git a/mod.py b/mod.py",
      "--- a/mod.py",
      "+++ b/mod.py",
      "@@ -10,3 +10,3 @@",
      " def get_test_data():",
      "     X, Y, Z = 1, 2, 3",
      "     return X, Y, Z",
    ].join("\n");
    const twoHunkLines = await highlightDiff(TWO_HUNK, hl);
    const oneHunkLines = await highlightDiff(ONE_HUNK, hl);
    const retInTwo = twoHunkLines.find((l) => l.kind === "ctx" && l.new === 12);
    const retInOne = oneHunkLines.find((l) => l.kind === "ctx" && l.new === 12);
    expect(retInTwo.html).toBe(retInOne.html);
  });

  it("never emits a non-hex colour", async () => {
    const hl = await createHighlighter({ themes: [THEME], langs: ["python"] });
    const lines = await highlightDiff(DIFF, hl);
    for (const line of lines) {
      expect(line.html).not.toMatch(/color:(?!#[0-9a-fA-F]{3,8}")/);
    }
  });
});
