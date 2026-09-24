import * as Tabs from "@radix-ui/react-tabs";
import { Info } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { assertBundle, type Bundle, type DiffLine, type Finding, type StoryIndex } from "./bundle";
import { AboutDialog } from "./components/AboutDialog";
import { DiffPane } from "./components/DiffPane";
import { FindingPanel, FindingSide } from "./components/FindingPanel";
import { Lanes } from "./components/Lanes";
import { ReplayControls } from "./components/ReplayControls";
import { stateAt } from "./engine";
import { labelWords, span } from "./format";
import { useReplay } from "./useReplay";

async function fetchJson(url: string): Promise<unknown> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

export default function App() {
  const [index, setIndex] = useState<StoryIndex | null>(null);
  const [indexError, setIndexError] = useState(false);
  const [active, setActive] = useState<string>("");
  const [about, setAbout] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchJson("/stories/index.json")
      .then((ix) => {
        if (cancelled) return;
        setIndex(ix as StoryIndex);
        setActive((ix as StoryIndex).stories[0]?.id ?? "");
      })
      .catch(() => {
        if (!cancelled) setIndexError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (indexError) return <main className="p-6 text-muted-foreground">Could not load the stories.</main>;
  if (!index) return <main className="p-6 text-muted-foreground">Loading…</main>;
  return (
    <Tabs.Root value={active} onValueChange={setActive} className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-border bg-card px-4 py-2">
        <span className="font-semibold">Chesterton</span>
        <Tabs.List aria-label="Stories" className="flex flex-wrap gap-1">
          {index.stories.map((s, i) => (
            <Tabs.Trigger key={s.id} value={s.id}
              className="cursor-pointer rounded-md px-3 py-1 text-[14px] text-muted-foreground data-[state=active]:bg-muted data-[state=active]:text-foreground">
              {i + 1} · {s.tab}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        <button type="button" onClick={() => setAbout(true)}
          className="ml-auto inline-flex cursor-pointer items-center gap-1.5 text-[14px] text-muted-foreground">
          <Info size={16} aria-hidden="true" /> About · how it runs on Nebius
        </button>
      </header>
      {index.stories.map((s) => (
        // Radix always puts the content panel itself in the tab order (tabIndex 0),
        // for panels with no focusable content. Ours always has some (the replay
        // controls, at least), so opt out and let Tab land on that directly.
        <Tabs.Content key={s.id} value={s.id} tabIndex={-1} className="min-h-0 flex-1">
          {active === s.id && <Story key={s.id} id={s.id} />}
        </Tabs.Content>
      ))}
      <AboutDialog open={about} onClose={() => setAbout(false)} />
    </Tabs.Root>
  );
}

function Story({ id }: { id: string }) {
  const [data, setData] = useState<{ bundle: Bundle; lines: DiffLine[] } | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(false);
    Promise.all([fetchJson(`/stories/${id}.json`), fetchJson(`/stories/${id}.lines.json`)])
      .then(([bundle, lines]) => {
        assertBundle(bundle);
        if (!cancelled) setData({ bundle, lines: lines as DiffLine[] });
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);
  if (error) return <p className="p-6 text-muted-foreground">Could not load this story.</p>;
  if (!data) return <p className="p-6 text-muted-foreground">Loading story…</p>;
  return <StoryView bundle={data.bundle} lines={data.lines} />;
}

function StoryView({ bundle, lines }: { bundle: Bundle; lines: DiffLine[] }) {
  const total = bundle.timeline.total_s;
  const clock = useReplay(total);
  const state = useMemo(() => stateAt(bundle, clock.t), [bundle, clock.t]);
  const headline = bundle.triage.headline;
  const [focus, setFocus] = useState<Finding | null>(null);

  useEffect(() => {
    if (state.showTriage && focus === null && headline.length > 0) setFocus(headline[0]);
  }, [state.showTriage, focus, headline]);

  const pause = clock.pause;
  const pick = useCallback((f: Finding) => {
    pause();
    setFocus(f);
  }, [pause]);

  // `clock` (from useReplay) is a fresh object every render, including every animation
  // frame during autoplay. Keep the latest handler in a ref and register the actual
  // window listener once, so autoplay doesn't remove/re-add it up to 60 times a second.
  const onKeyRef = useRef<(e: KeyboardEvent) => void>(() => {});
  onKeyRef.current = (e: KeyboardEvent) => {
    if (document.querySelector("dialog[open]")) return;
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const el = e.target instanceof Element ? e.target : null;
    const tag = el?.tagName ?? "";
    if (e.key === " ") {
      // Space activates a focused button, so leave it to the button.
      if (["INPUT", "SELECT", "BUTTON", "TEXTAREA"].includes(tag)) return;
      e.preventDefault();
      if (clock.playing) clock.pause();
      else clock.play();
      return;
    }
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      // Arrows belong to form fields and to tab lists (the story tabs, the PR/mutant switch).
      if (["INPUT", "SELECT", "TEXTAREA"].includes(tag)) return;
      if (el?.closest("[role=tab], [role=tablist]")) return;
      if (!state.showTriage || headline.length === 0) return;
      const i = focus ? headline.findIndex((f) => f.id === focus.id) : -1;
      const next = e.key === "ArrowRight" ? Math.min(i + 1, headline.length - 1) : Math.max(i - 1, 0);
      pick(headline[next]);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => onKeyRef.current(e);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const c = bundle.counters;
  const m = bundle.meta;
  return (
    <div className="flex h-full flex-col">
      <ReplayControls clock={clock} total={total} state={state} bundle={bundle} />
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-2">
        <h1 className="text-[17px] font-semibold">{m.title}</h1>
        <span className="min-w-0 text-[13px] text-muted-foreground">
          {m.repo} · <span title={m.submission}>patch by {m.system}</span> · UTBoost: {m.utboost === "wrong" ? "proven wrong" : "correct"}
        </span>
        <span className="text-[13px] text-muted-foreground tabular md:ml-auto">
          run totals: {c.sandbox_ops} sandboxes · {c.lightning_calls} Lightning · {c.super_calls} Super · {c.ultra_calls} Ultra · {Math.round(c.run_wall_s)} s
        </span>
      </div>
      {/* Below md the columns stack and this body scrolls as one; from md up they sit side by side. */}
      <div className="flex min-h-0 flex-1 flex-col overflow-auto md:flex-row md:overflow-hidden">
        <div className="flex h-[85vh] w-full min-w-0 shrink-0 flex-col border-b border-border md:h-auto md:w-[60%] md:shrink md:border-b-0 md:border-r">
          <div className="min-h-0 flex-1 overflow-auto">
            <DiffPane lines={lines} bundle={bundle} state={state} focus={focus} onPick={pick} reduced={clock.reduced} />
          </div>
          {state.showTriage && focus && (
            <div className="h-[42%] shrink-0 overflow-auto border-t border-border bg-card">
              <FindingPanel finding={focus} reduced={clock.reduced} />
            </div>
          )}
          {state.showTriage && !focus && headline.length === 0 && (
            <p className="shrink-0 border-t border-border bg-card px-4 py-3 text-[14px] text-muted-foreground">
              No headline findings: every survivor was dismissed or judged minor.
            </p>
          )}
        </div>
        <div className="w-full min-w-0 md:w-[40%] md:overflow-auto">
          <Lanes bundle={bundle} state={state} reduced={clock.reduced} />
          {state.showTriage && (
            <>
              <p className="px-3 py-2 text-[13px] text-muted-foreground">
                {headline.length} headline · {bundle.triage.worth_a_look.length} worth a look · {bundle.triage.dismissed.length} dismissed
                {bundle.patch.dropped_files.length > 0 && ` · ${bundle.patch.dropped_files.length} test or scratch files not shown`}
              </p>
              <TriageLists bundle={bundle} focus={focus} onPick={pick} />
              {focus && (
                <div className="px-3 pb-4">
                  <FindingSide storyId={m.id} finding={focus} regression={bundle.regression}
                    showRegression={state.showRegression} />
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** "axes3d.py:1157 · untested invariant · functional" */
function describeFinding(f: Finding): string {
  return `${f.file.split("/").pop()}:${span(f.start_line, f.end_line)} · ${labelWords(f.label)}${f.category ? ` · ${f.category}` : ""}`;
}

function TriageLists({ bundle, focus, onPick }: { bundle: Bundle; focus: Finding | null; onPick: (f: Finding) => void }) {
  const { worth_a_look: worth, dismissed } = bundle.triage;
  const summary = "cursor-pointer py-1 text-muted-foreground";
  return (
    <div className="px-3 pb-1 text-[14px]">
      {/* With no headline, worth-a-look is the review's whole answer, so it starts open. */}
      <details open={bundle.triage.headline.length === 0 && worth.length > 0}>
        <summary className={summary}>{`Worth a look (${worth.length})`}</summary>
        <ul className="mb-2 ml-4 space-y-0.5">
          {worth.map((f) => (
            <li key={f.id}>
              <button type="button" onClick={() => onPick(f)} title={f.file}
                aria-current={focus?.id === f.id ? "true" : undefined}
                className="cursor-pointer text-left underline-offset-2 hover:underline aria-[current=true]:text-accent">
                {describeFinding(f)}
              </button>
            </li>
          ))}
        </ul>
      </details>
      <details>
        <summary className={summary}>{`Dismissed (${dismissed.length})`}</summary>
        <ul className="mb-2 ml-4 space-y-0.5 text-muted-foreground">
          {dismissed.map((f) => <li key={f.id} title={f.file}>{describeFinding(f)}</li>)}
        </ul>
      </details>
    </div>
  );
}
