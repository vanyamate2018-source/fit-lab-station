import os

from master.ui.theme import THEME_NAMES, selected_theme


def test_named_themes_are_stable():
    assert THEME_NAMES == ("amber", "cyan")
    assert selected_theme("amber") == "amber"
    assert selected_theme("cyan") == "cyan"


def test_unknown_theme_falls_back_to_amber(monkeypatch):
    monkeypatch.setenv("FIT_LAB_THEME", "unknown")
    assert selected_theme() == "amber"
