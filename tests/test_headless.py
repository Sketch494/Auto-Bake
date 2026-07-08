# SPDX-License-Identifier: GPL-3.0-or-later
"""Head-less end-to-end test for Auto Bake.

Run inside Blender:

    blender -b --factory-startup --python tests/test_headless.py -- \
        --zip dist/auto_bake-1.0.0.zip \
        --ext-zip dist/auto_bake-1.0.0-extension.zip \
        --out /tmp/autobake_test

The script installs the add-on from the ZIP exactly like a user would,
builds a scene exercising every tricky code path (linked textures, missing
UVs, no-material objects, non-Principled materials, hidden objects), runs a
full bake + export + ZIP synchronously, and asserts the results.
"""

import os
import shutil
import sys
import traceback
import zipfile

import bpy

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition), detail))
    print("  [%s] %s%s" % (
        "PASS" if condition else "FAIL", name,
        (" - " + detail) if (detail and not condition) else ""))
    return bool(condition)


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = {"zip": "", "ext_zip": "", "out": "/tmp/autobake_test"}
    i = 0
    while i < len(argv):
        if argv[i] == "--zip":
            args["zip"] = argv[i + 1]; i += 2
        elif argv[i] == "--ext-zip":
            args["ext_zip"] = argv[i + 1]; i += 2
        elif argv[i] == "--out":
            args["out"] = argv[i + 1]; i += 2
        else:
            i += 1
    return args


def install_addon(zip_path, ext_zip_path):
    """Install + enable the add-on the way a user would. Returns module name."""
    # Path 1: classic add-on install (3.6 .. 4.x, possibly 5.x).
    try:
        bpy.ops.preferences.addon_install(filepath=zip_path, overwrite=True)
        bpy.ops.preferences.addon_enable(module="auto_bake")
        if "auto_bake" in bpy.context.preferences.addons:
            print("Installed as classic add-on")
            return "auto_bake"
    except Exception as exc:
        print("Classic add-on install failed: %s" % exc)

    # Path 2: extension install (4.2+).
    try:
        bpy.ops.extensions.repo_refresh_all()
    except Exception:
        pass
    candidates = (
        {"filepath": ext_zip_path, "repo": "user_default",
         "enable_on_install": True},
        {"filepath": ext_zip_path, "repo": "user_default"},
    )
    for kwargs in candidates:
        try:
            bpy.ops.extensions.package_install_files(**kwargs)
            break
        except Exception as exc:
            print("Extension install attempt failed: %s" % exc)
    module = "bl_ext.user_default.auto_bake"
    if module not in bpy.context.preferences.addons:
        try:
            bpy.ops.preferences.addon_enable(module=module)
        except Exception as exc:
            print("Extension enable failed: %s" % exc)
    if module in bpy.context.preferences.addons:
        print("Installed as extension")
        return module
    raise RuntimeError("Could not install Auto Bake by any method")


def make_material_principled(name, base_color, metallic, roughness,
                             emission=None):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    principled = None
    for node in mat.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            principled = node
            break
    principled.inputs["Base Color"].default_value = base_color
    principled.inputs["Metallic"].default_value = metallic
    principled.inputs["Roughness"].default_value = roughness
    if emission is not None:
        for socket_name in ("Emission Color", "Emission"):
            sock = principled.inputs.get(socket_name)
            if sock is not None:
                sock.default_value = emission
                break
        strength = principled.inputs.get("Emission Strength")
        if strength is not None:
            strength.default_value = 1.0
    return mat


def make_material_textured(name):
    """Material whose Base Color comes from a linked noise texture."""
    mat = make_material_principled(name, (1, 1, 1, 1), 0.0, 0.6)
    nt = mat.node_tree
    principled = [n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'][0]
    noise = nt.nodes.new('ShaderNodeTexNoise')
    noise.inputs["Scale"].default_value = 8.0
    nt.links.new(noise.outputs["Color"], principled.inputs["Base Color"])
    return mat


def make_material_emission_only(name):
    """Material with no Principled BSDF (fallback code path)."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    output = nt.nodes.new('ShaderNodeOutputMaterial')
    emission = nt.nodes.new('ShaderNodeEmission')
    emission.inputs["Color"].default_value = (0.1, 0.2, 0.9, 1.0)
    nt.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return mat


def build_scene():
    # Empty the factory scene.
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)

    bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
    cube_red = bpy.context.active_object
    cube_red.name = "CubeRed"
    cube_red.data.materials.append(make_material_principled(
        "MatRed", (0.9, 0.05, 0.05, 1.0), 0.8, 0.3,
        emission=(0.0, 1.0, 0.0, 1.0)))

    bpy.ops.mesh.primitive_cube_add(location=(3, 0, 0))
    cube_tex = bpy.context.active_object
    cube_tex.name = "CubeTex"
    cube_tex.data.materials.append(make_material_textured("MatTex"))

    bpy.ops.mesh.primitive_uv_sphere_add(location=(0, 3, 0), segments=16,
                                         ring_count=8)
    sphere = bpy.context.active_object
    sphere.name = "SphereEmit"
    sphere.data.materials.append(make_material_emission_only("MatEmitOnly"))

    bpy.ops.mesh.primitive_cone_add(location=(3, 3, 0))
    cone = bpy.context.active_object
    cone.name = "ConeBare"  # no material at all
    # Remove its UVs to exercise Smart UV Project.
    while cone.data.uv_layers:
        cone.data.uv_layers.remove(cone.data.uv_layers[0])

    bpy.ops.mesh.primitive_cube_add(location=(6, 6, 0))
    hidden = bpy.context.active_object
    hidden.name = "HiddenCube"
    hidden.hide_set(True)

    return cube_red, cube_tex, sphere, cone, hidden


def configure(out_dir):
    settings = bpy.context.scene.auto_bake
    settings.bake_scope = 'SCENE'
    for ident in ("basecolor", "normal", "roughness", "metallic",
                  "emission", "alpha", "ao"):
        setattr(settings, "use_%s" % ident, True)
    for ident in ("specular", "glossiness", "height", "displacement",
                  "combined"):
        setattr(settings, "use_%s" % ident, False)
    custom = settings.custom_passes.add()
    custom.name = "Sheen"
    custom.socket_name = "Sheen"
    settings.export_folder = out_dir
    settings.file_name = "AutoBake"
    settings.resolution = '512'
    settings.auto_resize_atlas = False
    settings.image_format = 'PNG'
    settings.color_depth = '8'
    settings.overwrite_mode = 'OVERWRITE'
    settings.use_subfolders = True
    settings.samples = 4
    settings.bake_margin = 4
    settings.device = 'CPU'
    settings.use_denoising = False
    settings.material_action = 'REPLACE'
    settings.export_textures = True
    settings.export_blend = True
    settings.export_fbx = True
    settings.export_obj = True
    settings.export_gltf = True
    settings.make_zip = True
    settings.zip_name = "AutoBake_Test"
    settings.zip_include_readme = True
    settings.zip_include_license = True
    settings.zip_clean_temp = False
    settings.open_folder_after = False
    return settings


def image_stats(path):
    """Return (mean_r, mean_g, mean_b, mean_lum, max_r) of a saved image."""
    image = bpy.data.images.load(path)
    try:
        pixels = image.pixels[:]
        count = len(pixels) // 4
        step = max(1, count // 20000)  # sample for speed
        r = g = b = 0.0
        max_r = 0.0
        samples = 0
        for i in range(0, count, step):
            base = i * 4
            r += pixels[base]
            g += pixels[base + 1]
            b += pixels[base + 2]
            max_r = max(max_r, pixels[base])
            samples += 1
        return (r / samples, g / samples, b / samples,
                (r + g + b) / (3 * samples), max_r)
    finally:
        bpy.data.images.remove(image)


def main():
    args = parse_args()
    out_dir = args["out"]
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    print("=" * 70)
    print("Auto Bake head-less test - Blender %s" % bpy.app.version_string)
    print("=" * 70)

    module = install_addon(args["zip"], args["ext_zip"])
    check("add-on installs and enables", module in
          bpy.context.preferences.addons)
    check("scene settings registered",
          hasattr(bpy.context.scene, "auto_bake"))

    # Round-trip disable/enable proves clean unregister/register.
    bpy.ops.preferences.addon_disable(module=module)
    disabled = not hasattr(bpy.context.scene, "auto_bake")
    bpy.ops.preferences.addon_enable(module=module)
    check("clean unregister/re-register",
          disabled and hasattr(bpy.context.scene, "auto_bake"))

    cube_red, cube_tex, sphere, cone, hidden = build_scene()
    configure(out_dir)

    result = bpy.ops.autobake.bake('EXEC_DEFAULT', sync=True)
    check("bake operator returns FINISHED", result == {'FINISHED'},
          str(result))

    tex_dir = os.path.join(out_dir, "textures")
    expected_textures = ["BaseColor", "Normal", "Roughness", "Metallic",
                         "Emission", "Alpha", "AO", "Sheen"]
    for suffix in expected_textures:
        path = os.path.join(tex_dir, "AutoBake_%s.png" % suffix)
        ok = os.path.isfile(path) and os.path.getsize(path) > 1024
        check("texture %s written" % suffix, ok, path)

    # Pixel-level sanity.
    base_stats = image_stats(os.path.join(tex_dir, "AutoBake_BaseColor.png"))
    check("base color contains red content (CubeRed)",
          base_stats[4] > 0.5 and base_stats[3] > 0.02,
          "stats=%s" % (base_stats,))
    normal_stats = image_stats(os.path.join(tex_dir, "AutoBake_Normal.png"))
    check("normal map is blue-dominant", normal_stats[2] > 0.55,
          "stats=%s" % (normal_stats,))
    metal_stats = image_stats(os.path.join(tex_dir, "AutoBake_Metallic.png"))
    check("metallic map has metal areas", metal_stats[4] > 0.5,
          "stats=%s" % (metal_stats,))
    alpha_stats = image_stats(os.path.join(tex_dir, "AutoBake_Alpha.png"))
    check("alpha map is white where baked", alpha_stats[4] > 0.9,
          "stats=%s" % (alpha_stats,))

    # Models.
    model_dir = os.path.join(out_dir, "models")
    for ext in (".fbx", ".obj", ".glb", ".blend"):
        path = os.path.join(model_dir, "AutoBake" + ext)
        check("model export %s" % ext,
              os.path.isfile(path) and os.path.getsize(path) > 0, path)

    # ZIP.
    zip_path = os.path.join(out_dir, "AutoBake_Test.zip")
    zip_ok = os.path.isfile(zip_path)
    check("ZIP archive written", zip_ok, zip_path)
    if zip_ok:
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            check("ZIP integrity", archive.testzip() is None)
            check("ZIP contains textures/",
                  any(n.startswith("textures/") for n in names))
            check("ZIP contains models/",
                  any(n.startswith("models/") for n in names))
            check("ZIP contains README.txt", "README.txt" in names)
            check("ZIP contains LICENSE.txt", "LICENSE.txt" in names)

    # Materials & atlas UVs.
    baked_mat = bpy.data.materials.get("AutoBake_Baked")
    check("baked material created", baked_mat is not None)
    check("baked material assigned to CubeRed",
          len(cube_red.data.materials) == 1 and
          cube_red.data.materials[0] == baked_mat)
    check("baked material assigned to bare cone",
          len(cone.data.materials) == 1 and
          cone.data.materials[0] == baked_mat)
    check("cone received UVs", len(cone.data.uv_layers) > 0)
    check("atlas UV layer on CubeTex",
          "AutoBake" in [l.name for l in cube_tex.data.uv_layers])
    check("hidden object untouched",
          len(hidden.data.materials) == 0)

    # Temporary data cleaned up.
    leftover_nodes = []
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        for node in mat.node_tree.nodes:
            if node.name.startswith("AutoBake_BakeTarget") or \
                    node.get("auto_bake_temp"):
                leftover_nodes.append((mat.name, node.name))
    check("no leftover temp nodes", not leftover_nodes, str(leftover_nodes))
    check("temp material removed",
          "AutoBake_TempMaterial" not in bpy.data.materials)
    # Factory default is an EEVEE variant on every supported version, so a
    # correct restore means we are no longer on CYCLES.
    check("render engine restored",
          bpy.context.scene.render.engine != 'CYCLES',
          bpy.context.scene.render.engine)

    failed = [c for c in CHECKS if not c[1]]
    print("-" * 70)
    print("%d checks, %d failed" % (len(CHECKS), len(failed)))
    if failed:
        for name, _ok, detail in failed:
            print("FAILED: %s (%s)" % (name, detail))
        print("RESULT: FAIL")
        sys.exit(1)
    print("RESULT: ALL TESTS PASSED")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        print("RESULT: FAIL (exception)")
        sys.exit(1)
