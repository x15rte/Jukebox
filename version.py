"""Version and resource helpers for Jukebox."""

import sys
import os
import shutil
import subprocess  # nosec B404: fixed args, local git only
from pathlib import Path


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


def _get_version() -> str:
    """Version for display: when frozen use BUILD_VERSION; when run from source use git commit."""
    if getattr(sys, "frozen", False):
        try:
            from _build_version import BUILD_VERSION  # type: ignore[import-not-found]

            return BUILD_VERSION if BUILD_VERSION else "packaged"
        except ImportError:
            return "packaged"
    return _get_git_version()


APP_VERSION = _get_version()
