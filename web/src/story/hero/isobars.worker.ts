// Contours every 15 minutes of the hero's loop off the main thread: ERA5 hours in, isobars and centres out.
import { blendInto, LOOP } from "./loop";
import { contourField, type Chart, type Grid } from "./synoptic";

export type IsobarJob = { mslp: Float32Array[]; grid: Grid; steps: number; from: number };
export type IsobarResult = { step: number; chart: Chart };

const scope = self as unknown as { onmessage: ((e: MessageEvent<IsobarJob>) => void) | null; postMessage: (m: IsobarResult[]) => void };

scope.onmessage = (e) => {
  const { mslp, grid, steps, from } = e.data;
  const field = new Float32Array(grid.nx * grid.ny);
  let batch: IsobarResult[] = [];
  // the steps the clock reaches first come first
  for (let n = 0; n < steps; n++) {
    const step = (from + n) % steps;
    blendInto(field, mslp, step * LOOP.scan);
    batch.push({ step, chart: contourField(field, grid) });
    if (batch.length === 4 || n === steps - 1) {
      scope.postMessage(batch);
      batch = [];
    }
  }
};
