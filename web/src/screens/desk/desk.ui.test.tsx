import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { setTransport, type ApiFetch } from "@/api/client";
import type { InjectResponse } from "@/api/types";
import { DayForm } from "./DayForm";
import { InjectResult } from "./InjectResult";
import { useDesk } from "./state";
import { useLiveFeed } from "@/api/stream";

const initial = useDesk.getState();

// These drive real typing through cmdk and motion; on a busy machine that outlasts vitest's 5 s default.
vi.setConfig({ testTimeout: 20_000 });
const typist = () => userEvent.setup({ delay: null });

beforeAll(() => {
  // jsdom lacks these; cmdk and motion reach for them.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  Element.prototype.scrollIntoView ??= () => {};
  window.matchMedia ??= ((q: string) => ({ matches: false, media: q, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as typeof window.matchMedia;
});

beforeEach(() => useDesk.setState(initial, true));
afterEach(() => {
  cleanup();
  setTransport((path, init) => fetch(`/api${path}`, init));
});

const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("the day form", () => {
  it("types an airport and a local date; Enter posts the ICAO and that date; a 422 is said inline", async () => {
    const calls: { path: string; body: unknown }[] = [];
    const transport: ApiFetch = async (path, init) => {
      calls.push({ path, body: init.body ? JSON.parse(String(init.body)) : null });
      return reply(422, { error: { code: "future_date", message: "1 Jan 2099 hasn't happened yet at Dublin, so there's no METAR to read." } });
    };
    setTransport(transport);
    render(<DayForm />);
    const user = typist();

    await user.click(screen.getByRole("combobox", { name: "Airport" }));
    await user.keyboard("dub{Enter}");
    const date = screen.getByLabelText("Local date");
    await waitFor(() => expect(date).toHaveFocus()); // picking moves on to the date
    await user.type(date, "1 Jan 2099{Enter}");

    await waitFor(() => expect(calls.some((c) => c.path === "/desk")).toBe(true));
    expect(calls.find((c) => c.path === "/desk")?.body).toEqual({ icao: "EIDW", date: "2099-01-01" });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("1 Jan 2099 hasn't happened yet at Dublin, so there's no METAR to read.");
    expect(alert).toHaveAttribute("data-code", "future_date");
    expect(date).toHaveAttribute("aria-invalid", "true");
    // Leaving the field without changing it keeps the message: it's still true.
    await user.tab();
    expect(screen.getByRole("alert")).toHaveTextContent("hasn't happened yet");
  });

  it("the airport list is keyboard-driven: arrows move, Enter picks, an unlisted ICAO can be used as typed", async () => {
    setTransport(async () => reply(200, {}));
    render(<DayForm />);
    const user = typist();
    const airport = screen.getByRole("combobox", { name: "Airport" });
    await user.click(airport);
    await user.keyboard("london");
    const options = await screen.findAllByRole("option");
    expect(options[0]).toHaveAccessibleName("LHR · EGLL · London Heathrow");
    await user.keyboard("{ArrowDown}{Enter}");
    expect(useDesk.getState().airport?.icao).toBe("EGKK");
    await waitFor(() => expect(screen.getByLabelText("Local date")).toHaveFocus());

    await user.click(airport);
    await user.keyboard("{Control>}a{/Control}KXYZ");
    expect(await screen.findByRole("option", { name: /Use KXYZ as typed/ })).toBeInTheDocument();
    await user.keyboard("{Enter}");
    expect(useDesk.getState().airport).toEqual({ icao: "KXYZ" });
  });

  it("'/' from the page goes to the airport field, but not while typing elsewhere", async () => {
    setTransport(async () => reply(200, {}));
    render(
      <>
        <DayForm />
        <textarea aria-label="elsewhere" />
      </>,
    );
    const user = typist();
    await user.keyboard("/");
    expect(screen.getByRole("combobox", { name: "Airport" })).toHaveFocus();
    await user.click(screen.getByLabelText("elsewhere"));
    await user.keyboard("/");
    expect(screen.getByLabelText("elsewhere")).toHaveFocus();
    expect(screen.getByLabelText("elsewhere")).toHaveValue("/");
  });

  it("asks for what's missing without calling the server", async () => {
    const calls: string[] = [];
    setTransport(async (path) => {
      calls.push(path);
      return reply(200, {});
    });
    render(<DayForm />);
    await typist().click(screen.getByRole("button", { name: /Run the day/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Name an airport first.");
    expect(calls).not.toContain("/desk");
  });

  it("says plainly when the server can't be reached, and keeps the form", async () => {
    setTransport(async () => {
      throw new TypeError("Failed to fetch");
    });
    render(<DayForm />);
    const user = typist();
    await user.click(screen.getByRole("button", { name: /Storm Éowyn/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Can't reach the StormCheck server.");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Run the day/ })).toBeEnabled();
  });
});

describe("an injection's answer", () => {
  const text = "23JAN 21:40Z EI-NSB DUB N/S. EXT LEAK EDP CASE DRAIN PORT, EXCEEDS AMM LIMIT. NO MEL RELIEF. A/C AOG.";
  const response: InjectResponse = {
    source: { id: "src:inject:1", kind: "tech_log", title: "Tech log pasted at the desk", text, sha256: "ab12cd34ef", received_at: "2025-01-25T09:00:00Z", trust_tier: 1, acl_tags: [] },
    facts: [
      { id: "f1", source_id: "src:inject:1", subject: "aircraft:EI-NSB", field: "aog.logged_at", value: "2025-01-23T21:40:00Z", span: "23JAN 21:40Z", extractor: "fallback:regex@1", recorded_at: "2025-01-25T09:00:00Z" },
      { id: "f2", source_id: "src:inject:1", subject: "aircraft:EI-NSB", field: "aog.mel_relief", value: false, span: "NO MEL RELIEF", extractor: "fallback:regex@1", recorded_at: "2025-01-25T09:00:00Z" },
    ],
    dropped_unverifiable: 2,
    events: [{ seq: 501, at: "2025-01-25T09:00:01Z", kind: "fact", actor: "agent.reader", summary: "2 facts recorded from the tech log", ref: "src:inject:1", chip: "APPLIED" }],
    affected: ["NS31@2025-01-24"],
    fallback_used: true,
    message: null,
  };

  it("lights each quoted span in the text, counts what was dropped, and labels the fallback", () => {
    render(
      <MemoryRouter>
        <InjectResult request={{ kind: "tech_log", text, flight_id: "NS31@2025-01-24" }} response={response} startSeq={500} before={{}} after={null} />
      </MemoryRouter>,
    );
    const doc = screen.getByTestId("inject-document");
    const marks = [...doc.querySelectorAll("mark")].map((m) => m.textContent?.replace(/\d+$/, ""));
    expect(marks).toEqual(["23JAN 21:40Z", "NO MEL RELIEF"]);
    expect(screen.getByTestId("inject-dropped")).toHaveTextContent("2 facts didn't quote the text verbatim and were dropped.");
    expect(screen.getByTestId("inject-fallback")).toHaveTextContent("Reader timed out; used the labelled regex fallback.");
    expect(screen.getByTestId("inject-affected")).toHaveTextContent("NS31");
    expect(screen.getByRole("link", { name: /NS31/ })).toHaveAttribute("href", "/flights/NS31%402025-01-24");
  });

  it("writes money and nested values the way a person reads them", () => {
    const claim = "Claim under UK261 for GBP 520 for flight NS100 Dublin to London Heathrow on 24 Jan 2025.";
    const res: InjectResponse = {
      ...response,
      source: { ...response.source, kind: "claim", text: claim, trust_tier: 4 },
      facts: [
        { id: "c1", source_id: "s", subject: "flight:NS100@2025-01-24", field: "claim.amount", value: { currency: "GBP", amount_cents: 52000 }, span: "GBP 520", extractor: "llm:claude-opus-5-5@reader-v1", recorded_at: "2025-01-25T09:00:00Z" },
        { id: "c2", source_id: "s", subject: "flight:NS100@2025-01-24", field: "claim.regime", value: "UK261", span: "UK261", extractor: "llm:claude-opus-5-5@reader-v1", recorded_at: "2025-01-25T09:00:00Z" },
      ],
      dropped_unverifiable: 0,
      fallback_used: false,
    };
    render(
      <MemoryRouter>
        <InjectResult request={{ kind: "claim", text: claim, flight_id: "NS100@2025-01-24" }} response={res} startSeq={500} before={{}} after={null} />
      </MemoryRouter>,
    );
    const facts = screen.getByTestId("inject-facts");
    expect(facts).toHaveTextContent("£520");
    expect(facts).not.toHaveTextContent("amount_cents");
    expect(screen.getByTestId("inject-dropped")).toHaveTextContent("Every fact kept quotes the text word for word.");
    expect(screen.queryByTestId("inject-fallback")).toBeNull();
  });

  it("streams later events about what it touched, never replayed history or unrelated news", async () => {
    useLiveFeed.setState({ events: [], lastSeq: 0 });
    render(
      <MemoryRouter>
        <InjectResult request={{ kind: "tech_log", text, flight_id: "NS31@2025-01-24" }} response={response} startSeq={500} before={{}} after={null} />
      </MemoryRouter>,
    );
    const ev = (seq: number, ref: string, summary: string) => ({ seq, at: "2025-01-25T09:00:02Z", kind: "decision" as const, actor: "agent.engine", summary, ref, chip: "APPLIED" as const });
    useLiveFeed.getState().add([ev(499, "NS31@2025-01-24", "an old NS31 event replayed late"), ev(510, "NS31@2025-01-24", "NS31 re-decided after the read"), ev(511, "NS100@2025-01-24", "something about NS100")]);
    const list = await screen.findByTestId("inject-events");
    await waitFor(() => expect(list).toHaveTextContent("NS31 re-decided after the read"), { timeout: 4000 });
    expect(list).toHaveTextContent("2 facts recorded from the tech log");
    expect(list).not.toHaveTextContent("an old NS31 event replayed late");
    expect(list).not.toHaveTextContent("something about NS100");
  });
});
