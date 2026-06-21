from pathlib import Path
from typing import Any, cast

import version

version = cast(Any, version)


def test_resource_dir_meipass_and_source(monkeypatch, tmp_path):
    monkeypatch.setattr(version.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert version._resource_dir() == Path(tmp_path)

    monkeypatch.delattr(version.sys, "_MEIPASS", raising=False)
    out = version._resource_dir()
    assert out.exists()


def test_get_git_version_paths(monkeypatch):
    monkeypatch.setattr(version.shutil, "which", lambda _n: None)
    assert version._get_git_version() == ""

    monkeypatch.setattr(version.shutil, "which", lambda _n: "git")

    class R:
        returncode = 0
        stdout = "abc123\n"

    monkeypatch.setattr(version.subprocess, "run", lambda *a, **k: R())
    assert version._get_git_version() == "abc123"

    class R2:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(version.subprocess, "run", lambda *a, **k: R2())
    assert version._get_git_version() == ""

    monkeypatch.setattr(version.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert version._get_git_version() == ""


def test_get_version_frozen_and_source(monkeypatch):
    version._VERSION_CACHED = None
    monkeypatch.setattr(version.sys, "frozen", True, raising=False)

    import builtins

    real_import = builtins.__import__

    class BuildMod:
        BUILD_VERSION = "1.2.3"

    def imp_ok(name, *args, **kwargs):
        if name == "_build_version":
            return BuildMod()
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", imp_ok)
    assert version.get_version() == "1.2.3"

    version._VERSION_CACHED = None
    class BuildModEmpty:
        BUILD_VERSION = ""

    def imp_empty(name, *args, **kwargs):
        if name == "_build_version":
            return BuildModEmpty()
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", imp_empty)
    assert version.get_version() == "0.0.0"
    version._VERSION_CACHED = None

    def imp_fail(name, *args, **kwargs):
        if name == "_build_version":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", imp_fail)
    assert version.get_version() == "0.0.0"
    version._VERSION_CACHED = None

    monkeypatch.setattr(version.sys, "frozen", False, raising=False)
    monkeypatch.setattr(version, "_get_git_version", lambda: "gitver")
    assert version.get_version() == "gitver"


def test_get_version_cached_value(monkeypatch):
    """Calling get_version() twice returns the cached value."""
    version._VERSION_CACHED = None
    monkeypatch.setattr(version, "_get_git_version", lambda: "abc123")
    first = version.get_version()
    second = version.get_version()
    assert first == "abc123"
    assert second == "abc123"
    version._VERSION_CACHED = None
