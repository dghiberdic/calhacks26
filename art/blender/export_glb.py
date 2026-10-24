"""
export_glb.py - lightweight web model (glTF binary) with the Northstar livery as simple PBR materials.

  Blender -b --factory-startup --python art/blender/export_glb.py

Y-up, metres, origin = ground point under the radome tip (glTF: +X aft, +Y up, +Z = port).
Nodes: A321neo (root) > fuselage, wing_L, wing_R, engine_1 (port), engine_2, fin, stabiliser,
gear_nose, gear_main_L, gear_main_R.  engine_N has children engine_N_fan (pivot on the engine axis,
spin about local X) and engine_N_body.
"""
import bpy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_a321 as B  # noqa: E402
import common as C  # noqa: E402

for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob)
objs = B.build("lo")

# drop render-only helpers
for ob in list(bpy.data.objects):
    if ob.type in ("LIGHT",) or ob.name == "lineart_guides" or ob.name.startswith("txt_"):
        bpy.data.objects.remove(ob)

# flatten procedural shading to constants (glTF has no procedural nodes)
for m in bpy.data.materials:
    if not m.node_tree:
        continue
    nt = m.node_tree
    b = nt.nodes.get("Principled BSDF")
    if not b:
        continue
    for nm in ("Roughness", "Coat Roughness", "Base Color"):
        for l in list(b.inputs[nm].links):
            nt.links.remove(l)
    if m.name == "window_glass":
        b.inputs["Base Color"].default_value = (0.015, 0.017, 0.02, 1)
        b.inputs["Roughness"].default_value = 0.08
    if m.name.startswith("light_"):
        pass

sc = bpy.context.scene


def join(name, members):
    members = [o for o in members if o and o.type == "MESH"]
    if not members:
        return None
    bpy.ops.object.select_all(action="DESELECT")
    for o in members:
        o.select_set(True)
    bpy.context.view_layer.objects.active = members[0]
    if len(members) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = name
    ob.data.name = name
    return ob


def get(n):
    return bpy.data.objects.get(n)


def set_origin(ob, loc):
    from mathutils import Matrix, Vector
    d = Vector(loc) - ob.matrix_world.translation
    ob.data.transform(Matrix.Translation(-d))
    ob.location = ob.location + d


lights = objs["lights"]
# split emitter meshes per side for the wings
groups = {
    "fuselage": [get("fuselage"), get("windows"), get("cockpit_windows"), get("door_lines"), get("titles"),
                 get("registration"), lights["beacon"]],
    "fin": [get("fin"), get("fin_star")],
    "stabiliser": [get("stabiliser")],
    "wing_L": [get("wing_L"), lights["nav_red"]],
    "wing_R": [get("wing_R"), lights["nav_green"]],
    "gear_nose": [o for o in bpy.data.objects if o.name.startswith("gear_nose_")],
    "gear_main_L": [o for o in bpy.data.objects if o.name.startswith("gear_main_L_")],
    "gear_main_R": [o for o in bpy.data.objects if o.name.startswith("gear_main_R_")],
}
strobe = lights["strobe"]
groups["fuselage"].append(strobe)
root = bpy.data.objects.new("A321neo", None)
sc.collection.objects.link(root)
made = {}
for name, members in groups.items():
    ob = join(name, members)
    if ob:
        ob.parent = root
        made[name] = ob
for tag, side in (("1", -1), ("2", 1)):
    body = join("engine_%s_body" % tag, [get("engine_%s_nacelle" % tag), get("engine_%s_core" % tag), get("engine_%s_plug" % tag),
                                         get("engine_%s_fandisc" % tag), get("pylon_%s" % ("L" if side < 0 else "R"))])
    fan = join("engine_%s_fan" % tag, [get("engine_%s_spinner" % tag), get("engine_%s_fan" % tag)])
    piv = (B.ENG_X0 + 0.9, side * B.ENG_Y, B.ENG_Z)
    eng = bpy.data.objects.new("engine_%s" % tag, None)
    sc.collection.objects.link(eng)
    eng.location = piv
    eng.parent = root
    for o in (body, fan):
        set_origin(o, piv)
        o.parent = eng
        o.location = (0, 0, 0)

tris = 0
for o in bpy.data.objects:
    if o.type == "MESH":
        o.data.calc_loop_triangles()
        tris += len(o.data.loop_triangles)
C.log("GLB triangles:", tris)
os.makedirs(C.OUT_WEB, exist_ok=True)
out = os.path.join(C.OUT_WEB, "a321.glb")
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_yup=True, export_apply=True, export_materials="EXPORT",
                          export_texcoords=False, export_normals=True, export_cameras=False, export_lights=False,
                          export_extras=False, use_selection=False, export_draco_mesh_compression_enable=False)
C.log("wrote", out, "%.2f MB" % (os.path.getsize(out) / 1e6))
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(C.SCRATCH, "a321_web.blend"), compress=True)
