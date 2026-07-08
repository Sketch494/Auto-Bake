# SPDX-License-Identifier: GPL-3.0-or-later
"""ZIP packaging and folder utilities."""

import os
import subprocess
import sys
import time
import zipfile

import bpy

from .errors import AutoBakeError

_README_TEMPLATE = """Auto Bake export
================

Created:      {date}
Blender:      {blender}
Add-on:       Auto Bake by Sketch494
Atlas size:   {size} x {size}
Bake passes:  {passes}

Contents
--------
textures/  Baked texture atlases
models/    Exported models (when enabled)

Generated automatically by Auto Bake.
https://autobake.sketch494.online
"""

_LICENSE_TEMPLATE = """License for exported assets
===========================

The textures and models in this archive were baked from your own scene with
the Auto Bake add-on. YOU own these assets - replace this file with the
license you want to ship them under (e.g. CC0, CC-BY, or a proprietary
notice).

The Auto Bake add-on itself is licensed under the GNU GPL-3.0-or-later,
which places no restriction on the assets you create with it.
"""


def build_zip(context, settings, texture_files, model_files, atlas_size,
              pass_labels, log):
    """Package the exported files into one ZIP archive.

    Returns the path of the archive written.
    """
    folder = bpy.path.abspath(settings.export_folder)
    zip_name = (settings.zip_name.strip() or "AutoBake_Export")
    if not zip_name.lower().endswith(".zip"):
        zip_name += ".zip"
    zip_path = os.path.join(folder, zip_name)

    entries = []
    for path in texture_files:
        if os.path.exists(path):
            entries.append((path, "textures/" + os.path.basename(path)))
    for path in model_files:
        if os.path.exists(path):
            entries.append((path, "models/" + os.path.basename(path)))

    if not entries:
        raise AutoBakeError(
            "Nothing to package - no textures or models were exported.",
            "Enable 'Textures' or at least one model format in the Export "
            "section.")

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for source, arcname in entries:
                archive.write(source, arcname)
            if settings.zip_include_readme:
                archive.writestr("README.txt", _README_TEMPLATE.format(
                    date=time.strftime("%Y-%m-%d %H:%M:%S"),
                    blender=bpy.app.version_string,
                    size=atlas_size,
                    passes=", ".join(pass_labels) or "-",
                ))
            if settings.zip_include_license:
                archive.writestr("LICENSE.txt", _LICENSE_TEMPLATE)
    except (OSError, PermissionError) as exc:
        raise AutoBakeError(
            "Could not write the ZIP archive: %s" % exc,
            "Check free disk space and folder permissions.")

    log.info("ZIP archive written: %s (%d files)", zip_path, len(entries))

    if settings.zip_clean_temp:
        removed = 0
        for source, _arc in entries:
            try:
                os.remove(source)
                removed += 1
            except OSError:
                pass
        # Remove now-empty subfolders quietly.
        for sub in ("textures", "models"):
            subdir = os.path.join(folder, sub)
            try:
                os.rmdir(subdir)
            except OSError:
                pass
        log.info("Removed %d loose file(s) after zipping", removed)
    return zip_path


def open_folder(path):
    """Open ``path`` in the platform's file browser (best effort)."""
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        return False
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606 - intended behavior
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except OSError:
        return False
