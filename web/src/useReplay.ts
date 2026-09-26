import { useEffect, useState } from "react";
import { defaultSpeed } from "./engine";

const REDUCED = "(prefers-reduced-motion: reduce)";

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => window.matchMedia?.(REDUCED).matches ?? false);
  useEffect(() => {
    const mql = window.matchMedia?.(REDUCED);
    if (!mql) return;
    const onChange = () => setReduced(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

/** Replay clock. Remount (key by story) to reset. Opens at the final state, not playing (spec §4). */
export function useReplay(total: number) {
  const reduced = usePrefersReducedMotion();
  const [t, setT] = useState(total);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(() => defaultSpeed(total));

  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      setT((prev) => Math.min(prev + dt * speed, total));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, total]);

  useEffect(() => {
    if (playing && t >= total) setPlaying(false);
  }, [playing, t, total]);

  return {
    t, playing, speed, reduced, setSpeed,
    play: () => {
      // Reduced motion: nothing animates, so Replay shows the end.
      if (reduced) {
        setT(total);
        return;
      }
      if (t >= total) setT(0);
      setPlaying(true);
    },
    pause: () => setPlaying(false),
    seek: (v: number) => {
      setPlaying(false);
      setT(Math.min(Math.max(v, 0), total));
    },
    skip: () => {
      setPlaying(false);
      setT(total);
    },
  };
}
