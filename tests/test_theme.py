from typing import Any, cast

import theme

theme = cast(Any, theme)


def test_apply_global_palette_sets_core_roles():
    class Palette:
        class ColorRole:
            Window = "Window"
            Base = "Base"
            AlternateBase = "AlternateBase"
            Text = "Text"
            WindowText = "WindowText"
            ButtonText = "ButtonText"
            ToolTipBase = "ToolTipBase"
            ToolTipText = "ToolTipText"

        def __init__(self):
            self.calls = []

        def setColor(self, role, color):
            self.calls.append((role, color))

    class App:
        def __init__(self):
            self.p = Palette()
            self.set_palette_called = False

        def palette(self):
            return self.p

        def setPalette(self, p):
            self.set_palette_called = p is self.p

    app = App()
    theme.apply_global_palette(cast(Any, app))

    roles = {role for role, _ in app.p.calls}
    assert "Window" in roles
    assert "Base" in roles
    assert "ToolTipText" in roles
    assert app.set_palette_called is True




def test_theme_helpers_and_dark_theme_payload():

    t = theme.get_dark_cyber_theme()
    assert t.background_main.startswith("#")
    assert t.logs.warning == t.accent_warning
    assert t.logs.error == t.accent_error
    assert "QPushButton#PrimaryButton" in t.qss
