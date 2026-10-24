"""
build_a321.py - procedural Airbus A321neo (A321-271NX) for Blender 5.2, livery "Northstar Air".

World axes (metres): origin on the ground directly under the radome tip,
+X aft (distance from the nose), +Y starboard, +Z up.  Port side is -Y.
Profiles follow web/src/lib/drawings/aircraft.ts (side + top silhouettes).

Run:
  Blender -b --factory-startup --python art/blender/build_a321.py -- [--lo] [--out file.blend]
Importable: `import build_a321 as A; A.build(quality="hi")` builds into the current scene.
"""
import bpy
import bmesh
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = os.environ.get(
    "A321_SCRATCH",
    "/private/tmp/claude-501/-Users-justinstoica-calhacks13/629b8d31-5e1a-4eb9-bd4e-f5cad7638d44/scratchpad/blender",
)
FONT_PATH = os.path.join(HERE, "fonts", "Archivo-ExpandedSemiBold.ttf")

NAVY = (0x13 / 255, 0x21 / 255, 0x3A / 255)  # #13213A (sRGB)
LOD = {"text_maxlen": 0.035, "win_corner": 8, "win_rings": (1.0, 0.86, 0.72, 0.55, 0.36, 0.18), "win_pts": 40,
       "door_step": 0.03, "pane_pts": 96, "pane_rings": (1.0, 0.94, 0.86, 0.76, 0.64, 0.5, 0.36, 0.22, 0.1)}


def log(*a):
    print("[a321]", *a, flush=True)


def srgb_to_lin(c):
    c = np.asarray(c, float)
    return tuple(np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4))


# ----------------------------------------------------------------------------- math helpers
def smoothstep(e0, e1, x):
    t = np.clip((np.asarray(x, float) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def cubic(p0, p1, p2, p3, n=400):
    t = np.linspace(0.0, 1.0, n)[:, None]
    p0, p1, p2, p3 = (np.asarray(p, float) for p in (p0, p1, p2, p3))
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3


def seg(p0, p1, n=80):
    t = np.linspace(0.0, 1.0, n)[:, None]
    return (1 - t) * np.asarray(p0, float) + t * np.asarray(p1, float)


def hermite(p0, m0, p1, m1, t):
    t2, t3 = t * t, t * t * t
    return (2 * t3 - 3 * t2 + 1) * p0 + (t3 - 2 * t2 + t) * m0 + (-2 * t3 + 3 * t2) * p1 + (t3 - t2) * m1


class Profile:
    """y(x) lookup from a chain of path pieces, optionally Gaussian-smoothed inside [lo, hi]."""

    def __init__(self, pieces, smooth=0.0, lo=None, hi=None):
        pts = np.vstack(pieces)
        o = np.argsort(pts[:, 0], kind="stable")
        xs, ys = pts[o, 0], pts[o, 1]
        xs, i = np.unique(xs, return_index=True)
        ys = ys[i]
        dx = 0.004
        self.xg = np.arange(xs[0], xs[-1] + dx * 0.5, dx)
        yg = np.interp(self.xg, xs, ys)
        if smooth > 0:
            k = int(smooth * 4 / dx)
            ker = np.exp(-0.5 * (np.arange(-k, k + 1) * dx / smooth) ** 2)
            ker /= ker.sum()
            ys_s = np.convolve(np.pad(yg, k, mode="edge"), ker, mode="valid")
            b = smoothstep(lo[0], lo[1], self.xg) * (1 - smoothstep(hi[0], hi[1], self.xg))
            yg = yg * (1 - b) + ys_s * b
        self.yg = yg

    def __call__(self, x):
        return np.interp(x, self.xg, self.yg)


def catmull(pts, n=10):
    """Centripetal-ish Catmull-Rom through pts (M,2) -> dense polyline."""
    P = np.asarray(pts, float)
    P = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        t = np.linspace(0, 1, n, endpoint=False)[:, None]
        out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(P[-2][None])
    return np.vstack(out)


def resample(poly, n):
    d = np.linalg.norm(np.diff(poly, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(d)])
    t = np.linspace(0, s[-1], n)
    return np.stack([np.interp(t, s, poly[:, k]) for k in range(poly.shape[1])], -1)


def profile_chain(segments, counts):
    """segments: list of control-point lists (each a smooth Catmull-Rom run; joints are corners).
    counts: points per segment.  Returns (M,2) polyline and per-point segment index."""
    pts, sid = [], []
    for k, (cps, n) in enumerate(zip(segments, counts)):
        poly = resample(catmull(cps, 24), n)
        if pts:
            poly = poly[1:]
        pts.append(poly)
        sid += [k] * len(poly)
    return np.vstack(pts), np.array(sid)


# ----------------------------------------------------------------------------- mesh helpers
def grid_faces(nu, nv, close_v=True):
    I, J = np.meshgrid(np.arange(nu - 1), np.arange(nv if close_v else nv - 1), indexing="ij")
    J2 = (J + 1) % nv
    f = np.stack([I * nv + J, I * nv + J2, (I + 1) * nv + J2, (I + 1) * nv + J], -1)
    return f.reshape(-1, 4), I.ravel(), J.ravel()


def new_object(name, me, mats=(), coll=None):
    for m in mats:
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    (coll or bpy.context.scene.collection).objects.link(ob)
    return ob


def build_mesh(name, verts, faces, mat_idx=None, uv=None, smooth=True, sharp_deg=35.0, merge=1e-6,
               recalc=True, edges=None):
    me = bpy.data.meshes.new(name)
    faces = [tuple(int(i) for i in f) for f in faces]
    me.from_pydata(np.asarray(verts, float).tolist(), edges or [], faces)
    if mat_idx is not None and len(faces):
        me.polygons.foreach_set("material_index", np.asarray(mat_idx, np.int32))
    if uv is not None and len(faces):
        lay = me.uv_layers.new(name="UVMap")
        lay.data.foreach_set("uv", np.asarray(uv, np.float32).ravel())
    if len(faces):
        bm = bmesh.new()
        bm.from_mesh(me)
        if merge:
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge)
        bmesh.ops.dissolve_degenerate(bm, dist=1e-7, edges=bm.edges)
        if recalc:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me)
        bm.free()
        if smooth:
            me.polygons.foreach_set("use_smooth", np.ones(len(me.polygons), bool))
            if sharp_deg:
                me.set_sharp_from_angle(angle=math.radians(sharp_deg))
    me.validate()
    me.update()
    return me


def grid_uv(faces_I, faces_J, us, vs_count):
    """Per-loop UVs for grid faces (corner order: (i,j),(i,j+1),(i+1,j+1),(i+1,j)); v wraps to 1.0."""
    nv = vs_count
    u0, u1 = us[faces_I], us[faces_I + 1]
    v0 = faces_J / nv
    v1 = (faces_J + 1) / nv
    return np.stack([np.stack([u0, v0], -1), np.stack([u0, v1], -1), np.stack([u1, v1], -1), np.stack([u1, v0], -1)], 1)


# ----------------------------------------------------------------------------- materials
def _set(node, name, val):
    if name in node.inputs:
        node.inputs[name].default_value = val


def principled(name, base, rough=0.4, metal=0.0, coat=0.0, coat_rough=0.04, rough_var=0.0, rough_scale=7.0,
               spec=0.5, emit=None, emit_strength=0.0, alpha=1.0, linear=False):
    m = bpy.data.materials.new(name)
    nt = m.node_tree
    b = nt.nodes.get("Principled BSDF")
    if b is None:
        b = nt.nodes.new("ShaderNodeBsdfPrincipled")
        out = nt.nodes.get("Material Output") or nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(b.outputs[0], out.inputs["Surface"])
    col = base if linear else srgb_to_lin(base)
    _set(b, "Base Color", (*col, 1.0))
    _set(b, "Metallic", metal)
    _set(b, "Roughness", rough)
    _set(b, "Specular IOR Level", spec)
    _set(b, "Coat Weight", coat)
    _set(b, "Coat Roughness", coat_rough)
    _set(b, "Coat IOR", 1.5)
    if emit is not None:
        _set(b, "Emission Color", (*emit, 1.0))
        _set(b, "Emission Strength", emit_strength)
    if rough_var > 0:
        tc = nt.nodes.new("ShaderNodeTexCoord")
        nz = nt.nodes.new("ShaderNodeTexNoise")
        nz.inputs["Scale"].default_value = rough_scale
        nz.inputs["Detail"].default_value = 6.0
        nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
        mr = nt.nodes.new("ShaderNodeMapRange")
        mr.inputs["To Min"].default_value = max(0.0, rough - rough_var)
        mr.inputs["To Max"].default_value = rough + rough_var
        mr.inputs["From Min"].default_value = 0.3
        mr.inputs["From Max"].default_value = 0.7
        nt.links.new(nz.outputs["Fac"], mr.inputs["Value"])
        nt.links.new(mr.outputs["Result"], b.inputs["Roughness"])
        if coat > 0:
            mr2 = nt.nodes.new("ShaderNodeMapRange")
            mr2.inputs["From Min"].default_value = 0.3
            mr2.inputs["From Max"].default_value = 0.7
            mr2.inputs["To Min"].default_value = coat_rough * 0.85
            mr2.inputs["To Max"].default_value = coat_rough * 1.2
            nt.links.new(nz.outputs["Fac"], mr2.inputs["Value"])
            nt.links.new(mr2.outputs["Result"], b.inputs["Coat Roughness"])
    m.diffuse_color = (*col, 1.0)
    return m


def emission_mat(name, color, strength):
    m = bpy.data.materials.new(name)
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (*color, 1)
    e.inputs["Strength"].default_value = strength
    out = nt.nodes.get("Material Output") or nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs[0], out.inputs["Surface"])
    m.diffuse_color = (*color, 1)
    return m


def window_mat(name="window_glass"):
    """Dark glossy cabin-window glass with a soft grey seal ring driven by UV.x (0 centre -> 1 edge)."""
    m = principled(name, (0.02, 0.022, 0.026), rough=0.06, coat=1.0, coat_rough=0.02, spec=0.6)
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    uv = nt.nodes.new("ShaderNodeUVMap")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(uv.outputs["UV"], sep.inputs[0])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    cr = ramp.color_ramp
    cr.elements[0].position = 0.80
    cr.elements[0].color = (*srgb_to_lin((0.03, 0.035, 0.04)), 1)
    cr.elements[1].position = 0.90
    cr.elements[1].color = (*srgb_to_lin((0.42, 0.44, 0.46)), 1)
    nt.links.new(sep.outputs["X"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = 0.80
    mr.inputs["From Max"].default_value = 0.90
    mr.inputs["To Min"].default_value = 0.05
    mr.inputs["To Max"].default_value = 0.45
    nt.links.new(sep.outputs["X"], mr.inputs["Value"])
    nt.links.new(mr.outputs["Result"], b.inputs["Roughness"])
    return m


def make_materials():
    M = {}
    M["paint_white"] = principled("paint_white", (0.86, 0.87, 0.875), rough=0.32, coat=1.0, coat_rough=0.035, rough_var=0.04)
    M["paint_grey"] = principled("paint_grey", (0.66, 0.68, 0.70), rough=0.38, coat=0.8, coat_rough=0.06, rough_var=0.05)
    M["paint_navy"] = principled("paint_navy", NAVY, rough=0.30, coat=1.0, coat_rough=0.03, rough_var=0.0)
    M["metal_le"] = principled("metal_le", (0.78, 0.79, 0.80), rough=0.22, metal=1.0, rough_var=0.08, rough_scale=6)
    M["metal_grey"] = principled("metal_grey", (0.55, 0.56, 0.57), rough=0.35, metal=1.0, rough_var=0.1)
    M["metal_dark"] = principled("metal_dark", (0.20, 0.19, 0.18), rough=0.45, metal=1.0, rough_var=0.15)
    M["metal_chrome"] = principled("metal_chrome", (0.92, 0.92, 0.93), rough=0.08, metal=1.0)
    M["inlet_liner"] = principled("inlet_liner", (0.50, 0.51, 0.52), rough=0.5, metal=0.6)
    M["fan_blade"] = principled("fan_blade", (0.18, 0.185, 0.19), rough=0.32, metal=0.9)
    M["spinner"] = principled("spinner", (0.05, 0.05, 0.055), rough=0.25, coat=0.8)
    M["black"] = principled("black_matte", (0.01, 0.01, 0.01), rough=0.9)
    M["rubber"] = principled("tyre_rubber", (0.025, 0.025, 0.027), rough=0.75, rough_var=0.1, rough_scale=20)
    M["gear_paint"] = principled("gear_paint", (0.72, 0.73, 0.74), rough=0.35, coat=0.5)
    M["door_line"] = principled("door_line", (0.12, 0.125, 0.13), rough=0.5)
    M["window"] = window_mat()
    M["cockpit_glass"] = principled("cockpit_glass", (0.01, 0.012, 0.016), rough=0.03, coat=1.0, coat_rough=0.01, spec=0.8)
    M["emit_red"] = emission_mat("light_red", (1.0, 0.02, 0.01), 400.0)
    M["emit_green"] = emission_mat("light_green", (0.05, 1.0, 0.25), 400.0)
    M["emit_white"] = emission_mat("light_white", (1.0, 0.97, 0.92), 900.0)
    M["emit_beacon"] = emission_mat("light_beacon", (1.0, 0.04, 0.02), 600.0)
    return M


# ============================================================================ FUSELAGE
R = 3.95 / 2.0
ZB, ZT = 1.95, 6.09
LEN = 44.51
K_W = 0.517  # max-width height as a fraction of section height (slightly taller lower lobe)

TOP = Profile([
    cubic((0, 3.55), (0.12, 4.38), (0.95, 4.86), (2.05, 5.06)),
    seg((2.05, 5.06), (3.1, 5.8)),
    cubic((3.1, 5.8), (4.0, 6.03), (5.3, ZT), (7.6, ZT)),
    seg((7.6, ZT), (33.4, ZT)),
    cubic((33.4, ZT), (38.2, 6.05), (42.1, 5.76), (44.22, 5.26)),
    seg((44.22, 5.26), (44.51, 5.12)),
], smooth=0.12, lo=(1.3, 1.7), hi=(43.6, 44.0))

BOT = Profile([
    cubic((0, 3.55), (0.2, 2.74), (1.7, 2.0), (5.6, ZB)),
    seg((5.6, ZB), (15.4, ZB)),
    cubic((15.4, ZB), (17.4, 1.72), (25.2, 1.72), (27.6, ZB)),
    seg((27.6, ZB), (32.6, ZB)),
    cubic((32.6, ZB), (36.2, 2.06), (40.6, 3.62), (44.22, 4.74)),
    seg((44.22, 4.74), (44.51, 4.88)),
], smooth=0.25, lo=(5.0, 6.0), hi=(43.6, 44.0))

BOT_BASE = Profile([
    cubic((0, 3.55), (0.2, 2.74), (1.7, 2.0), (5.6, ZB)),
    seg((5.6, ZB), (32.6, ZB)),
    cubic((32.6, ZB), (36.2, 2.06), (40.6, 3.62), (44.22, 4.74)),
    seg((44.22, 4.74), (44.51, 4.88)),
], smooth=0.25, lo=(5.0, 6.0), hi=(43.6, 44.0))

WID = Profile([
    cubic((0, 0), (0.25, 1.25), (2.9, R), (6.8, R)),
    seg((6.8, R), (33.6, R)),
    cubic((33.6, R), (38.6, R - 0.15), (43.2, 0.75), (44.51, 0.32)),
])

X_END = 44.42  # end of the tail-cone loft (APU exhaust lip follows)


def fairing(x):
    return smoothstep(14.4, 18.4, x) * (1.0 - smoothstep(25.2, 29.2, x))


def fus_params(x):
    x = np.asarray(x, float)
    zt, zb, zbb, w = TOP(x), BOT(x), BOT_BASE(x), WID(x)
    hh = 0.5 * (zt - zb)
    w = w + (hh - w) * smoothstep(42.0, 44.5, x) * 0.6  # round off the tail-cone end around the APU
    zw = zbb + K_W * (zt - zbb)
    return zt, zb, zw, w, fairing(x)


def fus_curve(x, th):
    """Section curve at stations x (broadcast with th).  th=0 starboard, pi/2 crown, pi port, 3pi/2 keel."""
    zt, zb, zw, w, f = fus_params(x)
    c, s = np.cos(th), np.sin(th)
    plo = 2.0 / (2.0 + 1.5 * f)  # belly-fairing: boxier lower lobe
    up = s >= 0
    y = np.where(up, w * c, w * np.sign(c) * np.abs(c) ** plo)
    z = np.where(up, zw + (zt - zw) * s, zw - (zw - zb) * np.abs(s) ** plo)
    return y, z


def fus_point(x, th):
    x = np.asarray(x, float) * np.ones_like(th)
    y, z = fus_curve(x, th)
    return np.stack([x, y, z], -1)


def fus_normal(x, th, e=1e-4):
    x = np.asarray(x, float) * np.ones_like(th)
    px = fus_point(x + e, th) - fus_point(x - e, th)
    pt = fus_point(x, th + e) - fus_point(x, th - e)
    n = np.cross(pt, px)
    n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-12
    return n


def fus_theta_side(x, z, side):
    """Invert z(theta) on one side (side=-1 port, +1 starboard)."""
    zt, zb, zw, w, f = fus_params(x)
    plo = 2.0 / (2.0 + 1.5 * f)
    up = z >= zw
    su = np.clip((z - zw) / np.maximum(zt - zw, 1e-6), -1, 1)
    sl = np.clip((zw - z) / np.maximum(zw - zb, 1e-6), 0, 1) ** (1.0 / plo)
    a = np.where(up, np.arcsin(su), -np.arcsin(sl))  # starboard angle in [-pi/2, pi/2]
    return a if side > 0 else np.pi - a


def fus_map(xz, side, offset):
    """Map side-projection (x,z) points onto the fuselage skin (+offset along the normal)."""
    x, z = xz[:, 0], xz[:, 1]
    th = fus_theta_side(x, z, side)
    p = fus_point(x, th)
    n = fus_normal(x, th)
    return p + n * offset, n


def fus_map_xt(x, th, offset):
    return fus_point(x, th) + fus_normal(x, th) * offset


def fus_section_pts(x, N):
    q = N // 4
    out = []
    for k in range(4):
        th = np.linspace(k * np.pi / 2, (k + 1) * np.pi / 2, 700)
        y, z = fus_curve(np.full_like(th, x), th)
        d = np.hypot(np.diff(y), np.diff(z))
        s = np.concatenate([[0], np.cumsum(d)])
        if s[-1] < 1e-9:
            thq = th[:q]
        else:
            thq = np.interp(np.linspace(0, s[-1], q + 1)[:-1], s, th)
        out.append(thq)
    th = np.concatenate(out)
    y, z = fus_curve(np.full_like(th, x), th)
    return np.stack([y, z], -1)


def build_fuselage(M, coll, hi=True):
    N = 192 if hi else 64
    if hi:
        xs = np.concatenate([
            [0.0, 0.0015, 0.006, 0.014, 0.026, 0.045, 0.07, 0.10, 0.14, 0.19, 0.25, 0.32, 0.40],
            np.arange(0.48, 7.6, 0.06), np.arange(7.6, 32.0, 0.2), np.linspace(32.0, X_END, 110)])
    else:
        xs = np.concatenate([[0.0, 0.01, 0.04, 0.09, 0.16, 0.26, 0.4], np.arange(0.6, 7.6, 0.25),
                             np.arange(7.6, 32.0, 0.8), np.linspace(32.0, X_END, 22)])
    secs = [fus_section_pts(x, N) for x in xs]
    P = [np.column_stack([np.full(N, x), s]) for x, s in zip(xs, secs)]
    # APU exhaust lip + cavity: rings scaled about the last section's centre
    zt, zb, zw, w, f = fus_params(X_END)
    last = secs[-1]
    ctr = np.array([0.0, float(zw)])
    extra = [(44.47, 0.93), (44.49, 0.80), (44.48, 0.70), (44.44, 0.66), (44.33, 0.60), (44.30, 0.0)]
    for x, sc in extra:
        P.append(np.column_stack([np.full(N, x), ctr + (last - ctr) * sc]))
    P = np.array(P)
    nu = len(P)
    faces, I, J = grid_faces(nu, N)
    mat = np.where(I >= len(xs) + 1, 1, 0)
    us = np.concatenate([xs, [e[0] for e in extra]]) / LEN
    uv = grid_uv(I, J, us, N).reshape(-1, 2)
    me = build_mesh("fuselage", P.reshape(-1, 3), faces, mat, uv, sharp_deg=40)
    ob = new_object("fuselage", me, [M["paint_white"], M["metal_dark"]], coll)
    log("fuselage verts", len(me.vertices))
    return ob


# ----------------------------------------------------------------------------- decals on the fuselage
def rounded_rect(cx, cz, w, h, r, n=10):
    r = min(r, w / 2, h / 2)
    pts = []
    for (ox, oz, a0) in [(w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180), (w / 2 - r, -h / 2 + r, 270)]:
        a = np.radians(a0 + np.linspace(0, 90, n))
        pts.append(np.stack([cx + ox + r * np.cos(a), cz + oz + r * np.sin(a)], -1))
    return np.vstack(pts)


def densify(loop, step=0.03, n=None):
    """Resample a closed 2D loop so straight runs follow the curved skin when mapped."""
    P = np.vstack([loop, loop[:1]])
    d = np.hypot(*np.diff(P, axis=0).T)
    s = np.concatenate([[0], np.cumsum(d)])
    n = n or max(int(s[-1] / step), len(loop))
    t = np.linspace(0, s[-1], n, endpoint=False)
    return np.column_stack([np.interp(t, s, P[:, 0]), np.interp(t, s, P[:, 1])])


def ring_patch(boundary, scales=(1.0, 0.9, 0.82, 0.6, 0.3)):
    """Concentric rings toward the centroid. Returns 2D verts, faces, per-vertex ring scale."""
    c = boundary.mean(0)
    M = len(boundary)
    V, S = [], []
    for s in scales:
        V.append(c + (boundary - c) * s)
        S.append(np.full(M, s))
    V.append(c[None])
    S.append(np.array([0.0]))
    V = np.vstack(V)
    S = np.concatenate(S)
    faces = []
    for k in range(len(scales) - 1):
        for j in range(M):
            j2 = (j + 1) % M
            faces.append((k * M + j, k * M + j2, (k + 1) * M + j2, (k + 1) * M + j))
    ci = len(scales) * M
    k = len(scales) - 1
    for j in range(M):
        faces.append((k * M + j, k * M + (j + 1) % M, ci))
    return V, faces, S


def ribbon(boundary_out, boundary_in):
    M = len(boundary_out)
    V = np.vstack([boundary_out, boundary_in])
    faces = [(j, (j + 1) % M, M + (j + 1) % M, M + j) for j in range(M)]
    return V, faces


class MeshAccum:
    def __init__(self):
        self.V, self.F, self.UV, self.MI = [], [], [], []
        self.n = 0

    def add(self, V, F, uvv=None, mi=0, nref=None):
        V = np.asarray(V, float)
        for f in F:
            if nref is not None and len(f) >= 3:
                a, b, c = V[f[0]], V[f[1]], V[f[2]]
                fn = np.cross(b - a, c - a)
                if np.linalg.norm(fn) > 1e-14 and np.dot(fn, np.mean([nref[i] for i in f], 0)) < 0:
                    f = tuple(f)[::-1]
            self.F.append(tuple(int(i) + self.n for i in f))
            self.MI.append(mi)
            if uvv is not None:
                self.UV.append([uvv[int(i)] for i in f])
        self.V.append(V)
        self.n += len(V)

    def mesh(self, name, smooth=True, recalc=False, sharp=None):
        uv = None
        if self.UV:
            uv = np.array([c for f in self.UV for c in f], float)
        return build_mesh(name, np.vstack(self.V), self.F, self.MI, uv, smooth=smooth, sharp_deg=sharp,
                          merge=0, recalc=recalc)


class EdgeAccum:
    def __init__(self):
        self.V, self.E, self.n = [], [], 0

    def loop(self, P, closed=True):
        P = np.asarray(P, float)
        m = len(P)
        for i in range(m - (0 if closed else 1)):
            self.E.append((self.n + i, self.n + (i + 1) % m))
        self.V.append(P)
        self.n += m

    def mesh(self, name):
        me = bpy.data.meshes.new(name)
        me.from_pydata(np.vstack(self.V).tolist(), self.E, [])
        me.update()
        return me


WIN_X = [x for x in np.arange(7.4, 38.3, 0.535)
         if not ((5.4 < x < 6.9) or (19.0 < x < 19.95) or (20.7 < x < 21.65) or (38.6 < x < 39.9))]
DOORS = [(5.75, 0.81, 2.55, 1.85), (19.3, 0.5, 3.45, 0.95), (21.0, 0.5, 3.45, 0.95), (38.9, 0.81, 2.75, 1.75)]


def build_windows(M, coll, guides):
    acc = MeshAccum()
    for side in (-1, 1):
        for x in WIN_X:
            b = densify(rounded_rect(x + 0.115, 4.05, 0.235, 0.335, 0.095, n=LOD["win_corner"]), n=LOD["win_pts"])
            V2, F, S = ring_patch(b, LOD["win_rings"])
            V3, N3 = fus_map(V2, side, 0.004)
            acc.add(V3, F, [(s, 0.5) for s in S], nref=N3)
            if side < 0:
                g, _ = fus_map(b, side, 0.012)
                guides.loop(g)
    me = acc.mesh("windows")
    return new_object("windows", me, [M["window"]], coll)


def build_doors(M, coll, guides):
    acc = MeshAccum()
    for side in (-1, 1):
        for (x, w, z0, h) in DOORS:
            cx, cz = x + w / 2, z0 + h / 2
            W, H = w + 0.24, h + 0.24  # TS door() adds 0.12 rounding outside the box
            nn = int(2 * (W + H) / LOD["door_step"])
            ob = densify(rounded_rect(cx, cz, W + 0.014, H + 0.014, 0.127, n=10), n=nn)
            ib = densify(rounded_rect(cx, cz, W - 0.014, H - 0.014, 0.113, n=10), n=nn)
            (Po, No), (Pi, Ni) = fus_map(ob, side, 0.003), fus_map(ib, side, 0.003)
            V, F = ribbon(Po, Pi)
            acc.add(V, F, nref=np.vstack([No, Ni]))
            g, _ = fus_map(densify(rounded_rect(cx, cz, W, H, 0.12, n=10), 0.03), side, 0.012)
            guides.loop(g)
            # door handle recess (small dark mark) on pax doors
            if w > 0.7:
                hb = rounded_rect(cx + 0.18 * (1 if side < 0 else -1) * -1, cz + 0.15, 0.16, 0.05, 0.02, n=4)
                V2, F2, S2 = ring_patch(hb, (1.0, 0.5))
                P2, N2 = fus_map(V2, side, 0.003)
                acc.add(P2, F2, nref=N2)
    me = acc.mesh("door_lines")
    return new_object("door_lines", me, [M["door_line"]], coll)


def quad_patch_xt(corners, side_sign, rad=0.1, n=8, scales=None, offset=0.006):
    """Rounded-quad patch defined by 4 (x, theta) corners [bl, br, tr, tl] in a unit square."""
    b = densify(rounded_rect(0.5, 0.5, 1.0, 1.0, rad, n=n), n=LOD["pane_pts"])
    V2, F, S = ring_patch(b, scales or LOD["pane_rings"])
    c = np.asarray(corners, float)
    u, v = V2[:, 0], V2[:, 1]
    xt = ((1 - u) * (1 - v))[:, None] * c[0] + (u * (1 - v))[:, None] * c[1] + (u * v)[:, None] * c[2] + ((1 - u) * v)[:, None] * c[3]
    P = fus_map_xt(xt[:, 0], xt[:, 1], offset)
    Nn = fus_normal(xt[:, 0], xt[:, 1])
    bd = ((1 - b[:, 0]) * (1 - b[:, 1]))[:, None] * c[0] + (b[:, 0] * (1 - b[:, 1]))[:, None] * c[1] + (b[:, 0] * b[:, 1])[:, None] * c[2] + ((1 - b[:, 0]) * b[:, 1])[:, None] * c[3]
    G = fus_map_xt(bd[:, 0], bd[:, 1], 0.012)
    return P, F, S, G, Nn


def build_cockpit(M, coll, guides):
    """A320-family flight-deck glazing: windshield + sliding window + rear side window per side.
    Corners are real skin positions: (x, z) on the side wall, or (x, 'crown') at the centre post."""
    acc = MeshAccum()
    post = 0.038  # half centre-post width (rad from the crown)
    panes = [
        # windshield: bottom-inner, bottom-outer, top-outer, top-inner
        [(2.10, "crown"), (2.40, 5.06), (3.10, 5.63), (2.98, "crown")],
        # sliding window (bl, br, tr, tl)
        [(2.56, 5.06), (3.56, 5.22), (3.64, 5.61), (3.23, 5.66)],
        # rear side window
        [(3.73, 5.25), (4.52, 5.32), (4.56, 5.64), (3.78, 5.65)],
    ]
    for side in (-1, 1):
        sgn = 1 if side < 0 else -1
        for k, pane in enumerate(panes):
            corners = []
            for x, z in pane:
                if z == "crown":
                    corners.append((x, np.pi / 2 + sgn * post))
                else:
                    corners.append((x, float(fus_theta_side(np.array([x]), np.array([z]), side)[0])))
            P, F, S, G, Nn = quad_patch_xt(corners, side, rad=0.10 if k else 0.07)
            acc.add(P, F, [(s, 0.5) for s in S], nref=Nn)
            guides.loop(G)
    me = acc.mesh("cockpit_windows")
    return new_object("cockpit_windows", me, [M["window"]], coll)


def text_triangles(body, cap_height, maxlen=None, space=1.08):
    """Archivo text -> 2D triangles (baseline at 0, left at 0) scaled to cap height."""
    font = bpy.data.fonts.load(FONT_PATH, check_existing=True) if os.path.exists(FONT_PATH) else None
    cu = bpy.data.curves.new("txt_" + body, "FONT")
    cu.body = body
    if font:
        cu.font = font
    cu.size = 1.0
    cu.space_character = space
    cu.resolution_u = 16
    ob = bpy.data.objects.new("txt_" + body, cu)
    bpy.context.scene.collection.objects.link(ob)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    bpy.data.objects.remove(ob)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    co = np.array([v.co[:2] for v in bm.verts])
    ymin, ymax = co[:, 1].min(), co[:, 1].max()
    s = cap_height / (ymax - ymin)
    for v in bm.verts:
        v.co.x = (v.co.x - co[:, 0].min()) * s
        v.co.y = (v.co.y - ymin) * s
        v.co.z = 0
    maxlen = maxlen or LOD["text_maxlen"]
    for _ in range(8):
        long = [e for e in bm.edges if e.calc_length() > maxlen]
        if not long:
            break
        bmesh.ops.subdivide_edges(bm, edges=long, cuts=1)
        bmesh.ops.triangulate(bm, faces=bm.faces)
    V = np.array([v.co[:2] for v in bm.verts])
    F = [tuple(v.index for v in f.verts) for f in bm.faces]
    bm.free()
    bpy.data.meshes.remove(me)
    return V, F, V[:, 0].max()


def build_text_decal(M, coll, body, x0, z0, cap, name, mat, space=1.08):
    V, F, L = text_triangles(body, cap, space=space)
    acc = MeshAccum()
    for side in (-1, 1):
        if side < 0:
            xz = np.column_stack([x0 + V[:, 0], z0 + V[:, 1]])
        else:  # starboard reads tail->nose: mirror in x
            xz = np.column_stack([x0 + L - V[:, 0], z0 + V[:, 1]])
        P, Nn = fus_map(xz, side, 0.003)
        acc.add(P, F, nref=Nn)
    me = acc.mesh(name, smooth=True, recalc=False)
    ob = new_object(name, me, [mat], coll)
    log(name, "length %.2f m" % L)
    return ob


# ============================================================================ WINGS / TAIL
def airfoil(xi, tc, camber=0.0, aft=1.21, te_closed=True):
    xp = xi ** aft
    a4 = -0.1036 if te_closed else -0.1015
    yt = 5 * tc * (0.2969 * np.sqrt(xp) - 0.1260 * xp - 0.3516 * xp ** 2 + 0.2843 * xp ** 3 + a4 * xp ** 4)
    yc = camber * 6.75 * xi ** 2 * (1 - xi)
    return yc + yt, yc - yt


def chord_ring(nc):
    k = np.arange(nc)
    xi = 0.5 * (1 - np.cos(np.pi * k / (nc - 1)))
    xi_r = np.concatenate([[1.0], xi[-2:0:-1], [0.0], xi[1:-1]])
    up = np.concatenate([[True], np.ones(nc - 2, bool), [True], np.zeros(nc - 2, bool)])
    return xi_r, up


TAN_LE = (27.05 - 18.9) / (17.35 - R)
DIHEDRAL = math.radians(5.5)
Z_LE_ROOT = 2.62
_ygrid = np.linspace(0.0, 18.5, 3700)
_xte_raw = np.where(_ygrid <= 6.3, 25.2 + (_ygrid - R) * (25.55 - 25.2) / (6.3 - R),
                    25.55 + (_ygrid - 6.3) * (28.5 - 25.55) / (17.35 - 6.3))
_k = np.exp(-0.5 * (np.arange(-200, 201) * 0.005 / 0.25) ** 2)
_k /= _k.sum()
_xte_s = np.convolve(np.pad(_xte_raw, 200, mode="edge"), _k, mode="valid")


def wing_xle(y):
    return 18.9 + (np.asarray(y) - R) * TAN_LE


def wing_xte(y):
    return np.interp(y, _ygrid, _xte_s)


def wing_zle(y):
    return Z_LE_ROOT + (np.asarray(y) - R) * math.tan(DIHEDRAL)


def wing_stations(hi=True):
    """Spanwise stations along the LE reference path (y,z), blended up into the sharklet."""
    st = []
    yb = 16.95
    n_main = 44 if hi else 16
    ys = np.unique(np.concatenate([np.linspace(1.0, 2.4, 5), np.linspace(2.4, yb, n_main), [5.9, 6.1, 6.2, 6.3, 6.4, 6.5, 6.7]]))
    for y in ys:
        f = (y - R) / (17.35 - R)
        tc = np.interp(y, [1.0, R, 6.3, 17.35], [0.15, 0.15, 0.125, 0.108])
        st.append(dict(py=y, pz=float(wing_zle(y)), ang=DIHEDRAL, xle=float(wing_xle(y)), xte=float(wing_xte(y)),
                       tc=float(tc), cam=0.014 - 0.004 * f, twist=math.radians(1.5 - 2.0 * np.clip(f, 0, 1)),
                       k=1.0, region=0))
    # blend arc + sharklet
    rb, a_end, top = 0.70, math.radians(80.0), 6.45
    Pb = np.array([yb, float(wing_zle(yb))])
    C = Pb + rb * np.array([-math.sin(DIHEDRAL), math.cos(DIHEDRAL)])
    pa_end = C + rb * np.array([math.sin(a_end), -math.cos(a_end)])
    Ls = (top - pa_end[1]) / math.sin(a_end)
    S_arc = rb * (a_end - DIHEDRAL)
    S_tot = S_arc + Ls
    x0, x1 = float(wing_xle(yb)), 28.35
    m0 = TAN_LE * math.cos(DIHEDRAL)
    t0, t1 = float(wing_xte(yb)), 29.05
    n_arc, n_str = (12, 14) if hi else (5, 6)
    samples = [("arc", a) for a in np.linspace(DIHEDRAL, a_end, n_arc + 1)[1:]] + [("str", l) for l in np.linspace(0, Ls, n_str + 1)[1:]]
    tc_tip = 0.108
    for kind, v in samples:
        if kind == "arc":
            P = C + rb * np.array([math.sin(v), -math.cos(v)])
            ang = v
            s = rb * (v - DIHEDRAL)
        else:
            P = pa_end + v * np.array([math.cos(a_end), math.sin(a_end)])
            ang = a_end
            s = S_arc + v
        u = s / S_tot
        xle = hermite(x0, m0 * S_tot, x1, 0.42 * S_tot, u)
        xte = hermite(t0, 0.266 * S_tot, t1, 0.116 * S_tot, u)
        st.append(dict(py=float(P[0]), pz=float(P[1]), ang=ang, xle=float(xle), xte=float(xte),
                       tc=float(tc_tip + (0.088 - tc_tip) * u), cam=0.010 * (1 - u) + 0.004, twist=math.radians(-0.5 * (1 - u)),
                       k=1.0, region=1 if ang > math.radians(40) else 0))
    # rounded tip cap
    last = st[-1]
    for dl, kk, inset in [(0.010, 0.82, 0.004), (0.019, 0.50, 0.012), (0.024, 0.0, 0.03)]:
        P = np.array([last["py"], last["pz"]]) + dl * np.array([math.cos(a_end), math.sin(a_end)])
        c = last["xte"] - last["xle"]
        d = dict(last)
        d.update(py=float(P[0]), pz=float(P[1]), xle=last["xle"] + inset * c, xte=last["xte"] - inset * c * 0.5, k=kk)
        st.append(d)
    return st


def loft_wing(stations, nc, side, symmetric=False):
    xi_r, up = chord_ring(nc)
    ns, nr = len(stations), len(xi_r)
    P = np.zeros((ns, nr, 3))
    for i, s in enumerate(stations):
        c = s["xte"] - s["xle"]
        yu, yl = airfoil(xi_r, s["tc"], 0.0 if symmetric else s["cam"])
        b = np.where(up, yu, yl) * c * s["k"]
        a = xi_r * c - 0.25 * c
        ct, sn = math.cos(s["twist"]), math.sin(s["twist"])
        ax = a * ct + b * sn
        bn = -a * sn + b * ct
        N = np.array([-math.sin(s["ang"]), math.cos(s["ang"])])
        P[i, :, 0] = s["xle"] + 0.25 * c + ax
        P[i, :, 1] = s["py"] + bn * N[0]
        P[i, :, 2] = s["pz"] + bn * N[1]
    if side < 0:
        P[:, :, 1] *= -1
    return P, xi_r, up


def build_wing(M, coll, side, hi=True, guides=None):
    st = wing_stations(hi)
    nc = 56 if hi else 22
    P, xi_r, up = loft_wing(st, nc, side)
    ns, nr = P.shape[:2]
    faces, I, J = grid_faces(ns, nr)
    J2 = (J + 1) % nr
    xi_f = 0.5 * (xi_r[J] + xi_r[J2])
    upper_face = np.where(J < nc - 1, True, False)  # ring order: TE, upper..., LE, lower...
    reg = np.array([s["region"] for s in st])[I]
    mat = np.where(xi_f < 0.065, 2, np.where(upper_face, 0, 1))
    mat = np.where(reg == 1, 3, mat)
    us = np.array([s["py"] for s in st]) / 20.0
    uv = grid_uv(I, J, us, nr).reshape(-1, 2)
    name = "wing_R" if side > 0 else "wing_L"
    me = build_mesh(name, P.reshape(-1, 3), faces, mat, uv, sharp_deg=50)
    ob = new_object(name, me, [M["paint_grey"], M["paint_white"], M["metal_le"], M["paint_navy"]], coll)
    if guides is not None:
        wing_guides(st, side, guides)
    return ob, st


def wing_surface_point(st_main, y, xi, upper=True, side=1, off=0.012):
    """Point on the main wing upper/lower surface at span y and chord fraction xi (interpolated stations)."""
    ys = np.array([s["py"] for s in st_main])
    s = {}
    for key in ("pz", "xle", "xte", "tc", "cam", "twist"):
        s[key] = float(np.interp(y, ys, [q[key] for q in st_main]))
    c = s["xte"] - s["xle"]
    yu, yl = airfoil(np.array([xi]), s["tc"], s["cam"])
    b = (yu if upper else yl)[0] * c + (off if upper else -off)
    a = xi * c - 0.25 * c
    ct, sn = math.cos(s["twist"]), math.sin(s["twist"])
    ax, bn = a * ct + b * sn, -a * sn + b * ct
    return np.array([s["xle"] + 0.25 * c + ax, side * (y - bn * math.sin(DIHEDRAL)), s["pz"] + bn * math.cos(DIHEDRAL)])


def wing_guides(st, side, guides):
    main = [s for s in st if s["region"] == 0 and s["ang"] < math.radians(10)]
    def line_xi(y0, y1, xi0, xi1, upper=True, n=24):
        ys = np.linspace(y0, y1, n)
        xis = np.linspace(xi0, xi1, n)
        guides.loop([wing_surface_point(main, y, xi, upper, side) for y, xi in zip(ys, xis)], closed=False)
    # flap / aileron hinge, spoiler line, slat line, aileron break (upper surface) after aircraft.ts topView
    def xi_at(y, x):
        return (x - float(wing_xle(y))) / (float(wing_xte(y)) - float(wing_xle(y)))
    for (y0, x0, y1, x1) in [(2.6, 24.25, 6.3, 24.85), (6.3, 24.85, 15.6, 27.35), (6.6, 23.2, 12.0, 25.4)]:
        line_xi(y0, y1, xi_at(y0, x0), xi_at(y1, x1))
    line_xi(12.4, 12.45, xi_at(12.4, 26.7), xi_at(12.45, 27.85), n=8)
    line_xi(2.4, 16.6, 0.13, 0.13)  # slat trailing edge


def hstab_stations(hi=True):
    st = []
    dih = math.radians(6.0)
    tan_le = (42.15 - 38.9) / (6.22 - 1.05)
    tan_te = (43.55 - 42.8) / (6.22 - 0.85)
    ytip = 6.225
    ys = np.linspace(0.25, ytip - 0.02, 26 if hi else 10)
    for y in ys:
        st.append(dict(py=y, pz=5.2 + (y - 1.05) * math.tan(dih), ang=dih, xle=38.9 + (y - 1.05) * tan_le,
                       xte=42.8 + (y - 0.85) * tan_te, tc=float(np.interp(y, [0, ytip], [0.11, 0.09])), cam=-0.006,
                       twist=0.0, k=1.0, region=0))
    last = st[-1]
    for dy, kk, inset in [(0.012, 0.8, 0.006), (0.022, 0.48, 0.02), (0.028, 0.0, 0.05)]:
        d = dict(last)
        c = last["xte"] - last["xle"]
        d.update(py=last["py"] + dy, pz=last["pz"] + dy * math.tan(dih), xle=last["xle"] + inset * c,
                 xte=last["xte"] - inset * c * 0.4, k=kk)
        st.append(d)
    return st


def build_hstab(M, coll, hi=True):
    st = hstab_stations(hi)
    nc = 40 if hi else 16
    acc_P, acc_F, acc_M, acc_UV = [], [], [], []
    base = 0
    for side in (-1, 1):
        P, xi_r, up = loft_wing(st, nc, side)
        ns, nr = P.shape[:2]
        faces, I, J = grid_faces(ns, nr)
        J2 = (J + 1) % nr
        xi_f = 0.5 * (xi_r[J] + xi_r[J2])
        mat = np.where(xi_f < 0.06, 2, np.where(J < nc - 1, 0, 1))
        us = np.array([s["py"] for s in st]) / 10.0
        acc_UV.append(grid_uv(I, J, us, nr).reshape(-1, 2))
        acc_P.append(P.reshape(-1, 3))
        acc_F.append(faces + base)
        acc_M.append(mat)
        base += ns * nr
    me = build_mesh("stabiliser", np.vstack(acc_P), np.vstack(acc_F), np.concatenate(acc_M), np.vstack(acc_UV), sharp_deg=50)
    return new_object("stabiliser", me, [M["paint_grey"], M["paint_white"], M["metal_le"]], coll)


# ----------------------------------------------------------------------------- fin
_fil = cubic((34.9, 6.08), (35.7, 6.18), (36.1, 6.5), (36.35, 6.95), 300)


def fin_xle(z):
    z = np.asarray(z, float)
    main = 36.35 + (z - 6.95) * (40.6 - 36.35) / (11.76 - 6.95)
    fil = np.interp(z, _fil[:, 1], _fil[:, 0])
    below = 34.9 - (6.08 - z) * 1.2
    return np.where(z >= 6.95, main, np.where(z >= 6.08, fil, below))


def fin_xte(z):
    return 43.78 + (np.asarray(z, float) - 5.44) * (42.86 - 43.78) / (11.76 - 5.44)


def fin_xhinge(z):
    return 42.92 + (np.asarray(z, float) - 5.7) * (42.0 - 42.92) / (11.66 - 5.7)


C_FIN_ROOT = float(fin_xte(6.95) - 36.35)
T_FIN_ROOT = 0.105 * C_FIN_ROOT


def fin_tc(z):
    z = np.asarray(z, float)
    c = fin_xte(z) - fin_xle(z)
    upper = 0.105 + (z - 6.95) / (11.76 - 6.95) * (0.092 - 0.105)
    return np.where(z >= 6.95, upper, T_FIN_ROOT / c)


def fin_half(xi, z):
    tc = fin_tc(z)
    c = fin_xte(z) - fin_xle(z)
    yu, _ = airfoil(np.clip(xi, 0, 1), tc, 0.0, aft=1.12)
    return yu * c


def build_fin(M, coll, hi=True, guides=None):
    zs = list(np.concatenate([[5.0, 5.3, 5.6, 5.85, 6.0, 6.08, 6.14, 6.22, 6.32, 6.45, 6.6, 6.77, 6.95],
                              np.linspace(7.2, 11.74, 22 if hi else 8)]))
    nc = 48 if hi else 18
    xi_r, up = chord_ring(nc)
    rings = []
    ks = [1.0] * len(zs)
    for dz, kk, inset in [(0.012, 0.8, 0.004), (0.022, 0.5, 0.012), (0.028, 0.0, 0.03)]:
        zs.append(11.74 + dz)
        ks.append((kk, inset))
    for z, k in zip(zs, ks):
        zz = min(z, 11.74)
        xl, xt = float(fin_xle(zz)), float(fin_xte(zz))
        kk, inset = (k, 0.0) if not isinstance(k, tuple) else k
        c = xt - xl
        xl2, xt2 = xl + inset * c, xt - inset * c * 0.4
        h = np.array([float(fin_half(xi, np.array(zz))) for xi in xi_r]) * kk
        X = xl2 + xi_r * (xt2 - xl2)
        Y = np.where(up, h, -h)
        rings.append(np.column_stack([X, Y, np.full_like(X, z)]))
    P = np.array(rings)
    ns, nr = P.shape[:2]
    faces, I, J = grid_faces(ns, nr)
    us = (np.array(zs) - 5.0) / 7.0
    uv = grid_uv(I, J, us, nr).reshape(-1, 2)
    me = build_mesh("fin", P.reshape(-1, 3), faces, None, uv, sharp_deg=50)
    ob = new_object("fin", me, [M["paint_navy"]], coll)
    if guides is not None:
        for side in (-1, 1):
            zz = np.linspace(5.75, 11.62, 40)
            xh = fin_xhinge(zz)
            xi = (xh - fin_xle(zz)) / (fin_xte(zz) - fin_xle(zz))
            yy = np.array([side * (float(fin_half(a, np.array(b))) + 0.012) for a, b in zip(xi, zz)])
            guides.loop(np.column_stack([xh, yy, zz]), closed=False)
    return ob


def fin_map(xz, side, offset):
    x, z = xz[:, 0], xz[:, 1]
    xl, xt = fin_xle(z), fin_xte(z)
    xi = (x - xl) / (xt - xl)
    h = np.array([float(fin_half(a, np.array(b))) for a, b in zip(xi, z)])
    return np.column_stack([x, side * (h + offset), z])


def star_polygon(cx, cz, rv, rh, p=0.62, n=220, rot=0.0):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    c, s = np.cos(t), np.sin(t)
    x = rh * np.sign(c) * np.abs(c) ** (2 / p)
    z = rv * np.sign(s) * np.abs(s) ** (2 / p)
    cr, sr = math.cos(rot), math.sin(rot)
    return np.column_stack([cx + x * cr - z * sr, cz + x * sr + z * cr])


def build_fin_star(M, coll):
    """White four-point compass star on both sides of the fin (+ a thin white ring)."""
    acc = MeshAccum()
    cx, cz = 40.25, 8.95
    for side in (-1, 1):
        b = star_polygon(cx, cz, 1.30, 0.86)
        V2, F, S = ring_patch(b, (1.0, 0.85, 0.65, 0.45, 0.28, 0.14, 0.05))
        P = fin_map(V2, side, 0.003)
        acc.add(P, F, nref=np.tile([0, side, 0], (len(P), 1)))
        # small diagonal points (8-point compass rose accent)
        b2 = star_polygon(cx, cz, 0.62, 0.62, p=0.55, rot=math.radians(45))
        V3, F3, S3 = ring_patch(b2, (1.0, 0.7, 0.4, 0.15))
        P3 = fin_map(V3, side, 0.0025)
        acc.add(P3, F3, nref=np.tile([0, side, 0], (len(P3), 1)))
    me = acc.mesh("fin_star", recalc=False)
    return new_object("fin_star", me, [M["paint_white"]], coll)


# ============================================================================ ENGINES
ENG_Y, ENG_Z, ENG_X0 = 5.75, 1.775, 14.85


def revolve(profile, n, origin, axis=(1, 0, 0), ref=(0, 0, 1), close=True):
    """profile (M,2): [t along axis, r].  Returns grid (M, n, 3)."""
    a = np.asarray(axis, float)
    a /= np.linalg.norm(a)
    r1 = np.asarray(ref, float)
    r1 = r1 - a * np.dot(r1, a)
    r1 /= np.linalg.norm(r1)
    r2 = np.cross(a, r1)
    phi = np.linspace(0, 2 * np.pi, n, endpoint=False)
    t, r = profile[:, 0][:, None, None], profile[:, 1][:, None, None]
    d = np.cos(phi)[None, :, None] * r1 + np.sin(phi)[None, :, None] * r2
    return np.asarray(origin, float) + t * a + r * d


def revolve_obj(name, profile, mat_seg, mats, n, origin, coll, axis=(1, 0, 0), ref=(0, 0, 1), sharp=40, uv_scale=1.0):
    P = revolve(profile, n, origin, axis, ref)
    M_, N_ = P.shape[:2]
    faces, I, J = grid_faces(M_, N_)
    mi = None if mat_seg is None else np.asarray(mat_seg)[I]
    us = np.linspace(0, 1, M_)
    uv = grid_uv(I, J, us, N_).reshape(-1, 2)
    me = build_mesh(name, P.reshape(-1, 3), faces, mi, uv, sharp_deg=sharp)
    return new_object(name, me, mats, coll)


def nacelle_profiles():
    cowl, sid = profile_chain([
        [(0.95, 0.988), (0.6, 0.982), (0.3, 0.990), (0.12, 1.010), (0.04, 1.036), (0.0, 1.070), (0.022, 1.108),
         (0.09, 1.148), (0.28, 1.184), (0.7, 1.209), (1.4, 1.222), (2.1, 1.212), (2.65, 1.172), (3.05, 1.094), (3.35, 1.004)],
        [(3.35, 1.004), (3.335, 0.988), (3.1, 0.994), (2.3, 1.008), (1.5, 1.000), (0.95, 0.988)],
    ], [150, 30])
    # material by position: inner duct liner / white lip / navy cowl / dark bypass
    mat = []
    for k, ((x, r), s) in enumerate(zip(cowl, sid)):
        if s == 1:
            mat.append(3)
        elif k < 150 and r < 1.07 and x > 0.035 and k < 75:
            mat.append(0)
        elif x < 0.30:
            mat.append(1)
        else:
            mat.append(2)
    core, csid = profile_chain([
        [(1.9, 0.86), (2.6, 0.83), (3.2, 0.785), (3.8, 0.685), (4.25, 0.545), (4.45, 0.497)],
        [(4.45, 0.497), (4.442, 0.478), (4.3, 0.482), (4.0, 0.505)],
    ], [70, 12])
    plug, _ = profile_chain([
        [(4.05, 0.0), (4.05, 0.42)],
        [(4.05, 0.42), (4.3, 0.432), (4.55, 0.405), (4.8, 0.30), (4.98, 0.165), (5.07, 0.06), (5.10, 0.0)],
    ], [6, 50])
    spinner, _ = profile_chain([
        [(0.06, 0.0), (0.16, 0.075), (0.36, 0.19), (0.58, 0.265), (0.8, 0.305), (0.97, 0.318)],
        [(0.97, 0.318), (0.98, 0.0)],
    ], [44, 6])
    return cowl, mat, core, csid, plug, spinner


def build_engine(M, coll, side, hi=True):
    n = 112 if hi else 40
    yc = side * ENG_Y
    origin = (ENG_X0, yc, ENG_Z)
    cowl, cmat, core, csid, plug, spinner = nacelle_profiles()
    tag = "1" if side < 0 else "2"
    parts = []
    parts.append(revolve_obj("engine_%s_nacelle" % tag, cowl, cmat[:-1] + [cmat[-1]],
                             [M["inlet_liner"], M["paint_white"], M["paint_navy"], M["metal_dark"]], n, origin, coll))
    parts.append(revolve_obj("engine_%s_core" % tag, core, [0 if s == 0 else 1 for s in csid],
                             [M["metal_grey"], M["metal_dark"]], n, origin, coll))
    parts.append(revolve_obj("engine_%s_plug" % tag, plug, None, [M["metal_dark"]], n, origin, coll))
    parts.append(revolve_obj("engine_%s_spinner" % tag, spinner, None, [M["spinner"]], n, origin, coll, sharp=30))
    # dark disc behind the fan so the inlet reads deep
    disc = np.array([[1.12, 0.0], [1.12, 0.99]])
    parts.append(revolve_obj("engine_%s_fandisc" % tag, disc, None, [M["black"]], n, origin, coll))
    # fan blades (18, wide-chord)
    nb = 18
    rr = np.linspace(0.30, 0.975, 12 if hi else 5)
    nsec = 14 if hi else 6
    acc = MeshAccum()
    for b in range(nb):
        phi0 = 2 * np.pi * b / nb
        secs = []
        for r in rr:
            f = (r - 0.30) / 0.675
            beta = math.radians(32 + 30 * f)
            chord = 0.30 + 0.14 * f
            th = 0.028 - 0.018 * f
            t = np.linspace(0, 2 * np.pi, nsec, endpoint=False)
            a = 0.5 * chord * np.cos(t)
            bb = 0.5 * th * np.sin(t) * (1 - 0.3 * np.cos(t))
            xa = 0.90 + 0.03 * f + a * math.cos(beta) - bb * math.sin(beta)
            ta = a * math.sin(beta) + bb * math.cos(beta)
            ang = phi0 + ta / r
            secs.append(np.column_stack([ENG_X0 + xa, yc + r * np.cos(ang), ENG_Z + r * np.sin(ang)]))
        P = np.array(secs)
        faces, I, J = grid_faces(len(rr), nsec)
        acc.add(P.reshape(-1, 3), faces)
        # tip cap
        base = (len(rr) - 1) * nsec
        acc.add(np.zeros((0, 3)), [])
    me = acc.mesh("engine_%s_fan" % tag, recalc=True, sharp=60)
    parts.append(new_object("engine_%s_fan" % tag, me, [M["fan_blade"]], coll))
    parts.append(build_pylon(M, coll, side, hi))
    return parts


def build_pylon(M, coll, side, hi=True):
    xs = np.linspace(16.2, 21.6, 64 if hi else 20)
    zt = np.interp(xs, [16.2, 16.5, 16.9, 17.3, 21.6], [2.95, 3.06, 3.17, 3.235, 3.0])
    zb = np.interp(xs, [16.2, 18.0, 18.6, 19.3, 19.95, 21.2, 21.6], [2.80, 2.80, 2.30, 2.15, 2.10, 2.60, 2.97])
    hw = np.interp(xs, [16.2, 16.6, 17.4, 19.6, 21.3, 21.6], [0.10, 0.19, 0.25, 0.25, 0.16, 0.04])
    n = 32 if hi else 12
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    c, s = np.cos(t), np.sin(t)
    p = 2 / 3.2
    secs = []
    for x, a, b, w in zip(xs, zt, zb, hw):
        zm, hh = 0.5 * (a + b), 0.5 * (a - b)
        y = w * np.sign(c) * np.abs(c) ** p
        z = zm + hh * np.sign(s) * np.abs(s) ** p
        secs.append(np.column_stack([np.full(n, x), side * ENG_Y + y, z]))
    P = np.array(secs)
    faces, I, J = grid_faces(len(xs), n)
    # close the ends with fans
    Vc = [P.reshape(-1, 3), P[0].mean(0)[None], P[-1].mean(0)[None]]
    nV = P.shape[0] * n
    F = [tuple(f) for f in faces]
    for j in range(n):
        F.append((nV, (j + 1) % n, j))
        F.append((nV + 1, (len(xs) - 1) * n + j, (len(xs) - 1) * n + (j + 1) % n))
    me = build_mesh("pylon_%s" % ("L" if side < 0 else "R"), np.vstack(Vc), F, None, None, sharp_deg=50)
    return new_object("pylon_%s" % ("L" if side < 0 else "R"), me, [M["paint_white"]], coll)


# ============================================================================ GEAR
def cylinder_obj(acc, p0, p1, r, n=24, cap=True):
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    ax = p1 - p0
    L = np.linalg.norm(ax)
    prof = np.array([[0, 0], [0, r], [L, r], [L, 0]]) if cap else np.array([[0, r], [L, r]])
    ref = (0, 0, 1) if abs(ax[2]) < 0.9 * L else (1, 0, 0)
    P = revolve(prof, n, p0, ax, ref)
    faces, I, J = grid_faces(P.shape[0], n)
    acc.add(P.reshape(-1, 3), faces)


def wheel(acc_tyre, acc_hub, centre, axis_y, r_out, width, n=48, hub_side=-1):
    cy = np.asarray(centre, float)
    hw = width / 2
    # tyre: rounded-rectangle section revolved around the axle (Y)
    t = np.linspace(0, 2 * np.pi, 40, endpoint=False)
    rr = r_out - 0.62 * width * 0.5
    sec_r = rr + 0.31 * width * np.sign(np.cos(t)) * np.abs(np.cos(t)) ** 0.5 + 0.0
    sec_r = (r_out + r_out * 0.58) / 2 + (r_out - r_out * 0.58) / 2 * np.sign(np.cos(t)) * np.abs(np.cos(t)) ** 0.45
    sec_t = hw * np.sign(np.sin(t)) * np.abs(np.sin(t)) ** 0.45
    prof = np.column_stack([sec_t, sec_r])
    P = revolve(prof, n, cy, (0, 1, 0), (0, 0, 1))
    faces, I, J = grid_faces(P.shape[0], n)
    # close the torus in the profile direction too
    m = P.shape[0]
    F = [tuple(f) for f in faces] + [((m - 1) * n + j, (m - 1) * n + (j + 1) % n, (j + 1) % n, j) for j in range(n)]
    acc_tyre.add(P.reshape(-1, 3), F)
    # hub: dished disc inside the tyre
    hp = np.array([[-hw * 0.82, 0.0], [-hw * 0.82, r_out * 0.33], [-hw * 0.9, r_out * 0.6], [hw * 0.9, r_out * 0.6],
                   [hw * 0.82, r_out * 0.33], [hw * 0.82, 0.0]])
    P2 = revolve(hp, n, cy, (0, 1, 0), (0, 0, 1))
    f2, _, _ = grid_faces(P2.shape[0], n)
    acc_hub.add(P2.reshape(-1, 3), f2)


def build_gear(M, coll, hi=True):
    objs = {}
    n = 32 if hi else 12
    # ---------------- nose gear
    strut, chrome, tyre, hub = MeshAccum(), MeshAccum(), MeshAccum(), MeshAccum()
    xg = 5.1
    cylinder_obj(strut, (xg, 0, 2.15), (xg, 0, 1.05), 0.085, n)
    cylinder_obj(chrome, (xg, 0, 1.10), (xg, 0, 0.52), 0.062, n)
    cylinder_obj(strut, (xg, -0.12, 0.38), (xg, 0.12, 0.38), 0.075, n)
    cylinder_obj(strut, (xg, 0, 0.55), (xg, 0, 0.38), 0.07, n)
    cylinder_obj(strut, (xg + 0.02, 0, 1.30), (xg - 0.75, 0, 2.05), 0.045, n)  # drag strut
    cylinder_obj(strut, (xg - 0.1, 0, 0.95), (xg - 0.16, 0, 0.72), 0.03, 12)  # torque link
    cylinder_obj(strut, (xg - 0.16, 0, 0.72), (xg - 0.05, 0, 0.55), 0.03, 12)
    cylinder_obj(chrome, (xg, -0.32, 0.38), (xg, 0.32, 0.38), 0.035, n)
    for s in (-1, 1):
        wheel(tyre, hub, (xg, s * 0.205, 0.38), True, 0.38, 0.20, 48 if hi else 20)
    nose = []
    for nm, acc, mat in (("strut", strut, M["gear_paint"]), ("chrome", chrome, M["metal_chrome"]), ("tyre", tyre, M["rubber"]),
                         ("hub", hub, M["metal_grey"])):
        nose.append(new_object("gear_nose_" + nm, acc.mesh("gear_nose_" + nm, recalc=True, sharp=40), [mat], coll))
    objs["gear_nose"] = nose
    # ---------------- main gear
    for side in (-1, 1):
        strut, chrome, tyre, hub, door = MeshAccum(), MeshAccum(), MeshAccum(), MeshAccum(), MeshAccum()
        xg, yg = 22.0, side * 3.8
        cylinder_obj(strut, (xg, yg, 2.70), (xg, yg, 1.35), 0.135, n)
        cylinder_obj(chrome, (xg, yg, 1.40), (xg, yg, 0.80), 0.098, n)
        cylinder_obj(strut, (xg, yg, 0.86), (xg, yg, 0.585), 0.11, n)
        cylinder_obj(strut, (xg, yg - 0.30, 0.585), (xg, yg + 0.30, 0.585), 0.10, n)
        cylinder_obj(chrome, (xg, yg - 0.62, 0.585), (xg, yg + 0.62, 0.585), 0.05, n)
        cylinder_obj(strut, (xg, yg, 1.70), (xg + 0.15, side * 2.2, 2.55), 0.065, n)  # side brace
        cylinder_obj(strut, (xg - 0.16, yg, 1.30), (xg - 0.26, yg, 1.05), 0.04, 12)  # torque links
        cylinder_obj(strut, (xg - 0.26, yg, 1.05), (xg - 0.12, yg, 0.84), 0.04, 12)
        for s in (-1, 1):
            wheel(tyre, hub, (xg, yg + s * 0.45, 0.585), True, 0.585, 0.40, 56 if hi else 20)
        # leg fairing door (outboard of the leg)
        dx = np.linspace(-0.48, 0.48, 10)
        dz = np.linspace(1.30, 2.45, 8)
        Pd = np.array([[[xg + x, yg + side * (0.20 + 0.06 * (1 - (x / 0.48) ** 2)), z] for x in dx] for z in dz])
        fd, _, _ = grid_faces(len(dz), len(dx), close_v=False)
        door.add(Pd.reshape(-1, 3), fd)
        Pd2 = Pd.copy()
        Pd2[:, :, 1] += side * 0.025
        door.add(Pd2.reshape(-1, 3), [tuple(f[::-1]) for f in fd])
        tag = "L" if side < 0 else "R"
        parts = []
        for nm, acc, mat in (("strut", strut, M["gear_paint"]), ("chrome", chrome, M["metal_chrome"]), ("tyre", tyre, M["rubber"]),
                             ("hub", hub, M["metal_grey"]), ("door", door, M["paint_white"])):
            parts.append(new_object("gear_main_%s_%s" % (tag, nm), acc.mesh("gear_main_%s_%s" % (tag, nm), recalc=(nm != "door"), sharp=40),
                                    [mat], coll))
        objs["gear_main_" + tag] = parts
    return objs


# ============================================================================ LIGHTS (emitters)
def sphere(acc, c, r, n=12):
    u = np.linspace(0, np.pi, n // 2 + 1)
    v = np.linspace(0, 2 * np.pi, n, endpoint=False)
    P = np.array([[[c[0] + r * math.sin(a) * math.cos(b), c[1] + r * math.sin(a) * math.sin(b), c[2] + r * math.cos(a)] for b in v] for a in u])
    f, _, _ = grid_faces(len(u), n)
    acc.add(P.reshape(-1, 3), f)


def build_lights(M, coll, wing_st):
    tip = [s for s in wing_st if s["region"] == 0][-1]
    out = {}
    specs = {
        "nav_red": (M["emit_red"], [(tip["xle"] - 0.02, -tip["py"], tip["pz"])], 0.06, (1, 0.02, 0.01), 15),
        "nav_green": (M["emit_green"], [(tip["xle"] - 0.02, tip["py"], tip["pz"])], 0.06, (0.05, 1, 0.25), 15),
        "strobe": (M["emit_white"], [(tip["xte"] + 0.03, -tip["py"], tip["pz"] + 0.02), (tip["xte"] + 0.03, tip["py"], tip["pz"] + 0.02), (44.53, 0.0, 5.22)], 0.05, (1, 0.97, 0.92), 30),
        "beacon": (M["emit_beacon"], [(20.6, 0, ZT + 0.06), (24.0, 0, 1.70)], 0.07, (1, 0.04, 0.02), 25),
    }
    for nm, (mat, pts, r, col, watt) in specs.items():
        acc = MeshAccum()
        for p in pts:
            sphere(acc, p, r)
        ob = new_object("light_" + nm, acc.mesh("light_" + nm, recalc=True, sharp=None), [mat], coll)
        ob.visible_shadow = False
        out[nm] = ob
        for k, p in enumerate(pts):
            ld = bpy.data.lights.new("pl_%s_%d" % (nm, k), "POINT")
            ld.color = col
            ld.energy = watt
            ld.shadow_soft_size = r * 0.6
            lo = bpy.data.objects.new("pl_%s_%d" % (nm, k), ld)
            lo.location = tuple(p)
            coll.objects.link(lo)
    return out


# ============================================================================ BUILD
def ensure_collection(name, parent=None):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    par = parent or bpy.context.scene.collection
    if c.name not in [x.name for x in par.children]:
        par.children.link(c)
    return c


def build(quality="hi"):
    hi = quality == "hi"
    if not hi:
        LOD.update(text_maxlen=0.25, win_corner=3, win_rings=(1.0, 0.5), win_pts=16, door_step=0.08, pane_pts=40,
                   pane_rings=(1.0, 0.8, 0.55, 0.3))
    M = make_materials()
    root = ensure_collection("A321")
    col_air = ensure_collection("A321_airframe", root)
    col_dec = ensure_collection("A321_livery", root)
    col_lit = ensure_collection("A321_lights", root)
    col_gd = ensure_collection("A321_guides", root)
    guides = EdgeAccum()
    objs = {}
    objs["fuselage"] = build_fuselage(M, col_air, hi)
    objs["wing_L"], st = build_wing(M, col_air, -1, hi, guides)
    objs["wing_R"], _ = build_wing(M, col_air, 1, hi, guides)
    objs["stabiliser"] = build_hstab(M, col_air, hi)
    objs["fin"] = build_fin(M, col_air, hi, guides)
    objs["engine_1"] = build_engine(M, col_air, -1, hi)
    objs["engine_2"] = build_engine(M, col_air, 1, hi)
    objs.update(build_gear(M, col_air, hi))
    objs["windows"] = build_windows(M, col_air, guides)
    objs["cockpit_windows"] = build_cockpit(M, col_air, guides)
    objs["door_lines"] = build_doors(M, col_dec, guides)
    objs["titles"] = build_text_decal(M, col_dec, "NORTHSTAR", 8.55, 4.66, 0.46, "titles", M["paint_navy"], space=1.14)
    objs["registration"] = build_text_decal(M, col_dec, "EI-NSA", 34.6, 4.42, 0.30, "registration", M["paint_navy"], space=1.06)
    objs["fin_star"] = build_fin_star(M, col_dec)
    objs["lights"] = build_lights(M, col_lit, st)
    # line-art guides: loose edges only (never rendered)
    gme = guides.mesh("lineart_guides")
    g = new_object("lineart_guides", gme, [], col_gd)
    g.hide_render = True
    objs["guides"] = g
    # line art usage flags
    for ob in col_dec.objects:
        ob.lineart.usage = "EXCLUDE"
    for ob in col_lit.objects:
        if ob.type == "MESH":
            ob.lineart.usage = "EXCLUDE"
    objs["door_lines"].lineart.usage = "EXCLUDE"
    return objs


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    quality = "lo" if "--lo" in argv else "hi"
    out = os.path.join(SCRATCH, "a321.blend" if quality == "hi" else "a321_lo.blend")
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    # clean scene
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    import time
    t0 = time.time()
    build(quality)
    log("built in %.1fs" % (time.time() - t0))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
    log("saved", out)


if __name__ == "__main__":
    main()
