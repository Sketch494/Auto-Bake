# SPDX-License-Identifier: GPL-3.0-or-later
"""Bake pass definitions.

Auto Bake supports two baking strategies:

``EMIT_TRICK``
    The material's surface output is temporarily replaced with an Emission
    shader wired to the channel being captured (e.g. the node graph feeding
    the Principled "Roughness" input).  A 1-sample ``EMIT`` bake then writes
    the raw channel value into the atlas.  This is fast, noise free and,
    unlike Cycles' built-in DIFFUSE pass, is not affected by metallic values
    swallowing the base color.

``NATIVE``
    Cycles' own bake types are used where they are the right tool:
    NORMAL (tangent space normals), AO (needs light transport) and COMBINED.

Each :class:`PassDef` carries everything the engine, image creation and
material builder need to know about one pass.
"""


class PassDef(object):
    """Static description of a single bake pass."""

    __slots__ = (
        "ident", "label", "icon", "strategy", "bake_type", "channel",
        "colorspace", "fill_color", "use_float", "suffix", "invert",
        "source", "noisy",
    )

    def __init__(self, ident, label, icon, strategy, bake_type=None,
                 channel=None, colorspace='Non-Color',
                 fill_color=(0.0, 0.0, 0.0, 1.0), use_float=False,
                 suffix=None, invert=False, source='PRINCIPLED', noisy=False):
        self.ident = ident            # settings property is "use_<ident>"
        self.label = label            # UI / progress label
        self.icon = icon              # UI icon name
        self.strategy = strategy      # 'EMIT_TRICK' or 'NATIVE'
        self.bake_type = bake_type or 'EMIT'  # cycles bake type for NATIVE
        self.channel = channel        # canonical Principled input name
        self.colorspace = colorspace  # image colorspace
        self.fill_color = fill_color  # background fill of the atlas
        self.use_float = use_float    # 32-bit float image buffer
        self.suffix = suffix or label.replace(" ", "")
        self.invert = invert          # invert the channel (glossiness)
        self.source = source          # 'PRINCIPLED' | 'HEIGHT' | 'DISPLACEMENT'
        self.noisy = noisy            # needs real sampling + denoising


# Declaration order == bake order == UI order.
BUILTIN_PASSES = (
    PassDef("basecolor", "Base Color", 'SHADING_TEXTURE', 'EMIT_TRICK',
            channel="Base Color", colorspace='sRGB',
            fill_color=(0.0, 0.0, 0.0, 1.0), suffix="BaseColor"),
    PassDef("normal", "Normal", 'NORMALS_FACE', 'NATIVE', bake_type='NORMAL',
            fill_color=(0.5, 0.5, 1.0, 1.0), use_float=True, suffix="Normal"),
    PassDef("roughness", "Roughness", 'MOD_SMOOTH', 'EMIT_TRICK',
            channel="Roughness", fill_color=(0.5, 0.5, 0.5, 1.0),
            suffix="Roughness"),
    PassDef("metallic", "Metallic", 'MATERIAL', 'EMIT_TRICK',
            channel="Metallic", suffix="Metallic"),
    PassDef("ao", "Ambient Occlusion", 'SHADING_RENDERED', 'NATIVE',
            bake_type='AO', fill_color=(1.0, 1.0, 1.0, 1.0), suffix="AO",
            noisy=True),
    PassDef("emission", "Emission", 'LIGHT', 'EMIT_TRICK',
            channel="Emission Color", colorspace='sRGB', suffix="Emission"),
    PassDef("alpha", "Alpha", 'IMAGE_ALPHA', 'EMIT_TRICK', channel="Alpha",
            fill_color=(1.0, 1.0, 1.0, 1.0), suffix="Alpha"),
    PassDef("specular", "Specular", 'NODE_MATERIAL', 'EMIT_TRICK',
            channel="Specular", fill_color=(0.5, 0.5, 0.5, 1.0),
            suffix="Specular"),
    PassDef("glossiness", "Glossiness", 'SHADING_SOLID', 'EMIT_TRICK',
            channel="Roughness", fill_color=(0.5, 0.5, 0.5, 1.0),
            suffix="Glossiness", invert=True),
    PassDef("height", "Height", 'IMAGE_ZDEPTH', 'EMIT_TRICK',
            channel=None, fill_color=(0.5, 0.5, 0.5, 1.0), use_float=True,
            suffix="Height", source='HEIGHT'),
    PassDef("displacement", "Displacement", 'MOD_DISPLACE', 'EMIT_TRICK',
            channel=None, fill_color=(0.0, 0.0, 0.0, 1.0), use_float=True,
            suffix="Displacement", source='DISPLACEMENT'),
    PassDef("combined", "Combined", 'RENDER_STILL', 'NATIVE',
            bake_type='COMBINED', colorspace='sRGB', suffix="Combined",
            noisy=True),
)

PASS_BY_ID = {p.ident: p for p in BUILTIN_PASSES}

# Neutral channel defaults used when a material has no Principled BSDF (or the
# requested socket simply does not exist on it).
NEUTRAL_DEFAULTS = {
    "Base Color": (0.8, 0.8, 0.8, 1.0),
    "Roughness": (0.5, 0.5, 0.5, 1.0),
    "Metallic": (0.0, 0.0, 0.0, 1.0),
    "Alpha": (1.0, 1.0, 1.0, 1.0),
    "Specular": (0.5, 0.5, 0.5, 1.0),
    "Emission Color": (0.0, 0.0, 0.0, 1.0),
}


def make_custom_pass(item):
    """Build a :class:`PassDef` from a custom pass collection item."""
    safe_suffix = "".join(
        c for c in item.name.title().replace(" ", "") if c.isalnum()
    ) or "Custom"
    return PassDef(
        "custom:%s" % item.name,
        item.name or "Custom",
        'PLUS',
        'EMIT_TRICK',
        channel=item.socket_name or "Base Color",
        colorspace='Non-Color' if item.non_color else 'sRGB',
        fill_color=(0.0, 0.0, 0.0, 1.0),
        suffix=safe_suffix,
    )


def enabled_passes(settings):
    """Return the ordered list of PassDefs enabled in ``settings``."""
    result = [
        p for p in BUILTIN_PASSES
        if getattr(settings, "use_%s" % p.ident, False)
    ]
    for item in settings.custom_passes:
        if item.enabled:
            result.append(make_custom_pass(item))
    return result
