import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { Bundle } from "../bundle";
import { stateAt } from "../engine";
import { Lanes } from "./Lanes";

const golden = JSON.parse(
  readFileSync(resolve(process.cwd(), "../tests/fixtures/demo_example_bundle.json"), "utf8"),
) as Bundle;
const end = stateAt(golden, golden.timeline.total_s);

describe("Lanes", () => {
  it("labels a one-line hunk with one number and a range with an en dash", () => {
    render(<Lanes bundle={golden} state={end} reduced />);
    expect(screen.getByText("pay.py:4")).toBeInTheDocument();
    expect(screen.getByText("pay.py:2–3")).toBeInTheDocument();
  });

  it("says 1 probe in the singular", () => {
    render(<Lanes bundle={{ ...golden, ddmin: { undefended: [], probes: 1 } }} state={end} reduced />);
    expect(screen.getByText("Hunk removal (ddmin), 1 probe: every hunk is needed by the tests")).toBeInTheDocument();
  });

  it("says probes in the plural", () => {
    render(<Lanes bundle={golden} state={end} reduced />);
    expect(screen.getByText("Hunk removal (ddmin), 3 probes: 1 hunk the tests would not miss")).toBeInTheDocument();
  });
});
