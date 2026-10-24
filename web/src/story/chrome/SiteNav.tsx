import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Logo } from "@/components/brand/Logo";
import { cn } from "@/lib/utils";

/**
 * Fixed, quiet, and readable on night and paper alike (difference blending). It slides away while
 * you scroll down through the story, so headings never run under it, and comes back on the way up.
 */
export function SiteNav() {
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    let last = window.scrollY;
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const y = window.scrollY;
        if (Math.abs(y - last) < 8) return; // ignore jitter and smooth-scroll settling
        setHidden(y > last && y > 160);
        last = y;
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <>
      <a href="#story-main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:text-navy-900">
        Skip to the story
      </a>
      <header
        className={cn(
          "pointer-events-none fixed inset-x-0 top-0 z-50 flex items-center justify-between px-5 py-4 text-white mix-blend-difference transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] focus-within:translate-y-0 motion-reduce:transition-none md:px-10 md:py-5",
          hidden && "-translate-y-full",
        )}
      >
        <Link to="/" className="pointer-events-auto flex items-center gap-2.5" aria-label="StormCheck: open the storm run">
          <Logo className="h-[20px] w-auto" />
          <span className="text-[17px] font-semibold tracking-[-0.01em] [font-stretch:112%]">StormCheck</span>
        </Link>
        <nav className="pointer-events-auto flex items-center gap-5 text-[14.5px]" aria-label="Story">
          <Link to="/pitch" className="hidden opacity-80 transition-opacity hover:opacity-100 sm:inline">
            Pitch
          </Link>
          <Link to="/" className="whitespace-nowrap rounded-full px-4 py-2 font-medium shadow-[inset_0_0_0_1.5px_currentColor] transition-colors hover:bg-white hover:text-black">
            <span className="hidden sm:inline">Open the storm run</span>
            <span className="sm:hidden">Open app</span>
          </Link>
        </nav>
      </header>
    </>
  );
}
