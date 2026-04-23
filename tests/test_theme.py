from types import SimpleNamespace
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


def test_heading_font_uses_provided_base_and_default_font(monkeypatch):
    class FakeFont:
        def __init__(self, src=None):
            if src is not None and hasattr(src, "size"):
                src_obj = cast(Any, src)
                self.size = src_obj.size
                self.bold = src_obj.bold
            else:
                self.size = 10.0
                self.bold = False

        def pointSizeF(self):
            return self.size

        def setPointSizeF(self, v):
            self.size = v

        def setBold(self, v):
            self.bold = v

    monkeypatch.setattr(theme, "QFont", FakeFont)
    monkeypatch.setattr(theme, "QApplication", SimpleNamespace(font=lambda: FakeFont()))

    base = FakeFont()
    base.size = 20.0
    f1 = cast(Any, theme.heading_font(base=cast(Any, base), scale=1.5))
    assert f1.size == 30.0
    assert f1.bold is True

    f2 = cast(Any, theme.heading_font(base=None, scale=1.2))
    assert f2.size == 12.0
    assert f2.bold is True


def test_theme_helpers_and_dark_theme_payload():
    assert "font-size" in theme.subtle_label_style()
    assert "QGroupBox" in theme.section_groupbox_style()

    t = theme.get_dark_cyber_theme()
    assert t.background_main.startswith("#")
    assert t.logs.warning == t.accent_warning
    assert t.logs.error == t.accent_error
    assert "QPushButton#PrimaryButton" in t.qss
