"""Convert the IDG A320neo exterior from AC3D/XML to glTF, without running model scripts.

Usage: python3 scripts/import-flightgear-aircraft.py /path/to/IDG-A32X
Source geometry, UVs, assembly offsets and textures are preserved. Flight simulation
systems, interiors and effects are excluded; the source's neutral gear pose is down.
"""

import array
import json
import math
from pathlib import Path
import shlex
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(sys.argv[1]).resolve()
OUT = Path(__file__).resolve().parents[1] / "public/story/idg-a320neo"
OUT.mkdir(parents=True, exist_ok=True)
doc = {"asset": {"version": "2.0", "generator": "StormCheck AC3D static exterior importer",
                 "copyright": "Immersive Design Group / FlightGear contributors; GPL-2.0"},
       "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [],
       "materials": [], "textures": [], "images": [],
       "samplers": [{"wrapS": 10497, "wrapT": 10497}],
       "bufferViews": [], "accessors": [], "buffers": []}
binary = bytearray()
sources = set()
materials = {}
textures = {}


def view(data, target=None):
    binary.extend(b"\0" * (-len(binary) % 4))
    result = {"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)}
    if target:
        result["target"] = target
    binary.extend(data)
    doc["bufferViews"].append(result)
    return len(doc["bufferViews"]) - 1


def accessor(values, size):
    result = {"bufferView": view(array.array("f", values).tobytes(), 34962),
              "componentType": 5126, "count": len(values) // size,
              "type": "VEC" + str(size)}
    if size == 3:
        result["min"] = [min(values[k::3]) for k in range(3)]
        result["max"] = [max(values[k::3]) for k in range(3)]
    doc["accessors"].append(result)
    return len(doc["accessors"]) - 1


def unit(v):
    length = math.sqrt(sum(x*x for x in v))
    return [x / length for x in v] if length > 1e-12 else [0, 1, 0]


def normal(a, b, c):
    u = [b[i]-a[i] for i in range(3)]
    v = [c[i]-a[i] for i in range(3)]
    return unit([u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]])


def node(name, **values):
    doc["nodes"].append({"name": name, **values})
    return len(doc["nodes"]) - 1


def material(m, texture, two_sided, mesh_name):
    key = (m["name"], tuple(m["rgb"]), str(texture), two_sided, mesh_name if mesh_name in ["Inside", "Fan", "Exhaust", "coneback"] else "")
    if key in materials:
        return materials[key]
    glass = "glass" in m["name"].lower()
    pbr = {"baseColorFactor": [*m["rgb"], 1], "metallicFactor": 0.05,
           "roughnessFactor": 0.36}
    if glass:
        # Exterior-only model: opaque smoked glazing prevents seeing an empty cabin.
        pbr.update(baseColorFactor=[0.025, 0.045, 0.065, 1], metallicFactor=0.35, roughnessFactor=0.15)
    if texture:
        if texture not in textures:
            sources.add(texture)
            doc["images"].append({"bufferView": view(texture.read_bytes()), "mimeType": "image/png"})
            doc["textures"].append({"source": len(doc["images"])-1, "sampler": 0})
            textures[texture] = len(doc["textures"])-1
        pbr["baseColorTexture"] = {"index": textures[texture]}
    if mesh_name in ["Inside", "Exhaust", "coneback"]:
        # Replace the simulator's baked reflection colour with web PBR metal.
        pbr.pop("baseColorTexture", None)
        pbr.update(baseColorFactor=[0.045, 0.055, 0.065, 1], metallicFactor=0.65, roughnessFactor=0.43)
    if mesh_name == "Fan":
        pbr.pop("baseColorTexture", None)
        pbr.update(baseColorFactor=[0.14, 0.16, 0.19, 1], metallicFactor=0.8, roughnessFactor=0.34)
    result = {"name": m["name"], "pbrMetallicRoughness": pbr, "doubleSided": two_sided}
    if m["trans"] >= 0.999 and not glass:
        result.update(alphaMode="BLEND")
        pbr["baseColorFactor"][3] = 0
    materials[key] = len(doc["materials"])
    doc["materials"].append(result)
    return materials[key]


def ac(path):
    print("Reading", path.relative_to(ROOT))
    sources.add(path)
    lines = path.read_text(errors="replace").splitlines()
    mats = []
    cursor = 1
    while cursor < len(lines) and not lines[cursor].startswith("OBJECT"):
        if lines[cursor].startswith("MATERIAL"):
            tok = shlex.split(lines[cursor])
            mats.append({"name": tok[1], "rgb": list(map(float, tok[tok.index("rgb")+1:tok.index("rgb")+4])),
                         "trans": float(tok[tok.index("trans")+1])})
        cursor += 1

    def obj():
        nonlocal cursor
        assert lines[cursor].startswith("OBJECT"), (path, cursor, lines[cursor])
        cursor += 1
        name = path.stem
        verts, faces = [], []
        texture = None
        translation = [0, 0, 0]
        rotation = None
        crease = 45
        repeat, offset = [1, 1], [0, 0]
        while cursor < len(lines):
            tok = shlex.split(lines[cursor]); cursor += 1
            if not tok:
                continue
            key = tok[0]
            if key == "name":
                name = tok[1]
            elif key == "data":
                # These sources use a single line of mesh metadata.
                cursor += 1
            elif key == "texture":
                texture = (path.parent / tok[1]).resolve()
                if not texture.is_file():
                    raise ValueError(f"Missing texture: {texture}")
            elif key == "loc":
                translation = list(map(float, tok[1:4]))
            elif key == "rot":
                rotation = list(map(float, tok[1:10]))
            elif key == "crease":
                crease = float(tok[1])
            elif key == "texrep":
                repeat = list(map(float, tok[1:3]))
            elif key == "texoff":
                offset = list(map(float, tok[1:3]))
            elif key == "numvert":
                for _ in range(int(tok[1])):
                    verts.append(list(map(float, lines[cursor].split()))); cursor += 1
            elif key == "numsurf":
                for _ in range(int(tok[1])):
                    while not lines[cursor].strip(): cursor += 1
                    flags = int(lines[cursor].split()[1], 0); cursor += 1
                    mat = 0
                    if lines[cursor].startswith("mat"):
                        mat = int(lines[cursor].split()[1]); cursor += 1
                    n = int(lines[cursor].split()[1]); cursor += 1
                    refs = []
                    for _ in range(n):
                        values = lines[cursor].split(); cursor += 1
                        refs.append((int(values[0]), float(values[1]), float(values[2])))
                    if flags & 0xf == 0 and len(refs) >= 3:
                        faces.append((mat, flags, refs))
            elif key == "kids":
                index = node(name, children=[], translation=translation)
                if rotation:
                    # AC3D stores a row-major 3x3; glTF matrices are column-major.
                    doc["nodes"][index].pop("translation")
                    doc["nodes"][index]["matrix"] = [rotation[0],rotation[3],rotation[6],0,
                        rotation[1],rotation[4],rotation[7],0,rotation[2],rotation[5],rotation[8],0,*translation,1]
                if faces:
                    adjacent = [[] for _ in verts]
                    normals = []
                    for _, _, refs in faces:
                        norm = normal(*(verts[r[0]] for r in refs[:3]))
                        normals.append(norm)
                        for r in refs: adjacent[r[0]].append(norm)
                    batches = {}
                    cos_crease = math.cos(math.radians(crease))
                    for i, (mat, flags, refs) in enumerate(faces):
                        surface_part = name
                        if name == "NacellePW1100G":
                            center = [sum(verts[r[0]][k] for r in refs) / len(refs) for k in range(3)]
                            if normals[i][1]*center[1] + normals[i][2]*center[2] < -0.05:
                                surface_part = "Inside"
                        batch = batches.setdefault((mat, bool(flags & 0x20), surface_part), ([], [], []))
                        for j in range(1, len(refs)-1):
                            for ref in [refs[0], refs[j], refs[j+1]]:
                                vertex, u, v = ref
                                n = normals[i]
                                if flags & 0x10:
                                    neighbors = [a for a in adjacent[vertex] if sum(a[k]*n[k] for k in range(3)) >= cos_crease-1e-6]
                                    n = unit([sum(a[k] for a in neighbors) for k in range(3)])
                                batch[0].extend(verts[vertex]); batch[1].extend(n)
                                batch[2].extend([u*repeat[0]+offset[0], 1-(v*repeat[1]+offset[1])])
                    primitives = []
                    for (mat, two_sided, surface_part), (p, n, uv) in batches.items():
                        primitives.append({"attributes": {"POSITION": accessor(p, 3), "NORMAL": accessor(n, 3),
                                                         "TEXCOORD_0": accessor(uv, 2)},
                                           "material": material(mats[mat], texture, two_sided, surface_part)})
                    doc["nodes"][index]["mesh"] = len(doc["meshes"])
                    doc["meshes"].append({"name": name, "primitives": primitives})
                for _ in range(int(tok[1])):
                    while cursor < len(lines) and not lines[cursor].strip(): cursor += 1
                    if cursor == len(lines):
                        # The published PW engine declares nine children but contains eight.
                        break
                    doc["nodes"][index]["children"].append(obj())
                return index
        raise ValueError(f"Unterminated object: {path}")

    children = []
    while cursor < len(lines):
        if lines[cursor].startswith("OBJECT"):
            children.append(obj())
        else:
            cursor += 1
    return node(path.stem, children=children)


def resolve(path, parent):
    return ROOT / path.removeprefix("Aircraft/IDG-A32X/") if path.startswith("Aircraft/") else parent / path


def offsets(element):
    if element is None:
        return {}
    get = lambda key: float(element.findtext(key, "0"))
    # FlightGear x aft/y starboard/z up -> glTF x aft/y up/z port.
    result = {"translation": [get("x-m"), get("z-m"), -get("y-m")]}
    # Sources use heading/pitch with no roll. Compose heading (Y) then pitch (Z).
    h, p, r = [math.radians(get(k))/2 for k in ["heading-deg", "pitch-deg", "roll-deg"]]
    assert r == 0, "Unexpected roll in source assembly"
    result["rotation"] = [math.sin(h)*math.sin(p), math.sin(h)*math.cos(p),
                           math.cos(h)*math.sin(p), math.cos(h)*math.cos(p)]
    return result


def model(path):
    if path.suffix == ".ac":
        return ac(path)
    sources.add(path)
    xml = ET.parse(path).getroot()
    index = node(path.stem, children=[], **offsets(xml.find("offsets")))
    content = xml.findtext("path")
    if content and content != "empty.ac":
        doc["nodes"][index]["children"].append(ac(resolve(content, path.parent)))
    for child in xml.findall("model"):
        childpath = child.findtext("path", "")
        if not any(prefix in childpath for prefix in ["/Fuselages/", "/Wings/", "/Engines/NEO/", "/LandingGears/"]):
            continue
        wrapper = node(child.findtext("name", Path(childpath).stem),
                       children=[model(resolve(childpath, path.parent))], **offsets(child.find("offsets")))
        doc["nodes"][index]["children"].append(wrapper)
    return index


root = model(ROOT / "Models/A320neo-PW.xml")
# Static exterior at rest. Keep all source parts at their published relative offsets.
doc["scenes"][0]["nodes"] = [root]
doc["nodes"][root]["translation"] = [-2.52583, 4.5384424, 0]
binary.extend(b"\0" * (-len(binary) % 4))
doc["buffers"] = [{"byteLength": len(binary)}]
payload = json.dumps(doc, separators=(",", ":")).encode()
payload += b" " * (-len(payload) % 4)
glb = struct.pack("<III", 0x46546C67, 2, 28+len(payload)+len(binary))
glb += struct.pack("<II", len(payload), 0x4E4F534A)+payload
glb += struct.pack("<II", len(binary), 0x004E4942)+binary
(OUT / "aircraft.glb").write_bytes(glb)
sources.update(p for p in [ROOT / "LICENSE", ROOT / "README.md", ROOT / "THANKS.md"] if p.exists())
with zipfile.ZipFile(OUT / "source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(sources):
        archive.write(path, path.relative_to(ROOT))
    archive.write(__file__, "scripts/import-flightgear-aircraft.py")
if (ROOT / "LICENSE").exists():
    (OUT / "COPYING.txt").write_bytes((ROOT / "LICENSE").read_bytes())
print(f"Wrote {OUT / 'aircraft.glb'}: {len(glb):,} bytes, {len(doc['meshes'])} meshes, {len(sources)} source files")
