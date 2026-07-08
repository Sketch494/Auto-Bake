# SPDX-License-Identifier: GPL-3.0-or-later
"""Property groups for Auto Bake.

* :class:`AB_CustomPass`    - one user defined bake channel.
* :class:`AB_Settings`      - per-scene bake configuration (saved in .blend).
* :class:`AB_RuntimeState`  - transient job state on the WindowManager
                              (progress bar, status text, cancellation flag);
                              never written into the .blend file.
"""

import bpy
from bpy.props import (
    BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
    IntProperty, PointerProperty, StringProperty,
)

RESOLUTION_ITEMS = (
    ('512', "512", "512 x 512 pixels"),
    ('1024', "1024", "1024 x 1024 pixels"),
    ('2048', "2048", "2048 x 2048 pixels"),
    ('4096', "4096", "4096 x 4096 pixels"),
    ('8192', "8192", "8192 x 8192 pixels"),
)

FORMAT_ITEMS = (
    ('PNG', "PNG", "Portable Network Graphics (lossless, compressed)"),
    ('TARGA', "TGA", "Truevision Targa"),
    ('TIFF', "TIFF", "Tagged Image File Format"),
    ('OPEN_EXR', "OpenEXR", "High dynamic range OpenEXR"),
)

DEPTH_ITEMS = (
    ('8', "8-bit", "8 bits per channel"),
    ('16', "16-bit", "16 bits per channel (PNG/TIFF/EXR half float)"),
    ('32', "32-bit", "32 bits per channel (OpenEXR full float only)"),
)

DEVICE_ITEMS = (
    ('AUTO', "Auto", "Use the GPU when one is available, otherwise the CPU"),
    ('GPU', "GPU", "Force GPU compute (falls back to CPU when unavailable)"),
    ('CPU', "CPU", "Force CPU baking"),
)

OVERWRITE_ITEMS = (
    ('OVERWRITE', "Overwrite", "Replace files that already exist"),
    ('RENAME', "Rename Automatically",
     "Keep existing files and append a numeric suffix to new ones"),
    ('ASK', "Ask", "Show a confirmation dialog when name conflicts exist"),
)


class AB_CustomPass(bpy.types.PropertyGroup):
    """A user defined bake pass captured from a Principled BSDF input."""

    name: StringProperty(
        name="Name",
        description="Pass name, used as the texture filename suffix",
        default="Custom",
    )
    socket_name: StringProperty(
        name="Socket",
        description=(
            "Principled BSDF input to capture (e.g. 'Sheen Weight', "
            "'Transmission Weight', 'Subsurface Weight')"
        ),
        default="Sheen",
    )
    non_color: BoolProperty(
        name="Non-Color Data",
        description="Save this pass with Non-Color colorspace (data maps)",
        default=True,
    )
    enabled: BoolProperty(
        name="Enabled",
        description="Include this custom pass in the bake",
        default=True,
    )


class AB_Settings(bpy.types.PropertyGroup):
    """All per-scene Auto Bake settings (stored in the .blend file)."""

    # -- Scope ---------------------------------------------------------
    bake_scope: EnumProperty(
        name="Bake",
        description="Which objects to bake",
        items=(
            ('SELECTED', "Selected Objects",
             "Bake only the currently selected mesh objects"),
            ('SCENE', "Entire Scene",
             "Bake every visible mesh object in the scene"),
        ),
        default='SELECTED',
    )

    # -- Bake maps -----------------------------------------------------
    use_basecolor: BoolProperty(
        name="Base Color", default=True,
        description="Bake the albedo / base color channel")
    use_normal: BoolProperty(
        name="Normal", default=True,
        description="Bake tangent space normal maps")
    use_roughness: BoolProperty(
        name="Roughness", default=True,
        description="Bake the roughness channel")
    use_metallic: BoolProperty(
        name="Metallic", default=False,
        description="Bake the metallic channel")
    use_ao: BoolProperty(
        name="Ambient Occlusion", default=False,
        description="Bake ambient occlusion (uses render samples)")
    use_emission: BoolProperty(
        name="Emission", default=False,
        description="Bake the emission color channel")
    use_alpha: BoolProperty(
        name="Alpha", default=False,
        description="Bake the alpha / opacity channel")
    use_specular: BoolProperty(
        name="Specular", default=False,
        description="Bake the specular level channel")
    use_glossiness: BoolProperty(
        name="Glossiness", default=False,
        description="Bake inverted roughness for glossiness workflows")
    use_height: BoolProperty(
        name="Height", default=False,
        description="Bake the height input of the material displacement")
    use_displacement: BoolProperty(
        name="Displacement", default=False,
        description="Bake displacement (height multiplied by scale)")
    use_combined: BoolProperty(
        name="Combined", default=False,
        description="Bake a fully lit combined render (uses render samples)")
    custom_passes: CollectionProperty(type=AB_CustomPass)
    custom_passes_index: IntProperty(default=0)

    # -- Output --------------------------------------------------------
    export_folder: StringProperty(
        name="Export Folder",
        description="Destination folder for baked textures and exports",
        subtype='DIR_PATH',
        default="//AutoBake/",
    )
    file_name: StringProperty(
        name="File Name",
        description="Base name for baked textures (suffix added per pass)",
        default="AutoBake",
    )
    resolution: EnumProperty(
        name="Resolution",
        description="Texture atlas resolution in pixels",
        items=RESOLUTION_ITEMS, default='2048',
    )
    image_format: EnumProperty(
        name="Format", description="Image file format for baked textures",
        items=FORMAT_ITEMS, default='PNG',
    )
    color_depth: EnumProperty(
        name="Color Depth",
        description=(
            "Bits per channel (clamped to what the chosen format supports)"
        ),
        items=DEPTH_ITEMS, default='8',
    )
    compression: IntProperty(
        name="Compression",
        description="PNG/EXR compression amount",
        min=0, max=100, default=15, subtype='PERCENTAGE',
    )
    overwrite_mode: EnumProperty(
        name="Existing Files",
        description="What to do when output files already exist",
        items=OVERWRITE_ITEMS, default='ASK',
    )
    use_subfolders: BoolProperty(
        name="Organize Subfolders",
        description="Save into textures/ and models/ subfolders",
        default=True,
    )

    # -- UV & atlas ----------------------------------------------------
    uv_create_missing: BoolProperty(
        name="Create Missing UVs",
        description="Smart UV Project any object that has no UV map",
        default=True,
    )
    uv_smart_angle: FloatProperty(
        name="Smart UV Angle",
        description="Angle limit for Smart UV Project (degrees)",
        min=1.0, max=89.0, default=66.0,
    )
    uv_island_margin: FloatProperty(
        name="Island Margin",
        description="Margin between packed UV islands (UV units)",
        min=0.0, max=0.2, default=0.02, precision=3,
    )
    uv_preserve_density: BoolProperty(
        name="Preserve Texel Density",
        description=(
            "Average island scale across all objects before packing so every "
            "surface gets uniform texture resolution"
        ),
        default=True,
    )
    uv_rotate_islands: BoolProperty(
        name="Rotate Islands",
        description="Allow rotating islands while packing for tighter fits",
        default=True,
    )
    auto_resize_atlas: BoolProperty(
        name="Auto Resize Atlas",
        description=(
            "Automatically increase the atlas resolution (up to 8192) when "
            "many objects share one atlas, to preserve texel density"
        ),
        default=True,
    )

    # -- Bake options --------------------------------------------------
    samples: IntProperty(
        name="Samples",
        description=(
            "Cycles samples for lighting passes (AO / Combined). Channel "
            "passes always use 1 sample because they are noise free"
        ),
        min=1, max=4096, default=32,
    )
    bake_margin: IntProperty(
        name="Margin",
        description="Bake margin in pixels (bleed around UV islands)",
        min=0, max=256, default=16,
    )
    use_selected_to_active: BoolProperty(
        name="Selected to Active",
        description=(
            "Bake detail from the selected (high poly) objects onto the "
            "active (low poly) object"
        ),
        default=False,
    )
    max_ray_distance: FloatProperty(
        name="Max Ray Distance",
        description="Maximum ray distance for selected-to-active baking",
        min=0.0, default=0.0, subtype='DISTANCE',
    )
    cage_extrusion: FloatProperty(
        name="Cage Extrusion",
        description="Inflate the active object for selected-to-active rays",
        min=0.0, default=0.02, subtype='DISTANCE',
    )
    device: EnumProperty(
        name="Device", description="Compute device used for baking",
        items=DEVICE_ITEMS, default='AUTO',
    )
    use_denoising: BoolProperty(
        name="Denoise",
        description="Denoise lighting passes (AO / Combined) when supported",
        default=True,
    )
    skip_hidden: BoolProperty(
        name="Skip Hidden Objects",
        description=(
            "Silently skip hidden objects and disabled collections (they can "
            "never be baked); when off, each skip is logged as a warning"
        ),
        default=True,
    )
    merge_duplicate_materials: BoolProperty(
        name="Merge Duplicate Materials",
        description=(
            "Treat materials that only differ by a .001 style suffix (with "
            "identical node counts) as one material"
        ),
        default=False,
    )
    dedupe_images: BoolProperty(
        name="Ignore Duplicate Textures",
        description=(
            "Merge image datablocks that point at the same file before "
            "baking, so duplicates don't waste memory"
        ),
        default=True,
    )

    # -- Materials -----------------------------------------------------
    material_action: EnumProperty(
        name="Baked Materials",
        description="What to do with materials after baking",
        items=(
            ('REPLACE', "Replace Originals",
             "Assign the baked material to the baked objects (original "
             "materials are kept in the file with a fake user)"),
            ('KEEP', "Create Copy Only",
             "Create the baked material but leave objects untouched"),
            ('NONE', "Textures Only",
             "Do not create any baked material"),
        ),
        default='REPLACE',
    )
    ao_multiply: BoolProperty(
        name="Multiply AO into Base Color",
        description=(
            "In the baked material, multiply the AO map over the base color"
        ),
        default=False,
    )

    # -- Export --------------------------------------------------------
    export_textures: BoolProperty(
        name="Textures", default=True,
        description="Save the baked texture files")
    export_blend: BoolProperty(
        name="Blend File", default=False,
        description="Save a copy of the .blend file next to the textures")
    export_fbx: BoolProperty(
        name="FBX", default=False,
        description="Export baked objects as FBX")
    export_obj: BoolProperty(
        name="OBJ", default=False,
        description="Export baked objects as OBJ")
    export_gltf: BoolProperty(
        name="glTF", default=False,
        description="Export baked objects as glTF binary (.glb)")

    # -- ZIP -----------------------------------------------------------
    make_zip: BoolProperty(
        name="Export as ZIP",
        description="Package textures and exports into a single ZIP archive",
        default=False,
    )
    zip_name: StringProperty(
        name="ZIP Name",
        description="Filename of the ZIP archive (without extension)",
        default="AutoBake_Export",
    )
    zip_include_readme: BoolProperty(
        name="Include README",
        description="Add a README.txt describing the exported content",
        default=True,
    )
    zip_include_license: BoolProperty(
        name="Include License",
        description="Add a LICENSE.txt template for your exported assets",
        default=False,
    )
    zip_clean_temp: BoolProperty(
        name="Remove Loose Files",
        description=(
            "After a successful ZIP export, delete the loose exported files "
            "and keep only the archive"
        ),
        default=False,
    )
    open_folder_after: BoolProperty(
        name="Open Folder When Done",
        description="Open the export folder after the bake finishes",
        default=True,
    )

    # -- UI section toggles (kept here so they persist per scene) -------
    ui_show_passes: BoolProperty(default=True)
    ui_show_custom: BoolProperty(default=False)


class AB_RuntimeState(bpy.types.PropertyGroup):
    """Transient job state - lives on the WindowManager, never saved."""

    running: BoolProperty(default=False)
    progress: FloatProperty(
        name="Progress", subtype='PERCENTAGE', min=0.0, max=100.0, default=0.0)
    status: StringProperty(default="")
    eta: StringProperty(default="")
    cancel_requested: BoolProperty(default=False)
    last_result: EnumProperty(
        items=(
            ('NONE', "None", ""),
            ('SUCCESS', "Success", ""),
            ('ERROR', "Error", ""),
            ('CANCELLED', "Cancelled", ""),
        ),
        default='NONE',
    )
    last_message: StringProperty(default="")
    last_suggestion: StringProperty(default="")


_CLASSES = (AB_CustomPass, AB_Settings, AB_RuntimeState)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.auto_bake = PointerProperty(type=AB_Settings)
    bpy.types.WindowManager.auto_bake_runtime = PointerProperty(
        type=AB_RuntimeState)


def unregister():
    del bpy.types.WindowManager.auto_bake_runtime
    del bpy.types.Scene.auto_bake
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
