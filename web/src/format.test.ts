// @vitest-environment node
import { describe, expect, it } from "vitest";
import { labelWords, lineRange, span } from "./format";

describe("lineRange", () => {
  it("names a single line in the singular", () => {
    expect(lineRange(1157, 1157)).toBe("line 1157");
  });

  it("names a range in the plural with an en dash", () => {
    expect(lineRange(1157, 1160)).toBe("lines 1157–1160");
  });
});

describe("span", () => {
  it("is one number for a single line", () => {
    expect(span(1157, 1157)).toBe("1157");
  });

  it("is a range with an en dash for several lines", () => {
    expect(span(1157, 1160)).toBe("1157–1160");
  });
});

describe("labelWords", () => {
  it("shows a triage label as words", () => {
    expect(labelWords("untested_invariant")).toBe("untested invariant");
    expect(labelWords("dead_code")).toBe("dead code");
    expect(labelWords("equivalent")).toBe("equivalent");
  });
});
