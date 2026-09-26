import { FastForward, Pause, Play } from "lucide-react";
import { useState } from "react";
import type { Bundle } from "../bundle";
import { SPEEDS, type ReplayState } from "../engine";
import type { useReplay } from "../useReplay";

export function statusLine(state: ReplayState, bundle: Bundle): string {
  return `${state.finished} of ${bundle.mutants.length} changes tested · ${state.survived} missed`;
}

/** A key that only changes at quarters of `finished` (and at the end), so the status
 *  line is re-announced at milestones, not on every survivor within the same quarter. */
function milestoneKey(state: ReplayState, bundle: Bundle): string {
  if (state.phase === "done") return "done";
  const n = Math.max(bundle.mutants.length, 1);
  return String(Math.floor((state.finished / n) * 4));
}

interface Props {
  clock: ReturnType<typeof useReplay>;
  total: number;
  state: ReplayState;
  bundle: Bundle;
}

export function ReplayControls({ clock, total, state, bundle }: Props) {
  // Hold the announced text in state, and only replace it when the milestone key
  // changes, so a screen reader hears a sentence at quarters and the end, not on
  // every tick (a mutant finishing) or every survivor within the same quarter.
  const [key, setKey] = useState(() => milestoneKey(state, bundle));
  const [announced, setAnnounced] = useState(() => statusLine(state, bundle));
  const nextKey = milestoneKey(state, bundle);
  if (nextKey !== key) {
    setKey(nextKey);
    setAnnounced(statusLine(state, bundle));
  }

  const btn = "inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border bg-muted px-3 py-1.5 text-[14px] font-medium";
  const primary = "inline-flex cursor-pointer items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[14px] font-medium text-accent-foreground";
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border bg-card px-4 py-2">
      {clock.playing ? (
        <button type="button" className={primary} onClick={clock.pause}>
          <Pause size={16} aria-hidden="true" /> Pause
        </button>
      ) : (
        <button type="button" className={primary} onClick={clock.play}>
          <Play size={16} aria-hidden="true" /> {clock.t >= total ? "Replay" : "Play"}
        </button>
      )}
      <button type="button" className={btn} onClick={clock.skip}>
        <FastForward size={16} aria-hidden="true" /> Skip to results
      </button>
      <input type="range" min={0} max={total} step={0.1} value={clock.t} aria-label="Replay position"
        onChange={(e) => clock.seek(Number(e.target.value))} className="min-w-40 flex-1 accent-[var(--accent)]" />
      <label className="text-[13px] text-muted-foreground">
        speed{" "}
        <select value={clock.speed} onChange={(e) => clock.setSpeed(Number(e.target.value))}
          className="rounded border border-border bg-muted px-1 tabular">
          {SPEEDS.map((s) => <option key={s} value={s}>×{s}</option>)}
        </select>
      </label>
      <p role="status" aria-atomic="true" className="text-[13px] text-muted-foreground tabular">{announced}</p>
      <span className="rounded-full border border-border px-2 text-[12px] text-muted-foreground">replay of a recorded run · real timings</span>
      <span className="hidden text-[12px] text-muted-foreground md:inline">{"Space play or pause · ←/→ changes · Esc close"}</span>
    </div>
  );
}
