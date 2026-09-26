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
    render(<Lanes bundle={golden} state={end} reduced selected={null} highlight={null} onSelect={() => {}} />);
    expect(screen.getByText("pay.py:4")).toBeInTheDocument();
    expect(screen.getByText("pay.py:2–3")).toBeInTheDocument();
  });

  it("shows nothing but pending lanes before any mutant runs", () => {
    render(<Lanes bundle={golden} state={stateAt(golden, 0)} reduced selected={null} highlight={null} onSelect={() => {}} />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });
});
