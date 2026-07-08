# SPDX-License-Identifier: GPL-3.0-or-later
"""Material handling.

Two responsibilities live here:

1. **Channel rigging** (:func:`rig_materials_for_channel`): temporarily wire
   the node graph feeding a Principled input straight into an Emission shader
   plugged into the Material Output, so a 1-sample ``EMIT`` bake captures the
   raw channel.  Every modification returns an undo callable.

2. **Baked material creation** (:func:`build_baked_material`): build a clean
   game-ready material from the finished atlases and optionally assign it to
   the baked objects.
"""

import re

import bpy

from . import compat
from .passes import NEUTRAL_DEFAULTS
from .uv_tools import ATLAS_UV_NAME

# Custom-property tag marking every temporary node/datablock Auto Bake makes.
TEMP_TAG = "auto_bake_temp"


# ----------------------------------------------------------------------
# Channel rigging (EMIT trick)
# ----------------------------------------------------------------------
def rig_materials_for_channel(material_list, pass_def, no_principled, log):
    """Rig every material for an EMIT_TRICK pass.

    Returns a list of undo callables (execute in reverse order).
    """
    undos = []
    for mat in material_list:
        undos.extend(_rig_single_material(mat, pass_def, no_principled, log))
    return undos


def _rig_single_material(mat, pass_def, no_principled, log):
    node_tree = mat.node_tree
    undos = []
    temp_nodes = []

    output = compat.get_output_node(node_tree)
    if output is None:
        output = node_tree.nodes.new('ShaderNodeOutputMaterial')
        temp_nodes.append(output)

    emission = node_tree.nodes.new('ShaderNodeEmission')
    emission.label = "Auto Bake %s" % pass_def.label
    emission[TEMP_TAG] = True
    emission.location = (output.location.x - 200, output.location.y - 200)
    temp_nodes.append(emission)

    source_socket, value, extra_nodes = _channel_source(
        node_tree, mat, pass_def, no_principled, log)
    temp_nodes.extend(extra_nodes)

    if source_socket is not None:
        node_tree.links.new(source_socket, emission.inputs["Color"])
    else:
        emission.inputs["Color"].default_value = value
    emission.inputs["Strength"].default_value = 1.0

    # Swap the surface connection over to our temporary emission shader.
    surface = output.inputs["Surface"]
    original_socket = surface.links[0].from_socket if surface.is_linked else None
    node_tree.links.new(emission.outputs["Emission"], surface)

    def undo(nt=node_tree, out=output, orig=original_socket, temps=temp_nodes):
        try:
            surf = out.inputs["Surface"]
            for link in list(surf.links):
                nt.links.remove(link)
            if orig is not None:
                nt.links.new(orig, surf)
        except (ReferenceError, RuntimeError):
            pass
        for node in temps:
            try:
                nt.nodes.remove(node)
            except (ReferenceError, RuntimeError):
                pass

    undos.append(undo)
    return undos


def _channel_source(node_tree, mat, pass_def, no_principled, log):
    """Locate the socket / constant feeding one channel of a material.

    Returns ``(socket_or_None, fallback_value, temp_nodes)``.
    """
    temp_nodes = []

    # --- Height / displacement channels come from the Material Output ----
    if pass_def.source in ('HEIGHT', 'DISPLACEMENT'):
        return _displacement_source(node_tree, pass_def, temp_nodes)

    # --- Regular Principled channels --------------------------------------
    principled = compat.get_principled(node_tree)
    if principled is None:
        value = NEUTRAL_DEFAULTS.get(
            pass_def.channel, (0.0, 0.0, 0.0, 1.0))
        if pass_def.invert:
            value = _invert_color(value)
        return None, value, temp_nodes

    socket = compat.find_input(principled, pass_def.channel)
    if socket is None:
        log.warning(
            "Material '%s' has no '%s' input - baking a neutral default",
            mat.name, pass_def.channel)
        value = NEUTRAL_DEFAULTS.get(pass_def.channel, (0.0, 0.0, 0.0, 1.0))
        if pass_def.invert:
            value = _invert_color(value)
        return None, value, temp_nodes

    if socket.is_linked:
        source = socket.links[0].from_socket
        if pass_def.invert:
            invert = node_tree.nodes.new('ShaderNodeInvert')
            invert[TEMP_TAG] = True
            invert.inputs["Fac"].default_value = 1.0
            node_tree.links.new(source, invert.inputs["Color"])
            temp_nodes.append(invert)
            return invert.outputs["Color"], None, temp_nodes
        return source, None, temp_nodes

    value = _socket_default_as_color(socket)
    if pass_def.invert:
        value = _invert_color(value)
    return None, value, temp_nodes


def _displacement_source(node_tree, pass_def, temp_nodes):
    """Resolve the height (or scaled displacement) feeding Material Output."""
    output = compat.get_output_node(node_tree)
    neutral = (0.5, 0.5, 0.5, 1.0) if pass_def.source == 'HEIGHT' \
        else (0.0, 0.0, 0.0, 1.0)
    if output is None:
        return None, neutral, temp_nodes
    disp_input = output.inputs.get("Displacement")
    if disp_input is None or not disp_input.is_linked:
        return None, neutral, temp_nodes
    disp_node = disp_input.links[0].from_node
    if disp_node.type != 'DISPLACEMENT':
        # Vector displacement or custom setup - bake its raw output.
        return disp_input.links[0].from_socket, None, temp_nodes

    height_input = disp_node.inputs.get("Height")
    scale = disp_node.inputs["Scale"].default_value \
        if "Scale" in disp_node.inputs else 1.0

    if height_input is not None and height_input.is_linked:
        height_socket = height_input.links[0].from_socket
        if pass_def.source == 'DISPLACEMENT' and abs(scale - 1.0) > 1e-6:
            math_node = node_tree.nodes.new('ShaderNodeMath')
            math_node.operation = 'MULTIPLY'
            math_node[TEMP_TAG] = True
            math_node.inputs[1].default_value = scale
            node_tree.links.new(height_socket, math_node.inputs[0])
            temp_nodes.append(math_node)
            return math_node.outputs["Value"], None, temp_nodes
        return height_socket, None, temp_nodes

    height = height_input.default_value if height_input is not None else 0.5
    if pass_def.source == 'DISPLACEMENT':
        height *= scale
    return None, (height, height, height, 1.0), temp_nodes


def _socket_default_as_color(socket):
    """Convert any socket default_value into an RGBA tuple."""
    value = socket.default_value
    try:
        length = len(value)
    except TypeError:
        v = float(value)
        return (v, v, v, 1.0)
    if length >= 4:
        return (value[0], value[1], value[2], value[3])
    if length == 3:
        return (value[0], value[1], value[2], 1.0)
    v = float(value[0])
    return (v, v, v, 1.0)


def _invert_color(color):
    return (1.0 - color[0], 1.0 - color[1], 1.0 - color[2], color[3])


# ----------------------------------------------------------------------
# Baked material creation
# ----------------------------------------------------------------------
def build_baked_material(settings, images_by_pass, enabled_passes, log):
    """Create a clean Principled material wired to the baked atlases."""
    name = "%s_Baked" % settings.file_name
    mat = bpy.data.materials.get(name)
    if mat is not None:
        bpy.data.materials.remove(mat)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    node_tree = mat.node_tree
    node_tree.nodes.clear()

    output = node_tree.nodes.new('ShaderNodeOutputMaterial')
    output.location = (600, 0)
    principled = node_tree.nodes.new('ShaderNodeBsdfPrincipled')
    principled.location = (250, 0)
    node_tree.links.new(
        principled.outputs["BSDF"], output.inputs["Surface"])

    by_ident = {p.ident: p for p in enabled_passes}
    y_position = 600

    def add_image_node(pass_ident, label):
        nonlocal y_position
        image = images_by_pass.get(pass_ident)
        if image is None:
            return None
        node = node_tree.nodes.new('ShaderNodeTexImage')
        node.image = image
        node.label = label
        node.location = (-500, y_position)
        y_position -= 320
        return node

    # Base color (optionally multiplied with AO).
    base_node = add_image_node("basecolor", "Base Color")
    ao_node = add_image_node("ao", "Ambient Occlusion") \
        if "ao" in by_ident else None
    base_input = compat.find_input(principled, "Base Color")
    if base_node is not None and base_input is not None:
        if ao_node is not None and settings.ao_multiply:
            mix = node_tree.nodes.new('ShaderNodeMixRGB')
            mix.blend_type = 'MULTIPLY'
            mix.inputs["Fac"].default_value = 1.0
            mix.location = (-150, 500)
            node_tree.links.new(base_node.outputs["Color"], mix.inputs["Color1"])
            node_tree.links.new(ao_node.outputs["Color"], mix.inputs["Color2"])
            node_tree.links.new(mix.outputs["Color"], base_input)
        else:
            node_tree.links.new(base_node.outputs["Color"], base_input)

    # Straightforward scalar/color channels.
    simple_channels = (
        ("roughness", "Roughness"),
        ("metallic", "Metallic"),
        ("specular", "Specular"),
        ("alpha", "Alpha"),
    )
    for ident, channel in simple_channels:
        if ident not in by_ident:
            continue
        node = add_image_node(ident, channel)
        target = compat.find_input(principled, channel)
        if node is not None and target is not None:
            node_tree.links.new(node.outputs["Color"], target)

    # Glossiness (only when roughness itself was not baked).
    if "glossiness" in by_ident and "roughness" not in by_ident:
        node = add_image_node("glossiness", "Glossiness")
        target = compat.find_input(principled, "Roughness")
        if node is not None and target is not None:
            invert = node_tree.nodes.new('ShaderNodeInvert')
            invert.location = (-150, y_position + 320)
            node_tree.links.new(node.outputs["Color"], invert.inputs["Color"])
            node_tree.links.new(invert.outputs["Color"], target)

    # Emission.
    if "emission" in by_ident:
        node = add_image_node("emission", "Emission")
        target = compat.find_input(principled, "Emission Color")
        if node is not None and target is not None:
            node_tree.links.new(node.outputs["Color"], target)
            strength = compat.find_input(principled, "Emission Strength")
            if strength is not None:
                strength.default_value = 1.0

    # Normal map.
    if "normal" in by_ident:
        node = add_image_node("normal", "Normal")
        target = compat.find_input(principled, "Normal")
        if node is not None and target is not None:
            normal_map = node_tree.nodes.new('ShaderNodeNormalMap')
            normal_map.location = (-150, y_position + 320)
            normal_map.uv_map = ATLAS_UV_NAME
            node_tree.links.new(
                node.outputs["Color"], normal_map.inputs["Color"])
            node_tree.links.new(normal_map.outputs["Normal"], target)

    # Height / displacement into the material output.
    disp_ident = "displacement" if "displacement" in by_ident else (
        "height" if "height" in by_ident else None)
    if disp_ident:
        node = add_image_node(disp_ident, "Displacement")
        if node is not None:
            disp = node_tree.nodes.new('ShaderNodeDisplacement')
            disp.location = (350, -300)
            if disp_ident == "height":
                disp.inputs["Midlevel"].default_value = 0.5
            node_tree.links.new(node.outputs["Color"], disp.inputs["Height"])
            node_tree.links.new(
                disp.outputs["Displacement"], output.inputs["Displacement"])

    # Transparency support.
    if "alpha" in by_ident:
        compat.set_material_transparency(mat)

    mat.use_fake_user = True
    log.info("Created baked material '%s'", mat.name)
    return mat


def assign_baked_material(targets, baked_material, log):
    """Replace every material slot on the targets with the baked material.

    Original materials are protected with a fake user so nothing is lost.
    """
    preserved = set()
    for obj in targets:
        for slot in obj.material_slots:
            if slot.material is not None and \
                    slot.material.name != baked_material.name and \
                    TEMP_TAG not in slot.material:
                slot.material.use_fake_user = True
                preserved.add(slot.material.name)
        obj.data.materials.clear()
        obj.data.materials.append(baked_material)
    if preserved:
        log.info(
            "Replaced materials on %d object(s); %d original material(s) "
            "kept with a fake user: %s",
            len(targets), len(preserved), ", ".join(sorted(preserved)))


# ----------------------------------------------------------------------
# Duplicate material merging
# ----------------------------------------------------------------------
_DUPLICATE_SUFFIX = re.compile(r"\.\d{3}$")


def merge_duplicate_materials(targets, log):
    """Merge ``Material.001`` style duplicates used by the targets.

    Only merges when the base material exists and both share the same node
    and link counts - a conservative equality proxy that avoids destroying
    genuinely different materials.
    """
    merged = 0
    for obj in targets:
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or not _DUPLICATE_SUFFIX.search(mat.name):
                continue
            base_name = _DUPLICATE_SUFFIX.sub("", mat.name)
            base = bpy.data.materials.get(base_name)
            if base is None or base == mat:
                continue
            if not _materials_look_equal(mat, base):
                continue
            slot.material = base
            merged += 1
            log.info(
                "Merged duplicate material '%s' -> '%s' on '%s'",
                mat.name, base_name, obj.name)
    if merged:
        log.info("Merged %d duplicate material assignment(s)", merged)
    return merged


def _materials_look_equal(a, b):
    if a.use_nodes != b.use_nodes:
        return False
    if not a.use_nodes:
        return True
    return (len(a.node_tree.nodes) == len(b.node_tree.nodes) and
            len(a.node_tree.links) == len(b.node_tree.links))
