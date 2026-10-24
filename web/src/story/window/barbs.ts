/**
 * A wind barb (WMO convention): the staff points to where the wind blows FROM.
 * Pennant = 50 kt, full barb = 10 kt, half barb = 5 kt, feathers on the northern-hemisphere side.
 */
export function windBarb(cx: number, cy: number, dirDeg: number, kt: number, L = 22): { staff: string; feathers: string; pennants: string } {
  const f = (n: number) => +n.toFixed(2);
  const a = ((dirDeg - 90) * Math.PI) / 180; // 0° = from north → staff points up
  const ux = Math.cos(a);
  const uy = Math.sin(a);
  const px = -uy;
  const py = ux;
  const tipX = cx + ux * L;
  const tipY = cy + uy * L;
  const staff = `M${f(cx)},${f(cy)} L${f(tipX)},${f(tipY)}`;

  let rem = Math.round(kt / 5) * 5;
  const pennants: string[] = [];
  const feathers: string[] = [];
  const gap = L * 0.14;
  const fl = L * 0.46;
  let pos = 0;
  while (rem >= 50) {
    const sx = tipX - ux * pos;
    const sy = tipY - uy * pos;
    const ex = tipX - ux * (pos + gap * 1.3);
    const ey = tipY - uy * (pos + gap * 1.3);
    pennants.push(`M${f(sx)},${f(sy)} L${f(sx + px * fl + ux * fl * 0.12)},${f(sy + py * fl + uy * fl * 0.12)} L${f(ex)},${f(ey)} Z`);
    pos += gap * 1.5;
    rem -= 50;
  }
  while (rem >= 10) {
    const sx = tipX - ux * pos;
    const sy = tipY - uy * pos;
    feathers.push(`M${f(sx)},${f(sy)} L${f(sx + px * fl + ux * fl * 0.32)},${f(sy + py * fl + uy * fl * 0.32)}`);
    pos += gap;
    rem -= 10;
  }
  if (rem >= 5) {
    if (pos === 0) pos = gap; // a lone half barb sits inboard of the tip
    const sx = tipX - ux * pos;
    const sy = tipY - uy * pos;
    feathers.push(`M${f(sx)},${f(sy)} L${f(sx + px * fl * 0.5 + ux * fl * 0.16)},${f(sy + py * fl * 0.5 + uy * fl * 0.16)}`);
  }
  return { staff, feathers: feathers.join(" "), pennants: pennants.join(" ") };
}
