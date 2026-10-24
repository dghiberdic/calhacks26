import Link from "next/link";
import { Logo } from "@/components/ui/Logo";

/** Fixed, quiet, and readable on both grounds via difference blending. */
export function SiteNav() {
  return (
    <>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:text-ink">
        Skip to content
      </a>
      <header className="pointer-events-none fixed inset-x-0 top-0 z-50 flex items-center justify-between px-5 py-5 text-white mix-blend-difference md:px-10">
        <Link href="/" className="pointer-events-auto flex items-center gap-3" aria-label="StormCheck home">
          <Logo className="h-[22px] w-auto" />
          <span className="text-[18px] font-semibold tracking-[-0.01em] [font-stretch:112%]">StormCheck</span>
        </Link>
        <nav className="pointer-events-auto flex items-center gap-6 text-[15px]">
          <Link href="/app/desk" className="hidden opacity-80 transition-opacity hover:opacity-100 md:inline">
            Judge&rsquo;s desk
          </Link>
          <Link href="/app" className="whitespace-nowrap rounded-full px-4 py-2 font-medium shadow-[inset_0_0_0_1.5px_currentColor] transition-colors hover:bg-white hover:text-black">
            <span className="hidden sm:inline">Open the storm night</span>
            <span className="sm:hidden">Open app</span>
          </Link>
        </nav>
      </header>
    </>
  );
}
