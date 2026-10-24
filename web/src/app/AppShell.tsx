import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { BadgeCheck, Clapperboard, CloudLightning, Gavel, GitCommitVertical, Landmark, Menu, MessagesSquare, Plane, Presentation, RotateCcw, ScrollText, X } from "lucide-react";
import { toast } from "sonner";
import { api, apiMode } from "@/api/client";
import { invalidateAfterWrite, useHealth, useQuestions, useStorms } from "@/api/queries";
import { useLiveFeed, useStreamConnection } from "@/api/stream";
import { Logo } from "@/components/brand/Logo";
import { longDate } from "@/lib/format";
import { HERO_STORM, stormName } from "@/lib/storms";
import { cn } from "@/lib/utils";
import { ErrorBoundary } from "./ErrorBoundary";
import { pageTitle } from "./pageTitle";
import { RoleSwitcher } from "./RoleSwitcher";
import { TimeScrubber, useClock } from "./TimeScrubber";
import { useSession } from "./session";

const NAV = [
  { to: "/", label: "Storm Run", icon: CloudLightning, end: true, match: ["/", "/run"] },
  { to: "/flights", label: "Flight File", icon: Plane },
  { to: "/questions", label: "Questions", icon: MessagesSquare, badge: "questions" as const },
  { to: "/policies", label: "Policies", icon: ScrollText },
  { to: "/trace", label: "Trace", icon: GitCommitVertical },
  { to: "/close", label: "Liability & Close", icon: Landmark },
  { to: "/desk", label: "Judge's Desk", icon: Gavel },
  { to: "/proof", label: "Proof", icon: BadgeCheck },
];

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  const open = useQuestions("open");
  const { pathname } = useLocation();
  const openCount = open.data?.length ?? 0;
  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5">
      {NAV.map((item) => {
        const runActive = item.match ? item.match.some((m) => (m === "/" ? pathname === "/" : pathname.startsWith(m))) : undefined;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "group flex h-9 items-center gap-3 rounded-lg px-3 text-[13.5px] transition-colors",
                (runActive ?? isActive) ? "bg-navy-800 text-cloud-50" : "text-cloud-400 hover:bg-navy-850 hover:text-cloud-100",
              )
            }
          >
            <item.icon className="size-4 shrink-0 opacity-90" aria-hidden="true" />
            <span className="flex-1">{item.label}</span>
            {item.badge === "questions" && openCount > 0 ? (
              <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-held px-1.5 font-mono text-[10.5px] font-bold text-navy-950" aria-label={`${openCount} open`}>
                {openCount}
              </span>
            ) : null}
          </NavLink>
        );
      })}
      <div className="my-2 h-px bg-navy-800" />
      <NavLink to="/pitch" onClick={onNavigate} className="flex h-9 items-center gap-3 rounded-lg px-3 text-[13.5px] text-cloud-400 transition-colors hover:bg-navy-850 hover:text-cloud-100">
        <Presentation className="size-4 shrink-0" aria-hidden="true" />
        Pitch
      </NavLink>
      <NavLink to="/story" onClick={onNavigate} className="flex h-9 items-center gap-3 rounded-lg px-3 text-[13.5px] text-cloud-400 transition-colors hover:bg-navy-850 hover:text-cloud-100">
        <Clapperboard className="size-4 shrink-0" aria-hidden="true" />
        The story
      </NavLink>
    </nav>
  );
}

/** Mock / stub / live / recorded, and whether the stream is up: a demo should never be vague about its data. */
function SourceStatus() {
  const mode = apiMode();
  const health = useHealth();
  const status = useLiveFeed((s) => s.status);
  const label =
    mode === "mock" ? "mock data" : mode === "recorded" ? "recorded demo" : health.data ? (String(health.data.mode ?? "") === "stub" ? "contract stub" : `live · ${String(health.data.mode ?? "server")}`) : health.isError ? "server offline" : "connecting";
  const dot = status === "live" ? "bg-tie" : status === "polling" ? "bg-held" : status === "offline" ? "bg-notweather" : "bg-cloud-500";
  return (
    <div className="flex items-center gap-2 px-3 font-mono text-[11px] text-cloud-500" title={`Stream: ${status}`}>
      <span className={cn("size-1.5 rounded-full", dot)} aria-hidden="true" />
      {label}
    </div>
  );
}

function ResetButton() {
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await api.reset();
          useClock.getState().setKnownAt(null);
          await invalidateAfterWrite();
          toast("Demo reset to the baseline");
        } catch (e) {
          toast.error(e instanceof Error ? e.message : "Reset failed.");
        } finally {
          setBusy(false);
        }
      }}
      className="flex items-center gap-2 rounded-md px-3 py-1.5 text-[12px] text-cloud-500 transition-colors hover:bg-navy-850 hover:text-cloud-200 disabled:opacity-50"
    >
      <RotateCcw className="size-3.5" aria-hidden="true" />
      Reset demo
    </button>
  );
}

/** Which storm a URL is about: /run/:id, /flights?storm=:id, or a flight's own date (NS31@2025-01-24). */
function stormFromUrl(pathname: string, search: string, ids: string[]): string | undefined {
  const run = pathname.match(/^\/run\/([^/]+)/)?.[1];
  if (run) return decodeURIComponent(run);
  const q = new URLSearchParams(search).get("storm");
  if (q) return q;
  const flightDate = decodeURIComponent(pathname.match(/^\/flights\/([^/]+)/)?.[1] ?? "").match(/@(\d{4}-\d{2}-\d{2})/)?.[1];
  return flightDate ? ids.find((id) => id.endsWith(`@${flightDate}`)) : undefined;
}

function StormContext() {
  const storms = useStorms();
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const ids = storms.data?.map((s) => s.id) ?? [];
  const current = stormFromUrl(pathname, search, ids) ?? (ids.includes(HERO_STORM) ? HERO_STORM : ids[0]);
  const storm = storms.data?.find((s) => s.id === current) ?? storms.data?.[0];
  if (!storm) return <span className="h-5 w-48 animate-pulse rounded bg-cloud-100" aria-hidden="true" />;
  return (
    <label className="flex min-w-0 items-center gap-2 text-[13.5px]">
      <span className="sr-only">Storm</span>
      <select
        value={storm.id}
        // The flights list stays the flights list; everywhere else the storm's run is the place to land.
        onChange={(e) => navigate(pathname === "/flights" ? `/flights?storm=${encodeURIComponent(e.target.value)}` : `/run/${encodeURIComponent(e.target.value)}`)}
        className="min-w-0 max-w-full cursor-pointer truncate rounded-md bg-transparent py-1 pr-1 font-medium text-navy-900 outline-none hover:bg-cloud-50"
      >
        {storms.data?.map((s) => (
          <option key={s.id} value={s.id}>
            {stormName(s.id) ?? s.id} · {s.station} · {longDate(s.date)}
          </option>
        ))}
      </select>
    </label>
  );
}

export function AppShell() {
  useStreamConnection();
  const restore = useSession((s) => s.restore);
  const knownAt = useClock((s) => s.knownAt);
  const [menu, setMenu] = useState(false);
  const { pathname } = useLocation();

  useEffect(() => {
    void restore();
  }, [restore]);
  useEffect(() => setMenu(false), [pathname]);
  useEffect(() => {
    document.title = pageTitle(pathname);
  }, [pathname]);

  return (
    <div className="min-h-svh bg-background lg:grid lg:grid-cols-[236px_minmax(0,1fr)]">
      {/* Sidebar (desktop) */}
      <aside className="sticky top-0 hidden h-svh flex-col bg-navy-900 px-3 pb-3 pt-4 lg:flex">
        <NavLink to="/" className="mb-6 flex items-center gap-2.5 px-3 text-cloud-50" aria-label="StormCheck, Storm Run">
          <Logo className="h-[17px] w-auto" />
          <span className="text-[16px] font-semibold tracking-[-0.01em] [font-stretch:112%]">StormCheck</span>
        </NavLink>
        <NavItems />
        <div className="mt-auto flex flex-col gap-1.5 border-t border-navy-800 pt-3">
          <p className="px-3 text-[11.5px] leading-snug text-cloud-500">Northstar Air · drafts only, never pays</p>
          <SourceStatus />
          <ResetButton />
        </div>
      </aside>

      {/* Mobile nav sheet */}
      {menu ? (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button type="button" className="absolute inset-0 bg-navy-950/40" aria-label="Close menu" onClick={() => setMenu(false)} />
          <div className="absolute inset-y-0 left-0 flex w-[260px] flex-col bg-navy-900 px-3 pb-3 pt-4">
            <div className="mb-6 flex items-center justify-between px-3 text-cloud-50">
              <span className="flex items-center gap-2.5">
                <Logo className="h-[16px] w-auto" />
                <span className="text-[16px] font-semibold [font-stretch:112%]">StormCheck</span>
              </span>
              <button type="button" onClick={() => setMenu(false)} aria-label="Close menu" className="text-cloud-400">
                <X className="size-5" />
              </button>
            </div>
            <NavItems onNavigate={() => setMenu(false)} />
            <div className="mt-auto flex flex-col gap-1.5 border-t border-navy-800 pt-3">
              <SourceStatus />
              <ResetButton />
            </div>
          </div>
        </div>
      ) : null}

      <div className="min-w-0">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-cloud-200 bg-background/85 px-4 backdrop-blur-md md:px-6">
          <button type="button" onClick={() => setMenu(true)} className="-ml-1 rounded-md p-1.5 text-slate-500 hover:bg-cloud-100 lg:hidden" aria-label="Open menu">
            <Menu className="size-5" />
          </button>
          <div className="min-w-0 flex-1">
            <StormContext />
          </div>
          {knownAt ? <span className="hidden font-mono text-[11px] text-slate-400 xl:inline">replaying with the facts known then</span> : null}
          <TimeScrubber />
          <RoleSwitcher />
        </header>
        <main id="main" className="px-4 pb-20 pt-6 md:px-6 xl:px-8">
          <ErrorBoundary key={pathname} label={pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
