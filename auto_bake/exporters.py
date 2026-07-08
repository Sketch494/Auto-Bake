# SPDX-License-Identifier: GPL-3.0-or-later
"""Model exporters (FBX / OBJ / glTF / .blend).

Every exporter is individually wrapped: a missing IO add-on or a failed
export is logged as a warning and reported, but never aborts the rest of the
pipeline - artists still get their textures and remaining formats.
"""

import os

import bpy

from .errors import AutoBakeError
from .images import ensure_writable_folder


def export_all(context, settings, targets, log):
    """Run every enabled exporter.  Returns the list of files written."""
    folder = bpy.path.abspath(settings.export_folder)
    if settings.use_subfolders:
        model_folder = os.path.join(folder, "models")
    else:
        model_folder = folder
    needs_models = settings.export_fbx or settings.export_obj or \
        settings.export_gltf or settings.export_blend
    if needs_models:
        ensure_writable_folder(model_folder)

    # Exporters honour the current selection - select exactly the targets.
    bpy.ops.object.select_all(action='DESELECT')
    for obj in targets:
        obj.select_set(True)
    if targets:
        context.view_layer.objects.active = targets[0]

    written = []
    base = os.path.join(model_folder, settings.file_name)

    if settings.export_fbx:
        written += _try_export(
            log, "FBX", _export_fbx, base + ".fbx")
    if settings.export_obj:
        written += _try_export(
            log, "OBJ", _export_obj, base + ".obj")
    if settings.export_gltf:
        written += _try_export(
            log, "glTF", _export_gltf, base + ".glb")
    if settings.export_blend:
        written += _try_export(
            log, "Blend", _export_blend, base + ".blend")
    return written


def _try_export(log, label, func, filepath):
    """Run one exporter; on failure log and continue with the others."""
    try:
        log.info("Exporting %s -> %s", label, filepath)
        func(filepath)
    except AutoBakeError:
        raise
    except AttributeError:
        log.warning(
            "%s export skipped - the %s exporter add-on is not available in "
            "this Blender build. Enable it in Preferences > Add-ons.",
            label, label)
        return []
    except RuntimeError as exc:
        log.warning("%s export failed: %s", label, str(exc).strip())
        return []
    extra = []
    if label == "OBJ":
        mtl = os.path.splitext(filepath)[0] + ".mtl"
        if os.path.exists(mtl):
            extra.append(mtl)
    return [filepath] + extra


def _export_fbx(filepath):
    bpy.ops.export_scene.fbx(
        filepath=filepath,
        use_selection=True,
        path_mode='COPY',
        embed_textures=False,
        mesh_smooth_type='FACE',
        add_leaf_bones=False,
    )


def _export_obj(filepath):
    bpy.ops.wm.obj_export(
        filepath=filepath,
        export_selected_objects=True,
        export_materials=True,
        path_mode='COPY',
    )


def _export_gltf(filepath):
    bpy.ops.export_scene.gltf(
        filepath=filepath,
        use_selection=True,
        export_format='GLB',
    )


def _export_blend(filepath):
    bpy.ops.wm.save_as_mainfile(
        filepath=filepath,
        copy=True,
        compress=True,
    )
