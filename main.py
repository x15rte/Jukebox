#!/usr/bin/env python3
"""Jukebox entry point: creates QApplication, initializes theme/icon, and launches MainWindow."""

import os
import struct
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QSharedMemory

from version import _resource_dir, get_version
from platform_utils import set_app_user_model_id
from main_window import MainWindow, APP_ID
import theme


def main():
    # Single-instance guard — store PID to detect orphaned segments after crash
    shared_mem = QSharedMemory("Jukebox-7f3a1b2c")
    if not shared_mem.create(4):
        if shared_mem.error() == QSharedMemory.SharedMemoryError.AlreadyExists:
            owner_alive = False
            if shared_mem.attach(QSharedMemory.AccessMode.ReadOnly):
                raw = shared_mem.constData().asstring(4) if shared_mem.constData() else b""
                owner_pid = struct.unpack('i', raw)[0] if len(raw) == 4 else 0
                try:
                    os.kill(owner_pid, 0)
                    owner_alive = True
                except (OSError, ProcessLookupError):
                    pass
                shared_mem.detach()
            if owner_alive:
                print("Jukebox is already running.", file=sys.stderr)
                return
            # Orphaned segment from crashed process — we detached it above.
            # Try to create a fresh segment.
            if not shared_mem.create(4):
                print(f"Jukebox startup error (after reclaim): {shared_mem.error()}", file=sys.stderr)
                # Continue without single-instance guard
        else:
            print(f"Jukebox startup error: {shared_mem.error()}", file=sys.stderr)
            # Continue without single-instance guard

    # Write our PID into shared memory
    if shared_mem.isAttached():
        raw = shared_mem.data()
        if raw:
            # voidptr supports buffer protocol; slice assignment writes into shared memory
            raw[:4] = struct.pack('i', os.getpid())
    set_app_user_model_id(APP_ID)

    app = QApplication(sys.argv)
    theme.apply_global_palette(app)

    icon_path = _resource_dir() / "icon.ico"
    app_icon = QIcon(str(icon_path)) if icon_path.is_file() else None
    if app_icon:
        app.setWindowIcon(app_icon)

    window = MainWindow(app_version=get_version())
    if app_icon:
        window.setWindowIcon(app_icon)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        from PyQt6.QtWidgets import QMessageBox
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "Jukebox Error",
            f"Jukebox encountered an error during startup:\n\n{e}\n\n{traceback.format_exc()}")
        sys.exit(1)
