import { afterEach, describe, expect, it } from "vitest";
import { ApiError, api, setTransport } from "./client";

const json = (status: number, body: unknown) => async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => setTransport((path, init) => fetch(`/api${path}`, init)));

describe("api client", () => {
  it("returns typed JSON on success", async () => {
    setTransport(json(200, { ok: true, mode: "stub", impl: {} }));
    await expect(api.health()).resolves.toMatchObject({ ok: true });
  });
  it("turns the error envelope into a plain ApiError", async () => {
    setTransport(json(422, { error: { code: "future_date", message: "That date hasn't happened yet." } }));
    const err = await api.desk("EIDW", "2030-01-01").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422);
    expect(err.code).toBe("future_date");
    expect(err.message).toBe("That date hasn't happened yet.");
    expect(err.isUserFacing).toBe(true);
  });
  it("never surfaces a 500's internals", async () => {
    setTransport(async () => new Response("Traceback (most recent call last)…", { status: 500 }));
    const err = await api.storms().catch((e) => e);
    expect(err.message).toBe("The server had a problem. Nothing was changed.");
  });
  it("says so when the server can't be reached", async () => {
    setTransport(async () => {
      throw new TypeError("fetch failed");
    });
    const err = await api.storms().catch((e) => e);
    expect(err.code).toBe("network");
  });
});
