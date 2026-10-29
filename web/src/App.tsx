import * as Tabs from "@radix-ui/react-tabs";
import { ChevronDown, ChevronRight, Info } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { assertBundle, type Bundle, type DiffLine, type StoryIndex, type Verdict } from "./bundle";
import { AboutDialog } from "./components/AboutDialog";
import { AnswerCard } from "./components/AnswerCard";
import { DiffPane } from "./components/DiffPane";
import { Lanes } from "./components/Lanes";
import { MutantDetail } from "./components/MutantDetail";
import { ReplayControls } from "./components/ReplayControls";
import { SummaryLine } from "./components/SummaryLine";
import { stateAt } from "./engine";
import { mutantAtLine, mutantsInLaneOrder, summarise } from "./story";
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
      <header className="flex flex-wrap items-center gap-x-8 gap-y-2 border-b border-border px-4 py-3 md:px-8">
        <p className="flex flex-wrap items-baseline gap-x-3">
          <span className="text-[16px] font-semibold">Chesterton</span>
          <span className="text-[14px] text-muted-foreground">finds the bugs an AI agent's tests miss</span>
        </p>
        <Tabs.List aria-label="Stories" className="flex flex-wrap gap-1">
          {index.stories.map((s, i) => (
            <Tabs.Trigger key={s.id} value={s.id}
              className="cursor-pointer rounded-md px-3 py-1 text-[14px] text-muted-foreground hover:text-foreground data-[state=active]:bg-muted data-[state=active]:text-foreground">
              {i + 1} · {s.tab}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        <button type="button" onClick={() => setAbout(true)}
          className="ml-auto inline-flex cursor-pointer items-center gap-1.5 text-[14px] text-muted-foreground hover:text-foreground">
          <Info size={16} aria-hidden="true" /> About · how it runs on Nebius
        </button>
      </header>
      {index.stories.map((s) => (
        // Radix puts the panel itself in the tab order; ours always has focusable content.
        <Tabs.Content key={s.id} value={s.id} tabIndex={-1} className="min-h-0 flex-1 overflow-auto">
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
  const order = useMemo(() => mutantsInLaneOrder(bundle), [bundle]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pendingFocus, setPendingFocus] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<Verdict | null>(null);
  // The answer comes first; the replay of how it was found opens on request.
  const [traceOpen, setTraceOpen] = useState(false);
  const selected = order.find((m) => m.id === selectedId) ?? null;
  const toggleTrace = () => {
    if (traceOpen) clock.pause();
    setTraceOpen(!traceOpen);
  };

  const select = (id: string) => {
    clock.pause();
    setSelectedId(id);
  };
  // Closing the detail (Close button or Esc) returns focus to the capsule that opened it.
  const closeDetail = () => {
    setPendingFocus(selectedId);
    setSelectedId(null);
  };
  useEffect(() => {
    if (pendingFocus === null) return;
    document.querySelector<HTMLElement>(`[data-capsule="${pendingFocus}"]`)?.focus();
    setPendingFocus(null);
  }, [pendingFocus]);
  // Starting the replay clears the selection: the detail panel would otherwise show a
  // change from a moment the replay has moved past.
  useEffect(() => {
    if (clock.playing) setSelectedId(null);
  }, [clock.playing]);
  const step = (dir: 1 | -1) => {
    if (order.length === 0) return;
    const i = selected ? order.indexOf(selected) : -1;
    const next = i === -1 ? (dir === 1 ? 0 : order.length - 1) : Math.min(Math.max(i + dir, 0), order.length - 1);
    select(order[next].id);
  };
  const selectLine = (file: string, line: number) => {
    const m = mutantAtLine(bundle, file, line);
    if (m) select(m.id);
  };

  // `clock` is a fresh object every render; keep the latest handler in a ref and
  // register the window listener once.
  const onKeyRef = useRef<(e: KeyboardEvent) => void>(() => {});
  onKeyRef.current = (e: KeyboardEvent) => {
    if (!traceOpen) return;
    if (document.querySelector("dialog[open]")) return;
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const el = e.target instanceof Element ? e.target : null;
    const tag = el?.tagName ?? "";
    if (e.key === " ") {
      // Space activates a focused button, so leave it to the button.
      if (["INPUT", "SELECT", "BUTTON", "TEXTAREA", "SUMMARY"].includes(tag)) return;
      e.preventDefault();
      if (clock.playing) clock.pause();
      else clock.play();
      return;
    }
    if (e.key === "Escape") {
      if (["SELECT", "INPUT"].includes(tag)) return;
      closeDetail();
      return;
    }
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      // Arrows belong to form fields and to tab lists.
      if (["INPUT", "SELECT", "TEXTAREA"].includes(tag)) return;
      if (el?.closest("[role=tab], [role=tablist]")) return;
      step(e.key === "ArrowRight" ? 1 : -1);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => onKeyRef.current(e);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const c = bundle.counters;
  const s = summarise(bundle);
  return (
    <div className="flex flex-col">
      <AnswerCard bundle={bundle} reduced={clock.reduced} />
      <section aria-labelledby="how-found" className="flex flex-col">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-border px-4 py-3 md:px-8">
          <h2 id="how-found" className="text-[16px] font-semibold">
            <button type="button" aria-expanded={traceOpen} aria-controls="trace" onClick={toggleTrace}
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-md py-1 hover:text-muted-foreground">
              {traceOpen ? <ChevronDown size={18} aria-hidden="true" /> : <ChevronRight size={18} aria-hidden="true" />}
              How Chesterton found this
            </button>
          </h2>
          <span className="text-[14px] text-muted-foreground tabular">
            {s.total} deliberate changes to the patch · {s.missed} the tests didn't notice · {s.matter} that matter
          </span>
        </div>
        {traceOpen && (
          <div id="trace" className="flex flex-col">
            <p className="px-4 pt-3 text-[13px] text-muted-foreground tabular md:px-8">
              run totals: {c.sandbox_ops} Nebius sandboxes · Nemotron calls: {c.lightning_calls} Lightning · {c.super_calls} Super · {c.ultra_calls} Ultra · {Math.round(c.run_wall_s)} s
            </p>
            <SummaryLine bundle={bundle} highlight={highlight} onHighlight={setHighlight} />
            <ReplayControls clock={clock} total={total} state={state} bundle={bundle} />
            <div className="flex flex-col md:h-[75vh] md:flex-row">
              <div className="min-w-0 border-b border-border md:w-[60%] md:overflow-auto md:border-b-0 md:border-r">
                <DiffPane lines={lines} bundle={bundle} state={state} selected={selected} onSelectLine={selectLine} reduced={clock.reduced} />
              </div>
              <div className="min-w-0 overflow-auto md:w-[40%]">
                <Lanes bundle={bundle} state={state} reduced={clock.reduced} selected={selectedId} highlight={highlight} onSelect={select} />
                {selected ? (
                  <MutantDetail bundle={bundle} mutant={selected} reduced={clock.reduced}
                    onClose={closeDetail} onStep={step} />
                ) : (
                  <p className="px-3 py-3 text-[14px] text-muted-foreground">Click a change, or a marked line in the diff, to see what it did.</p>
                )}
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
