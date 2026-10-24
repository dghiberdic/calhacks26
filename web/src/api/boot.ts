import { apiMode, setTransport } from "./client";

/** Wire the transport for this load before the first query runs. */
export async function bootApi() {
  const mode = apiMode();
  if (mode === "mock") {
    const { createMockFetch } = await import("@/mocks");
    setTransport(createMockFetch());
  } else if (mode === "recorded") {
    const { createRecordedFetch } = await import("./recorded");
    setTransport(createRecordedFetch());
  }
  return mode;
}
