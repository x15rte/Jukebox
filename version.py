"""Version and resource helpers for Jukebox."""

import sys
import os
import shutil
import subprocess  # nosec B404: fixed args, local git only
from pathlib import Path
from typing import Optional


def _resource_dir() -> Path:
    """Base directory for bundled resources: PyInstaller temp dir when frozen, else script dir."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(os.path.dirname(os.path.abspath(__file__)))


def _get_git_version() -> str:
    """Return short git rev (HEAD) for display; empty if not a repo or on error."""
    try:
        git_path = shutil.which("git")
        if not git_path:
            return ""
        result = subprocess.run(  # nosec: fixed args, absolute git path from shutil.which
            [git_path, "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return ""




_VERSION_CACHED: Optional[str] = None


def get_version() -> str:
    """Lazily compute and cache the version string (git commit or frozen build version)."""
    # Called only from main thread (QApplication init); no lock needed.
    global _VERSION_CACHED
    if _VERSION_CACHED is not None:
        return _VERSION_CACHED

    def _get_version() -> str:
        """Version for display: when frozen use BUILD_VERSION; when run from source use git commit."""
        if getattr(sys, "frozen", False):
            try:
                from _build_version import BUILD_VERSION  # type: ignore[import-not-found]

                return BUILD_VERSION if BUILD_VERSION else "0.0.0"
            except ImportError:
                return '0.0.0'
        v = _get_git_version()
        return v if v else "0.0.0"

    _VERSION_CACHED = _get_version()
    return _VERSION_CACHED



