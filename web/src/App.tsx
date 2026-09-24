import * as Tabs from "@radix-ui/react-tabs";
import { Info } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { assertBundle, type Bundle, type DiffLine, type Finding, type StoryIndex } from "./bundle";
import { AboutDialog } from "./components/AboutDialog";
import { DiffPane } from "./components/DiffPane";
import { FindingPanel } from "./components/FindingPanel";
import { Lanes } from "./components/Lanes";
import { ReplayControls } from "./components/ReplayControls";
import { stateAt } from "./engine";
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
      <header className="flex items-center gap-4 border-b border-border bg-card px-4 py-2">
        <span className="font-semibold">Chesterton</span>
        <Tabs.List aria-label="Stories" className="flex gap-1">
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
    const tag = (e.target as HTMLElement).tagName;
    if (["INPUT", "SELECT", "BUTTON", "TEXTAREA"].includes(tag)) return;
    if (e.key === " ") {
      e.preventDefault();
      if (clock.playing) clock.pause();
      else clock.play();
    }
    if ((e.key === "ArrowRight" || e.key === "ArrowLeft") && state.showTriage && headline.length) {
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
  return (
    <div className="flex h-full flex-col">
      <ReplayControls clock={clock} total={total} state={state} bundle={bundle} />
      <div className="flex items-baseline gap-4 px-4 py-2">
        <h1 className="text-[17px] font-semibold">{bundle.meta.title}</h1>
        <span className="text-[13px] text-muted-foreground">
          {bundle.meta.repo} · {bundle.meta.submission} · UTBoost: {bundle.meta.utboost === "wrong" ? "proven wrong" : "correct"}
        </span>
        <span className="ml-auto text-[13px] text-muted-foreground tabular">
          {c.sandbox_ops} sandboxes · {c.lightning_calls} Lightning · {c.super_calls} Super · {c.ultra_calls} Ultra · {Math.round(c.run_wall_s)} s
        </span>
      </div>
      <div className="flex min-h-0 flex-1">
        <div className="flex w-[60%] min-w-0 flex-col border-r border-border">
          <div className="min-h-0 flex-1 overflow-auto">
            <DiffPane lines={lines} bundle={bundle} state={state} focus={focus} onPick={pick} />
          </div>
          {state.showTriage && focus && (
            <div className="max-h-[55%] overflow-auto">
              <FindingPanel storyId={bundle.meta.id} finding={focus} regression={bundle.regression}
                showRegression={state.showRegression} reduced={clock.reduced} />
            </div>
          )}
        </div>
        <div className="flex w-[40%] min-w-0 flex-col">
          <Lanes bundle={bundle} state={state} reduced={clock.reduced} />
          {state.showTriage && (
            <p className="px-3 py-2 text-[13px] text-muted-foreground">
              {headline.length} headline · {bundle.triage.worth_a_look.length} worth a look · {bundle.triage.dismissed.length} dismissed
              {bundle.patch.dropped_files.length > 0 && ` · ${bundle.patch.dropped_files.length} test or scratch files not shown`}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
