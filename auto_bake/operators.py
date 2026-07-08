# SPDX-License-Identifier: GPL-3.0-or-later
"""Operators: the modal bake driver, confirmation dialogs and utilities.

The bake operator follows Blender's modal-timer pattern: every timer tick
executes exactly one task of the :class:`~.bake_core.BakeJob` state machine.
Status text is published one tick *before* the task runs so the UI gets a
redraw in between - the progress bar and messages stay live even though the
individual Cycles bake calls are blocking.
"""

import os
import time

import bpy

from . import bake_core, exporters, images, log_utils, passes, prefs, zip_export
from .errors import AutoBakeError


def _runtime(context):
    return context.window_manager.auto_bake_runtime


def _redraw_3d_views(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _predict_conflicts(context, settings):
    """List output files that already exist (for the overwrite dialog)."""
    folder = bpy.path.abspath(settings.export_folder)
    conflicts = []
    if settings.export_textures:
        tex_folder = os.path.join(folder, "textures") \
            if settings.use_subfolders else folder
        extension = images.FORMAT_EXTENSIONS[settings.image_format]
        for pass_def in passes.enabled_passes(settings):
            path = os.path.join(tex_folder, "%s_%s%s" % (
                settings.file_name, pass_def.suffix, extension))
            if os.path.exists(path):
                conflicts.append(os.path.basename(path))
    model_folder = os.path.join(folder, "models") \
        if settings.use_subfolders else folder
    for enabled, ext in (
            (settings.export_fbx, ".fbx"), (settings.export_obj, ".obj"),
            (settings.export_gltf, ".glb"), (settings.export_blend, ".blend")):
        if enabled:
            path = os.path.join(model_folder, settings.file_name + ext)
            if os.path.exists(path):
                conflicts.append(os.path.basename(path))
    return conflicts


class AUTOBAKE_OT_bake(bpy.types.Operator):
    """Bake the enabled maps into texture atlases and export them"""

    bl_idname = "autobake.bake"
    bl_label = "Auto Bake"
    bl_description = (
        "Bake all enabled maps for the chosen objects into texture atlases, "
        "then save, export and package them"
    )
    bl_options = {'REGISTER'}

    overwrite_choice: bpy.props.EnumProperty(
        name="Existing Files",
        description="The destination folder already contains files with "
                    "these names. How would you like to proceed?",
        items=(
            ('OVERWRITE', "Overwrite", "Replace the existing files"),
            ('RENAME', "Rename Automatically",
             "Keep existing files, save new ones with a numeric suffix"),
            ('CANCEL', "Cancel", "Do not bake"),
        ),
        default='OVERWRITE',
        options={'SKIP_SAVE'},
    )
    sync: bpy.props.BoolProperty(
        name="Synchronous",
        description="Run the whole bake in one blocking call (scripts/tests)",
        default=False,
        options={'SKIP_SAVE', 'HIDDEN'},
    )

    _timer = None
    _job = None
    _pending_label = None
    _esc_armed_until = 0.0

    @classmethod
    def poll(cls, context):
        return not context.window_manager.auto_bake_runtime.running

    # -- Confirmation dialog -------------------------------------------
    def invoke(self, context, _event):
        settings = context.scene.auto_bake
        targets, _sources = bake_core.collect_targets(context, settings)
        if not targets:
            error = bake_core.no_targets_error(settings.bake_scope)
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        if not passes.enabled_passes(settings):
            self.report(
                {'ERROR'},
                "No bake maps are enabled. Enable at least one in the "
                "Bake Maps section.")
            return {'CANCELLED'}

        self._dialog_targets = len(targets)
        self._dialog_passes = len(passes.enabled_passes(settings))
        self._dialog_conflicts = _predict_conflicts(context, settings)
        return context.window_manager.invoke_props_dialog(self, width=430)

    def draw(self, context):
        settings = context.scene.auto_bake
        layout = self.layout
        col = layout.column()
        col.label(
            text="Auto Bake is about to bake %d map(s) for %d object(s)."
                 % (self._dialog_passes, self._dialog_targets),
            icon='QUESTION')
        col.label(text="This operation may take several minutes.")

        if settings.material_action == 'REPLACE':
            box = col.box()
            box.label(
                text="Existing materials will be replaced with baked "
                     "versions.", icon='ERROR')
            box.label(
                text="This cannot be automatically undone (originals are "
                     "kept with a fake user).")

        if self._dialog_conflicts and settings.overwrite_mode == 'ASK':
            box = col.box()
            box.label(
                text="The destination folder already contains %d of these "
                     "files:" % len(self._dialog_conflicts), icon='FILE')
            for name in self._dialog_conflicts[:5]:
                box.label(text="  " + name)
            if len(self._dialog_conflicts) > 5:
                box.label(
                    text="  ...and %d more"
                         % (len(self._dialog_conflicts) - 5))
            box.prop(self, "overwrite_choice", expand=True)

    # -- Execution ------------------------------------------------------
    def execute(self, context):
        settings = context.scene.auto_bake

        overwrite_resolved = None
        if settings.overwrite_mode == 'ASK':
            conflicts = getattr(self, "_dialog_conflicts", None)
            if conflicts is None:
                conflicts = _predict_conflicts(context, settings)
            if conflicts:
                if self.overwrite_choice == 'CANCEL':
                    self.report({'INFO'}, "Bake cancelled.")
                    return {'CANCELLED'}
                overwrite_resolved = self.overwrite_choice
            else:
                overwrite_resolved = 'OVERWRITE'

        log_utils.clear_log()
        preferences = prefs.get_prefs(context)
        if preferences is not None:
            log_utils.set_level(preferences.log_level)

        try:
            self._job = bake_core.BakeJob(
                context, settings, overwrite_resolved=overwrite_resolved)
        except AutoBakeError as error:
            self._report_error(context, error)
            return {'CANCELLED'}

        runtime = _runtime(context)
        runtime.running = True
        runtime.progress = 0.0
        runtime.status = "Preparing objects..."
        runtime.eta = ""
        runtime.cancel_requested = False
        runtime.last_result = 'NONE'
        runtime.last_message = ""
        runtime.last_suggestion = ""

        # Head-less (tests, render farms, CLI) or explicit request: run the
        # whole job in one call - modal timers need a window/event loop.
        if self.sync or bpy.app.background:
            while self._job.step():
                pass
            return self._finish(context)

        wm = context.window_manager
        wm.progress_begin(0, 100)
        self._pending_label = None
        self._esc_armed_until = 0.0
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        runtime = _runtime(context)

        if event.type == 'ESC' and event.value == 'PRESS':
            now = time.time()
            if now < self._esc_armed_until:
                self._job.request_cancel()
            else:
                self._esc_armed_until = now + 3.0
                runtime.eta = "Press ESC again to cancel"
                _redraw_3d_views(context)
            return {'RUNNING_MODAL'}

        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        if runtime.cancel_requested:
            self._job.request_cancel()

        # Phase 1: publish the upcoming task's label, give the UI one tick
        # to redraw, then (phase 2) actually run the blocking task.
        next_label = self._job.peek_label()
        if self._pending_label != next_label:
            self._pending_label = next_label
            runtime.status = next_label
            if time.time() >= self._esc_armed_until:
                runtime.eta = self._job.eta_text()
            runtime.progress = self._job.progress() * 100.0
            context.window_manager.progress_update(int(runtime.progress))
            _redraw_3d_views(context)
            return {'RUNNING_MODAL'}

        more = self._job.step()
        runtime.progress = self._job.progress() * 100.0
        if not more:
            return self._finish(context)
        return {'RUNNING_MODAL'}

    # -- Completion ------------------------------------------------------
    def _finish(self, context):
        job = self._job
        runtime = _runtime(context)
        wm = context.window_manager

        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
            wm.progress_end()

        runtime.running = False
        runtime.eta = ""
        runtime.cancel_requested = False

        if job.cancelled:
            runtime.last_result = 'CANCELLED'
            runtime.last_message = "Bake cancelled."
            runtime.status = "Bake cancelled."
            runtime.progress = 0.0
            self.report({'WARNING'}, "Auto Bake: cancelled by user.")
            _redraw_3d_views(context)
            return {'CANCELLED'}

        if job.error is not None:
            self._report_error(context, job.error)
            _redraw_3d_views(context)
            return {'CANCELLED'}

        runtime.progress = 100.0
        runtime.last_result = 'SUCCESS'
        summary = "Baked %d map(s) for %d object(s)" % (
            len(job.images) or len(passes.enabled_passes(
                context.scene.auto_bake)), len(job.targets))
        details = []
        if job.saved_files:
            details.append("%d texture(s)" % len(job.saved_files))
        if job.exported_files:
            details.append("%d model file(s)" % len(job.exported_files))
        if job.zip_path:
            details.append(os.path.basename(job.zip_path))
        if details:
            summary += " - " + ", ".join(details)
        if job.warnings:
            summary += " (%d warning(s), see log)" % len(job.warnings)
        runtime.last_message = summary
        runtime.status = "Finished successfully!"
        self.report({'INFO'}, "Auto Bake: " + summary)

        settings = context.scene.auto_bake
        if settings.open_folder_after and not bpy.app.background:
            zip_export.open_folder(bpy.path.abspath(settings.export_folder))
        _redraw_3d_views(context)
        return {'FINISHED'}

    def _report_error(self, context, error):
        runtime = _runtime(context)
        runtime.last_result = 'ERROR'
        runtime.last_message = getattr(error, "message", str(error))
        runtime.last_suggestion = getattr(error, "suggestion", "")
        runtime.status = "Bake failed."
        runtime.progress = 0.0
        self.report({'ERROR'}, str(error))


class AUTOBAKE_OT_cancel(bpy.types.Operator):
    """Cancel the bake operation that is currently running"""

    bl_idname = "autobake.cancel"
    bl_label = "Cancel Bake?"
    bl_description = "Stop the running bake after the current step finishes"

    @classmethod
    def poll(cls, context):
        return context.window_manager.auto_bake_runtime.running

    def invoke(self, context, event):
        # "A bake operation is currently running. Are you sure?"
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        _runtime(context).cancel_requested = True
        self.report({'INFO'}, "Cancelling after the current step...")
        return {'FINISHED'}


class AUTOBAKE_OT_export_only(bpy.types.Operator):
    """Export models / ZIP for the chosen objects without baking"""

    bl_idname = "autobake.export_only"
    bl_label = "Export Without Baking"
    bl_description = (
        "Run only the export and ZIP steps for the chosen objects, using "
        "their current materials"
    )

    @classmethod
    def poll(cls, context):
        return not context.window_manager.auto_bake_runtime.running

    def invoke(self, context, _event):
        return context.window_manager.invoke_confirm(self, _event)

    def execute(self, context):
        settings = context.scene.auto_bake
        targets, _ = bake_core.collect_targets(context, settings)
        if not targets:
            self.report({'ERROR'}, str(
                bake_core.no_targets_error(settings.bake_scope)))
            return {'CANCELLED'}
        try:
            images.ensure_writable_folder(
                bpy.path.abspath(settings.export_folder))
            exported = exporters.export_all(
                context, settings, targets, log_utils.get_logger())
            zip_path = None
            if settings.make_zip:
                zip_path = zip_export.build_zip(
                    context, settings, [], exported, 0, [],
                    log_utils.get_logger())
        except AutoBakeError as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        message = "Exported %d file(s)" % len(exported)
        if zip_path:
            message += " and packaged %s" % os.path.basename(zip_path)
        self.report({'INFO'}, message)
        return {'FINISHED'}


class AUTOBAKE_OT_custom_pass_add(bpy.types.Operator):
    """Add a custom bake pass"""

    bl_idname = "autobake.custom_pass_add"
    bl_label = "Add Custom Pass"

    def execute(self, context):
        settings = context.scene.auto_bake
        item = settings.custom_passes.add()
        item.name = "Custom%d" % len(settings.custom_passes)
        settings.custom_passes_index = len(settings.custom_passes) - 1
        return {'FINISHED'}


class AUTOBAKE_OT_custom_pass_remove(bpy.types.Operator):
    """Remove the selected custom bake pass"""

    bl_idname = "autobake.custom_pass_remove"
    bl_label = "Remove Custom Pass"

    @classmethod
    def poll(cls, context):
        return len(context.scene.auto_bake.custom_passes) > 0

    def execute(self, context):
        settings = context.scene.auto_bake
        index = settings.custom_passes_index
        settings.custom_passes.remove(index)
        settings.custom_passes_index = max(0, index - 1)
        return {'FINISHED'}


class AUTOBAKE_OT_open_folder(bpy.types.Operator):
    """Open the export folder in the system file browser"""

    bl_idname = "autobake.open_folder"
    bl_label = "Open Export Folder"

    def execute(self, context):
        folder = bpy.path.abspath(context.scene.auto_bake.export_folder)
        if not zip_export.open_folder(folder):
            self.report(
                {'WARNING'},
                "Folder does not exist yet: %s" % folder)
            return {'CANCELLED'}
        return {'FINISHED'}


class AUTOBAKE_OT_save_log(bpy.types.Operator):
    """Save the Auto Bake session log to a text file"""

    bl_idname = "autobake.save_log"
    bl_label = "Save Log"

    def execute(self, context):
        settings = context.scene.auto_bake
        folder = bpy.path.abspath(settings.export_folder)
        try:
            images.ensure_writable_folder(folder)
            path = os.path.join(
                folder, "autobake_log_%s.txt" % time.strftime("%Y%m%d_%H%M%S"))
            log_utils.save_log(path)
        except (AutoBakeError, OSError) as error:
            self.report({'ERROR'}, "Could not save the log: %s" % error)
            return {'CANCELLED'}
        self.report({'INFO'}, "Log saved: %s" % path)
        return {'FINISHED'}


class AUTOBAKE_OT_apply_pref_defaults(bpy.types.Operator):
    """Copy the add-on preference defaults into this scene's settings"""

    bl_idname = "autobake.apply_pref_defaults"
    bl_label = "Apply Preference Defaults?"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        preferences = prefs.get_prefs(context)
        if preferences is None:
            self.report({'ERROR'}, "Add-on preferences unavailable.")
            return {'CANCELLED'}
        preferences.apply_to_settings(context.scene.auto_bake)
        self.report({'INFO'}, "Preference defaults applied to this scene.")
        return {'FINISHED'}


class AUTOBAKE_OT_reset_settings(bpy.types.Operator):
    """Reset every Auto Bake setting in this scene to its default"""

    bl_idname = "autobake.reset_settings"
    bl_label = "Reset Auto Bake Settings?"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        settings = context.scene.auto_bake
        for prop in settings.bl_rna.properties:
            if prop.identifier in ("rna_type", "name"):
                continue
            try:
                settings.property_unset(prop.identifier)
            except (AttributeError, TypeError):
                pass
        settings.custom_passes.clear()
        self.report({'INFO'}, "Auto Bake settings reset to defaults.")
        return {'FINISHED'}


_CLASSES = (
    AUTOBAKE_OT_bake,
    AUTOBAKE_OT_cancel,
    AUTOBAKE_OT_export_only,
    AUTOBAKE_OT_custom_pass_add,
    AUTOBAKE_OT_custom_pass_remove,
    AUTOBAKE_OT_open_folder,
    AUTOBAKE_OT_save_log,
    AUTOBAKE_OT_apply_pref_defaults,
    AUTOBAKE_OT_reset_settings,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
