import { useCallback, useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from "react";
import { useNavigate, useParams } from "react-router";
import { AnimatePresence, motion, useReducedMotion, type Variants } from "motion/react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { usePitchData } from "./data";
import { clampSlide, clickTarget, keyToAction, parseSlide } from "./nav";
import { SLIDES } from "./slides";
import { COVER_IMAGE } from "./slides/Cover";
import { EASE_OUT, STAGE_H, STAGE_W, useDirection, useElapsed, useFitScale, useFontsReady } from "./stage";

const TOTAL = SLIDES.length;

/** On a cold open the deck waits this long at most for its fonts and figures, then shows what it has. */
const MAX_WAIT_MS = 1600;

// Calm and the same every time: the slide dips through navy, the next one drifts in from the side it comes
// from. Opacity and transform only: nothing is laid out or repainted while it moves.
const SLIDE_MOTION: Variants = {
  enter: (dir: number) => ({ opacity: 0, x: dir * 40 }),
  center: { opacity: 1, x: 0, transition: { duration: 0.55, ease: EASE_OUT } },
  exit: (dir: number) => ({ opacity: 0, x: dir * -24, transition: { duration: 0.2, ease: [0.4, 0, 1, 1] } }),
};
const SLIDE_STILL: Variants = {
  enter: { opacity: 0 },
  center: { opacity: 1, transition: { duration: 0.12 } },
  exit: { opacity: 0, transition: { duration: 0.08 } },
};

/**
 * `/pitch/<n>`: the judges' deck. A 16:9 stage that scales to any screen (letterboxed), keyboard and clicker
 * friendly, every number read from the API. Esc returns to the app.
 */
export default function PitchScreen() {
  const params = useParams();
  const navigate = useNavigate();
  const index = parseSlide(params["*"], TOTAL);
  const data = usePitchData();
  const scale = useFitScale();
  const reduce = useReducedMotion();
  const idle = useIdle(2600);
  const fontsReady = useFontsReady();
  const waited = useElapsed(MAX_WAIT_MS);
  // A slide lays out once: with its fonts in and its figures answered, so nothing jumps while it plays.
  const ready = waited || (fontsReady && (!SLIDES[index].usesData || !!data.settled));

  // Direction of travel, for the transition (forward slides in from the right).
  const dir = useDirection(index);

  // Keep the index in the URL so a reload stays put ("/pitch" → "/pitch/0", "/pitch/99" → the last slide).
  useEffect(() => {
    if (params["*"] !== String(index)) navigate(`/pitch/${index}`, { replace: true });
  }, [index, params, navigate]);

  // Where the deck is headed. `go` moves it at once, so a clicker pressed twice before React re-renders still
  // moves twice; any other change of URL (load, back/forward) re-syncs it.
  const target = useRef(index);
  useLayoutEffect(() => {
    target.current = index;
  }, [index]);

  const go = useCallback(
    (to: number) => {
      const next = clampSlide(to, TOTAL);
      if (next === target.current) return;
      target.current = next;
      navigate(`/pitch/${next}`, { replace: true });
    },
    [navigate],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      const action = keyToAction(e, target.current, TOTAL);
      if (!action) return;
      e.preventDefault();
      if (action.type === "go") go(action.to);
      else if (action.type === "exit") navigate("/");
      else toggleFullscreen();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, navigate]);

  useEffect(() => {
    const previous = document.title;
    document.title = `Pitch · ${index + 1}/${TOTAL} · StormCheck`;
    return () => {
      document.title = previous;
    };
  }, [index]);

  // The cover is a large image: start fetching it whichever slide the deck opens on.
  useEffect(() => {
    const img = new Image();
    img.src = COVER_IMAGE;
  }, []);

  const onClick = (e: MouseEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest("a, button, [data-deck-ui]")) return;
    go(clickTarget(e.clientX, window.innerWidth, target.current));
  };

  const { Component, label } = SLIDES[index];

  return (
    <div
      className={cn("fixed inset-0 select-none overflow-hidden bg-[#04070d] text-cloud-50", idle && "cursor-none")}
      onClick={onClick}
      data-testid="pitch-deck"
      data-slide={index}
    >
      <h1 className="sr-only">StormCheck pitch</h1>
      <p className="sr-only" aria-live="polite">
        Slide {index + 1} of {TOTAL}: {label}
      </p>

      <div
        className="absolute left-1/2 top-1/2 overflow-hidden bg-navy-950 shadow-[0_0_0_1px_rgba(200,208,219,0.05)]"
        style={{ width: STAGE_W, height: STAGE_H, transform: `translate(-50%, -50%) scale(${scale})` }}
      >
        <AnimatePresence mode="wait" custom={dir}>
          {ready ? (
            <motion.section
              key={index}
              custom={dir}
              variants={reduce ? SLIDE_STILL : SLIDE_MOTION}
              initial="enter"
              animate="center"
              exit="exit"
              className="absolute inset-0"
              aria-roledescription="slide"
              aria-label={`${index + 1} of ${TOTAL}: ${label}`}
              data-testid={`slide-${SLIDES[index].id}`}
            >
              <Component data={data} />
            </motion.section>
          ) : null}
        </AnimatePresence>
        <Progress index={index} onJump={go} />
      </div>

      {/* Presenter chrome: appears when the pointer moves, gets out of the way when it rests. */}
      <div data-deck-ui className={cn("pointer-events-none absolute inset-0 transition-opacity duration-500", idle ? "opacity-0" : "opacity-100")}>
        <button
          type="button"
          onClick={() => navigate("/")}
          className="pointer-events-auto absolute right-4 top-4 inline-flex items-center gap-2 rounded-full bg-navy-900/80 py-2 pl-3 pr-4 text-[13px] text-cloud-300 ring-1 ring-white/10 backdrop-blur-sm transition-colors hover:text-cloud-50"
          aria-label="Leave the pitch (Esc)"
        >
          <X className="size-4" aria-hidden="true" /> Esc
        </button>
        <button
          type="button"
          onClick={() => go(index - 1)}
          disabled={index === 0}
          className="pointer-events-auto absolute left-3 top-1/2 grid size-11 -translate-y-1/2 place-items-center rounded-full bg-navy-900/70 text-cloud-300 ring-1 ring-white/10 backdrop-blur-sm transition hover:text-cloud-50 disabled:opacity-0"
          aria-label="Previous slide"
        >
          <ChevronLeft className="size-5" aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={() => go(index + 1)}
          disabled={index === TOTAL - 1}
          className="pointer-events-auto absolute right-3 top-1/2 grid size-11 -translate-y-1/2 place-items-center rounded-full bg-navy-900/70 text-cloud-300 ring-1 ring-white/10 backdrop-blur-sm transition hover:text-cloud-50 disabled:opacity-0"
          aria-label="Next slide"
        >
          <ChevronRight className="size-5" aria-hidden="true" />
        </button>
      </div>

      <p className="pointer-events-none absolute inset-x-0 bottom-[max(24px,env(safe-area-inset-bottom))] hidden text-center font-mono text-[11px] uppercase tracking-[0.16em] text-cloud-500 portrait:block">
        Turn sideways for the full slide
      </p>
    </div>
  );
}

/** Dots for every slide plus a quiet counter, bottom right of the stage. */
function Progress({ index, onJump }: { index: number; onJump: (n: number) => void }) {
  return (
    <nav aria-label="Slides" data-deck-ui className="absolute bottom-[64px] right-[112px] flex items-center gap-7">
      <ol className="flex items-center gap-2.5">
        {SLIDES.map((s, i) => (
          <li key={s.id}>
            <button
              type="button"
              onClick={() => onJump(i)}
              aria-label={`Slide ${i + 1}: ${s.label}`}
              aria-current={i === index ? "step" : undefined}
              className="group grid h-[30px] place-items-center px-1"
            >
              <span className={cn("block h-[8px] rounded-full transition-all duration-500", i === index ? "w-[34px] bg-cloud-50" : "w-[8px] bg-white/25 group-hover:bg-white/50")} />
            </button>
          </li>
        ))}
      </ol>
      <span className={cn("w-[96px] text-right font-mono text-[18px] tabular-nums tracking-[0.08em] text-cloud-500", index === 0 && "invisible")}>
        {String(index).padStart(2, "0")} / {String(TOTAL - 1).padStart(2, "0")}
      </span>
    </nav>
  );
}

function toggleFullscreen() {
  if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
  else void document.documentElement.requestFullscreen?.().catch(() => {});
}

/** True after the pointer has rested for `ms`: hides the cursor and the presenter chrome on a projector. */
function useIdle(ms: number) {
  const [idle, setIdle] = useState(false);
  useEffect(() => {
    let timer = window.setTimeout(() => setIdle(true), ms);
    const wake = () => {
      setIdle(false);
      window.clearTimeout(timer);
      timer = window.setTimeout(() => setIdle(true), ms);
    };
    window.addEventListener("pointermove", wake);
    window.addEventListener("pointerdown", wake);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("pointermove", wake);
      window.removeEventListener("pointerdown", wake);
    };
  }, [ms]);
  return idle;
}
