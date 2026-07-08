## Auto Bake v1.0.0: initial release

Bake entire scenes or selected objects into optimized texture atlases with configurable bake passes, automatic UV handling, baked material creation, multi-format export and one-click ZIP packaging.

### 📦 Which file do I download?

| File | For |
|------|-----|
| **`auto_bake.zip`** | Everyone: classic add-on ZIP, installs on **Blender 3.6 → latest** via *Edit → Preferences → Add-ons → Install* |
| `auto_bake-1.0.0.zip` | Same file, version-pinned name |
| `auto_bake-1.0.0-extension.zip` | Blender **4.2+** Extension format (*Install from Disk*) |

Do **not** extract the ZIP: install it directly from Blender.

### ✨ Highlights

- **13 bake passes**: Base Color, Normal, Roughness, Metallic, AO, Emission, Alpha, Specular, Glossiness, Height, Displacement, Combined + unlimited custom Principled-input passes
- **True shared atlases** with texel-density preservation, island packing and automatic atlas resizing up to 8192
- **Noise-free channel captures** via a temporary emission rig (metallic surfaces keep their albedo)
- **Automatic UVs** (Smart UV Project) on objects that have none: originals never touched
- **Baked material generation** with full Principled wiring, transparency and normal-map support
- **Exports**: .blend, FBX, OBJ, glTF (GLB) + organized **ZIP packaging** with optional README/license
- **Production UX**: confirmation dialogs, live progress + ETA, friendly errors with fixes, session log, GPU/CPU with graceful fallback
- **Tested end-to-end on Blender 3.6.23 LTS, 4.2.22 LTS and 5.1.2** (35 automated checks each)

Full documentation: https://autobake.sketch494.online · [User Guide](https://github.com/Sketch494/Auto-Bake/blob/main/docs/USER_GUIDE.md) · [Changelog](https://github.com/Sketch494/Auto-Bake/blob/main/CHANGELOG.md)
