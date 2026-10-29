import { Play } from "lucide-react";
import { useEffect, useState } from "react";
import type { Bundle } from "../bundle";
import { stateAt } from "../engine";
import { VERDICTS } from "../verdicts";

/** How long the recorded run takes on screen in demo mode. */
export const DEMO_RUN_S = 5;
/** A beat between the run finishing and the answer replacing it, so the final counts can be read. */
const SETTLE_MS = 900;

/** Demo mode (`?demo`): the review is revealed by a click, as the recorded run replayed
 *  in a few seconds, so the answer arrives on camera where a recorder's click-zoom points. */
export function DemoRun({ bundle, reduced, onDone }: { bundle: Bundle; reduced: boolean; onDone: () => void }) {
  const [running, setRunning] = useState(false);
  const [t, setT] = useState(0);
  const total = bundle.timeline.total_s;

  useEffect(() => {
    if (!running) return;
    // Reduced motion: nothing animates, so the answer appears at once.
    if (reduced) {
      onDone();
      return;
    }
    let raf = 0;
    let settle = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const p = Math.min((now - start) / 1000 / DEMO_RUN_S, 1);
      setT(p * total);
      if (p < 1) raf = requestAnimationFrame(tick);
      else settle = window.setTimeout(onDone, SETTLE_MS);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(settle);
    };
  }, [running, reduced, total, onDone]);

  if (!running) {
    return (
      <div className="mt-5">
        <button type="button" data-demo="run" onClick={() => setRunning(true)}
          className="inline-flex cursor-pointer items-center gap-2 rounded-md bg-accent px-4 py-2 text-[16px] font-semibold text-accent-foreground hover:opacity-90">
          <Play size={18} aria-hidden="true" /> Run Chesterton review
        </button>
        <p className="mt-2 text-[14px] text-muted-foreground">Breaks the patch on purpose, line by line, and checks whether the tests notice.</p>
      </div>
    );
  }

  const s = stateAt(bundle, t);
  const n = bundle.mutants.length;
  const missed = VERDICTS.survived;
  const caught = VERDICTS.killed;
  return (
    <div data-demo="running" role="status" aria-live="polite"
      className="mt-5 max-w-3xl rounded-lg border border-border bg-card p-4 md:p-5">
      <p className="text-[16px] font-semibold">
        {s.finished < n ? "Breaking the patch on purpose and running the tests…" : "Nemotron is judging which misses matter…"}
      </p>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        <div className="h-full bg-foreground" style={{ width: `${(s.finished / Math.max(n, 1)) * 100}%` }} />
      </div>
      <p className="mt-3 text-[15px] tabular">
        {s.finished} of {n} changes tested ·{" "}
        <span style={{ color: caught.cssVar }}>{caught.glyph} {s.killed} caught</span> ·{" "}
        <span style={{ color: missed.cssVar }}>{missed.glyph} {s.survived} the tests didn't notice</span>
      </p>
      <p className="mt-2 text-[13px] text-muted-foreground">
        Replay of a recorded run · {bundle.counters.sandbox_ops} Nebius sandboxes · Nemotron on Token Factory
      </p>
    </div>
  );
}
