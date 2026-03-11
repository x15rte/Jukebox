#!/usr/bin/env python3
# -*- mode: python ; coding: utf-8 -*-

import os
import sys
import shutil
from pathlib import Path
import subprocess
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# PyInstaller exec()'s the spec without __file__; it injects SPEC (path to .spec file).
try:
    project_dir = Path(__file__).resolve().parent
except NameError:
    project_dir = Path(SPEC).resolve().parent


def _get_build_version_for_spec() -> str:
    """Version for packaged exe: BUILD_VERSION env (CI tag), else git describe --tags --exact-match, else 'packaged'."""
    version = os.environ.get("BUILD_VERSION", "").strip()
    if version:
        return version
    git_cmd = shutil.which("git") or "git"
    try:
        result = subprocess.run(
            [git_cmd, "describe", "--tags", "--exact-match"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(project_dir),
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout.strip()
    except Exception:
        pass
    return "packaged"


# Write _build_version.py so main.py can import BUILD_VERSION when frozen (no VERSION file).
build_version = _get_build_version_for_spec()
_build_version_py = project_dir / "_build_version.py"
try:
    _build_version_py.write_text(f'BUILD_VERSION = {repr(build_version)}\n', encoding="utf-8")
except OSError:
    pass

# ---------------------------------------------------------------------------
# Resource files (bundled into the exe and accessed from the temp directory at runtime)
# ---------------------------------------------------------------------------
datas = []

# icon.ico: for window/taskbar icon at runtime (exe icon is set via EXE(icon=...) above)
if (project_dir / "icon.ico").is_file():
    datas.append((str(project_dir / "icon.ico"), "."))

# images directory (if present)
images_dir = project_dir / "images"
if images_dir.is_dir():
    for p in images_dir.iterdir():
        if p.is_file():
            # (source path, runtime relative directory)
            datas.append((str(p), f"images/{p.name}"))

# To bundle additional resources, append to datas similarly, e.g.:
# datas.append((str(project_dir / "README.md"), "README.md"))

# ---------------------------------------------------------------------------
# If PyInstaller reports missing modules, add them here in hiddenimports.
#
# _build_version: written by this spec before Analysis; main.py imports it
# only when frozen (sys.frozen), so the conditional import is not traced.
# ---------------------------------------------------------------------------
hiddenimports = [
    "_build_version",
]

a = Analysis(
    ['main.py'],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

# ---------------------------------------------------------------------------
# Single-file exe: do not use COLLECT, just create one EXE.
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Jukebox',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI app, no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_dir / "icon.ico") if (project_dir / "icon.ico").is_file() else None,
)

