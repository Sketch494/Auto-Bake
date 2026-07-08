# SPDX-License-Identifier: GPL-3.0-or-later
#
# Auto Bake by Sketch494
# Copyright (C) 2026 Sketch494
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Auto Bake by Sketch494.

Bake entire scenes or selected objects into optimized texture atlases with
configurable bake passes, automatic UV handling, baked material creation,
multi-format export and one-click ZIP packaging.

Package layout:
    __init__.py    add-on registration entry point (this file)
    compat.py      Blender 3.6 -> 5.x API compatibility helpers
    errors.py      friendly error types and messages
    log_utils.py   logging (console + in-memory buffer + save to file)
    passes.py      bake pass definitions / metadata
    props.py       Scene settings + WindowManager runtime state
    prefs.py       add-on preferences
    uv_tools.py    UV creation, atlas packing, texel density helpers
    images.py      bake image creation and saving
    bake_core.py   the bake job state machine (engine)
    materials.py   baked material creation and assignment
    exporters.py   FBX / OBJ / glTF / .blend exporters
    zip_export.py  ZIP packaging and folder helpers
    operators.py   operators (modal bake, dialogs, utilities)
    panels.py      3D View sidebar UI
"""

bl_info = {
    "name": "Auto Bake",
    "author": "Sketch494",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "3D View > Sidebar > Auto Bake",
    "description": (
        "Bake scenes or selections into optimized texture atlases with "
        "configurable passes, exports and ZIP packaging"
    ),
    "doc_url": "https://autobake.sketch494.online",
    "tracker_url": "https://github.com/Sketch494/Auto-Bake/issues",
    "category": "Material",
}

# ---------------------------------------------------------------------------
# Module import / reload support
# ---------------------------------------------------------------------------
# When the add-on is reloaded (F3 > "Reload Scripts" or during development),
# the submodules must be reloaded too, otherwise stale code keeps running.
if "props" in locals():  # pragma: no cover - only hit on add-on reload
    import importlib

    for _mod in (
        compat, errors, log_utils, passes, props, prefs, uv_tools, images,
        bake_core, materials, exporters, zip_export, operators, panels,
    ):
        importlib.reload(_mod)
else:
    from . import (
        compat, errors, log_utils, passes, props, prefs, uv_tools, images,
        bake_core, materials, exporters, zip_export, operators, panels,
    )

# Modules that own bpy classes and therefore need (un)registration, in order.
_REGISTER_MODULES = (props, prefs, operators, panels)


def register():
    """Register every class the add-on provides."""
    for mod in _REGISTER_MODULES:
        mod.register()
    log_utils.get_logger().info(
        "Auto Bake %s registered (Blender %s)",
        ".".join(str(v) for v in bl_info["version"]),
        compat.blender_version_string(),
    )


def unregister():
    """Unregister in reverse order so dependencies unwind cleanly."""
    for mod in reversed(_REGISTER_MODULES):
        mod.unregister()
    log_utils.get_logger().info("Auto Bake unregistered")
