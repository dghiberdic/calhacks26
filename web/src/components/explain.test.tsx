import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TooltipProvider } from "@/components/ui/tooltip";
import { GLOSSARY, type Term } from "@/lib/glossary";
import { Explain, Glossary, WhatsThis } from "./explain";
import { Details } from "./kit";

beforeAll(() => {
  // Radix measures the tooltip's arrow; jsdom has no ResizeObserver.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});
afterEach(cleanup);
const wrap = (ui: React.ReactNode) => render(<TooltipProvider delayDuration={0}>{ui}</TooltipProvider>);

describe("glossary", () => {
  it("has every term the screens explain, each a sentence or two in plain words", () => {
    const needed: Term[] = ["eu261", "extraordinary", "metar", "storm-window", "tech-log", "aog", "no-mel-relief", "delay-codes", "knock-on", "voucher-in-lieu", "cash-basis", "full-entitlement", "drafted-liability", "claim-rate", "liability-2140", "dr-cr", "ifrs15", "confidence", "sources-disagree", "no-precedent", "preparer-approver"];
    for (const t of needed) expect(GLOSSARY[t].plain.length, t).toBeGreaterThan(30);
  });
  it("keeps plan §9 wording and the house style", () => {
    const all = Object.values(GLOSSARY).map((e) => `${e.term} ${e.plain}`).join(" ");
    expect(all).not.toMatch(/provision|worst case|\$\d|gate voucher|—/i);
  });
});

describe("Explain", () => {
  it("shows the plain meaning when the word is tapped", async () => {
    wrap(<p>Real <Explain term="metar">METAR</Explain> for the day.</p>);
    await userEvent.click(screen.getByRole("button", { name: "METAR" }));
    expect((await screen.findAllByText(/official airport weather report/)).length).toBeGreaterThan(0);
  });
  it("labels the question mark with the term", () => {
    wrap(<WhatsThis term="claim-rate" />);
    expect(screen.getByRole("button", { name: "What's this? Claim rate" })).toBeInTheDocument();
  });
  it("writes meanings out in a list", () => {
    wrap(<Glossary terms={["cash-basis", "full-entitlement"]} />);
    expect(screen.getByText("Cash basis:")).toBeInTheDocument();
    expect(screen.getByText(/every passenger claims/)).toBeInTheDocument();
  });
});

describe("Details", () => {
  it("starts closed and opens on click", async () => {
    wrap(<Details summary="How we got this"><p>35% × €99,000</p></Details>);
    const details = screen.getByText("How we got this").closest("details")!;
    expect(details.open).toBe(false);
    await userEvent.click(screen.getByText("How we got this"));
    expect(details.open).toBe(true);
  });
});
