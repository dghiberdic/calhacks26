// Prints SVG snippets for the Claude Design boards from the same geometry the site uses.
// usage: npx tsx scripts/design-svgs.ts <outdir>
import { writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { sideView, topView, hydraulicRoutes, dimension, A321NEO } from "../src/lib/drawings/aircraft";
import { isobars, syntheticField, windBarb } from "../src/lib/drawings/meteo";

const out = process.argv[2] ?? "./design-out";
mkdirSync(out, { recursive: true });

const ink = "#E8F0FA";

// 1. Side elevation blueprint
{
  const strokes = sideView();
  const dimL = dimension(0, 1.9, A321NEO.length, 1.9, 0);
  const dimH = dimension(46.3, 0, 46.3, -A321NEO.height, -0.0);
  const body = strokes
    .map((s) => `<path d="${s.d}" fill="none" stroke="${ink}" stroke-width="${s.kind === "outline" ? 0.09 : 0.05}" stroke-opacity="${s.kind === "outline" ? 0.95 : 0.7}" stroke-linejoin="round" stroke-linecap="round"/>`)
    .join("");
  const svg = `<svg viewBox="-3 -13.5 53 17.6" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" style="width:100%;height:auto;display:block">
<g>${body}</g>
<path d="M-2.5,0 L49.5,0" stroke="${ink}" stroke-width="0.04" stroke-dasharray="0.6 0.3" opacity="0.6"/>
<path d="${dimL.d}" stroke="${ink}" stroke-width="0.035" fill="none" opacity="0.75"/>
<text x="${dimL.label.x}" y="${dimL.label.y + 1.0}" fill="${ink}" font-family="B612 Mono, monospace" font-size="0.62" text-anchor="middle" opacity="0.85">44.51 m</text>
<path d="M46.3,0 L46.3,-11.76 M45.9,0 L46.7,0 M45.9,-11.76 L46.7,-11.76" stroke="${ink}" stroke-width="0.035" opacity="0.75"/>
<text x="47.1" y="-5.7" fill="${ink}" font-family="B612 Mono, monospace" font-size="0.62" opacity="0.85">11.76 m</text>
</svg>`;
  writeFileSync(join(out, "side.svg"), svg);
  void dimH;
}

// 2. Plan view with hydraulic systems
{
  const strokes = topView();
  const hyd = hydraulicRoutes();
  const body = strokes
    .map((s) => `<path d="${s.d}" fill="none" stroke="${ink}" stroke-width="${s.kind === "outline" ? 0.09 : 0.05}" stroke-opacity="${s.kind === "outline" ? 0.9 : 0.55}" stroke-linejoin="round"/>`)
    .join("");
  const sys = (d: string, c: string) => `<path d="${d}" fill="none" stroke="${c}" stroke-width="0.16" stroke-linecap="round" stroke-linejoin="round"/>`;
  const svg = `<svg viewBox="-2 -19.5 49 39" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" style="width:100%;height:auto;display:block">
<g>${body}</g>
${sys(hyd.blue.d, "#8FC8FF")}${sys(hyd.yellow.d, "#F5C542")}${sys(hyd.green.d, "#5FD08A")}
<circle cx="${hyd.leak.x}" cy="${hyd.leak.y}" r="0.55" fill="none" stroke="#FF5A3C" stroke-width="0.14"/>
<circle cx="${hyd.leak.x}" cy="${hyd.leak.y}" r="1.25" fill="none" stroke="#FF5A3C" stroke-width="0.06" stroke-dasharray="0.25 0.2"/>
</svg>`;
  writeFileSync(join(out, "plan-hyd.svg"), svg);
}

// 3. Isobars (synthetic, art direction only)
{
  const W = 120;
  const Hh = 80;
  const grid = syntheticField(W, Hh, [
    { x: 46, y: 34, delta: -62, rx: 22, ry: 16, rot: 0.5 },
    { x: 102, y: 66, delta: 18, rx: 30, ry: 24 },
    { x: 8, y: 74, delta: 14, rx: 26, ry: 20 },
  ], 1014, 11);
  const iso = isobars(grid, 4);
  const paths = iso.map((i) => `<path d="${i.d}" fill="none" stroke="#121417" stroke-width="${i.hpa % 20 === 0 ? 0.32 : 0.18}" stroke-opacity="0.85"/>`).join("");
  const svg = `<svg viewBox="0 0 ${W} ${Hh}" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" style="width:100%;height:auto;display:block">${paths}
<text x="44.6" y="35.6" font-family="Archivo, sans-serif" font-weight="700" font-size="5" fill="#C2381F">L</text>
<text x="44" y="40.5" font-family="B612 Mono, monospace" font-size="1.9" fill="#121417">952</text>
</svg>`;
  writeFileSync(join(out, "isobars.svg"), svg);
  console.log("isobars:", iso.length);
}

// 4. Wind barbs row
{
  const speeds = [5, 15, 25, 35, 48, 65];
  const items = speeds
    .map((kt, i) => {
      const b = windBarb(30 + i * 62, 46, 230, kt, 28);
      return `<g><circle cx="${30 + i * 62}" cy="46" r="3" fill="none" stroke="#121417" stroke-width="1.4"/><path d="${b.staff} ${b.feathers}" stroke="#121417" stroke-width="1.6" stroke-linecap="round" fill="none"/><path d="${b.pennants}" fill="#121417"/><text x="${30 + i * 62}" y="78" text-anchor="middle" font-family="B612 Mono, monospace" font-size="10" fill="#5A6068">${kt} kt</text></g>`;
    })
    .join("");
  const svg = `<svg viewBox="0 0 380 86" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" style="width:100%;height:auto;display:block">${items}</svg>`;
  writeFileSync(join(out, "barbs.svg"), svg);
}

console.log("wrote", out);
