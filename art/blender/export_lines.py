"""
export_lines.py - hidden-line-removed line art (Grease Pencil Line Art modifier) exported to SVG,
from exactly the same camera as the renders.

  Blender -b <scratch>/a321.blend --python art/blender/export_lines.py -- --view side|hero|top|front|sideortho [--op]

Pipeline: LINEART modifier (contour/silhouette, crease, intersections, loose-edge guides, occlusion level 0)
-> evaluated GP strokes -> (a) wm.grease_pencil_export_svg for reference, and (b) our own projection through the
same camera into render pixels -> cleaned SVG (stroke-only <path> per stroke, tiny strokes dropped,
viewBox = render pixel size).
"""
import bpy
import json
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

VIEW = C.arg_val("--view", "side")
OUT_DIR = C.arg_val("--out", C.OUT_WEB)
STROKE = C.arg_val("--stroke", "#0d1626")
NAMES = {
    "side": "ns31-side-lines.svg",
    "hero": "ns31-hero-lines.svg",
    "top": "a321-top.svg",
    "front": "a321-front.svg",
    "sideortho": "a321-side.svg",
}


def setup_camera(sc):
    if VIEW == "side":
        cam = C.side_camera(sc)
        res = C.SIDE_RES
        # tighter clip range around the aircraft for line-art depth precision (projection unchanged)
        cam.data.clip_start, cam.data.clip_end = C.SIDE_DIST - 40, C.SIDE_DIST + 40
    elif VIEW == "hero":
        cam = C.hero_camera(sc)
        res = C.HERO_RES
        cam.data.clip_start, cam.data.clip_end = 1.0, 200.0
    else:
        v = "side" if VIEW == "sideortho" else VIEW
        cam = C.ortho_camera(sc, v)
        res = C.ORTHO[v]["res"]
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.camera = cam
    return cam, res


def make_lineart(sc, crease_deg=140.0, use_material=False):
    gpd = bpy.data.grease_pencils.new("LineArtData")
    gp = bpy.data.objects.new("LineArt", gpd)
    sc.collection.objects.link(gp)
    layer = gpd.layers.new("Lines")
    mat = bpy.data.materials.new("LineArtInk")
    bpy.data.materials.create_gpencil_data(mat)
    mat.grease_pencil.color = (0.05, 0.08, 0.15, 1.0)
    gpd.materials.append(mat)
    m = gp.modifiers.new("LineArt", "LINEART")
    m.source_type = "COLLECTION"
    m.source_collection = bpy.data.collections["A321"]
    m.target_layer = layer.name
    m.target_material = mat
    m.use_contour = True
    m.use_crease = True
    m.crease_threshold = math.radians(crease_deg)
    m.use_crease_on_smooth = True
    m.use_crease_on_sharp = True
    m.use_material = use_material
    m.use_edge_mark = False
    m.use_intersection = True
    m.use_loose = True
    m.use_loose_as_contour = False
    m.use_multiple_levels = False
    m.level_start = 0
    m.level_end = 0
    m.radius = 0.004
    m.chaining_image_threshold = 0.0015
    m.smooth_tolerance = 0.0
    m.split_angle = 0.0
    m.use_fuzzy_intersections = False
    m.use_back_face_culling = False
    m.use_image_boundary_trimming = True
    m.overscan = 0.0
    return gp, m


def collect_strokes(gp):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = gp.evaluated_get(dg)
    strokes = []
    for layer in ev.data.layers:
        fr = layer.current_frame()
        if fr is None:
            continue
        dr = fr.drawing
        mw = np.array(ev.matrix_world)
        for st in dr.strokes:
            pts = np.array([p.position[:] for p in st.points], float)
            if len(pts) < 2:
                continue
            pts = (np.c_[pts, np.ones(len(pts))] @ mw.T)[:, :3]
            strokes.append(pts)
    return strokes


def project(cam, res, P):
    """World -> render pixel coordinates (origin top-left), same maths as Blender's camera."""
    sc = bpy.context.scene
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    W, H = res
    out = np.empty((len(P), 2))
    for i, p in enumerate(P):
        v = world_to_camera_view(sc, cam, Vector(p))
        out[i] = (v.x * W, (1.0 - v.y) * H)
    return out


def rdp(P, eps):
    if len(P) < 3:
        return P
    a, b = P[0], P[-1]
    ab = b - a
    n = np.hypot(*ab)
    if n < 1e-9:
        d = np.hypot(*(P - a).T)
    else:
        d = np.abs(np.cross(ab, P - a)) / n
    i = int(np.argmax(d))
    if d[i] > eps:
        l = rdp(P[: i + 1], eps)
        r = rdp(P[i:], eps)
        return np.vstack([l[:-1], r])
    return np.vstack([a, b])


def write_svg(path, strokes_px, res, min_len, stroke_w, meta=None):
    W, H = res
    kept = []
    for P in strokes_px:
        # clip to frame (keep points inside with a small margin)
        inside = (P[:, 0] > -2) & (P[:, 0] < W + 2) & (P[:, 1] > -2) & (P[:, 1] < H + 2)
        if inside.sum() < 2:
            continue
        # split at runs outside the frame
        runs, cur = [], []
        for q, ok in zip(P, inside):
            if ok:
                cur.append(q)
            elif cur:
                runs.append(np.array(cur))
                cur = []
        if cur:
            runs.append(np.array(cur))
        for R in runs:
            if len(R) < 2:
                continue
            L = np.hypot(*np.diff(R, axis=0).T).sum()
            if L < min_len:
                continue
            kept.append(rdp(R, 0.3))
    kept.sort(key=lambda R: (R[:, 0].min(), R[:, 1].min()))
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">' % (W, H, W, H)]
    if meta:
        lines.append("<!-- %s -->" % json.dumps(meta))
    lines.append('<g fill="none" stroke="%s" stroke-width="%.2f" stroke-linecap="round" stroke-linejoin="round">' % (STROKE, stroke_w))
    for k, R in enumerate(kept):
        d = "M" + " L".join("%.1f,%.1f" % (x, y) for x, y in R)
        lines.append('<path id="l%d" d="%s"/>' % (k, d))
    lines.append("</g></svg>")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return len(kept)


def main():
    C.ensure_aircraft()
    sc = bpy.context.scene
    # apron/env must not exist here; only aircraft collection is the source anyway
    cam, res = setup_camera(sc)
    t0 = time.time()
    crease = C.arg_val("--crease", 140.0, float)
    gp, mod = make_lineart(sc, crease_deg=crease, use_material="--no-material" not in C.args())
    strokes = collect_strokes(gp)
    C.log("line art: %d raw strokes in %.1fs" % (len(strokes), time.time() - t0))
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, NAMES[VIEW])
    # (a) the official exporter, kept in scratch for reference
    if "--op" in C.args():
        try:
            bpy.ops.object.select_all(action="DESELECT")
            gp.select_set(True)
            bpy.context.view_layer.objects.active = gp
            ref = os.path.join(C.SCRATCH, "lines_op_%s.svg" % VIEW)
            r = bpy.ops.wm.grease_pencil_export_svg(filepath=ref, selected_object_type="ACTIVE", use_fill=False,
                                                     use_uniform_width=True, use_clip_camera=True, check_existing=False)
            C.log("operator export:", r, ref, os.path.getsize(ref) if os.path.exists(ref) else "missing")
        except Exception as e:
            C.log("operator export failed:", e)
    # (b) projected strokes -> cleaned SVG
    px = [project(cam, res, P) for P in strokes]
    W = res[0]
    stroke_w = {"side": 1.6, "hero": 1.5}.get(VIEW, 1.4)
    meta = dict(view=VIEW, res=list(res), camera=cam.name, source="Blender 5.2 Grease Pencil Line Art (occlusion level 0)")
    n = write_svg(out, px, res, min_len=0.005 * W, stroke_w=stroke_w, meta=meta)
    C.log("wrote %s: %d paths, %.1f KB" % (out, n, os.path.getsize(out) / 1024))
    if VIEW in ("top", "front", "sideortho"):
        jpath = os.path.join(OUT_DIR, "a321-views.json")
        data = {}
        if os.path.exists(jpath):
            with open(jpath) as f:
                data = json.load(f)
        v = "side" if VIEW == "sideortho" else VIEW
        meta = C.ortho_meta(v)
        meta["file"] = NAMES[VIEW]
        data[v] = meta
        data["_aircraft"] = dict(type="A321-271NX (A321neo)", length_m=44.51, span_m=35.80, height_m=11.76,
                                 fuselage_width_m=3.95, fuselage_height_m=4.14, wheelbase_m=16.9, track_m=7.6,
                                 origin="ground point under the radome tip; x aft, y starboard, z up")
        with open(jpath, "w") as f:
            json.dump(data, f, indent=2)
        C.log("updated", jpath)


main()
