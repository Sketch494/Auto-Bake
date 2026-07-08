# Auto Bake — User Guide

Auto Bake bakes entire scenes or selected objects into optimized texture
atlases and packages the result for production. This guide covers every
setting, the baking pipeline, scripting, and troubleshooting.

---

## 1. The pipeline at a glance

When you press **Bake**, Auto Bake runs these stages (you'll see each one in
the progress area):

1. **Preparing objects** — collects targets, validates them, switches to
   Cycles, configures the compute device, checks the output folder is
   writable *before* spending minutes baking.
2. **Checking materials** — enables nodes where needed, substitutes a neutral
   temporary material on objects without one, optionally merges duplicate
   materials and image datablocks.
3. **Checking / creating UV maps** — Smart UV Projects any object without
   UVs, then adds a dedicated `AutoBake` UV layer (a copy of the object's
   active layer) so your original UVs are never touched.
4. **Packing UV islands** — averages island scale across *all* objects
   (uniform texel density) and packs everything into one shared 0–1 space.
5. **Creating bake images / nodes** — one atlas image per enabled pass,
   pre-filled with the correct neutral color (e.g. flat normal blue).
6. **Baking passes** — object by object, pass by pass, with live progress
   and time estimates.
7. **Saving textures** — written with a neutral view transform so Filmic/AgX
   can never distort your data maps.
8. **Creating materials** — a clean Principled material wired to the atlases.
9. **Exporting assets / Compressing ZIP** — models and archive.
10. **Cleaning temporary data** — every temp node, image, setting, selection
    and UV state is restored. This also happens on failure or cancellation.

## 2. Bake maps

| Map | How it's captured | Notes |
|-----|-------------------|-------|
| Base Color | Emission rig on `Base Color` | True albedo — metallic surfaces keep their color |
| Normal | Cycles NORMAL pass | Tangent space, OpenGL (+Y) |
| Roughness | Emission rig | |
| Metallic | Emission rig | |
| Ambient Occlusion | Cycles AO pass | Uses **Samples** + optional denoise |
| Emission | Emission rig on `Emission Color` | |
| Alpha | Emission rig | Baked material gets transparency enabled |
| Specular | Emission rig | Handles the 4.0 rename to *Specular IOR Level* |
| Glossiness | Emission rig, inverted roughness | For gloss workflows |
| Height | Emission rig on the Displacement node's Height input | Mid-gray neutral |
| Displacement | Height × Scale | |
| Combined | Cycles COMBINED pass | Full lighting; uses **Samples** |
| Custom | Emission rig on any Principled input | e.g. `Sheen Weight`, `Transmission Weight` |

**Custom passes:** open *Bake Maps → Custom Passes*, add a row, set the pass
name (used in the filename) and the Principled input socket name. Old (3.x)
and new (4.x) socket names both work. The `D` toggle marks the pass as
Non-Color data.

Materials without a Principled BSDF are baked with neutral defaults for
channel passes (and logged as warnings) — Normal, AO and Combined still bake
their real result.

## 3. Output settings

- **Export Folder / File Name** — textures are saved as
  `<name>_<Pass>.<ext>` inside `textures/` (when *Organize Subfolders* is on).
- **Resolution** — 512 to 8192. With **Auto Resize Atlas** on, the atlas
  doubles (capped at 8192) as more objects share it, roughly every 4 objects.
- **Format / Color Depth / Compression** — PNG (8/16-bit), TGA (8-bit),
  TIFF (8/16-bit), OpenEXR (16/32-bit float). Invalid combinations are
  clamped automatically and logged.
- **Existing Files** — *Overwrite*, *Rename Automatically* (`_001` suffix),
  or *Ask* (a dialog lists the conflicts before baking starts).

## 4. Baking options

- **Device** — Auto / GPU / CPU. If no compatible GPU is found, Auto Bake
  falls back to CPU and tells you.
- **Samples** — only used by AO and Combined. Channel passes always render
  1 sample (they are noise free by construction).
- **Margin** — pixel bleed around UV islands.
- **Skip Hidden Objects** — hidden objects can never be baked; this toggle
  controls whether skipping them is silent or logged as a warning.
- **Merge Duplicate Materials** — conservatively re-points `Mat.001`-style
  duplicates at their base material when node/link counts match.
- **Ignore Duplicate Textures** — merges image datablocks pointing at the
  same file before baking.
- **Selected to Active** — with scope *Selected Objects*, bakes all selected
  (high-poly) objects onto the *active* (low-poly) object, honoring
  **Max Ray Distance** and **Cage Extrusion**.

## 5. Materials

- **Replace Originals** — objects get the baked material; original materials
  are kept in the file with a fake user (nothing is lost, but slots change —
  hence the confirmation dialog).
- **Create Copy Only** — the baked material is created (with a fake user) but
  no object is modified.
- **Textures Only** — no material is created; atlas images are removed from
  the file after saving to keep it clean.
- **Multiply AO into Base Color** — inserts a multiply mix node in the baked
  material when both maps exist.

## 6. Export & ZIP

Enable any combination of **Textures**, **Blend File**, **FBX**, **OBJ**,
**glTF** (GLB). Models are written to `models/` and self-contained (textures
copied for FBX/OBJ, embedded for GLB).

**Export as ZIP** packages everything into `<ZIP Name>.zip`:

```
AutoBake_Export.zip
├── textures/   ← baked atlases
├── models/     ← exported models
├── README.txt  ← optional bake summary
└── LICENSE.txt ← optional license template for YOUR assets
```

*Remove Loose Files* keeps only the archive afterwards. *Open Folder When
Done* reveals the destination in your file browser. **Export Only** runs the
export/ZIP stages without baking.

## 7. Preferences, logging, scripting

**Edit → Preferences → Add-ons → Auto Bake** holds studio defaults (folder,
resolution, format, device, default passes, ZIP name) and the **Logging
Level**. Use *Advanced → Apply Preference Defaults* to copy them into the
current scene.

*Advanced → Save Log* writes the full session log
(`autobake_log_<timestamp>.txt`) next to your export.

Auto Bake is fully scriptable — the whole pipeline runs synchronously in
head-less Blender:

```python
import bpy
s = bpy.context.scene.auto_bake
s.bake_scope = 'SCENE'
s.export_folder = "/tmp/bake_out"
s.use_metallic = True
s.make_zip = True
bpy.ops.autobake.bake(sync=True)   # blocks until finished
```

## 8. Troubleshooting

| Message | Cause & fix |
|---------|-------------|
| *No bakeable objects are selected* | Select at least one visible mesh, or switch scope to Entire Scene. |
| *Object … has no UV map* | Enable **Create Missing UVs**, or unwrap manually. |
| *No write permission for the export folder* | Pick a folder inside your user directory or fix permissions. |
| *Material … has no Principled BSDF* (warning) | Channel passes use neutral defaults for that material. Add a Principled BSDF for accurate captures. |
| *No compatible GPU found — falling back to CPU* | Baking continues on CPU. Check Cycles device settings in Preferences → System. |
| *Baking … failed on object …* | Usually invalid geometry or UVs. Check the object, lower the resolution, or switch the device to CPU. |
| *UV operation 'pack_islands' failed* | Pack the UVs manually in the UV editor, then bake again. |
| *Nothing to package* | Enable Textures or at least one model format before using ZIP export. |
| Bake seems frozen | Individual Cycles bakes are blocking; the status/progress update between objects and passes. Lower resolution/samples for faster feedback. |
| Files missing after ZIP | *Remove Loose Files* was enabled — everything is inside the archive. |

## 9. Uninstalling

Disable or remove the add-on in **Edit → Preferences → Add-ons**. Auto Bake
stores its settings inside your .blend files only; no external files are kept
besides the exports you created.
