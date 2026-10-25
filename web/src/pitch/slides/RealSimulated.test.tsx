import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { EvalReport } from "@/api/types";
import { RealSimulated } from "./RealSimulated";

afterEach(cleanup);

describe("pitch proof", () => {
  it("labels a missing baseline as not run rather than showing loading figures", () => {
    render(<RealSimulated data={{ evalReport: {
      split: {}, baseline: { liability_eur: [] },
      stormcheck_runs: { liability_eur: [34650, 34650, 34650], hash_identical: true },
      label: "Synthetic test cases; not airline validation.",
    } as unknown as EvalReport }} />);
    expect(screen.getByText("Not run yet")).toBeInTheDocument();
    expect(screen.getByText("same number, same hash, every run")).toBeInTheDocument();
    expect(screen.getByText("Synthetic test cases; not airline validation.")).toBeInTheDocument();
  });

  it("describes the method without claiming results when evaluation is unavailable", () => {
    render(<RealSimulated data={{ evalFailed: true }} />);
    expect(screen.getByText("Results unavailable")).toBeInTheDocument();
    expect(screen.queryByText("same number, same hash, every run")).not.toBeInTheDocument();
  });
});
