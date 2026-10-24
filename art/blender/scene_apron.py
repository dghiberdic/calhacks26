"""
scene_apron.py - night storm apron: wet asphalt with puddles, yellow lead-in line, storm sky,
apron floodlights (4000 K), cool rim light, logo lights, light mist, distant airport lights, bloom.
"""
import bpy
import math
import random

import numpy as np


def _lin(c):
    c = np.asarray(c, float)
    return tuple(np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4))


def _coll(name):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if c.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(c)
    return c


def _obj(name, me, coll, mat=None):
    if mat:
        me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def _new_mat(name):
    m = bpy.data.materials.new(name)
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    return m, nt, out


# ----------------------------------------------------------------------------- materials
def asphalt_material():
    m, nt, out = _new_mat("wet_asphalt")
    L = nt.links.new
    tc = nt.nodes.new("ShaderNodeTexCoord")
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    L(b.outputs[0], out.inputs["Surface"])
    # puddles: anisotropic blobs (long along x so they read as reflective bands from the side)
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (0.045, 0.11, 0.05)
    L(tc.outputs["Object"], mp.inputs["Vector"])
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 1.0
    nz.inputs["Detail"].default_value = 5.0
    nz.inputs["Roughness"].default_value = 0.6
    L(mp.outputs["Vector"], nz.inputs["Vector"])
    pr = nt.nodes.new("ShaderNodeValToRGB")
    pr.color_ramp.elements[0].position = 0.47
    pr.color_ramp.elements[0].color = (0, 0, 0, 1)
    pr.color_ramp.elements[1].position = 0.56
    pr.color_ramp.elements[1].color = (1, 1, 1, 1)
    L(nz.outputs["Fac"], pr.inputs["Fac"])
    mp2 = nt.nodes.new("ShaderNodeMapping")
    mp2.inputs["Scale"].default_value = (0.32, 0.45, 0.3)
    L(tc.outputs["Object"], mp2.inputs["Vector"])
    nzs = nt.nodes.new("ShaderNodeTexNoise")
    nzs.inputs["Scale"].default_value = 1.0
    nzs.inputs["Detail"].default_value = 6.0
    nzs.inputs["Roughness"].default_value = 0.65
    L(mp2.outputs["Vector"], nzs.inputs["Vector"])
    pr2 = nt.nodes.new("ShaderNodeValToRGB")
    pr2.color_ramp.elements[0].position = 0.52
    pr2.color_ramp.elements[0].color = (0, 0, 0, 1)
    pr2.color_ramp.elements[1].position = 0.60
    pr2.color_ramp.elements[1].color = (0.85, 0.85, 0.85, 1)
    L(nzs.outputs["Fac"], pr2.inputs["Fac"])
    pmax = nt.nodes.new("ShaderNodeMix")
    pmax.data_type = "RGBA"
    pmax.blend_type = "LIGHTEN"
    pmax.inputs["Factor"].default_value = 1.0
    L(pr.outputs["Color"], pmax.inputs["A"])
    L(pr2.outputs["Color"], pmax.inputs["B"])
    puddle = pmax.outputs["Result"]
    # asphalt tone variation
    nz2 = nt.nodes.new("ShaderNodeTexNoise")
    nz2.inputs["Scale"].default_value = 0.35
    nz2.inputs["Detail"].default_value = 8.0
    L(tc.outputs["Object"], nz2.inputs["Vector"])
    tone = nt.nodes.new("ShaderNodeValToRGB")
    tone.color_ramp.elements[0].color = (*_lin((0.055, 0.056, 0.058)), 1)
    tone.color_ramp.elements[1].color = (*_lin((0.115, 0.115, 0.118)), 1)
    L(nz2.outputs["Fac"], tone.inputs["Fac"])
    dark = nt.nodes.new("ShaderNodeMix")
    dark.data_type = "RGBA"
    dark.inputs["B"].default_value = (*_lin((0.035, 0.036, 0.04)), 1)
    L(puddle, dark.inputs["Factor"])
    L(tone.outputs["Color"], dark.inputs["A"])
    L(dark.outputs["Result"], b.inputs["Base Color"])
    # roughness: damp asphalt -> mirror-like puddles
    rr = nt.nodes.new("ShaderNodeMapRange")
    rr.inputs["To Min"].default_value = 0.20
    rr.inputs["To Max"].default_value = 0.02
    L(puddle, rr.inputs["Value"])
    nz3 = nt.nodes.new("ShaderNodeTexNoise")
    nz3.inputs["Scale"].default_value = 3.0
    L(tc.outputs["Object"], nz3.inputs["Vector"])
    rv = nt.nodes.new("ShaderNodeMath")
    rv.operation = "MULTIPLY_ADD"
    L(nz3.outputs["Fac"], rv.inputs[0])
    rv.inputs[1].default_value = 0.10
    L(rr.outputs["Result"], rv.inputs[2])
    L(rv.outputs[0], b.inputs["Roughness"])
    # grain bump, flattened in puddles
    gr = nt.nodes.new("ShaderNodeTexNoise")
    gr.inputs["Scale"].default_value = 60.0
    gr.inputs["Detail"].default_value = 3.0
    L(tc.outputs["Object"], gr.inputs["Vector"])
    bs = nt.nodes.new("ShaderNodeMapRange")
    bs.inputs["To Min"].default_value = 0.22
    bs.inputs["To Max"].default_value = 0.0
    L(puddle, bs.inputs["Value"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Distance"].default_value = 0.002
    L(bs.outputs["Result"], bump.inputs["Strength"])
    L(gr.outputs["Fac"], bump.inputs["Height"])
    L(bump.outputs["Normal"], b.inputs["Normal"])
    b.inputs["Specular IOR Level"].default_value = 0.5
    return m


def paint_line_material():
    m, nt, out = _new_mat("taxi_line_yellow")
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(b.outputs[0], out.inputs["Surface"])
    b.inputs["Base Color"].default_value = (*_lin((0.86, 0.62, 0.06)), 1)
    b.inputs["Roughness"].default_value = 0.22
    # glass-bead paint picks up stray apron light: a faint retroreflective glow keeps it readable at night
    b.inputs["Emission Color"].default_value = (*_lin((1.0, 0.68, 0.08)), 1)
    b.inputs["Emission Strength"].default_value = 0.22
    tc = nt.nodes.new("ShaderNodeTexCoord")
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 4.0
    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["To Min"].default_value = 0.08
    mr.inputs["To Max"].default_value = 0.35
    nt.links.new(nz.outputs["Fac"], mr.inputs["Value"])
    nt.links.new(mr.outputs["Result"], b.inputs["Roughness"])
    return m


def backdrop_material():
    """Emissive storm-sky card for the telephoto side view (object coords x,z in metres)."""
    m, nt, out = _new_mat("storm_backdrop")
    L = nt.links.new
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    L(tc.outputs["Object"], sep.inputs[0])
    # height gradient
    hz = nt.nodes.new("ShaderNodeMapRange")
    hz.inputs["From Min"].default_value = 0.0
    hz.inputs["From Max"].default_value = 60.0
    L(sep.outputs["Z"], hz.inputs["Value"])
    grad = nt.nodes.new("ShaderNodeValToRGB")
    cr = grad.color_ramp
    cr.elements[0].position = 0.0
    cr.elements[0].color = (*_lin((0.30, 0.28, 0.27)), 1)  # sodium/LED city glow at the horizon
    cr.elements.new(0.10).color = (*_lin((0.17, 0.18, 0.20)), 1)
    cr.elements.new(0.35).color = (*_lin((0.09, 0.105, 0.135)), 1)
    cr.elements[-1].position = 1.0
    cr.elements[-1].color = (*_lin((0.05, 0.062, 0.085)), 1)
    L(hz.outputs["Result"], grad.inputs["Fac"])
    # clouds
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (0.022, 0.05, 0.05)
    L(tc.outputs["Object"], mp.inputs["Vector"])
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.noise_dimensions = "3D"
    nz.inputs["Scale"].default_value = 1.0
    nz.inputs["Detail"].default_value = 10.0
    nz.inputs["Roughness"].default_value = 0.62
    nz.inputs["Distortion"].default_value = 0.4
    L(mp.outputs["Vector"], nz.inputs["Vector"])
    cl = nt.nodes.new("ShaderNodeMapRange")
    cl.inputs["From Min"].default_value = 0.38
    cl.inputs["From Max"].default_value = 0.70
    cl.inputs["To Min"].default_value = 0.35
    cl.inputs["To Max"].default_value = 1.7
    L(nz.outputs["Fac"], cl.inputs["Value"])
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs["Factor"].default_value = 1.0
    L(grad.outputs["Color"], mul.inputs["A"])
    cc = nt.nodes.new("ShaderNodeCombineColor")
    L(cl.outputs["Result"], cc.inputs[0])
    L(cl.outputs["Result"], cc.inputs[1])
    L(cl.outputs["Result"], cc.inputs[2])
    L(cc.outputs[0], mul.inputs["B"])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 2.6
    L(mul.outputs["Result"], em.inputs["Color"])
    L(em.outputs[0], out.inputs["Surface"])
    return m, em


def world_storm(strength=1.0):
    w = bpy.data.worlds.get("storm_world") or bpy.data.worlds.new("storm_world")
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    L = nt.links.new
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    L(bg.outputs[0], out.inputs["Surface"])
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    L(tc.outputs["Generated"], sep.inputs[0])
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = -0.02
    mr.inputs["From Max"].default_value = 0.6
    L(sep.outputs["Z"], mr.inputs["Value"])
    grad = nt.nodes.new("ShaderNodeValToRGB")
    cr = grad.color_ramp
    cr.elements[0].color = (*_lin((0.27, 0.255, 0.25)), 1)
    cr.elements.new(0.07).color = (*_lin((0.16, 0.17, 0.19)), 1)
    cr.elements.new(0.30).color = (*_lin((0.075, 0.09, 0.115)), 1)
    cr.elements[-1].color = (*_lin((0.03, 0.038, 0.055)), 1)
    L(mr.outputs["Result"], grad.inputs["Fac"])
    # clouds on the view direction
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1.2, 1.2, 3.0)
    L(tc.outputs["Generated"], mp.inputs["Vector"])
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 2.2
    nz.inputs["Detail"].default_value = 10.0
    nz.inputs["Roughness"].default_value = 0.6
    nz.inputs["Distortion"].default_value = 0.5
    L(mp.outputs["Vector"], nz.inputs["Vector"])
    cl = nt.nodes.new("ShaderNodeMapRange")
    cl.inputs["From Min"].default_value = 0.38
    cl.inputs["From Max"].default_value = 0.70
    cl.inputs["To Min"].default_value = 0.35
    cl.inputs["To Max"].default_value = 1.7
    L(nz.outputs["Fac"], cl.inputs["Value"])
    cc = nt.nodes.new("ShaderNodeCombineColor")
    for i in range(3):
        L(cl.outputs["Result"], cc.inputs[i])
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs["Factor"].default_value = 1.0
    L(grad.outputs["Color"], mul.inputs["A"])
    L(cc.outputs[0], mul.inputs["B"])
    L(mul.outputs["Result"], bg.inputs["Color"])
    lp = nt.nodes.new("ShaderNodeLightPath")
    mx = nt.nodes.new("ShaderNodeMath")
    mx.operation = "MAXIMUM"
    L(lp.outputs["Is Camera Ray"], mx.inputs[0])
    L(lp.outputs["Is Glossy Ray"], mx.inputs[1])
    st = nt.nodes.new("ShaderNodeMapRange")
    st.inputs["To Min"].default_value = strength
    st.inputs["To Max"].default_value = strength * 3.2
    L(mx.outputs[0], st.inputs["Value"])
    L(st.outputs["Result"], bg.inputs["Strength"])
    bpy.context.scene.world = w
    return w, bg


def mist_material(density):
    m, nt, out = _new_mat("apron_mist")
    v = nt.nodes.new("ShaderNodeVolumePrincipled")
    v.inputs["Color"].default_value = (*_lin((0.78, 0.82, 0.88)), 1)
    v.inputs["Density"].default_value = density
    v.inputs["Anisotropy"].default_value = 0.45
    nt.links.new(v.outputs[0], out.inputs["Volume"])
    return m, v


def emit_material(name, color, strength):
    m, nt, out = _new_mat(name)
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (*color, 1)
    e.inputs["Strength"].default_value = strength
    nt.links.new(e.outputs[0], out.inputs["Surface"])
    return m


# ----------------------------------------------------------------------------- geometry
def plane(name, x0, x1, y0, y1, z, coll, mat):
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)], [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new()
    return _obj(name, me, coll, mat)


def strip_along(points, width, z, name, coll, mat):
    """Flat ribbon on the ground following a 2D polyline."""
    P = np.asarray(points, float)
    d = np.gradient(P, axis=0)
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    n = np.column_stack([-d[:, 1], d[:, 0]])
    L = P + n * width / 2
    R = P - n * width / 2
    V = [(x, y, z) for x, y in L] + [(x, y, z) for x, y in R]
    m = len(P)
    F = [(i, i + 1, m + i + 1, m + i) for i in range(m - 1)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(V, [], F)
    return _obj(name, me, coll, mat)


def lead_in_path():
    """Stand centreline along the aircraft axis + a curve sweeping in from the camera side."""
    # spline through control points (x, y)
    cps = np.array([(14.0, -560.0), (14.6, -320.0), (14.0, -160.0), (11.8, -70.0), (8.0, -26.0), (3.0, -7.0),
                    (-4.0, -1.2), (-12.0, 0.0), (-30.0, 0.0)])
    t = np.linspace(0, 1, len(cps))
    tt = np.linspace(0, 1, 600)
    # monotone-ish smooth interpolation via Catmull-Rom
    P = np.vstack([2 * cps[0] - cps[1], cps, 2 * cps[-1] - cps[-2]])
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        s = np.linspace(0, 1, 60, endpoint=False)[:, None]
        out.append(0.5 * ((2 * p1) + (-p0 + p2) * s + (2 * p0 - 5 * p1 + 4 * p2 - p3) * s ** 2 + (-p0 + 3 * p1 - 3 * p2 + p3) * s ** 3))
    curve = np.vstack(out)
    centre = np.column_stack([np.linspace(-120, 60, 200), np.zeros(200)])
    return curve, centre


# ----------------------------------------------------------------------------- lights
def area_light(name, loc, target, power, size=(6, 3), spread=60, kelvin=4000, coll=None, color=None):
    ld = bpy.data.lights.new(name, "AREA")
    ld.shape = "RECTANGLE"
    ld.size, ld.size_y = size
    ld.energy = power
    ld.spread = math.radians(spread)
    if color is not None:
        ld.color = color
    else:
        ld.use_temperature = True
        ld.temperature = kelvin
    ob = bpy.data.objects.new(name, ld)
    ob.location = loc
    d = np.array(target, float) - np.array(loc, float)
    ob.rotation_euler = _look_rot(d)
    ob.visible_camera = False
    (coll or bpy.context.scene.collection).objects.link(ob)
    return ob


def spot_light(name, loc, target, power, angle=40, blend=0.4, kelvin=3500, radius=0.1, coll=None):
    ld = bpy.data.lights.new(name, "SPOT")
    ld.energy = power
    ld.spot_size = math.radians(angle)
    ld.spot_blend = blend
    ld.shadow_soft_size = radius
    ld.use_temperature = True
    ld.temperature = kelvin
    ob = bpy.data.objects.new(name, ld)
    ob.location = loc
    ob.rotation_euler = _look_rot(np.array(target, float) - np.array(loc, float))
    (coll or bpy.context.scene.collection).objects.link(ob)
    return ob


def _look_rot(d):
    from mathutils import Vector
    return Vector(d).to_track_quat("-Z", "Y").to_euler()


# ----------------------------------------------------------------------------- build
def build_apron(variant="side", mist_density=0.0007, key_power=1.0):
    sc = bpy.context.scene
    coll = _coll("Apron")
    world, bg = world_storm(0.9)
    asphalt = asphalt_material()
    plane("apron_ground", -3000, 3000, -3000, 1300, 0.0, coll, asphalt)
    yel = paint_line_material()
    curve, centre = lead_in_path()
    strip_along(curve, 0.30, 0.004, "lead_in_curve", coll, yel)
    strip_along(centre, 0.30, 0.004, "stand_centreline", coll, yel)
    # stop bar ahead of the nose gear + short stand markings
    strip_along([(4.2, -1.6), (4.2, 1.6)], 0.45, 0.005, "stop_bar", coll, yel)
    # telephoto backdrop (behind the aircraft) for the side camera
    bm, bem = backdrop_material()
    me = bpy.data.meshes.new("storm_backdrop")
    me.from_pydata([(-260, 0, -8), (300, 0, -8), (300, 0, 140), (-260, 0, 140)], [], [(0, 1, 2, 3)])
    bd = _obj("storm_backdrop", me, coll, bm)
    bd.location = (0, 1300, 0)
    bd.visible_shadow = False
    bd.visible_diffuse = False
    # distant airport lights in the haze (between aircraft and backdrop)
    rnd = random.Random(7)
    cols = [((1.0, 0.62, 0.30), 60), ((1.0, 0.78, 0.55), 50), ((0.75, 0.85, 1.0), 45), ((1.0, 0.9, 0.8), 40),
            ((0.35, 0.55, 1.0), 70), ((1.0, 0.25, 0.1), 50)]
    dl = []
    acc_v, acc_f, mats = [], [], []
    lights = bpy.data.collections.get("Apron_distant") or bpy.data.collections.new("Apron_distant")
    if lights.name not in coll.children:
        coll.children.link(lights)
    mcache = {}
    for i in range(70):
        x = rnd.uniform(-70, 110)
        y = rnd.uniform(380, 1250)
        kind = rnd.random()
        if kind < 0.45:  # ground-level taxiway/runway edge lights
            z = 0.4
            r = 0.10
            col, st = (0.35, 0.55, 1.0) if rnd.random() < 0.6 else (1.0, 0.75, 0.35), 90
        elif kind < 0.85:  # mast / building lights
            z = rnd.uniform(1.5, 7.5)
            r = rnd.uniform(0.14, 0.26)
            col, st = cols[rnd.randrange(len(cols))]
        else:  # terminal windows band
            z = rnd.uniform(2.0, 5.0)
            r = 0.2
            col, st = (1.0, 0.82, 0.6), 25
        key = (col, st)
        if key not in mcache:
            mcache[key] = emit_material("dist_%d" % len(mcache), col, st)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=10, ring_count=6, radius=r, location=(x, y, z))
        ob = bpy.context.active_object
        ob.name = "distant_light_%02d" % i
        ob.data.materials.append(mcache[key])
        for c in ob.users_collection:
            c.objects.unlink(ob)
        lights.objects.link(ob)
        ob.visible_shadow = False
    # floodlights (warm 4000 K) + cool rim + logo lights
    L = _coll("Apron_lights")
    k = key_power
    area_light("flood_key", (-22, -62, 27), (14, 0, 3.5), 17000 * k, size=(5, 2.5), spread=70, kelvin=4000, coll=L)
    area_light("flood_rear", (64, -55, 26), (32, 0, 5), 8000 * k, size=(5, 2.5), spread=70, kelvin=4000, coll=L)
    fill = area_light("flood_fill_far", (8, 70, 25), (16, 0, 2.0), 4000 * k, size=(5, 2.5), spread=80, kelvin=4000, coll=L)
    rim = area_light("rim_cool", (30, 75, 32), (24, 0, 7.0), 26000 * k, size=(8, 3), spread=45, kelvin=9000, coll=L)
    rim.visible_volume_scatter = False
    # back lights only touch the aircraft (no glare off the wet apron)
    air = bpy.data.collections.get("A321")
    for lt in (fill, rim):
        try:
            lt.light_linking.receiver_collection = air
        except Exception as e:
            print("light linking unavailable:", e)
    for s in (-1, 1):
        lg = spot_light("logo_%s" % ("L" if s < 0 else "R"), (42.4, s * 4.6, 5.95), (40.4, s * 0.25, 9.6), 260 * k, angle=55,
                        blend=0.6, kelvin=3600, radius=0.05, coll=L)
        lg.visible_volume_scatter = False  # no noisy in-scatter right in front of the fin
    # mist volume (around the aircraft only, so the side camera is outside it)
    if mist_density > 0:
        mm, mv = mist_material(mist_density)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(25, 72, 11))
        box = bpy.context.active_object
        box.name = "apron_mist"
        box.scale = (240, 196, 22)
        box.data.materials.append(mm)
        for c in box.users_collection:
            c.objects.unlink(box)
        coll.objects.link(box)
    # decorative emitters are not light-sampled
    names = ["storm_backdrop", "taxi_line_yellow", "light_red", "light_green", "light_white", "light_beacon"]
    names += [m.name for m in bpy.data.materials if m.name.startswith("dist_")]
    n = sum(no_light_sampling(bpy.data.materials[nm]) for nm in names if nm in bpy.data.materials)
    print("[render] emission sampling off for %d materials" % n)
    # bloom
    setup_compositor()
    return coll


def no_light_sampling(mat):
    """Decorative emitters: visible / reflected, but not sampled as lights (less noise, faster)."""
    for owner in (getattr(mat, "cycles", None), mat):
        if owner is not None and hasattr(owner, "emission_sampling"):
            owner.emission_sampling = "NONE"
            return True
    return False


def setup_compositor(threshold=1.0, size=7, mix_strength=0.6):
    sc = bpy.context.scene
    ng = bpy.data.node_groups.get("apron_comp") or bpy.data.node_groups.new("apron_comp", "CompositorNodeTree")
    for n in list(ng.nodes):
        ng.nodes.remove(n)
    if not any(s.name == "Image" for s in ng.interface.items_tree):
        ng.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rl = ng.nodes.new("CompositorNodeRLayers")
    gl = ng.nodes.new("CompositorNodeGlare")
    out = ng.nodes.new("NodeGroupOutput")
    try:
        gl.inputs["Type"].default_value = "Bloom"
    except Exception:
        try:
            gl.inputs["Type"].default_value = "Fog Glow"
        except Exception as e:
            print("glare type:", e)
    for nm, v in (("Threshold", threshold), ("Strength", mix_strength), ("Size", 0.6)):
        try:
            gl.inputs[nm].default_value = v
        except Exception:
            pass
    ng.links.new(rl.outputs["Image"], gl.inputs["Image"])
    ng.links.new(gl.outputs[0], out.inputs[0])
    sc.compositing_node_group = ng
    sc.render.use_compositing = True
    return ng


def clear_compositor():
    sc = bpy.context.scene
    sc.compositing_node_group = None
    sc.render.use_compositing = False


def hide_apron(hide=True):
    for name in ("Apron", "Apron_lights", "Apron_distant"):
        c = bpy.data.collections.get(name)
        if c:
            c.hide_render = hide
