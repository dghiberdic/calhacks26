import { describe, expect, it } from "vitest";
import { pageTitle } from "./pageTitle";

describe("page titles", () => {
  it("names the page, then the product", () => {
    expect(pageTitle("/")).toBe("Storm Run · StormCheck");
    expect(pageTitle("/run/EIDW%402025-01-26")).toBe("Storm Run · StormCheck");
    expect(pageTitle("/flights")).toBe("Flight File · StormCheck");
    expect(pageTitle("/flights/NS31%402025-01-24")).toBe("NS31 · Flight File · StormCheck");
    expect(pageTitle("/close")).toBe("Liability & Close · StormCheck");
    expect(pageTitle("/nowhere")).toBe("Not on the board · StormCheck");
  });
});
