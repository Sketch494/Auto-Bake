# SPDX-License-Identifier: GPL-3.0-or-later
"""The Auto Bake engine.

:class:`BakeJob` is a resumable state machine.  It is *driven* rather than
run: the caller repeatedly invokes :meth:`BakeJob.step` until :attr:`done`.
That design lets the modal operator execute one task per UI timer tick (so
progress, status and estimated time stay live) while head-less scripts and
tests can simply loop synchronously.

Every mutation of the user's scene is registered in a :class:`RestoreStack`
(LIFO undo callables) so that success, failure and cancellation all leave the
file in a sane state.
"""

import os
import time

import bpy

from . import compat, exporters, images, materials, passes, uv_tools, zip_export
from .errors import AutoBakeError, BakeCancelled, bake_failed_error
from .errors import no_targets_error, unsupported_node_warning
from .log_utils import get_logger
from .materials import TEMP_TAG

TEMP_MATERIAL_NAME = "AutoBake_TempMaterial"


class RestoreStack(object):
    """LIFO stack of undo callables - guarantees scene restoration."""

    def __init__(self, log):
        self._items = []
        self._log = log

    def push(self, func, description=""):
        self._items.append((func, description))

    def unwind(self):
        while self._items:
            func, description = self._items.pop()
            try:
                func()
            except Exception as exc:  # never let cleanup break cleanup
                self._log.warning(
                    "Cleanup step failed (%s): %s", description or "?", exc)


class _Task(object):
    __slots__ = ("label", "func", "weight", "is_bake")

    def __init__(self, label, func, weight=1.0, is_bake=False):
        self.label = label
        self.func = func
        self.weight = weight
        self.is_bake = is_bake


class BakeJob(object):
    """A complete bake-and-export run, executed task by task."""

    def __init__(self, context, settings, overwrite_resolved=None):
        self.context = context
        self.settings = settings
        # 'OVERWRITE' or 'RENAME' chosen in the pre-bake dialog when the
        # scene setting is 'ASK'; None means "use the scene setting".
        self.overwrite_resolved = overwrite_resolved
        self.log = get_logger()
        self.restore = RestoreStack(self.log)

        self.targets = []          # objects that get baked
        self.s2a_sources = []      # selected-to-active source objects
        self.all_materials = []    # unique materials across targets
        self.no_principled = set() # material names lacking a Principled BSDF
        self.bake_nodes = {}       # material name -> temp image texture node
        self.images = {}           # pass ident -> bpy Image
        self.saved_files = []      # texture files written to disk
        self.exported_files = []   # model files written to disk
        self.zip_path = None
        self.atlas_size = 0
        self.warnings = []

        self.done = False
        self.cancelled = False
        self.error = None

        self._tasks = []
        self._index = 0
        self._completed_weight = 0.0
        self._bake_times = []
        self._start_time = time.time()

        self._enabled_passes = passes.enabled_passes(settings)
        self._build_initial_tasks()

    # ------------------------------------------------------------------
    # Task plumbing
    # ------------------------------------------------------------------
    def _add(self, label, func, weight=1.0, is_bake=False):
        self._tasks.append(_Task(label, func, weight, is_bake))

    def _build_initial_tasks(self):
        self._add("Preparing objects...", self._task_prepare, 1.0)
        # The remaining tasks depend on the discovered targets, so
        # _task_prepare extends the queue dynamically.

    def peek_label(self):
        if self._index < len(self._tasks):
            return self._tasks[self._index].label
        return "Finished successfully!"

    @property
    def total_weight(self):
        return sum(t.weight for t in self._tasks) or 1.0

    def progress(self):
        return min(1.0, self._completed_weight / self.total_weight)

    def eta_text(self):
        """Human readable estimate of the remaining time."""
        remaining_bake = [t for t in self._tasks[self._index:] if t.is_bake]
        remaining_light = [
            t for t in self._tasks[self._index:] if not t.is_bake]
        if not self._bake_times:
            if not remaining_bake:
                return ""
            return "estimating..."
        mean_bake = sum(self._bake_times) / len(self._bake_times)
        seconds = mean_bake * len(remaining_bake) + 0.2 * len(remaining_light)
        if seconds < 1:
            return ""
        if seconds < 60:
            return "~%ds remaining" % int(round(seconds))
        return "~%dm %02ds remaining" % (int(seconds // 60), int(seconds % 60))

    def request_cancel(self):
        self.cancelled = True

    def step(self):
        """Execute the next task.  Returns True while there is more work."""
        if self.done:
            return False
        if self.cancelled:
            self._finish(BakeCancelled())
            return False
        if self._index >= len(self._tasks):
            self._finish(None)
            return False

        task = self._tasks[self._index]
        self.log.info(task.label)
        started = time.time()
        try:
            task.func()
        except (AutoBakeError, BakeCancelled) as exc:
            self._finish(exc)
            return False
        except Exception as exc:  # unexpected - wrap with a readable message
            self.log.exception("Unexpected error during '%s'", task.label)
            self._finish(AutoBakeError(
                "Unexpected error during '%s': %s" % (task.label, exc),
                "See the console or saved log for details."))
            return False
        duration = time.time() - started
        if task.is_bake:
            self._bake_times.append(duration)
        self._completed_weight += task.weight
        self._index += 1
        if self._index >= len(self._tasks):
            self._finish(None)
            return False
        return True

    def _finish(self, exc):
        """Common termination path for success, error and cancellation."""
        self.done = True
        if isinstance(exc, BakeCancelled):
            self.cancelled = True
            self.log.warning("Bake cancelled by user")
        elif isinstance(exc, AutoBakeError):
            self.error = exc
            self.log.error("Bake failed: %s", exc)
        success = exc is None
        self.log.info("Cleaning temporary data...")
        self.restore.unwind()
        if not success:
            self._remove_bake_images()
        elif self.settings.material_action == 'NONE':
            # Textures are on disk; keep the .blend clean.
            self._remove_bake_images()
        if success:
            elapsed = time.time() - self._start_time
            self.log.info("Finished successfully in %.1fs", elapsed)

    def _remove_bake_images(self):
        for image in self.images.values():
            try:
                if image and image.name in bpy.data.images:
                    bpy.data.images.remove(image)
            except (ReferenceError, RuntimeError):
                pass
        self.images.clear()

    # ------------------------------------------------------------------
    # Task: preparation
    # ------------------------------------------------------------------
    def _task_prepare(self):
        context = self.context
        settings = self.settings
        scene = context.scene

        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        self.targets, self.s2a_sources = collect_targets(context, settings)
        if not self.targets:
            raise no_targets_error(settings.bake_scope)
        if not self._enabled_passes:
            raise AutoBakeError(
                "No bake maps are enabled.",
                "Enable at least one map in the Bake Maps section.")

        self.log.info(
            "Baking %d object(s), %d pass(es)",
            len(self.targets), len(self._enabled_passes))

        # Remember selection & active object.
        previous_selection = [o for o in context.selected_objects]
        previous_active = context.view_layer.objects.active

        def restore_selection():
            bpy.ops.object.select_all(action='DESELECT')
            for obj in previous_selection:
                try:
                    obj.select_set(True)
                except (ReferenceError, RuntimeError):
                    pass
            try:
                context.view_layer.objects.active = previous_active
            except (ReferenceError, RuntimeError):
                pass
        self.restore.push(restore_selection, "selection")

        # Remember and switch render settings.
        saved_render = {
            "engine": scene.render.engine,
            "samples": getattr(scene.cycles, "samples", None),
            "device": getattr(scene.cycles, "device", None),
            "denoise": getattr(scene.cycles, "use_denoising", None),
            "bake_margin": scene.render.bake.margin,
            "bake_clear": scene.render.bake.use_clear,
            "bake_s2a": scene.render.bake.use_selected_to_active,
            "film_transparent": scene.render.film_transparent,
        }
        if hasattr(scene.render.bake, "margin_type"):
            saved_render["margin_type"] = scene.render.bake.margin_type

        def restore_render():
            scene.render.engine = saved_render["engine"]
            if saved_render["samples"] is not None:
                scene.cycles.samples = saved_render["samples"]
            if saved_render["device"] is not None:
                scene.cycles.device = saved_render["device"]
            if saved_render["denoise"] is not None:
                scene.cycles.use_denoising = saved_render["denoise"]
            scene.render.bake.margin = saved_render["bake_margin"]
            scene.render.bake.use_clear = saved_render["bake_clear"]
            scene.render.bake.use_selected_to_active = saved_render["bake_s2a"]
            scene.render.film_transparent = saved_render["film_transparent"]
            if "margin_type" in saved_render:
                scene.render.bake.margin_type = saved_render["margin_type"]
        self.restore.push(restore_render, "render settings")

        scene.render.engine = 'CYCLES'
        device, message = compat.configure_cycles_device(
            scene, settings.device)
        self.log.info(message)
        if device == 'CPU' and settings.device == 'GPU':
            self.warnings.append(message)

        # Output folder must be writable before we spend minutes baking.
        folder = bpy.path.abspath(settings.export_folder)
        if not folder.strip() or folder.strip() in ("/", "\\"):
            raise AutoBakeError(
                "No export folder is set.",
                "Pick a destination folder in the Output section.")
        images.ensure_writable_folder(folder)

        if settings.dedupe_images:
            images.dedupe_image_datablocks(self.log)

        self._add("Checking materials...", self._task_materials_prepare, 0.5)
        for obj in self.targets:
            self._add("Checking UV maps... (%s)" % obj.name,
                      self._make_uv_task(obj), 0.5)
        self._add("Packing UV islands...", self._task_pack_uvs, 1.0)
        self._add("Creating bake images...", self._task_create_images, 0.3)
        self._add("Creating bake nodes...", self._task_create_bake_nodes, 0.3)

        bake_targets = self.targets
        for pass_def in self._enabled_passes:
            self._add("Preparing %s pass..." % pass_def.label,
                      self._make_pass_setup_task(pass_def), 0.3)
            for obj in bake_targets:
                self._add(
                    "Baking %s... (%s)" % (pass_def.label, obj.name),
                    self._make_bake_task(pass_def, obj), 4.0, is_bake=True)
            self._add("Finishing %s pass..." % pass_def.label,
                      self._make_pass_teardown_task(), 0.2)

        if settings.export_textures:
            self._add("Saving textures...", self._task_save_images, 1.0)
        if settings.material_action != 'NONE':
            self._add("Creating materials...", self._task_build_materials, 0.5)
        if (settings.export_blend or settings.export_fbx or
                settings.export_obj or settings.export_gltf):
            self._add("Exporting assets...", self._task_export, 1.5)
        if settings.make_zip:
            self._add("Compressing ZIP...", self._task_zip, 1.0)

    # ------------------------------------------------------------------
    # Task: materials sanity + dedupe
    # ------------------------------------------------------------------
    def _task_materials_prepare(self):
        settings = self.settings
        if settings.merge_duplicate_materials:
            materials.merge_duplicate_materials(self.targets, self.log)

        temp_material = None
        for obj in self.targets:
            # Fill objects/slots that have no material with a temporary one,
            # otherwise Cycles cannot bake them.
            if not obj.material_slots:
                if temp_material is None:
                    temp_material = _get_temp_material()
                obj.data.materials.append(temp_material)
                self.log.info(
                    "Object '%s' has no material - using a temporary neutral "
                    "material", obj.name)
                mesh = obj.data

                def remove_slot(mesh=mesh, mat=temp_material):
                    for i, slot_mat in enumerate(mesh.materials):
                        if slot_mat == mat:
                            mesh.materials.pop(index=i)
                            break
                self.restore.push(remove_slot, "temp material slot")
            else:
                for slot_index, slot in enumerate(obj.material_slots):
                    if slot.material is None:
                        if temp_material is None:
                            temp_material = _get_temp_material()
                        slot.material = temp_material

                        def clear_slot(obj=obj, idx=slot_index):
                            # Only clear the slot when it still holds our
                            # temporary material (REPLACE mode may have put
                            # the baked material there in the meantime).
                            if idx < len(obj.material_slots):
                                current = obj.material_slots[idx].material
                                if current is not None and TEMP_TAG in current:
                                    obj.material_slots[idx].material = None
                        self.restore.push(clear_slot, "empty material slot")

        if temp_material is not None:
            def remove_temp_mat(mat=temp_material):
                if mat.name in bpy.data.materials and mat.users <= 1:
                    bpy.data.materials.remove(mat)
            self.restore.push(remove_temp_mat, "temp material datablock")

        # Collect the unique material set and normalize node usage.
        seen = set()
        for obj in self.targets:
            for slot in obj.material_slots:
                mat = slot.material
                if mat is None or mat.name in seen:
                    continue
                seen.add(mat.name)
                if not mat.use_nodes:
                    mat.use_nodes = True
                    self.log.info(
                        "Enabled nodes on material '%s'", mat.name)
                self.all_materials.append(mat)
                if compat.get_principled(mat.node_tree) is None:
                    self.no_principled.add(mat.name)
                    warning = unsupported_node_warning(mat.name)
                    self.log.warning(warning)
                    self.warnings.append(warning)

    # ------------------------------------------------------------------
    # Task: UVs
    # ------------------------------------------------------------------
    def _make_uv_task(self, obj):
        def task():
            settings = self.settings
            if not uv_tools.has_uvs(obj):
                if not settings.uv_create_missing:
                    raise AutoBakeError(
                        "Object '%s' has no UV map." % obj.name,
                        "Enable 'Create Missing UVs' or unwrap the object "
                        "manually.")
                uv_tools.ensure_uvs(self.context, obj, settings, self.log)
            previous = uv_tools.create_atlas_layer(obj, self.log)
            if self.settings.material_action != 'REPLACE':
                # Original materials stay in use, so give them back their
                # original UV setup once baking is over.
                self.restore.push(
                    lambda o=obj, p=previous: uv_tools.restore_uv_layers(o, p),
                    "uv layers of %s" % obj.name)
        return task

    def _task_pack_uvs(self):
        uv_tools.pack_atlas(self.context, self.targets, self.settings, self.log)

    # ------------------------------------------------------------------
    # Task: images & bake nodes
    # ------------------------------------------------------------------
    def _task_create_images(self):
        settings = self.settings
        size = int(settings.resolution)
        if settings.auto_resize_atlas:
            size = _auto_atlas_size(size, len(self.targets))
            if size != int(settings.resolution):
                self.log.info(
                    "Auto-resized atlas %s -> %d to preserve texel density "
                    "across %d objects",
                    settings.resolution, size, len(self.targets))
        self.atlas_size = size
        for pass_def in self._enabled_passes:
            name = "%s_%s" % (settings.file_name, pass_def.suffix)
            self.images[pass_def.ident] = images.create_bake_image(
                name, size, pass_def)
        self.log.info(
            "Created %d atlas image(s) at %dx%d",
            len(self.images), size, size)

    def _task_create_bake_nodes(self):
        for mat in self.all_materials:
            node_tree = mat.node_tree
            node = node_tree.nodes.new('ShaderNodeTexImage')
            node.name = "AutoBake_BakeTarget"
            node.label = "Auto Bake Target"
            node[TEMP_TAG] = True
            node.location = (-1200, 800)
            self.bake_nodes[mat.name] = node

            def remove_node(nt=node_tree, n=node):
                try:
                    nt.nodes.remove(n)
                except (ReferenceError, RuntimeError):
                    pass
            self.restore.push(remove_node, "bake node in %s" % mat.name)

    # ------------------------------------------------------------------
    # Task: per-pass setup / bake / teardown
    # ------------------------------------------------------------------
    def _make_pass_setup_task(self, pass_def):
        def task():
            scene = self.context.scene
            image = self.images[pass_def.ident]

            # Point every material's bake target node at this pass' atlas
            # and make it the active node (that is where Cycles bakes to).
            for mat in self.all_materials:
                node = self.bake_nodes.get(mat.name)
                if node is None:
                    continue
                node.image = image
                for other in mat.node_tree.nodes:
                    other.select = False
                node.select = True
                mat.node_tree.nodes.active = node

            # Sampling: channel captures are noise free at 1 sample.
            scene.cycles.samples = (
                self.settings.samples if pass_def.noisy else 1)
            if compat.supports_bake_denoising(scene):
                try:
                    scene.cycles.use_denoising = (
                        pass_def.noisy and self.settings.use_denoising)
                except Exception:
                    pass

            if pass_def.strategy == 'EMIT_TRICK':
                self._current_rigs = materials.rig_materials_for_channel(
                    self.all_materials, pass_def, self.no_principled, self.log)
            else:
                self._current_rigs = []
        return task

    def _make_pass_teardown_task(self):
        def task():
            for undo in reversed(getattr(self, "_current_rigs", [])):
                undo()
            self._current_rigs = []
        return task

    def _make_bake_task(self, pass_def, obj):
        def task():
            self._bake_object(pass_def, obj)
        return task

    def _bake_object(self, pass_def, obj):
        context = self.context
        scene = context.scene
        settings = self.settings

        bpy.ops.object.select_all(action='DESELECT')
        use_s2a = bool(settings.use_selected_to_active and self.s2a_sources)
        if use_s2a:
            for source in self.s2a_sources:
                source.select_set(True)
        obj.select_set(True)
        context.view_layer.objects.active = obj

        bake_type = (
            'EMIT' if pass_def.strategy == 'EMIT_TRICK' else pass_def.bake_type)
        scene.render.bake.use_clear = False
        scene.render.bake.margin = settings.bake_margin
        if hasattr(scene.render.bake, "margin_type"):
            scene.render.bake.margin_type = 'EXTEND'

        kwargs = {
            "type": bake_type,
            "margin": settings.bake_margin,
            "use_clear": False,
            "use_selected_to_active": use_s2a,
        }
        if use_s2a:
            kwargs["cage_extrusion"] = settings.cage_extrusion
            kwargs["max_ray_distance"] = settings.max_ray_distance
        if bake_type == 'NORMAL':
            kwargs["normal_space"] = 'TANGENT'

        try:
            result = bpy.ops.object.bake(**kwargs)
        except RuntimeError as exc:
            raise bake_failed_error(pass_def.label, obj.name, str(exc))
        if 'CANCELLED' in result:
            raise bake_failed_error(
                pass_def.label, obj.name, "Bake operator was cancelled")

    # ------------------------------------------------------------------
    # Task: saving / materials / export / zip
    # ------------------------------------------------------------------
    def _texture_folder(self):
        folder = bpy.path.abspath(self.settings.export_folder)
        if self.settings.use_subfolders:
            return os.path.join(folder, "textures")
        return folder

    def _task_save_images(self):
        settings = self.settings
        folder = self._texture_folder()
        extension = images.FORMAT_EXTENSIONS[settings.image_format]
        overwrite = self.overwrite_resolved or settings.overwrite_mode
        if overwrite == 'ASK':
            # The pre-bake dialog resolves ASK; default defensively.
            overwrite = 'RENAME'
        for pass_def in self._enabled_passes:
            image = self.images[pass_def.ident]
            path = images.resolve_output_path(
                folder, settings.file_name, pass_def.suffix, extension,
                overwrite)
            images.save_image(self.context, image, path, settings, self.log)
            self.saved_files.append(path)

    def _task_build_materials(self):
        baked_mat = materials.build_baked_material(
            self.settings, self.images, self._enabled_passes, self.log)
        if self.settings.material_action == 'REPLACE':
            materials.assign_baked_material(
                self.targets, baked_mat, self.log)

    def _task_export(self):
        self.exported_files = exporters.export_all(
            self.context, self.settings, self.targets, self.log)

    def _task_zip(self):
        self.zip_path = zip_export.build_zip(
            self.context, self.settings, self.saved_files,
            self.exported_files, self.atlas_size,
            [p.label for p in self._enabled_passes], self.log)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def collect_targets(context, settings):
    """Return ``(targets, selected_to_active_sources)`` for this bake."""
    log = get_logger()
    if settings.bake_scope == 'SELECTED':
        candidates = list(context.selected_objects)
    else:
        candidates = list(context.scene.objects)

    targets = []
    skipped_hidden = 0
    for obj in candidates:
        if obj.type != 'MESH':
            if settings.bake_scope == 'SELECTED':
                log.info("Skipping non-mesh object '%s'", obj.name)
            continue
        try:
            visible = obj.visible_get()
        except Exception:
            visible = not obj.hide_render
        if not visible:
            skipped_hidden += 1
            if not settings.skip_hidden:
                log.warning(
                    "Skipping hidden object '%s' (hidden objects can never "
                    "be baked)", obj.name)
            continue
        if len(obj.data.polygons) == 0:
            log.warning("Skipping '%s' - it has no faces", obj.name)
            continue
        targets.append(obj)
    if skipped_hidden and settings.skip_hidden:
        log.info("Skipped %d hidden object(s)", skipped_hidden)

    sources = []
    if (settings.use_selected_to_active and
            settings.bake_scope == 'SELECTED' and len(targets) > 1):
        active = context.view_layer.objects.active
        if active in targets:
            sources = [o for o in targets if o != active]
            targets = [active]
            log.info(
                "Selected to Active: baking %d source object(s) onto '%s'",
                len(sources), active.name)
    return targets, sources


def _get_temp_material():
    mat = bpy.data.materials.get(TEMP_MATERIAL_NAME)
    if mat is None:
        mat = bpy.data.materials.new(TEMP_MATERIAL_NAME)
        mat.use_nodes = True
        mat[TEMP_TAG] = True
    return mat


def _auto_atlas_size(base_size, object_count):
    """Grow the atlas so texel density survives many objects sharing it.

    Every 4 objects roughly quarter the area available per object, so the
    resolution doubles.  Hard capped at 8192.
    """
    size = base_size
    budget = 4
    while object_count > budget and size < 8192:
        size *= 2
        budget *= 4
    return min(size, 8192)
