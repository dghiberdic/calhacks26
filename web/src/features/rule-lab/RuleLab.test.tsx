import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import scoped from "./recorded/scoped.json";
import broader from "./recorded/broader_scope.json";
import authority from "./recorded/wrong_authority.json";
import { RuleLab } from "./RuleLab";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function show() {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  return render(<QueryClientProvider client={client}><RuleLab /></QueryClientProvider>);
}

it("lets a reviewer inspect a passing candidate and then its scope failure", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify(url.includes("broader_scope") ? broader : scoped)))));
  show();
  expect(await screen.findByRole("heading", {name: "Ready for human review"})).toBeInTheDocument();
  expect(screen.getByText("Live checks · simulated cases")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", {name: "Widen the scope"}));
  expect(await screen.findByRole("heading", {name: "Candidate blocked"})).toBeInTheDocument();
  const detail = within(screen.getByRole("region", {name: "Case evidence"}));
  expect(detail.getByText("NS30@2025-01-25:23F")).toBeInTheDocument();
  expect(detail.getByText("Needs a ruling")).toBeInTheDocument();
  expect(detail.getByText("Owed")).toBeInTheDocument();
  expect(screen.queryByRole("button", {name: /approve|confirm/i})).not.toBeInTheDocument();
});

it("shows the authority stop without displaying stale case or accounting results", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify(url.includes("wrong_authority") ? authority : scoped)))));
  show();
  await screen.findByRole("heading", {name: "Ready for human review"});
  await userEvent.click(screen.getByRole("button", {name: "Change the author"}));
  expect(await screen.findByText("No candidate simulation ran.")).toBeInTheDocument();
  expect(screen.queryByRole("region", {name: "Case evidence"})).not.toBeInTheDocument();
  expect(screen.getByText("Not run")).toBeInTheDocument();
});

it("identifies saved evidence and never presents it as a fresh run", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  show();
  expect(await screen.findByText("Saved evidence · simulated cases")).toBeInTheDocument();
  expect(screen.getByText("Saved from the real lab runner. A fresh run has not been performed here.")).toBeInTheDocument();
  expect(screen.getByRole("button", {name: "Refresh evidence"})).toBeInTheDocument();
});
