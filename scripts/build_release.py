#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the distributable Auto Bake ZIPs.

Produces two archives in ``dist/``:

* ``auto_bake-<version>.zip``            classic add-on layout (the zip
  contains the ``auto_bake/`` package folder).  Installable through
  Edit > Preferences > Add-ons > Install on Blender 3.6 - 4.x, and through
  "Install from Disk" as a legacy add-on where supported.
* ``auto_bake-<version>-extension.zip``  Blender Extension layout (manifest
  at the zip root).  Installable through "Install from Disk" on 4.2+ and the
  primary format for Blender 5.x.

Usage:  python3 scripts/build_release.py
"""

import ast
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "auto_bake")
DIST = os.path.join(ROOT, "dist")

EXCLUDE_DIRS = {"__pycache__"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo")


def read_version():
    """Extract the version tuple from bl_info without importing bpy."""
    with open(os.path.join(PACKAGE, "__init__.py"), encoding="utf-8") as fh:
        source = fh.read()
    match = re.search(r"bl_info\s*=\s*({.*?^})", source, re.S | re.M)
    if not match:
        raise SystemExit("bl_info not found in auto_bake/__init__.py")
    info = ast.literal_eval(match.group(1))
    return ".".join(str(v) for v in info["version"])


def iter_package_files():
    for dirpath, dirnames, filenames in os.walk(PACKAGE):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for filename in sorted(filenames):
            if filename.endswith(EXCLUDE_SUFFIXES):
                continue
            full = os.path.join(dirpath, filename)
            rel = os.path.relpath(full, PACKAGE)
            yield full, rel


def build_zip(path, prefix):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for full, rel in iter_package_files():
            arcname = os.path.join(prefix, rel) if prefix else rel
            archive.write(full, arcname)
    size_kb = os.path.getsize(path) / 1024.0
    print("  built %s (%.1f KB)" % (os.path.relpath(path, ROOT), size_kb))


def main():
    version = read_version()
    os.makedirs(DIST, exist_ok=True)
    print("Auto Bake %s" % version)
    legacy = os.path.join(DIST, "auto_bake-%s.zip" % version)
    extension = os.path.join(DIST, "auto_bake-%s-extension.zip" % version)
    build_zip(legacy, prefix="auto_bake")
    build_zip(extension, prefix="")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
