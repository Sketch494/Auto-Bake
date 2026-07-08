# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender version compatibility layer.

Auto Bake supports Blender 3.6 LTS through the latest stable release.  All
version-dependent API access is funneled through this module so the rest of
the code base can stay clean.  The main differences handled here:

* Principled BSDF input sockets were renamed in Blender 4.0
  (e.g. "Specular" -> "Specular IOR Level", "Emission" -> "Emission Color").
* ``UILayout.progress`` only exists in Blender 4.0+.
* UV packing / material blend settings gained or lost parameters over time.
* Cycles GPU device configuration.
"""

import bpy

# Blender version as a comparable tuple, e.g. (3, 6, 23).
BLENDER_VERSION = bpy.app.version

IS_BLENDER_4 = BLENDER_VERSION >= (4, 0, 0)
IS_BLENDER_42 = BLENDER_VERSION >= (4, 2, 0)
IS_BLENDER_5 = BLENDER_VERSION >= (5, 0, 0)


def blender_version_string():
    """Return the running Blender version as a printable string."""
    return ".".join(str(v) for v in BLENDER_VERSION)


# ---------------------------------------------------------------------------
# Principled BSDF socket names
# ---------------------------------------------------------------------------
# Canonical name (as used internally by Auto Bake) -> candidate socket names,
# ordered from newest to oldest Blender naming.  ``find_input`` tries them all,
# so user supplied names from either era keep working.
_SOCKET_CANDIDATES = {
    "Base Color": ("Base Color",),
    "Metallic": ("Metallic",),
    "Roughness": ("Roughness",),
    "Alpha": ("Alpha",),
    "Normal": ("Normal",),
    "Specular": ("Specular IOR Level", "Specular"),
    "Emission Color": ("Emission Color", "Emission"),
    "Emission Strength": ("Emission Strength",),
    "Transmission": ("Transmission Weight", "Transmission"),
    "Sheen": ("Sheen Weight", "Sheen"),
    "Coat": ("Coat Weight", "Clearcoat"),
    "Subsurface": ("Subsurface Weight", "Subsurface"),
}

# Reverse lookup: any known alias -> canonical name.
_ALIAS_TO_CANONICAL = {}
for _canonical, _aliases in _SOCKET_CANDIDATES.items():
    _ALIAS_TO_CANONICAL[_canonical] = _canonical
    for _a in _aliases:
        _ALIAS_TO_CANONICAL[_a] = _canonical


def find_input(node, name):
    """Find an input socket on ``node`` by name, tolerant of version renames.

    ``name`` may be the canonical Auto Bake name, the modern (4.x) name or the
    legacy (3.x) name.  Returns the socket or ``None`` when the node simply
    does not have it (e.g. a custom node group).
    """
    if node is None:
        return None
    # Direct hit first - covers custom node groups with arbitrary sockets.
    sock = node.inputs.get(name)
    if sock is not None:
        return sock
    canonical = _ALIAS_TO_CANONICAL.get(name)
    if canonical:
        for candidate in _SOCKET_CANDIDATES[canonical]:
            sock = node.inputs.get(candidate)
            if sock is not None:
                return sock
    return None


def get_output_node(node_tree):
    """Return the active Material Output node (or any output as fallback)."""
    active = None
    for node in node_tree.nodes:
        if node.type == 'OUTPUT_MATERIAL':
            if node.is_active_output:
                return node
            if active is None:
                active = node
    return active


def get_principled(node_tree):
    """Return the 'best' Principled BSDF node of a node tree, or ``None``.

    Prefers the node actually feeding the Material Output surface socket so
    that decorative/unused nodes do not confuse channel extraction.
    """
    output = get_output_node(node_tree)
    if output is not None:
        surface = output.inputs.get("Surface")
        if surface and surface.is_linked:
            visited = set()
            stack = [surface.links[0].from_node]
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                if node.type == 'BSDF_PRINCIPLED':
                    return node
                # Walk upstream through simple pass-through nodes
                # (mix shader, add shader, group) looking for a Principled.
                for sock in node.inputs:
                    for link in sock.links:
                        stack.append(link.from_node)
    for node in node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node
    return None


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------
def draw_progress(layout, runtime, factor, text=""):
    """Draw a progress bar that works on every supported Blender version.

    Blender 4.0 introduced ``UILayout.progress``.  On 3.6 we fall back to a
    slider-styled percentage property which reads almost identically.
    """
    if hasattr(layout, "progress"):
        layout.progress(factor=max(0.0, min(1.0, factor)), type='BAR', text=text)
    else:  # Blender 3.6 fallback
        row = layout.row(align=True)
        row.enabled = False
        row.prop(runtime, "progress", text=text, slider=True)


# ---------------------------------------------------------------------------
# Operators with changing signatures
# ---------------------------------------------------------------------------
def pack_islands(margin=0.02, rotate=True):
    """Call ``uv.pack_islands`` with parameters valid for this Blender."""
    try:
        return bpy.ops.uv.pack_islands(rotate=rotate, margin=margin)
    except TypeError:
        # Very old/new signature - fall back to the lowest common denominator.
        return bpy.ops.uv.pack_islands(margin=margin)


def smart_uv_project(angle_limit_radians, island_margin):
    """Call ``uv.smart_project`` (stable signature since 2.91)."""
    return bpy.ops.uv.smart_project(
        angle_limit=angle_limit_radians,
        island_margin=island_margin,
        correct_aspect=True,
        scale_to_bounds=False,
    )


def set_material_transparency(mat):
    """Enable alpha blending on a material across EEVEE generations."""
    # Legacy EEVEE (<= 4.1) and compatibility attribute in newer versions.
    if hasattr(mat, "blend_method"):
        try:
            mat.blend_method = 'HASHED'
        except TypeError:
            pass
    if hasattr(mat, "shadow_method"):
        try:
            mat.shadow_method = 'HASHED'
        except TypeError:
            pass
    # EEVEE Next (4.2+).
    if hasattr(mat, "surface_render_method"):
        try:
            mat.surface_render_method = 'DITHERED'
        except TypeError:
            pass


# ---------------------------------------------------------------------------
# Cycles device configuration
# ---------------------------------------------------------------------------
_GPU_BACKENDS = ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL')


def configure_cycles_device(scene, preference):
    """Configure Cycles for CPU or GPU rendering.

    ``preference`` is one of ``'AUTO'``, ``'GPU'`` or ``'CPU'``.
    Returns a tuple ``(device_used, message)`` where ``device_used`` is
    ``'GPU'`` or ``'CPU'``.  Never raises: when no GPU is available the
    function silently falls back to CPU and reports it in ``message``.
    """
    if preference == 'CPU':
        scene.cycles.device = 'CPU'
        return 'CPU', "Using CPU (by preference)"

    try:
        cycles_prefs = bpy.context.preferences.addons["cycles"].preferences
    except (KeyError, AttributeError):
        scene.cycles.device = 'CPU'
        return 'CPU', "Cycles preferences unavailable - using CPU"

    for backend in _GPU_BACKENDS:
        try:
            cycles_prefs.compute_device_type = backend
        except TypeError:
            continue
        try:
            devices = cycles_prefs.get_devices_for_type(backend)
        except (AttributeError, ValueError):
            try:
                cycles_prefs.get_devices()
                devices = [d for d in cycles_prefs.devices if d.type == backend]
            except Exception:
                devices = []
        gpu_found = False
        for device in devices:
            device.use = True
            gpu_found = True
        if gpu_found:
            scene.cycles.device = 'GPU'
            return 'GPU', "Using GPU (%s)" % backend

    # Nothing usable - back to CPU.
    try:
        cycles_prefs.compute_device_type = 'NONE'
    except TypeError:
        pass
    scene.cycles.device = 'CPU'
    if preference == 'GPU':
        return 'CPU', "No compatible GPU found - falling back to CPU"
    return 'CPU', "Using CPU"


def supports_bake_denoising(scene):
    """Whether this build exposes denoise settings we can use for baking."""
    return hasattr(scene.cycles, "use_denoising")
