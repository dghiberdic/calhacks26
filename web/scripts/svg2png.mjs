// usage: node scripts/svg2png.mjs in.svg out.png [width] [background]
import { Resvg } from "@resvg/resvg-js";
import { readFileSync, writeFileSync } from "node:fs";
const [,, inp, outp, width = "1600", bg = "#ffffff"] = process.argv;
const svg = readFileSync(inp, "utf8");
const r = new Resvg(svg, { fitTo: { mode: "width", value: +width }, background: bg, font: { loadSystemFonts: true } });
writeFileSync(outp, r.render().asPng());
console.log("ok", outp);
