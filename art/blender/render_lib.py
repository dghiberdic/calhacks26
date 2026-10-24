"""
render_lib.py - beauty + clay passes for a given camera, writing a PNG master (scratchpad) and WebP (web).
"""
import bpy
import math
import os
import time

import common as C
import scene_apron as A


def _save_result(path, fmt, quality=85, alpha=False, depth="8"):
    sc = bpy.context.scene
    s = sc.render.image_settings
    s.file_format = fmt
    s.color_mode = "RGBA" if alpha else "RGB"
    if fmt == "PNG":
        s.color_depth = depth
        s.compression = 30
    else:
        s.quality = quality
    bpy.data.images["Render Result"].save_render(path, scene=sc)
    C.log("saved", path, "%.1f KB" % (os.path.getsize(path) / 1024))


def render_beauty(name, cam_fn, res, samples=384, pct=100, exposure=0.0, mist=0.0007, key_power=1.0, tag=""):
    sc = bpy.context.scene
    A.build_apron("side" if "side" in name else "hero", mist_density=mist, key_power=key_power)
    cam_fn(sc)
    C.setup_cycles(sc, samples=samples, res=res, pct=pct, threshold=C.arg_val("--threshold", 0.012, float))
    sc.view_settings.exposure = exposure
    sc.cycles.volume_step_rate = 4.0
    sc.cycles.volume_max_steps = 256
    t0 = time.time()
    bpy.ops.render.render()
    dt = time.time() - t0
    C.log("RENDER %s %dx%d @%d%% samples=%d: %.1fs" % (name, res[0], res[1], pct, samples, dt))
    os.makedirs(os.path.join(C.SCRATCH, "renders"), exist_ok=True)
    os.makedirs(C.OUT_WEB, exist_ok=True)
    png = os.path.join(C.SCRATCH, "renders", "%s%s.png" % (name, tag))
    _save_result(png, "PNG", depth="16")
    if not tag:
        _save_result(os.path.join(C.OUT_WEB, name + ".webp"), "WEBP", quality=85)
    else:
        _save_result(os.path.join(C.SCRATCH, "renders", "%s%s.jpg" % (name, tag)), "JPEG", quality=88)
    return dt


def clay_material():
    m = bpy.data.materials.get("clay_white") or bpy.data.materials.new("clay_white")
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (0.86, 0.86, 0.86, 1)
    b.inputs["Roughness"].default_value = 0.6
    b.inputs["Specular IOR Level"].default_value = 0.35
    return m


def render_clay(name, cam_fn, res, samples=128, pct=100, tag=""):
    sc = bpy.context.scene
    A.hide_apron(True)
    for cn in ("A321_lights",):
        c = bpy.data.collections.get(cn)
        if c:
            c.hide_render = True
    A.clear_compositor()
    vl = sc.view_layers[0]
    vl.material_override = clay_material()
    w = bpy.data.worlds.get("clay_world") or bpy.data.worlds.new("clay_world")
    bg = w.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.8, 0.82, 0.86, 1)
    bg.inputs["Strength"].default_value = 0.35
    sc.world = w
    if not bpy.data.objects.get("clay_key"):
        ld = bpy.data.lights.new("clay_key", "SUN")
        ld.energy = 4.2
        ld.angle = math.radians(10)
        ob = bpy.data.objects.new("clay_key", ld)
        ob.rotation_euler = (math.radians(30), 0, math.radians(-48))
        sc.collection.objects.link(ob)
        ld2 = bpy.data.lights.new("clay_fill", "SUN")
        ld2.energy = 0.8
        ld2.angle = math.radians(30)
        ob2 = bpy.data.objects.new("clay_fill", ld2)
        ob2.rotation_euler = (math.radians(70), 0, math.radians(160))
        sc.collection.objects.link(ob2)
    cam_fn(sc)
    C.setup_cycles(sc, samples=samples, res=res, pct=pct, threshold=0.02)
    sc.render.film_transparent = True
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0
    t0 = time.time()
    bpy.ops.render.render()
    dt = time.time() - t0
    C.log("RENDER %s-clay %dx%d samples=%d: %.1fs" % (name, res[0], res[1], samples, dt))
    png = os.path.join(C.SCRATCH, "renders", "%s%s.png" % (name.replace("render", "clay"), tag))
    _save_result(png, "PNG", alpha=True)
    if not tag:
        _save_result(os.path.join(C.OUT_WEB, name.replace("render", "clay") + ".webp"), "WEBP", quality=88, alpha=True)
    vl.material_override = None
    return dt
