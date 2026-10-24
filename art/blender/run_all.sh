#!/usr/bin/env bash
# Rebuild every A321neo / Northstar asset.  Usage: art/blender/run_all.sh   (from anywhere)
set -euo pipefail
B="${BLENDER:-$HOME/Applications/Blender.app/Contents/MacOS/Blender}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SP="${A321_SCRATCH:-/private/tmp/claude-501/-Users-justinstoica-calhacks13/629b8d31-5e1a-4eb9-bd4e-f5cad7638d44/scratchpad/blender}"
export A321_SCRATCH="$SP"
mkdir -p "$SP"
# 1. model -> $SP/a321.blend  (~5 s)
"$B" -b --factory-startup --python "$HERE/build_a321.py"
# 2. renders: beauty (night storm) + clay, PNG masters in $SP/renders, WebP in web/public/renders
"$B" -b "$SP/a321.blend" --python "$HERE/render_side.py" -- --samples 160 --threshold 0.01 --exposure -0.25   # ~2.3 min + ~1 min clay
"$B" -b "$SP/a321.blend" --python "$HERE/render_hero.py" -- --samples 160 --threshold 0.01 --exposure -0.2    # ~2 min + 20 s clay
# 3. line art SVGs (same cameras) + 3-view JSON
rm -f "$HERE/../../web/public/renders/a321-views.json"
for v in side hero top front sideortho; do
  "$B" -b "$SP/a321.blend" --python "$HERE/export_lines.py" -- --view "$v"
done
# 4. web model
"$B" -b --factory-startup --python "$HERE/export_glb.py"
# 5. rain overlay (plain python3 + numpy + Pillow)
python3 "$HERE/make_rain.py"
