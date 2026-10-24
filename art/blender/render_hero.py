"""
render_hero.py - low front-3/4 hero pair (night-storm beauty + clay), 2560x1440.
  Blender -b <scratch>/a321.blend --python art/blender/render_hero.py -- [--pct 100] [--samples 384] [--tag _test]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import render_lib as R  # noqa: E402

pct = C.arg_val("--pct", 100, int)
samples = C.arg_val("--samples", 384, int)
tag = C.arg_val("--tag", "")
exposure = C.arg_val("--exposure", 0.0, float)
mist = C.arg_val("--mist", 0.0007, float)
key = C.arg_val("--key", 1.0, float)
a = C.args()

C.ensure_aircraft()
if "--no-beauty" not in a:
    R.render_beauty("ns31-hero-render", C.hero_camera, C.HERO_RES, samples, pct, exposure, mist, key, tag)
if "--no-clay" not in a:
    R.render_clay("ns31-hero-render", C.hero_camera, C.HERO_RES, max(64, samples // 3), pct, tag)
