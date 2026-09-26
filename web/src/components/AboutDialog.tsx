import { X } from "lucide-react";
import { useEffect, useRef } from "react";

export function AboutDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose}
      className="m-auto max-w-2xl rounded-lg border border-border bg-card p-6 text-foreground backdrop:bg-scrim">
      <button type="button" onClick={onClose} aria-label="Close" className="float-right cursor-pointer"><X size={18} /></button>
      <h2 className="text-lg font-semibold">How this runs on Nebius</h2>
      <ul className="mt-3 list-disc space-y-2 pl-5 text-[15px]">
        <li>A mutant is a small deliberate change to a line the agent wrote. If every test still passes, the tests missed it.</li>
        <li>Each run forks one seed checkpoint in Nebius Token Factory Sandboxes: one sandbox per mutant, 24 at a time, each running only the tests that execute the changed code.</li>
        <li>Nemotron 3.5 Lightning proposes mutants, Nemotron 3 Super triages the survivors, and Nemotron 3 Ultra writes the regression test, all on Token Factory.</li>
        <li><b>What is live here:</b> "Ask Nemotron why" makes a real Nemotron Super call now. <b>What is replayed:</b> the sandbox runs, recorded from real runs; mutant durations are as measured.</li>
        <li><b>The benchmark, honestly:</b> across 151 pre-registered pairs, "flagged at all" did not separate wrong agent patches from accepted ones (p = 0.28). The value is in which survivor matters and the verified test, not in the flag.</li>
        <li>Run it yourself: <code className="font-mono">chesterton seed</code>, <code className="font-mono">chesterton run</code>, <code className="font-mono">chesterton review</code>. See the README. MIT licensed.</li>
      </ul>
    </dialog>
  );
}
