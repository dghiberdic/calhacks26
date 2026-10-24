// Social/Devpost card: Blender side render + headline. usage: node scripts/og-image.mjs <render.png> <fontDir>
import sharp from "sharp";
import { Resvg } from "@resvg/resvg-js";
import { writeFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const [, , renderPath, fontDir] = process.argv;
const W = 1200, H = 630;
const bg = await sharp(renderPath).resize(W, H, { fit: "cover", position: "centre" }).modulate({ brightness: 0.82 }).jpeg({ quality: 90 }).toBuffer();
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <defs><linearGradient id="g" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#0b0e13" stop-opacity="0.85"/><stop offset="0.45" stop-color="#0b0e13" stop-opacity="0.1"/><stop offset="1" stop-color="#0b0e13" stop-opacity="0.75"/></linearGradient></defs>
  <image href="data:image/jpeg;base64,${bg.toString("base64")}" x="0" y="0" width="${W}" height="${H}" preserveAspectRatio="xMidYMid slice"/>
  <rect width="${W}" height="${H}" fill="url(#g)"/>
  <path d="M60 52 q5 -14 10 0 t10 0 t10 0 L102 70 L148 28" transform="translate(0 0) scale(0.62) translate(36 38)" fill="none" stroke="#f4f6f8" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="122" y="70" font-family="Archivo" font-weight="600" font-size="30" fill="#f4f6f8">StormCheck</text>
  <text x="60" y="${H - 104}" font-family="Archivo" font-weight="600" font-size="70" letter-spacing="-2" fill="#f4f6f8">Every storm leaves a bill.</text>
  <text x="62" y="${H - 58}" font-family="Archivo" font-weight="600" font-size="24" fill="#c9d3dd">The real cause of every cancelled flight. Every euro traced to evidence.</text>
</svg>`;
const fonts = readdirSync(fontDir).filter((f) => f.endsWith(".ttf")).map((f) => join(fontDir, f));
const png = new Resvg(svg, { font: { fontFiles: fonts, loadSystemFonts: false, defaultFontFamily: "Archivo" } }).render().asPng();
writeFileSync("src/app/opengraph-image.png", png);
writeFileSync("public/stormcheck-card.png", png);
console.log("ok", png.length);
