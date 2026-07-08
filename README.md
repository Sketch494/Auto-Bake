# Auto Bake

**by Sketch494.** Bake entire scenes or selected objects into optimized texture atlases, with configurable bake passes, automatic UV handling, multi-format export and one-click ZIP packaging.

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
[![Blender 3.6+](https://img.shields.io/badge/Blender-3.6%20%E2%86%92%20latest-orange.svg)](https://www.blender.org/)
[![Release](https://img.shields.io/github/v/release/Sketch494/Auto-Bake)](https://github.com/Sketch494/Auto-Bake/releases/latest)

**Download:** [autobake.sketch494.online](https://autobake.sketch494.online) · [Latest release ZIP](https://github.com/Sketch494/Auto-Bake/releases/latest/download/auto_bake.zip)

---

## Why Auto Bake?

Getting assets game-ready usually means a long manual dance: unwrap, pack, create images, wire bake nodes into every material, bake pass after pass, save each map, rebuild a clean material, export, archive. Auto Bake does the entire dance in one click, and it is built for production:

- **True texture atlases.** All selected objects (or the whole scene) share one atlas per map. Island scale is averaged first so texel density stays uniform, and the atlas auto-grows (up to 8192) when many objects share it.
- **Accurate channel captures.** Base color, roughness, metallic, alpha, specular, glossiness, height, displacement and custom channels are captured through a temporary emission rig at 1 sample: noise-free, fast, and immune to the classic "metallic surfaces bake black albedo" problem.
- **Zero babysitting.** Missing UVs are created, missing materials are substituted, hidden objects are skipped, and every temporary node, image and setting is restored afterwards, even when a bake fails or is cancelled.

## Features

- **13 bake passes:** Base Color, Normal, Roughness, Metallic, Ambient Occlusion, Emission, Alpha, Specular, Glossiness, Height, Displacement, Combined, plus unlimited **custom passes** captured from any Principled BSDF input.
- **Bake scope:** selected objects or entire scene, with optional selected-to-active (high-poly → low-poly) baking with ray distance and cage extrusion controls.
- **UV automation:** Smart UV Project for objects without UVs, dedicated non-destructive `AutoBake` atlas layer, texel-density averaging, island packing with configurable margin and rotation.
- **Output control:** PNG / TGA / TIFF / OpenEXR, 512 to 8192 resolution, color depth and compression settings, overwrite / auto-rename / ask policies.
- **Baked materials:** clean Principled setup wired automatically (normal map node, alpha transparency, optional AO multiply, displacement output). Replace originals (kept safe with a fake user) or just create the material.
- **Export:** .blend, FBX, OBJ and glTF (GLB) in any combination, plus **Export as ZIP** with organized `textures/` and `models/` folders, optional README and license, and optional cleanup of loose files.
- **Professional UX:** confirmation dialogs before baking, replacing materials, overwriting files and cancelling; live progress bar with friendly stage messages and estimated remaining time; readable error messages with suggested fixes.
- **Pipeline friendly:** GPU/CPU selection with graceful CPU fallback, add-on preferences for studio defaults, session log with save-to-file, fully scriptable (`bpy.ops.autobake.bake(sync=True)` runs head-less).

## Compatibility

| Blender | Status | Install method |
|---------|--------|----------------|
| 3.6 LTS | ✅ tested (3.6.23) | classic add-on ZIP |
| 4.0 / 4.1 | ✅ supported | classic add-on ZIP |
| 4.2 LTS | ✅ tested (4.2.22) | classic add-on ZIP or extension ZIP |
| 4.3 to 4.5 | ✅ supported | classic add-on ZIP or extension ZIP |
| 5.x (latest) | ✅ tested (5.1.2) | classic add-on ZIP or extension ZIP |

The version-compatibility layer transparently handles the Principled BSDF socket renames introduced in Blender 4.0 (`Specular` → `Specular IOR Level`, `Emission` → `Emission Color`, and others), UI API differences, and EEVEE material setting changes.

## Installation

1. Download `auto_bake.zip` from the [latest release](https://github.com/Sketch494/Auto-Bake/releases/latest) (do **not** extract it).
2. In Blender open **Edit → Preferences → Add-ons → Install** (Blender 4.2+: the dropdown arrow → **Install from Disk**).
3. Select the ZIP and enable **Auto Bake**.
4. Find the panel in the **3D View → Sidebar (N) → Auto Bake** tab.

## Quick start

1. Select the objects you want to bake (or set scope to *Entire Scene*).
2. Pick your maps in **Bake Maps** (Base Color + Normal + Roughness are on by default).
3. Set the destination in **Output** (folder, name, format, resolution).
4. Press **Bake**, review the confirmation dialog, and watch the progress bar.
5. Your atlases land in `textures/`, models in `models/`, and, if enabled, everything is packaged into a ZIP.

## Documentation

Full documentation, including a settings reference and a troubleshooting table, lives in [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) and on the project site: **[autobake.sketch494.online](https://autobake.sketch494.online)**.

## Building from source

```bash
python3 scripts/build_release.py       # → dist/auto_bake-<version>.zip (+ extension zip)
```

Run the automated end-to-end test inside any Blender build:

```bash
blender -b --factory-startup --python tests/test_headless.py -- \
    --zip dist/auto_bake-1.0.0.zip \
    --ext-zip dist/auto_bake-1.0.0-extension.zip \
    --out /tmp/autobake_test
```

The test installs the add-on like a user would, bakes a scene that exercises linked textures, missing UVs, material-less and non-Principled objects, then pixel-checks the atlases and validates every export. CI runs it on every release build.

## License

[GPL-3.0-or-later](LICENSE) © 2026 Sketch494. Assets you bake with Auto Bake are entirely yours.
