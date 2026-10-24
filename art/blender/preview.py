"""
preview.py - quick geometry check renders (studio light, low samples).
  Blender -b <scratch>/a321.blend --python art/blender/preview.py -- --views side,top,front,hero,nose --samples 24 --pct 50
"""
import bpy
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

views = C.arg_val("--views", "side,top,front,hero,nose").split(",")
samples = C.arg_val("--samples", 24, int)
pct = C.arg_val("--pct", 50, int)
outdir = os.path.join(C.SCRATCH, "preview")
os.makedirs(outdir, exist_ok=True)

C.ensure_aircraft()
sc = bpy.context.scene

w = bpy.data.worlds.get("preview_world") or bpy.data.worlds.new("preview_world")
sc.world = w
bg = w.node_tree.nodes.get("Background")
bg.inputs["Color"].default_value = (0.55, 0.6, 0.68, 1)
bg.inputs["Strength"].default_value = 0.9
if not bpy.data.objects.get("pv_sun"):
    ld = bpy.data.lights.new("pv_sun", "SUN")
    ld.energy = 3.5
    ld.angle = math.radians(8)
    so = bpy.data.objects.new("pv_sun", ld)
    so.rotation_euler = (math.radians(50), math.radians(-10), math.radians(-60))
    sc.collection.objects.link(so)
if not bpy.data.objects.get("pv_ground"):
    me = bpy.data.meshes.new("pv_ground")
    me.from_pydata([(-300, -300, 0), (300, -300, 0), (300, 300, 0), (-300, 300, 0)], [], [(0, 1, 2, 3)])
    g = bpy.data.objects.new("pv_ground", me)
    m = bpy.data.materials.new("pv_ground")
    m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.3, 0.3, 0.3, 1)
    me.materials.append(m)
    sc.collection.objects.link(g)

for v in views:
    ground = bpy.data.objects["pv_ground"]
    ground.hide_render = v in ("top",)
    if v == "side":
        C.setup_cycles(sc, samples, (2000, 640), pct=100)
        C.ortho_camera(sc, "side")
    elif v == "top":
        C.setup_cycles(sc, samples, (2000, 1600), pct=100)
        C.ortho_camera(sc, "top")
    elif v == "front":
        C.setup_cycles(sc, samples, (1600, 640), pct=100)
        C.ortho_camera(sc, "front")
    elif v == "hero":
        C.setup_cycles(sc, samples, C.HERO_RES, pct=pct)
        C.hero_camera(sc)
    elif v == "sidecam":
        C.setup_cycles(sc, samples, C.SIDE_RES, pct=pct)
        C.side_camera(sc)
    elif v == "nose":
        C.setup_cycles(sc, samples, (1600, 1000), pct=pct)
        C._cam(sc, "cam_nose", (-7.0, -7.5, 5.2), (82, 0, -42), lens=50)
    elif v == "cockpit":
        C.setup_cycles(sc, samples, (1600, 1000), pct=pct)
        C._cam(sc, "cam_cockpit", (-6.0, -6.5, 5.6), (80, 0, -42), lens=55)
    elif v == "cockpitf":
        C.setup_cycles(sc, samples, (1600, 1000), pct=pct)
        C._cam(sc, "cam_cockpitf", (-9.0, -0.0, 5.2), (86, 0, -90), lens=60)
    elif v == "tail":
        C.setup_cycles(sc, samples, (1600, 1000), pct=pct)
        C._cam(sc, "cam_tail", (54.0, -14.0, 8.5), (78, 0, 55), lens=45)
    elif v == "engine":
        C.setup_cycles(sc, samples, (1600, 1000), pct=pct)
        C._cam(sc, "cam_engine", (9.0, -12.5, 1.6), (88, 0, -38), lens=45)
    elif v == "gear":
        C.setup_cycles(sc, samples, (1600, 1000), pct=pct)
        C._cam(sc, "cam_gear", (16.0, -10.0, 1.0), (88, 0, -50), lens=35)
    elif v == "under":
        C.setup_cycles(sc, samples, (1600, 1000), pct=pct)
        C._cam(sc, "cam_under", (8.0, -26.0, 14.0), (62, 0, -20), lens=28)
    elif v == "wingtip":
        C.setup_cycles(sc, samples, (1600, 1000), pct=pct)
        C._cam(sc, "cam_wt", (22.0, -24.0, 5.0), (86, 0, -25), lens=60)
    sc.view_settings.look = "None"
    sc.render.filepath = os.path.join(outdir, "pv_%s.png" % v)
    bpy.ops.render.render(write_still=True)
    C.log("wrote", sc.render.filepath)
