# Changelog

All notable changes to Auto Bake are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-07-08

Initial public release.

### Added
- One-click baking of selected objects or entire scenes into shared texture atlases.
- 12 built-in bake passes: Base Color, Normal, Roughness, Metallic, Ambient Occlusion, Emission, Alpha, Specular, Glossiness, Height, Displacement, Combined.
- Unlimited custom passes captured from any Principled BSDF input socket.
- Emission-rig channel capture: noise-free 1-sample bakes for all data channels, immune to metallic albedo loss.
- Automatic UV pipeline: Smart UV Project for unwrapped objects, dedicated non-destructive atlas UV layer, texel-density averaging, island packing with margin/rotation controls.
- Atlas auto-resize (up to 8192) preserving texel density as object count grows.
- Baked material generation with automatic Principled wiring (normal map, transparency, optional AO multiply, displacement), with replace / create-only / textures-only modes; replaced originals are preserved with a fake user.
- Output options: PNG, TGA, TIFF, OpenEXR; 512 to 8192 resolutions; color depth and compression; overwrite / auto-rename / ask policies with a conflict dialog.
- Exporters: .blend copy, FBX, OBJ, glTF (GLB), in any combination.
- Export-as-ZIP packaging with organized folder structure, optional README and license, optional loose-file cleanup, and open-folder-when-done.
- Selected-to-active (high→low poly) baking with max ray distance and cage extrusion.
- GPU/CPU device selection with automatic CPU fallback, denoising for lighting passes.
- Live progress bar, stage-by-stage status messages, estimated remaining time, double-ESC / confirmed cancellation.
- Confirmation dialogs before baking, replacing materials, overwriting files and cancelling.
- Friendly error messages with suggested fixes; session logging with save-to-file; configurable log level.
- Add-on preferences with studio pipeline defaults and one-click apply-to-scene.
- Compatibility layer covering Blender 3.6 LTS through the latest release (tested on 3.6.23, 4.2.22 and 5.1.2), including Principled socket renames and UI API differences.
- Dual packaging: classic add-on ZIP (3.6+) and Blender Extension ZIP (4.2+).
- Head-less end-to-end test suite and release build script.

[1.0.0]: https://github.com/Sketch494/Auto-Bake/releases/tag/v1.0.0
