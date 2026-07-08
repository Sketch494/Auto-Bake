# SPDX-License-Identifier: GPL-3.0-or-later
"""3D View sidebar UI (N-panel > "Auto Bake" tab).

A main panel hosts the big bake button, live progress and result messages;
collapsible sub-panels group every setting.  All properties carry
descriptions, so every control has a tooltip.
"""

import bpy

from . import compat

DOCS_URL = "https://autobake.sketch494.online"


class AUTOBAKE_UL_custom_passes(bpy.types.UIList):
    """List row for user defined bake passes."""

    def draw_item(self, _context, layout, _data, item, _icon, _active_data,
                  _active_prop, _index=0, _flt_flag=0):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.prop(item, "name", text="", emboss=False)
        row.prop(item, "socket_name", text="", emboss=True)
        row.prop(item, "non_color", text="", icon='EVENT_D', toggle=True)


class _BasePanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Auto Bake"


class AUTOBAKE_PT_main(_BasePanel, bpy.types.Panel):
    bl_idname = "AUTOBAKE_PT_main"
    bl_label = "Auto Bake"

    def draw_header(self, _context):
        self.layout.label(icon='RENDER_STILL')

    def draw(self, context):
        layout = self.layout
        settings = context.scene.auto_bake
        runtime = context.window_manager.auto_bake_runtime

        col = layout.column()
        col.prop(settings, "bake_scope", text="")

        if runtime.running:
            box = col.box()
            box_col = box.column(align=True)
            compat.draw_progress(
                box_col, runtime, runtime.progress / 100.0,
                text="%d%%" % int(runtime.progress))
            box_col.label(text=runtime.status, icon='TIME')
            if runtime.eta:
                box_col.label(text=runtime.eta, icon='PREVIEW_RANGE')
            cancel = box.row()
            cancel.scale_y = 1.2
            cancel.operator(
                "autobake.cancel", text="Cancel", icon='CANCEL')
        else:
            bake_row = col.row()
            bake_row.scale_y = 1.6
            bake_row.operator(
                "autobake.bake", text="Bake", icon='RENDER_STILL')

            if runtime.last_result != 'NONE':
                box = col.box()
                icon = {
                    'SUCCESS': 'CHECKMARK',
                    'ERROR': 'ERROR',
                    'CANCELLED': 'CANCEL',
                }[runtime.last_result]
                # Wrap long messages over a few rows for readability.
                message = runtime.last_message or runtime.status
                box.label(text=_truncate(message, 42), icon=icon)
                for line in _wrap_rest(message, 42, max_lines=3):
                    box.label(text=line)
                if runtime.last_result == 'ERROR' and runtime.last_suggestion:
                    for line in _wrap_all(
                            "Fix: " + runtime.last_suggestion, 42,
                            max_lines=4):
                        box.label(text=line, icon='INFO')


class AUTOBAKE_PT_passes(_BasePanel, bpy.types.Panel):
    bl_parent_id = "AUTOBAKE_PT_main"
    bl_label = "Bake Maps"

    def draw_header(self, _context):
        self.layout.label(icon='IMAGE_DATA')

    def draw(self, context):
        layout = self.layout
        settings = context.scene.auto_bake

        grid = layout.grid_flow(
            row_major=True, columns=2, even_columns=True, align=True)
        for ident in (
                "basecolor", "normal", "roughness", "metallic", "ao",
                "emission", "alpha", "specular", "glossiness", "height",
                "displacement", "combined"):
            grid.prop(settings, "use_%s" % ident, toggle=True)

        box = layout.box()
        header = box.row()
        header.prop(
            settings, "ui_show_custom",
            icon='TRIA_DOWN' if settings.ui_show_custom else 'TRIA_RIGHT',
            text="Custom Passes", emboss=False)
        if settings.ui_show_custom:
            row = box.row()
            row.template_list(
                "AUTOBAKE_UL_custom_passes", "", settings, "custom_passes",
                settings, "custom_passes_index", rows=2)
            buttons = row.column(align=True)
            buttons.operator("autobake.custom_pass_add", icon='ADD', text="")
            buttons.operator(
                "autobake.custom_pass_remove", icon='REMOVE', text="")
            box.label(
                text="Socket = Principled input name, e.g. 'Sheen Weight'",
                icon='INFO')


class AUTOBAKE_PT_output(_BasePanel, bpy.types.Panel):
    bl_parent_id = "AUTOBAKE_PT_main"
    bl_label = "Output"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, _context):
        self.layout.label(icon='FILE_FOLDER')

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        settings = context.scene.auto_bake

        col = layout.column()
        col.prop(settings, "export_folder")
        col.prop(settings, "file_name")
        col.separator()
        col.prop(settings, "resolution")
        col.prop(settings, "image_format")
        col.prop(settings, "color_depth")
        if settings.image_format in ('PNG', 'OPEN_EXR'):
            col.prop(settings, "compression")
        col.separator()
        col.prop(settings, "overwrite_mode")
        col.prop(settings, "use_subfolders")


class AUTOBAKE_PT_bake_options(_BasePanel, bpy.types.Panel):
    bl_parent_id = "AUTOBAKE_PT_main"
    bl_label = "Baking"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, _context):
        self.layout.label(icon='SETTINGS')

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        settings = context.scene.auto_bake

        col = layout.column()
        col.prop(settings, "device")
        col.prop(settings, "samples")
        col.prop(settings, "use_denoising")
        col.prop(settings, "bake_margin")
        col.separator()
        col.prop(settings, "skip_hidden")
        col.prop(settings, "merge_duplicate_materials")
        col.prop(settings, "dedupe_images")

        box = layout.box()
        box.prop(settings, "use_selected_to_active")
        if settings.use_selected_to_active:
            sub = box.column()
            sub.enabled = settings.bake_scope == 'SELECTED'
            sub.prop(settings, "max_ray_distance")
            sub.prop(settings, "cage_extrusion")
            if settings.bake_scope != 'SELECTED':
                box.label(
                    text="Requires 'Selected Objects' scope", icon='INFO')


class AUTOBAKE_PT_uv(_BasePanel, bpy.types.Panel):
    bl_parent_id = "AUTOBAKE_PT_main"
    bl_label = "UV && Atlas"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, _context):
        self.layout.label(icon='UV')

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        settings = context.scene.auto_bake

        col = layout.column()
        col.prop(settings, "uv_create_missing")
        if settings.uv_create_missing:
            col.prop(settings, "uv_smart_angle")
        col.prop(settings, "uv_island_margin")
        col.prop(settings, "uv_rotate_islands")
        col.prop(settings, "uv_preserve_density")
        col.separator()
        col.prop(settings, "auto_resize_atlas")
        col.label(
            text="All objects share one atlas per enabled map",
            icon='INFO')


class AUTOBAKE_PT_materials(_BasePanel, bpy.types.Panel):
    bl_parent_id = "AUTOBAKE_PT_main"
    bl_label = "Materials"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, _context):
        self.layout.label(icon='MATERIAL')

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        settings = context.scene.auto_bake

        col = layout.column()
        col.prop(settings, "material_action")
        if settings.material_action != 'NONE' and settings.use_ao:
            col.prop(settings, "ao_multiply")


class AUTOBAKE_PT_export(_BasePanel, bpy.types.Panel):
    bl_parent_id = "AUTOBAKE_PT_main"
    bl_label = "Export"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, _context):
        self.layout.label(icon='EXPORT')

    def draw(self, context):
        layout = self.layout
        settings = context.scene.auto_bake

        grid = layout.grid_flow(
            row_major=True, columns=2, even_columns=True, align=True)
        for prop_name in ("export_textures", "export_blend", "export_fbx",
                          "export_obj", "export_gltf"):
            grid.prop(settings, prop_name, toggle=True)

        box = layout.box()
        box.prop(settings, "make_zip", icon='PACKAGE')
        if settings.make_zip:
            col = box.column()
            col.use_property_split = True
            col.use_property_decorate = False
            col.prop(settings, "zip_name")
            col.prop(settings, "zip_include_readme")
            col.prop(settings, "zip_include_license")
            col.prop(settings, "zip_clean_temp")

        layout.prop(settings, "open_folder_after")
        row = layout.row(align=True)
        row.operator(
            "autobake.export_only", text="Export Only", icon='EXPORT')
        row.operator(
            "autobake.open_folder", text="Open Folder", icon='FILE_FOLDER')


class AUTOBAKE_PT_advanced(_BasePanel, bpy.types.Panel):
    bl_parent_id = "AUTOBAKE_PT_main"
    bl_label = "Advanced && Log"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, _context):
        self.layout.label(icon='TOOL_SETTINGS')

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.operator(
            "autobake.apply_pref_defaults",
            text="Apply Preference Defaults", icon='PREFERENCES')
        col.operator(
            "autobake.save_log", text="Save Log", icon='TEXT')
        col.operator(
            "autobake.reset_settings",
            text="Reset Settings", icon='LOOP_BACK')
        col.separator()
        col.operator(
            "wm.url_open", text="Documentation",
            icon='HELP').url = DOCS_URL

        layout.label(
            text="Auto Bake 1.0.0 - Blender %s"
                 % compat.blender_version_string(),
            icon='BLENDER')


# ----------------------------------------------------------------------
# Small text helpers (Blender labels cannot wrap on their own)
# ----------------------------------------------------------------------
def _truncate(text, width):
    return text if len(text) <= width else text[:width]


def _wrap_rest(text, width, max_lines=3):
    return _wrap_all(text, width, max_lines, skip_first=True)


def _wrap_all(text, width, max_lines=4, skip_first=False):
    words = text.split()
    lines, current = [], ""
    for word in words:
        if len(current) + len(word) + 1 > width and current:
            lines.append(current)
            current = word
        else:
            current = (current + " " + word).strip()
    if current:
        lines.append(current)
    if skip_first:
        lines = lines[1:]
    return lines[:max_lines]


_CLASSES = (
    AUTOBAKE_UL_custom_passes,
    AUTOBAKE_PT_main,
    AUTOBAKE_PT_passes,
    AUTOBAKE_PT_output,
    AUTOBAKE_PT_bake_options,
    AUTOBAKE_PT_uv,
    AUTOBAKE_PT_materials,
    AUTOBAKE_PT_export,
    AUTOBAKE_PT_advanced,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
