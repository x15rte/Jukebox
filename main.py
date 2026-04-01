#!/usr/bin/env python3
"""Jukebox entry point: creates QApplication, initializes theme/icon, and launches MainWindow."""

import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from version import _resource_dir, APP_VERSION
from platform_utils import set_app_user_model_id
from main_window import MainWindow, APP_ID
import theme


def main():
    set_app_user_model_id(APP_ID)

    app = QApplication(sys.argv)
    theme.apply_global_palette(app)

    icon_path = _resource_dir() / "icon.ico"
    app_icon = QIcon(str(icon_path)) if icon_path.is_file() else None
    if app_icon:
        app.setWindowIcon(app_icon)

    window = MainWindow(app_version=APP_VERSION)
    if app_icon:
        window.setWindowIcon(app_icon)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
