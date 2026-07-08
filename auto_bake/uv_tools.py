# SPDX-License-Identifier: GPL-3.0-or-later
"""UV preparation for atlas baking.

Workflow (all driven from :mod:`bake_core`):

1. Every target object gets UVs if missing (Smart UV Project).
2. A dedicated atlas UV layer (``AutoBake``) is created on every target as a
   copy of its current active layer.
3. All targets enter multi-object edit mode together; island scale is
   averaged (texel density preservation) and everything is packed into the
   shared 0..1 space -> one atlas region per object with no overlaps.
"""

import math

import bpy

from . import compat

ATLAS_UV_NAME = "AutoBake"


def has_uvs(obj):
    """True when the mesh has at least one UV layer."""
    return bool(obj.data.uv_layers)


def ensure_uvs(context, obj, settings, log):
    """Create UVs for ``obj`` when it has none.  Returns True if created."""
    if has_uvs(obj):
        return False
    log.info("Object '%s' has no UV map - running Smart UV Project", obj.name)
    _select_only(context, [obj])
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    compat.smart_uv_project(
        math.radians(settings.uv_smart_angle), settings.uv_island_margin)
    bpy.ops.object.mode_set(mode='OBJECT')
    return True


def create_atlas_layer(obj, log):
    """Ensure the atlas UV layer exists and is active on ``obj``.

    Returns the previous (active layer name, active_render layer name) so the
    caller can restore them if the user keeps their original materials.
    """
    mesh = obj.data
    previous_active = mesh.uv_layers.active.name if mesh.uv_layers.active else ""
    previous_render = ""
    for layer in mesh.uv_layers:
        if layer.active_render:
            previous_render = layer.name
            break

    layer = mesh.uv_layers.get(ATLAS_UV_NAME)
    if layer is None:
        if len(mesh.uv_layers) >= 8:
            # Blender's hard UV layer limit; reuse the active layer instead.
            log.warning(
                "Object '%s' already has 8 UV maps - baking into its active "
                "UV map instead of a dedicated atlas layer", obj.name)
            layer = mesh.uv_layers.active
        else:
            # uv_layers.new() duplicates the active layer's coordinates,
            # which is exactly what we want as a packing starting point.
            layer = mesh.uv_layers.new(name=ATLAS_UV_NAME)
            log.debug("Created atlas UV layer on '%s'", obj.name)

    mesh.uv_layers.active = layer
    layer.active_render = True
    return previous_active, previous_render


def restore_uv_layers(obj, previous):
    """Restore active/render UV layers recorded by :func:`create_atlas_layer`."""
    mesh = obj.data
    previous_active, previous_render = previous
    if previous_active and previous_active in mesh.uv_layers:
        mesh.uv_layers.active = mesh.uv_layers[previous_active]
    if previous_render and previous_render in mesh.uv_layers:
        mesh.uv_layers[previous_render].active_render = True


def pack_atlas(context, objects, settings, log):
    """Pack the atlas UV layer of all ``objects`` into shared 0..1 space."""
    if not objects:
        return
    _select_only(context, objects)
    bpy.ops.object.mode_set(mode='EDIT')  # multi-object edit mode
    try:
        context.scene.tool_settings.use_uv_select_sync = True
        bpy.ops.mesh.reveal(select=False)
        bpy.ops.mesh.select_all(action='SELECT')
        if settings.uv_preserve_density:
            log.info("Averaging island scale (texel density)")
            _run_uv_op(
                context, log, "average_islands_scale",
                lambda: bpy.ops.uv.average_islands_scale(),
                critical=False)
        log.info(
            "Packing UV islands of %d object(s), margin %.3f",
            len(objects), settings.uv_island_margin)
        _run_uv_op(
            context, log, "pack_islands",
            lambda: compat.pack_islands(
                margin=settings.uv_island_margin,
                rotate=settings.uv_rotate_islands),
            critical=True)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')


def _run_uv_op(context, log, name, func, critical):
    """Run a UV operator, retrying with an overridden UI context if needed.

    Some ``uv.*`` operators poll for specific editor contexts that may not be
    current (e.g. when driven from the sidebar or a head-less script).  We
    retry the call inside every plausible area before giving up.
    """
    try:
        func()
        return True
    except RuntimeError as first_error:
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type not in ('IMAGE_EDITOR', 'VIEW_3D'):
                    continue
                for region in area.regions:
                    if region.type != 'WINDOW':
                        continue
                    try:
                        with context.temp_override(
                                window=window, area=area, region=region):
                            func()
                        return True
                    except (RuntimeError, AttributeError):
                        continue
        if critical:
            from .errors import AutoBakeError
            raise AutoBakeError(
                "UV operation '%s' failed: %s" % (
                    name, str(first_error).strip()),
                "Try packing the UVs manually in the UV editor, then bake "
                "again with 'Preserve Texel Density' off.")
        log.warning("UV operation '%s' skipped: %s", name, first_error)
        return False


def _select_only(context, objects):
    """Deselect everything, select ``objects``, make the first one active."""
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    context.view_layer.objects.active = objects[0]
