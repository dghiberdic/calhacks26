"use client";

import { useEffect, useRef } from "react";

// Open dialogs, innermost last: only the topmost one reacts to Escape and traps Tab.
const stack: symbol[] = [];

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Escape-to-close (topmost only), focus moved in on open, Tab trapped, focus restored on close. */
export function useDialog<T extends HTMLElement>(open: boolean, onClose: () => void) {
  const ref = useRef<T>(null);
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const id = Symbol("dialog");
    stack.push(id);
    const previous = document.activeElement as HTMLElement | null;
    const focusTimer = window.setTimeout(() => {
      const el = ref.current;
      if (!el) return;
      const first = el.querySelector<HTMLElement>("[data-autofocus]") ?? el.querySelector<HTMLElement>(FOCUSABLE);
      (first ?? el).focus({ preventScroll: true });
    }, 40);

    const onKey = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== id) return;
      if (e.key === "Escape") {
        e.preventDefault();
        close.current();
        return;
      }
      if (e.key === "Tab" && ref.current) {
        const items = [...ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((n) => n.offsetParent !== null);
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener("keydown", onKey);
      const i = stack.indexOf(id);
      if (i >= 0) stack.splice(i, 1);
      previous?.focus?.({ preventScroll: true });
    };
  }, [open]);

  return ref;
}

/** True while any dialog is open (keyboard shortcuts elsewhere should stand down). */
export const dialogOpen = () => stack.length > 0;
