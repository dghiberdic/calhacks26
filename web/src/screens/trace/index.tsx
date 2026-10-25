import { useEffect, type ReactNode } from "react";
import { useSearchParams } from "react-router";
import { MotionConfig } from "motion/react";
import { Explain } from "@/components/explain";
import { PageHeader } from "@/components/kit";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AccessTab } from "./AccessTab";
import { BlameTab } from "./BlameTab";
import { CommitsTab } from "./CommitsTab";
import { ControlsTab } from "./ControlsTab";
import { LiveTab } from "./LiveTab";
import { TABS, TAB_LABEL, isTab, tabForTarget, type TraceTab } from "./model";

/** What each tab is for, in a line. Access and Controls open with their own. */
const TAB_INTRO: Partial<Record<TraceTab, ReactNode>> = {
  live: "Recent actions across all runs. Repeated steps are grouped.",
  commits: (
    <>
      Each record is linked to the previous one by a <Explain term="trace">hash chain</Explain>, so edits to earlier records can be detected.
    </>
  ),
  blame: (
    <>
      Follow an amount to its <Explain term="blame">source evidence</Explain>: the calculation, policy, human ruling and original record.
    </>
  ),
};

/** J5 · Trace: the whole live trace (Live), the git-like record (Commits, Blame), who may do what (Access) and the SOC 2 mapping (Controls). */
export default function TraceScreen() {
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab");
  const target = params.get("target");
  // A bare ?target= (Flight File, Questions) opens its blame, or a question's events.
  const tab: TraceTab = isTab(raw) ? raw : target ? tabForTarget(target) : "live";

  useEffect(() => {
    document.title = `${TAB_LABEL[tab]} · Trace · StormCheck`;
  }, [tab]);

  const select = (value: string) => {
    if (!isTab(value)) return;
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("tab", value);
        if (value !== "blame" && value !== "live") next.delete("target");
        if (value !== "commits") {
          next.delete("commit");
          next.delete("q");
        }
        return next;
      },
      { replace: true },
    );
  };

  return (
    <MotionConfig reducedMotion="user">
      <div className="mx-auto max-w-[1120px]">
        <PageHeader title="Audit trail">See the evidence behind a decision, who approved it, and what changed.</PageHeader>
        <Tabs value={tab} onValueChange={select} className="mt-6 gap-0">
          <TabsList variant="line" className="h-auto w-full justify-start gap-0.5 rounded-none border-b border-cloud-200 p-0 sm:gap-1">
            {TABS.map((t) => (
              <TabsTrigger
                key={t}
                value={t}
                className="h-10 flex-none rounded-none border-0 px-2.5 text-[14px] font-medium text-slate-500 after:absolute after:inset-x-2! after:bottom-[-1px]! after:h-[2px]! after:rounded-full after:bg-navy-900 sm:px-3 hover:text-navy-900 data-[state=active]:text-navy-900 data-[state=active]:after:opacity-100 focus-visible:ring-0 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-metar-ink"
              >
                {TAB_LABEL[t]}
              </TabsTrigger>
            ))}
          </TabsList>
          {TABS.map((t) => (
            <TabsContent key={t} value={t} className="pt-6 text-[14px]">
              {TAB_INTRO[t] ? <p className="-mt-1 mb-4 max-w-[80ch] text-[13.5px] leading-relaxed text-slate-500">{TAB_INTRO[t]}</p> : null}
              {t === "live" ? <LiveTab /> : t === "commits" ? <CommitsTab /> : t === "blame" ? <BlameTab /> : t === "access" ? <AccessTab /> : <ControlsTab />}
            </TabsContent>
          ))}
        </Tabs>
      </div>
    </MotionConfig>
  );
}
