# SPDX-License-Identifier: GPL-3.0-or-later
"""Bake image creation and saving.

Saving uses ``Image.save_render`` with a temporarily overridden scene so the
user's color management (Filmic / AgX view transforms) can never distort data
maps - a classic baking pitfall.  All format specific options (color depth,
compression, EXR codec) are validated against what the chosen format really
supports.
"""

import os

import bpy

from .errors import AutoBakeError

FORMAT_EXTENSIONS = {
    'PNG': ".png",
    'TARGA': ".tga",
    'TIFF': ".tif",
    'OPEN_EXR': ".exr",
}

# Color depths each format accepts (Blender rejects anything else).
_VALID_DEPTHS = {
    'PNG': ('8', '16'),
    'TARGA': ('8',),
    'TIFF': ('8', '16'),
    'OPEN_EXR': ('16', '32'),
}


def valid_color_depth(image_format, requested, log=None):
    """Clamp the requested color depth to what ``image_format`` supports."""
    valid = _VALID_DEPTHS.get(image_format, ('8',))
    if requested in valid:
        return requested
    clamped = valid[-1] if int(requested) > int(valid[-1]) else valid[0]
    if log is not None:
        log.warning(
            "%s does not support %s-bit output - using %s-bit",
            image_format, requested, clamped)
    return clamped


def create_bake_image(name, size, pass_def):
    """Create the atlas image for one bake pass."""
    existing = bpy.data.images.get(name)
    if existing is not None:
        bpy.data.images.remove(existing)
    image = bpy.data.images.new(
        name, width=size, height=size, alpha=True,
        float_buffer=pass_def.use_float)
    image.generated_color = pass_def.fill_color
    image.colorspace_settings.name = pass_def.colorspace
    image["auto_bake"] = True
    return image


def resolve_output_path(folder, base_name, suffix, extension, overwrite_mode):
    """Compute the output filepath honoring the overwrite policy.

    ``overwrite_mode`` here is 'OVERWRITE' or 'RENAME' ('ASK' is resolved to
    one of those by the confirmation dialog before the job starts).
    """
    filename = "%s_%s%s" % (base_name, suffix, extension)
    path = os.path.join(folder, filename)
    if overwrite_mode == 'RENAME' and os.path.exists(path):
        counter = 1
        while counter < 1000:
            candidate = os.path.join(
                folder, "%s_%s_%03d%s" % (base_name, suffix, counter, extension))
            if not os.path.exists(candidate):
                return candidate
            counter += 1
        raise AutoBakeError(
            "Could not find a free filename for %s." % filename,
            "Clean up the export folder or choose 'Overwrite'.")
    return path


def save_image(context, image, filepath, settings, log):
    """Save ``image`` to ``filepath`` with the configured format options."""
    scene = context.scene
    image_settings = scene.render.image_settings
    view = scene.view_settings

    # Remember everything we are about to touch.
    saved = {
        "file_format": image_settings.file_format,
        "color_mode": image_settings.color_mode,
        "color_depth": image_settings.color_depth,
        "compression": image_settings.compression,
        "quality": image_settings.quality,
        "exr_codec": getattr(image_settings, "exr_codec", None),
        "tiff_codec": getattr(image_settings, "tiff_codec", None),
        "view_transform": view.view_transform,
        "look": view.look,
        "exposure": view.exposure,
        "gamma": view.gamma,
    }
    try:
        image_settings.file_format = settings.image_format
        # RGBA keeps baked alpha; data maps stay RGB.
        wants_alpha = image.colorspace_settings.name == 'sRGB' or \
            image.name.endswith(("Alpha",))
        try:
            image_settings.color_mode = 'RGBA' if wants_alpha else 'RGB'
        except TypeError:
            image_settings.color_mode = 'RGB'
        image_settings.color_depth = valid_color_depth(
            settings.image_format, settings.color_depth, log)
        image_settings.compression = settings.compression
        if settings.image_format == 'OPEN_EXR' and saved["exr_codec"]:
            image_settings.exr_codec = 'ZIP'
        # Neutral view transform: guarantees data maps are written raw and
        # color maps get a plain sRGB encode (no Filmic/AgX tone mapping).
        try:
            view.view_transform = 'Standard'
        except TypeError:
            try:
                view.view_transform = 'Raw'
            except TypeError:
                pass
        try:
            view.look = 'None'
        except TypeError:
            pass
        view.exposure = 0.0
        view.gamma = 1.0

        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        image.save_render(filepath, scene=scene)
        # Point the datablock at the saved file so exported models and the
        # baked material reference it from disk.
        image.filepath = filepath
        image.source = 'FILE'
        image.reload()
        log.info("Saved %s", filepath)
    except (OSError, PermissionError) as exc:
        raise AutoBakeError(
            "Could not save '%s': %s" % (os.path.basename(filepath), exc),
            "Check that the folder exists and that you have write "
            "permission, then bake again.")
    finally:
        # Restore every render/view setting we touched.
        image_settings.file_format = saved["file_format"]
        try:
            image_settings.color_mode = saved["color_mode"]
        except TypeError:
            pass
        try:
            image_settings.color_depth = saved["color_depth"]
        except TypeError:
            pass
        image_settings.compression = saved["compression"]
        image_settings.quality = saved["quality"]
        if saved["exr_codec"] is not None:
            image_settings.exr_codec = saved["exr_codec"]
        if saved["tiff_codec"] is not None:
            image_settings.tiff_codec = saved["tiff_codec"]
        try:
            view.view_transform = saved["view_transform"]
            view.look = saved["look"]
        except TypeError:
            pass
        view.exposure = saved["exposure"]
        view.gamma = saved["gamma"]


def ensure_writable_folder(folder):
    """Create ``folder`` when missing and verify it is writable."""
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        raise AutoBakeError(
            "The export folder could not be created: %s" % folder,
            "Reason: %s. Choose a different folder." % exc)
    if not os.access(folder, os.W_OK):
        raise AutoBakeError(
            "No write permission for the export folder: %s" % folder,
            "Choose a folder inside your user directory, or fix the folder "
            "permissions.")
    return folder


def dedupe_image_datablocks(log):
    """Merge image datablocks that point at the same file on disk."""
    seen = {}
    merged = 0
    for image in list(bpy.data.images):
        path = bpy.path.abspath(image.filepath) if image.filepath else ""
        if not path:
            continue
        key = os.path.normpath(path)
        if key in seen:
            image.user_remap(seen[key])
            bpy.data.images.remove(image)
            merged += 1
        else:
            seen[key] = image
    if merged:
        log.info("Merged %d duplicate image datablock(s)", merged)
    return merged
