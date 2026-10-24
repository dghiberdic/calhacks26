"""
common.py - shared render setup, camera definitions and environment for the A321neo renders.

Every deliverable pair (render / clay / line art) builds its camera from the functions here, so
the pixel grids match exactly.
"""
import bpy
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SCRATCH = os.environ.get(
    "A321_SCRATCH",
    "/private/tmp/claude-501/-Users-justinstoica-calhacks13/629b8d31-5e1a-4eb9-bd4e-f5cad7638d44/scratchpad/blender",
)
OUT_WEB = os.path.join(REPO, "web", "public", "renders")
BLEND = os.path.join(SCRATCH, "a321.blend")

AC_LEN = 44.51


def args():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg_val(name, default=None, cast=str):
    a = args()
    if name in a:
        return cast(a[a.index(name) + 1])
    return default


def log(*a):
    print("[render]", *a, flush=True)


# ----------------------------------------------------------------------------- engine
def setup_cycles(scene, samples=256, res=(3200, 1400), pct=100, threshold=0.015, denoise=True):
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.refresh_devices()
    for d in prefs.devices:
        d.use = d.type == "METAL"
    scene.cycles.device = "GPU"
    scene.cycles.samples = samples
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = threshold
    scene.cycles.use_denoising = denoise
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
    try:
        scene.cycles.denoising_use_gpu = True
    except Exception:
        pass
    scene.cycles.max_bounces = 8
    scene.cycles.diffuse_bounces = 3
    scene.cycles.glossy_bounces = 4
    scene.cycles.transmission_bounces = 4
    scene.cycles.volume_bounces = 1
    scene.cycles.transparent_max_bounces = 8
    scene.cycles.caustics_reflective = False
    scene.cycles.caustics_refractive = False
    scene.cycles.blur_glossy = 1.0
    scene.cycles.use_light_tree = True
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.resolution_percentage = pct
    scene.render.film_transparent = False
    scene.render.use_persistent_data = False
    try:
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.look = "AgX - Medium High Contrast"
    except Exception as e:
        log("colour management:", e)
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "16"


# ----------------------------------------------------------------------------- cameras
def _cam(scene, name, loc, rot_deg, lens=50.0, ortho=None, shift=(0.0, 0.0), clip=(0.1, 10000.0)):
    cd = bpy.data.cameras.get(name) or bpy.data.cameras.new(name)
    cd.sensor_fit = "HORIZONTAL"
    cd.sensor_width = 36.0
    if ortho:
        cd.type = "ORTHO"
        cd.ortho_scale = ortho
    else:
        cd.type = "PERSP"
        cd.lens = lens
    cd.shift_x, cd.shift_y = shift
    cd.clip_start, cd.clip_end = clip
    ob = bpy.data.objects.get(name) or bpy.data.objects.new(name, cd)
    if ob.name not in scene.collection.objects:
        scene.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = tuple(math.radians(a) for a in rot_deg)
    scene.camera = ob
    return ob


# Side profile: 600 mm lens, 824 m away, exactly side-on from port (looking +Y), level.
SIDE_RES = (3200, 1400)
SIDE_LENS = 600.0
SIDE_FRAME_W = AC_LEN / 0.90          # metres across the frame at the aircraft plane (y = 0)
SIDE_DIST = SIDE_LENS / 36.0 * SIDE_FRAME_W
SIDE_CAM_Z = 3.0                      # camera height
SIDE_FRAME_BOTTOM = -3.1              # z (aircraft plane) at the bottom edge of the frame


def side_camera(scene):
    fw = SIDE_FRAME_W
    fh = fw * SIDE_RES[1] / SIDE_RES[0]
    zc = SIDE_FRAME_BOTTOM + fh / 2
    shift_y = (zc - SIDE_CAM_Z) / fw
    return _cam(scene, "cam_side", (AC_LEN / 2, -SIDE_DIST, SIDE_CAM_Z), (90, 0, 0), lens=SIDE_LENS,
                shift=(0.0, shift_y), clip=(50.0, 20000.0))


def side_pixel(x, z, y=0.0):
    """Project a world point (x, y, z) into side-camera pixel coordinates (origin top-left)."""
    fw = SIDE_FRAME_W
    d = SIDE_DIST + y
    s = SIDE_DIST / d
    W, H = SIDE_RES
    fh = fw * H / W
    zc = SIDE_FRAME_BOTTOM + fh / 2
    u = (AC_LEN / 2 + (x - AC_LEN / 2) * s - (AC_LEN / 2 - fw / 2)) / fw * W
    vz = SIDE_CAM_Z + (z - SIDE_CAM_Z) * s
    v = (zc + fh / 2 - vz) / fw * W
    return u, v


HERO_RES = (2560, 1440)


def hero_camera(scene):
    return _cam(scene, "cam_hero", HERO_LOC, HERO_ROT, lens=HERO_LENS, shift=HERO_SHIFT, clip=(0.5, 20000.0))


HERO_LOC = (-12.0, -29.0, 0.9)
HERO_ROT = (88.0, 0.0, -48.0)
HERO_LENS = 32.0
HERO_SHIFT = (0.02, 0.055)

# Orthographic blueprint views (same scale for all three): 40 px per metre.
PPM = 40.0
ORTHO = {
    # name: (res, location, rotation, ortho_scale, metadata about the frame)
    "side": dict(res=(2000, 640), loc=(AC_LEN / 2, -200.0, 5.4), rot=(90, 0, 0)),
    "top": dict(res=(2000, 1600), loc=(AC_LEN / 2, 0.0, 200.0), rot=(0, 0, 0)),
    "front": dict(res=(1600, 640), loc=(-200.0, 0.0, 5.4), rot=(90, 0, -90)),
}


def ortho_camera(scene, view):
    o = ORTHO[view]
    W, H = o["res"]
    cam = _cam(scene, "cam_" + view, o["loc"], o["rot"], ortho=W / PPM, clip=(1.0, 600.0))
    scene.render.resolution_x, scene.render.resolution_y = W, H
    scene.render.resolution_percentage = 100
    return cam


def ortho_meta(view):
    """Pixel positions of the nose tip, centreline and ground line for each orthographic view."""
    o = ORTHO[view]
    W, H = o["res"]
    cx, cy, cz = o["loc"]
    mpp = 1.0 / PPM
    if view == "side":   # image x = world x, image up = world z
        px = lambda x, z: (W / 2 + (x - cx) * PPM, H / 2 - (z - cz) * PPM)
        nose = px(0.0, 3.55)
        ground = px(0.0, 0.0)[1]
        return dict(res=[W, H], metres_per_pixel=mpp, nose_tip_px=[round(nose[0], 2), round(nose[1], 2)],
                    ground_line_y_px=round(ground, 2), centreline_y_px=None,
                    axes="x_px = nose_x + x_m/mpp (aft), y_px = ground_y - z_m/mpp (up)")
    if view == "top":    # image x = world x, image up = world +y (starboard), port at the bottom
        px = lambda x, y: (W / 2 + (x - cx) * PPM, H / 2 - (y - cy) * PPM)
        nose = px(0.0, 0.0)
        return dict(res=[W, H], metres_per_pixel=mpp, nose_tip_px=[round(nose[0], 2), round(nose[1], 2)],
                    centreline_y_px=round(nose[1], 2), ground_line_y_px=None,
                    axes="x_px = nose_x + x_m/mpp (aft), y_px = centre_y - y_m/mpp (starboard up, port down)")
    if view == "front":  # camera looks aft (+x): image right = port (-y), image up = z
        px = lambda y, z: (W / 2 - (y - cy) * PPM, H / 2 - (z - cz) * PPM)
        nose = px(0.0, 3.55)
        ground = px(0.0, 0.0)[1]
        return dict(res=[W, H], metres_per_pixel=mpp, nose_tip_px=[round(nose[0], 2), round(nose[1], 2)],
                    centreline_x_px=round(nose[0], 2), ground_line_y_px=round(ground, 2),
                    axes="x_px = centre_x - y_m/mpp (port to the right), y_px = ground_y - z_m/mpp")


# ----------------------------------------------------------------------------- misc
def ensure_aircraft():
    """Open the built aircraft .blend (rebuild first if missing)."""
    if bpy.data.objects.get("fuselage") is None:
        if os.path.exists(BLEND):
            bpy.ops.wm.open_mainfile(filepath=BLEND)
        else:
            import build_a321
            build_a321.build("hi")


def aircraft_objects():
    col = bpy.data.collections.get("A321")
    return list(col.all_objects) if col else []


def save_webp(src_png, dst_webp, quality=85, alpha=False):
    """Convert with Blender's own image writer (no PIL inside Blender)."""
    img = bpy.data.images.load(src_png, check_existing=False)
    sc = bpy.context.scene
    s = sc.render.image_settings
    old = (s.file_format, s.color_mode, s.quality if hasattr(s, "quality") else None)
    s.file_format = "WEBP"
    s.color_mode = "RGBA" if alpha else "RGB"
    s.quality = quality
    img.save_render(dst_webp, scene=sc)
    s.file_format = old[0]
    s.color_mode = old[1]
    bpy.data.images.remove(img)
