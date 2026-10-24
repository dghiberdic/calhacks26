/**
 * A320-family hydraulic architecture, schematic (not structural), on the plan view in metres:
 * x aft of the radome tip, y to port (+) / starboard (−), matching TOP_LINES (port is +y, drawn below
 * the centreline with the nose to the left).
 *
 * Green: engine 1 (port) driven pump, plus the PTU. Yellow: engine 2 (starboard) driven pump, plus an
 * electric pump. Blue: electric pump, plus the RAT. EI-NSB's tech log reads "ECAM HYD Y ENG 2 PUMP LO PR":
 * the yellow system's engine-2 pump, leaking at its case drain port.
 */
export const A321 = { length: 44.51, span: 35.8, height: 11.76 } as const;

/** Nacelle centre lines on the plan view (LEAP-1A), metres. */
const ENG_X = 17.6;
const ENG_Y = 5.75;

const P = (x: number, y: number) => `${+x.toFixed(3)},${+y.toFixed(3)}`;

export type HydSystem = "green" | "blue" | "yellow";

export const HYDRAULICS: Record<HydSystem, { label: string; pump: string; d: string }> = {
  green: {
    label: "Green",
    pump: "ENG 1 EDP",
    d: [
      `M${P(ENG_X, ENG_Y)} L${P(20.4, 4.9)} L${P(22.9, 0.9)}`, // engine 1 pump → reservoir
      `M${P(22.9, 0.9)} L${P(5.4, 0.9)}`, // forward to the nose gear
      `M${P(22.9, 0.9)} L${P(40.2, 0.9)} L${P(42.2, 4.6)}`, // aft to the elevator
      `M${P(40.2, 0.9)} L${P(42.3, 0)}`, // rudder
      `M${P(22.9, 0.9)} L${P(24.6, 6.3)} L${P(27.2, 14.6)}`, // port aileron
      `M${P(22.9, 0.9)} L${P(24.6, -6.3)} L${P(27.2, -14.6)}`, // starboard aileron
    ].join(" "),
  },
  blue: {
    label: "Blue",
    pump: "ELEC PUMP",
    d: [
      `M${P(23.6, 0)} L${P(41.0, 0)} L${P(42.0, 3.8)}`,
      `M${P(41.0, 0)} L${P(42.0, -3.8)}`,
      `M${P(23.6, 0)} L${P(25.4, 9.8)} L${P(26.6, 13.0)}`,
      `M${P(23.6, 0)} L${P(25.4, -9.8)} L${P(26.6, -13.0)}`,
      `M${P(23.6, 0)} L${P(24.4, -2.5)}`, // RAT
    ].join(" "),
  },
  yellow: {
    label: "Yellow",
    pump: "ENG 2 EDP",
    d: [
      `M${P(ENG_X, -ENG_Y)} L${P(20.4, -4.9)} L${P(22.9, -0.9)}`, // engine 2 pump → reservoir
      `M${P(22.9, -0.9)} L${P(40.6, -0.9)} L${P(42.6, -4.8)}`,
      `M${P(22.9, -0.9)} L${P(23.9, -6.9)} L${P(25.1, -11.6)}`,
      `M${P(22.9, -0.9)} L${P(23.9, 6.9)} L${P(25.1, 11.6)}`,
      `M${P(22.9, -0.9)} L${P(6.2, -0.9)}`,
    ].join(" "),
  },
};

/** Where EI-NSB's leak is: the engine-2 (starboard) driven pump, on the yellow system. */
export const LEAK = { system: "yellow" as HydSystem, x: ENG_X, y: -ENG_Y, label: "ENG 2 EDP" };
