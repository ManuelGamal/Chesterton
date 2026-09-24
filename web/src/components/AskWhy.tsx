import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import type { Finding } from "../bundle";
import { labelWords } from "../format";

type State =
  | { kind: "idle" }
  | { kind: "waiting"; since: number }
  | {
      kind: "done"; label: string; category: string | null; explanation: string; elapsed: number;
      model: string | null; confident: boolean | null;
    }
  | { kind: "failed"; message: string };

export function AskWhy({ storyId, finding }: { storyId: string; finding: Finding }) {
  const [state, setState] = useState<State>({ kind: "idle" });
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (state.kind !== "waiting") return;
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [state.kind]);

  async function ask() {
    setState({ kind: "waiting", since: Date.now() });
    try {
      const res = await fetch("/api/why", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ story: storyId, finding: finding.id }),
      });
      const body = await res.json();
      if (res.ok) {
        setState({
          kind: "done", label: body.label, category: body.category, explanation: body.explanation,
          elapsed: body.elapsed_s, model: body.model ?? null, confident: body.confident ?? null,
        });
      } else {
        setState({ kind: "failed", message: body.message ?? "the live call failed" });
      }
    } catch {
      setState({ kind: "failed", message: "the live call could not be reached" });
    }
  }

  const verdict = (label: string, category: string | null) => `${labelWords(label)}${category ? ` · ${category}` : ""}`;
  const recorded = verdict(finding.label, finding.category);
  const live = (s: Extract<State, { kind: "done" }>) =>
    ["live", s.model?.split("/").pop(), `${s.elapsed} s`, s.confident === false ? "not confident" : null]
      .filter(Boolean)
      .join(" · ");
  return (
    <div className="mt-3 rounded-md border border-border p-3">
      <button type="button" onClick={ask} disabled={state.kind === "waiting"}
        className="inline-flex cursor-pointer items-center gap-2 rounded-md bg-accent px-3 py-1.5 font-medium text-accent-foreground disabled:opacity-50">
        <Sparkles size={16} aria-hidden="true" /> Ask Nemotron why (live)
      </button>
      <div className="mt-2 text-[14px]" aria-live="polite">
        {state.kind === "waiting" && (
          // The seconds tick four times a second: hide them from the live region so it
          // announces "Asking Nemotron Super…" once, then the answer.
          <p className="text-muted-foreground tabular">
            Asking Nemotron Super…{" "}
            <span aria-hidden="true">{Math.floor((now - state.since) / 1000)} s</span>
          </p>
        )}
        {state.kind === "done" && (
          <div>
            <p><span className="text-muted-foreground">recorded:</span> {recorded}</p>
            <p><span className="text-muted-foreground">{`${live(state)}:`}</span> {verdict(state.label, state.category)}</p>
            <p className="mt-1">{state.explanation}</p>
            {state.label !== finding.label && (
              <p className="mt-1 text-muted-foreground">The live answer differs. Model answers vary, which is why each headline was confirmed 3 of 3 times.</p>
            )}
          </div>
        )}
        {state.kind === "failed" && (
          <p className="text-muted-foreground">{state.message}. Recorded answer: {recorded}: {finding.explanation}</p>
        )}
      </div>
    </div>
  );
}
