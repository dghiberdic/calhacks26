// Airbus A321neo line geometry in metres, derived from the Airbus Aircraft
// Characteristics (AC) document. Used for the blueprint drawings and as the
// fallback when Blender-exported line art is unavailable.
//
// Coordinate systems
//   side view:  x = metres aft of the radome tip, y = metres above ground (SVG flips it)
//   top view:   x = metres aft of the radome tip, y = metres to starboard (+) / port (-)

export type Stroke = {
  d: string;
  /** outline: silhouette, detail: panel lines/windows, dim: dimension lines */
  kind: "outline" | "detail" | "dim" | "hidden";
  id?: string;
};

export const A321NEO = {
  type: "A321-271NX",
  length: 44.51,
  span: 35.8,
  height: 11.76,
  fuselageWidth: 3.95,
  fuselageHeight: 4.14,
  wheelbase: 16.9,
  track: 7.59,
} as const;

const zb = 1.95; // fuselage underside above ground
const zt = zb + A321NEO.fuselageHeight; // 6.09 crown

// SVG y grows downward: flip heights so the drawing sits on the ground line.
const H = (z: number) => +(-z).toFixed(3);
const P = (x: number, z: number) => `${+x.toFixed(3)},${H(z)}`;

/** Side elevation (port side). */
export function sideView(): Stroke[] {
  const s: Stroke[] = [];

  // Fuselage silhouette: nose → crown → tail cone → upswept belly → nose
  s.push({
    id: "fuselage",
    kind: "outline",
    d: [
      `M${P(0, 3.55)}`,
      `C${P(0.12, 4.38)} ${P(0.95, 4.86)} ${P(2.05, 5.06)}`,
      `L${P(3.1, 5.8)}`,
      `C${P(4.0, 6.03)} ${P(5.3, zt)} ${P(7.6, zt)}`,
      `L${P(33.4, zt)}`,
      `C${P(38.2, 6.05)} ${P(42.1, 5.76)} ${P(44.22, 5.26)}`,
      `L${P(44.51, 5.12)} L${P(44.51, 4.88)} L${P(44.22, 4.74)}`,
      `C${P(40.6, 3.62)} ${P(36.2, 2.06)} ${P(32.6, zb)}`,
      `L${P(27.6, zb)}`,
      `C${P(25.2, 1.72)} ${P(17.4, 1.72)} ${P(15.4, zb)}`,
      `L${P(5.6, zb)}`,
      `C${P(1.7, 2.0)} ${P(0.2, 2.74)} ${P(0, 3.55)}`,
      "Z",
    ].join(" "),
  });

  // Cockpit windows
  s.push({
    id: "cockpit",
    kind: "detail",
    d: `M${P(2.25, 5.12)} L${P(3.05, 5.62)} L${P(3.75, 5.6)} L${P(3.6, 5.3)} Z M${P(3.95, 5.62)} L${P(4.75, 5.66)} L${P(4.62, 5.36)} L${P(3.8, 5.32)} Z`,
  });

  // Doors: forward pax door, two over-wing exits, aft door
  const door = (x: number, w: number, z0: number, h: number) =>
    `M${P(x, z0)} L${P(x, z0 + h)} Q${P(x, z0 + h + 0.12)} ${P(x + 0.12, z0 + h + 0.12)} L${P(x + w - 0.12, z0 + h + 0.12)} Q${P(x + w, z0 + h + 0.12)} ${P(x + w, z0 + h)} L${P(x + w, z0)} Q${P(x + w, z0 - 0.12)} ${P(x + w - 0.12, z0 - 0.12)} L${P(x + 0.12, z0 - 0.12)} Q${P(x, z0 - 0.12)} ${P(x, z0)} Z`;
  s.push({ id: "doors", kind: "detail", d: [door(5.75, 0.81, 2.55, 1.85), door(19.3, 0.5, 3.45, 0.95), door(21.0, 0.5, 3.45, 0.95), door(38.9, 0.81, 2.75, 1.75)].join(" ") });

  // Cabin windows
  const win: string[] = [];
  const skip = (x: number) => (x > 5.4 && x < 6.9) || (x > 19.0 && x < 19.95) || (x > 20.7 && x < 21.65) || (x > 38.6 && x < 39.9);
  for (let x = 7.4; x < 38.3; x += 0.535) {
    if (skip(x)) continue;
    const z = 4.05;
    win.push(`M${P(x, z - 0.17)} a0.115,0.17 0 1,0 0.23,0 a0.115,0.17 0 1,0 -0.23,0`);
  }
  s.push({ id: "windows", kind: "detail", d: win.join(" ") });

  // Vertical stabiliser + rudder hinge
  s.push({
    id: "fin",
    kind: "outline",
    d: `M${P(34.9, 6.08)} C${P(35.7, 6.18)} ${P(36.1, 6.5)} ${P(36.35, 6.95)} L${P(40.6, A321NEO.height)} L${P(42.86, A321NEO.height)} L${P(43.78, 5.44)}`,
  });
  s.push({ id: "rudder", kind: "detail", d: `M${P(42.0, 11.66)} L${P(42.92, 5.7)}` });

  // Horizontal stabiliser (near side)
  s.push({
    id: "stabiliser",
    kind: "outline",
    d: `M${P(38.4, 5.2)} C${P(39.3, 5.04)} ${P(41.6, 5.05)} ${P(43.35, 5.2)} C${P(41.6, 5.33)} ${P(39.3, 5.34)} ${P(38.4, 5.2)} Z`,
  });

  // Wing (near side, projected) with sharklet
  s.push({
    id: "wing",
    kind: "outline",
    d: `M${P(18.6, 2.62)} L${P(27.05, 4.12)} C${P(27.5, 4.4)} ${P(27.9, 5.4)} ${P(28.35, 6.45)} L${P(29.05, 6.45)} C${P(28.95, 5.6)} ${P(28.8, 4.6)} ${P(28.55, 4.2)} L${P(25.1, 2.45)}`,
  });
  // Flap track fairings
  s.push({
    id: "flaptracks",
    kind: "detail",
    d: [0.3, 0.52, 0.74].map((t) => {
      const x = 25.1 + (28.55 - 25.1) * t;
      const z = 2.45 + (4.2 - 2.45) * t;
      return `M${P(x - 1.1, z - 0.05)} Q${P(x - 0.2, z - 0.42)} ${P(x + 0.45, z - 0.1)}`;
    }).join(" "),
  });

  // Engine nacelle (LEAP-1A) + pylon
  s.push({
    id: "nacelle",
    kind: "outline",
    d: `M${P(14.85, 2.92)} C${P(14.7, 2.6)} ${P(14.7, 0.95)} ${P(14.85, 0.62)} L${P(17.9, 0.56)} C${P(18.9, 0.62)} ${P(19.6, 1.0)} ${P(19.95, 1.45)} L${P(19.95, 2.1)} C${P(19.6, 2.55)} ${P(18.9, 2.95)} ${P(17.9, 3.0)} Z`,
  });
  s.push({ id: "inlet", kind: "detail", d: `M${P(15.25, 2.86)} C${P(15.12, 2.5)} ${P(15.12, 1.05)} ${P(15.25, 0.7)}` });
  s.push({ id: "pylon", kind: "outline", d: `M${P(16.2, 2.97)} L${P(17.3, 3.25)} L${P(21.6, 3.0)} L${P(21.2, 2.6)} L${P(19.95, 2.1)}` });

  // Landing gear (nose + main), down and locked
  const wheel = (cx: number, r: number) => `M${P(cx - r, r)} a${r},${r} 0 1,0 ${2 * r},0 a${r},${r} 0 1,0 ${-2 * r},0`;
  s.push({
    id: "gear",
    kind: "outline",
    d: [
      `M${P(5.1, zb)} L${P(5.1, 0.38)}`,
      wheel(5.1, 0.38),
      `M${P(22.0, 1.85)} L${P(22.0, 0.6)}`,
      wheel(21.55, 0.585),
      wheel(22.55, 0.585),
    ].join(" "),
  });

  return s;
}

/** Plan view. */
export function topView(): Stroke[] {
  const s: Stroke[] = [];
  const R = A321NEO.fuselageWidth / 2;
  const Y = (y: number) => +y.toFixed(3);
  const T = (x: number, y: number) => `${+x.toFixed(3)},${Y(y)}`;

  s.push({
    id: "fuselage",
    kind: "outline",
    d: [
      `M${T(0, 0)}`,
      `C${T(0.25, -1.25)} ${T(2.9, -R)} ${T(6.8, -R)}`,
      `L${T(33.6, -R)}`,
      `C${T(38.6, -R + 0.15)} ${T(43.2, -0.75)} ${T(44.51, -0.32)}`,
      `L${T(44.51, 0.32)}`,
      `C${T(43.2, 0.75)} ${T(38.6, R - 0.15)} ${T(33.6, R)}`,
      `L${T(6.8, R)}`,
      `C${T(2.9, R)} ${T(0.25, 1.25)} ${T(0, 0)}`,
      "Z",
    ].join(" "),
  });

  // Wings: root chord at the fuselage side, kinked trailing edge, sharklet tip
  const wing = (sgn: 1 | -1) => {
    const y = (v: number) => sgn * v;
    return [
      `M${T(18.9, y(R))}`,
      `L${T(27.05, y(17.35))}`,
      `L${T(27.6, y(17.9))}`,
      `L${T(28.65, y(17.9))}`,
      `L${T(28.5, y(17.35))}`,
      `L${T(25.55, y(6.3))}`,
      `L${T(25.2, y(R))}`,
    ].join(" ");
  };
  // Seen from above with the nose to the left, the port wing is at +y (bottom).
  s.push({ id: "wing-port", kind: "outline", d: wing(1) });
  s.push({ id: "wing-stbd", kind: "outline", d: wing(-1) });

  // Control surfaces (ailerons, flaps, spoilers) as detail lines
  const surf = (sgn: 1 | -1) => {
    const y = (v: number) => sgn * v;
    return [
      `M${T(24.25, y(2.6))} L${T(24.85, y(6.3))} L${T(27.35, y(15.6))}`, // flap / aileron hinge
      `M${T(26.7, y(12.4))} L${T(27.85, y(12.45))}`, // aileron break
      `M${T(23.2, y(6.6))} L${T(25.4, y(12.0))}`, // spoiler line
    ].join(" ");
  };
  s.push({ id: "surfaces", kind: "detail", d: surf(-1) + " " + surf(1) });

  // Nacelles
  const nac = (sgn: 1 | -1) => {
    const y0 = sgn * 5.75;
    return `M${T(14.85, y0 - 1.15)} L${T(18.6, y0 - 1.1)} C${T(19.5, y0 - 0.95)} ${T(19.95, y0 - 0.6)} ${T(19.95, y0)} C${T(19.95, y0 + 0.6)} ${T(19.5, y0 + 0.95)} ${T(18.6, y0 + 1.1)} L${T(14.85, y0 + 1.15)} Z`;
  };
  s.push({ id: "nacelles", kind: "outline", d: nac(-1) + " " + nac(1) });

  // Horizontal stabiliser
  const hstab = (sgn: 1 | -1) => {
    const y = (v: number) => sgn * v;
    return `M${T(38.9, y(1.05))} L${T(42.15, y(6.22))} L${T(43.55, y(6.22))} L${T(42.8, y(0.85))}`;
  };
  s.push({ id: "hstab", kind: "outline", d: hstab(-1) + " " + hstab(1) });
  s.push({ id: "fin-top", kind: "detail", d: `M${T(35.2, 0)} L${T(43.8, 0)}` });

  return s;
}

/**
 * Simplified A320-family hydraulic architecture on the plan view.
 * Green: engine-1 pump (+ PTU). Yellow: engine-2 pump + electric pump. Blue: electric pump + RAT.
 * Routes are schematic, not structural.
 */
export function hydraulicRoutes() {
  // Routes are authored with port at -y; flip so port (ENG 1) lands at +y like topView().
  const T = (x: number, y: number) => `${+x.toFixed(3)},${+(-y).toFixed(3)}`;
  return {
    green: {
      label: "GREEN",
      pump: { x: 17.6, y: 5.75, name: "ENG 1 EDP" },
      reservoir: { x: 22.9, y: 0.9 },
      d: [
        `M${T(17.6, -5.75)} L${T(20.4, -4.9)} L${T(22.9, -0.9)}`,
        `M${T(22.9, -0.9)} L${T(5.4, -0.9)}`, // fwd to nose gear
        `M${T(22.9, -0.9)} L${T(40.2, -0.9)} L${T(42.2, -4.6)}`, // aft to elevator
        `M${T(40.2, -0.9)} L${T(42.3, 0)}`, // rudder
        `M${T(22.9, -0.9)} L${T(24.6, -6.3)} L${T(27.2, -14.6)}`, // port aileron
        `M${T(22.9, -0.9)} L${T(24.6, 6.3)} L${T(27.2, 14.6)}`, // stbd aileron
      ].join(" "),
    },
    blue: {
      label: "BLUE",
      pump: { x: 23.6, y: 0.0, name: "ELEC PUMP" },
      reservoir: { x: 23.6, y: 0.0 },
      d: [
        `M${T(23.6, 0)} L${T(41.0, 0.0)} L${T(42.0, -3.8)}`,
        `M${T(41.0, 0)} L${T(42.0, 3.8)}`,
        `M${T(23.6, 0)} L${T(25.4, -9.8)} L${T(26.6, -13.0)}`,
        `M${T(23.6, 0)} L${T(25.4, 9.8)} L${T(26.6, 13.0)}`,
        `M${T(23.6, 0)} L${T(24.4, 2.5)}`, // RAT
      ].join(" "),
    },
    yellow: {
      label: "YELLOW",
      pump: { x: 17.6, y: -5.75, name: "ENG 2 EDP" },
      reservoir: { x: 22.9, y: -0.9 },
      d: [
        `M${T(17.6, 5.75)} L${T(20.4, 4.9)} L${T(22.9, 0.9)}`,
        `M${T(22.9, 0.9)} L${T(40.6, 0.9)} L${T(42.6, 4.8)}`,
        `M${T(22.9, 0.9)} L${T(23.9, 6.9)} L${T(25.1, 11.6)}`,
        `M${T(22.9, 0.9)} L${T(23.9, -6.9)} L${T(25.1, -11.6)}`,
        `M${T(22.9, 0.9)} L${T(6.2, 0.9)}`,
      ].join(" "),
    },
    leak: { x: 17.6, y: 5.75, system: "green", text: "HYD G RSVR LO LVL — LEAK AT ENG 1 EDP CASE DRAIN" },
  };
}

/** Dimension line with ticks + label anchor, in view units. */
export function dimension(x1: number, y1: number, x2: number, y2: number, offset: number) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy);
  const nx = -dy / len;
  const ny = dx / len;
  const ax = x1 + nx * offset;
  const ay = y1 + ny * offset;
  const bx = x2 + nx * offset;
  const by = y2 + ny * offset;
  const t = 0.35;
  const f = (n: number) => +n.toFixed(3);
  return {
    d: `M${f(x1 + nx * 0.25)},${f(y1 + ny * 0.25)} L${f(ax + nx * 0.35)},${f(ay + ny * 0.35)} M${f(x2 + nx * 0.25)},${f(y2 + ny * 0.25)} L${f(bx + nx * 0.35)},${f(by + ny * 0.35)} M${f(ax)},${f(ay)} L${f(bx)},${f(by)} M${f(ax - t)},${f(ay + t)} L${f(ax + t)},${f(ay - t)} M${f(bx - t)},${f(by + t)} L${f(bx + t)},${f(by - t)}`,
    label: { x: f((ax + bx) / 2), y: f((ay + by) / 2), length: +len.toFixed(2) },
  };
}
