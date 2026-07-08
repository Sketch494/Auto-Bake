# SPDX-License-Identifier: GPL-3.0-or-later
"""Add-on preferences for Auto Bake.

Preferences hold *defaults* that can be applied to any scene via the
``Apply Preference Defaults`` operator (Advanced section of the panel) so
artists can configure their studio pipeline once.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from . import props as ab_props

# Works for classic add-ons ("auto_bake") and 4.2+ extensions
# ("bl_ext.user_default.auto_bake") alike.
ADDON_ID = __package__

LOG_LEVEL_ITEMS = (
    ('DEBUG', "Debug", "Very verbose logging"),
    ('INFO', "Info", "Standard logging"),
    ('WARNING', "Warning", "Warnings and errors only"),
    ('ERROR', "Error", "Errors only"),
)


def get_prefs(context=None):
    """Return the AddonPreferences instance (or ``None`` headless-safe)."""
    context = context or bpy.context
    addon = context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon else None


class AB_Preferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    default_export_folder: StringProperty(
        name="Default Export Folder",
        description="Export folder applied to new scenes",
        subtype='DIR_PATH',
        default="//AutoBake/",
    )
    default_resolution: EnumProperty(
        name="Default Resolution",
        description="Texture resolution applied to new scenes",
        items=ab_props.RESOLUTION_ITEMS,
        default='2048',
    )
    default_format: EnumProperty(
        name="Preferred Format",
        description="Image format applied to new scenes",
        items=ab_props.FORMAT_ITEMS,
        default='PNG',
    )
    default_zip_name: StringProperty(
        name="Default ZIP Name",
        description="ZIP archive name applied to new scenes",
        default="AutoBake_Export",
    )
    default_device: EnumProperty(
        name="Preferred Device",
        description="Bake device applied to new scenes",
        items=ab_props.DEVICE_ITEMS,
        default='AUTO',
    )
    # Default bake passes for new scenes.
    default_basecolor: BoolProperty(name="Base Color", default=True)
    default_normal: BoolProperty(name="Normal", default=True)
    default_roughness: BoolProperty(name="Roughness", default=True)
    default_metallic: BoolProperty(name="Metallic", default=False)
    default_ao: BoolProperty(name="Ambient Occlusion", default=False)
    default_emission: BoolProperty(name="Emission", default=False)

    log_level: EnumProperty(
        name="Logging Level",
        description="How much detail Auto Bake writes to the console and log",
        items=LOG_LEVEL_ITEMS,
        default='INFO',
        update=lambda self, ctx: _apply_log_level(self),
    )

    def draw(self, _context):
        layout = self.layout

        box = layout.box()
        box.label(text="Pipeline Defaults", icon='TOOL_SETTINGS')
        col = box.column()
        col.prop(self, "default_export_folder")
        row = col.row(align=True)
        row.prop(self, "default_resolution")
        row.prop(self, "default_format")
        row = col.row(align=True)
        row.prop(self, "default_device")
        row.prop(self, "default_zip_name")

        box = layout.box()
        box.label(text="Default Bake Passes", icon='IMAGE_DATA')
        grid = box.grid_flow(columns=3, align=True)
        for prop_name in (
            "default_basecolor", "default_normal", "default_roughness",
            "default_metallic", "default_ao", "default_emission",
        ):
            grid.prop(self, prop_name, toggle=True)

        box = layout.box()
        box.label(text="Diagnostics", icon='CONSOLE')
        box.prop(self, "log_level")
        box.label(
            text="Use 'Apply Preference Defaults' in the panel's Advanced "
                 "section to copy these into a scene.",
            icon='INFO',
        )

    # Called by the "Apply Preference Defaults" operator.
    def apply_to_settings(self, settings):
        settings.export_folder = self.default_export_folder
        settings.resolution = self.default_resolution
        settings.image_format = self.default_format
        settings.zip_name = self.default_zip_name
        settings.device = self.default_device
        settings.use_basecolor = self.default_basecolor
        settings.use_normal = self.default_normal
        settings.use_roughness = self.default_roughness
        settings.use_metallic = self.default_metallic
        settings.use_ao = self.default_ao
        settings.use_emission = self.default_emission


def _apply_log_level(prefs_instance):
    from . import log_utils
    log_utils.set_level(prefs_instance.log_level)


def register():
    bpy.utils.register_class(AB_Preferences)
    prefs = get_prefs()
    if prefs is not None:
        _apply_log_level(prefs)


def unregister():
    bpy.utils.unregister_class(AB_Preferences)
