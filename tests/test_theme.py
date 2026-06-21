from typing import Any, cast

import theme
import pytest

theme = cast(Any, theme)


def test_apply_global_palette_sets_all_color_roles():
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
            Highlight = "Highlight"
            HighlightedText = "HighlightedText"

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

    assert len(app.p.calls) == 10
    roles = {role for role, _ in app.p.calls}
    all_roles = {"Window", "Base", "AlternateBase", "Text",
                 "WindowText", "ButtonText", "ToolTipBase", "ToolTipText",
                 "Highlight", "HighlightedText"}
    assert roles == all_roles
    assert app.set_palette_called is True



def test_get_theme_lazy_init_and_cache():
    theme._theme_cache = None
    original_get = theme.get_dark_cyber_theme
    called = []
    theme.get_dark_cyber_theme = lambda: (called.append(1), original_get())[1]
    try:
        t1 = theme.get_theme()
        t2 = theme.get_theme()
        assert t1 is t2
        assert len(called) == 1
    finally:
        theme._theme_cache = None
        theme.get_dark_cyber_theme = original_get


def test_apply_global_palette_handles_none_app():
    with pytest.raises(AttributeError):
        theme.apply_global_palette(None)  # type: ignore[arg-type]



def test_theme_helpers_and_dark_theme_payload():

    t = theme.get_dark_cyber_theme()
    assert t.background_main.startswith("#")
    assert t.logs.warning.name().lower() == t.accent_warning.lower()
    assert t.logs.error.name().lower() == t.accent_error.lower()
    assert "QPushButton#PrimaryButton" in t.qss
