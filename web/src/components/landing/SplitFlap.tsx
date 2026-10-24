"use client";

import { memo, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";

const CHARSET = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:.,-€/";

/** One Solari flap. Steps through the drum until it reaches `value`. */
export const FlapCell = memo(function FlapCell({
  value,
  delay = 0,
  step = 64,
  className,
}: {
  value: string;
  delay?: number;
  step?: number;
  className?: string;
}) {
  const target = CHARSET.includes(value) ? value : " ";
  const [cur, setCur] = useState(" ");
  const [next, setNext] = useState(" ");
  const [flip, setFlip] = useState(0); // increments per flap so the keyed spans restart their animation
  const curRef = useRef(" ");

  useEffect(() => {
    let cancelled = false;
    const timers: number[] = [];
    const from = CHARSET.indexOf(curRef.current);
    const to = CHARSET.indexOf(target);
    if (from === to) return;
    const seq: string[] = [];
    for (let i = (from + 1) % CHARSET.length; ; i = (i + 1) % CHARSET.length) {
      seq.push(CHARSET[i]);
      if (i === to) break;
    }
    // Long drums would take seconds; real boards skip ahead visually, so do we.
    const trimmed = seq.length > 9 ? [...seq.slice(0, 4), ...seq.slice(-5)] : seq;
    trimmed.forEach((c, i) => {
      timers.push(
        window.setTimeout(() => {
          if (cancelled) return;
          setNext(c);
          setFlip((f) => f + 1);
          timers.push(
            window.setTimeout(() => {
              if (cancelled) return;
              curRef.current = c;
              setCur(c);
            }, step),
          );
        }, delay + i * step),
      );
    });
    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  }, [target, delay, step]);

  const flipping = next !== cur;
  return (
    <span className={cn("flap-cell", className)} aria-hidden="true">
      <span className="flap-half flap-top">
        <span>{flipping ? next : cur}</span>
      </span>
      <span className="flap-half flap-bottom">
        <span>{cur}</span>
      </span>
      {flipping && (
        <>
          <span key={`f${flip}`} className="flap-half flap-leaf-front" style={{ animationDuration: `${step / 2}ms` }}>
            <span>{cur}</span>
          </span>
          <span
            key={`b${flip}`}
            className="flap-half flap-leaf-back"
            style={{ animationDuration: `${step / 2}ms`, animationDelay: `${step / 2}ms` }}
          >
            <span>{next}</span>
          </span>
        </>
      )}
      <span className="flap-axis" />
    </span>
  );
});

export function FlapText({
  text,
  width,
  delay = 0,
  stagger = 28,
  className,
  cellClassName,
}: {
  text: string;
  width: number;
  delay?: number;
  stagger?: number;
  className?: string;
  cellClassName?: string;
}) {
  const padded = text.toUpperCase().padEnd(width, " ").slice(0, width);
  return (
    <span className={cn("inline-flex gap-[0.08em]", className)} role="text" aria-label={text}>
      {Array.from(padded).map((c, i) => (
        <FlapCell key={i} value={c} delay={delay + i * stagger} className={cellClassName} />
      ))}
    </span>
  );
}
