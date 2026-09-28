"""CLOUDS design language tokens and control styles (docs/UI_STYLE.md).

Pulled out of the window so the flight sidebar is styled from the same source
as the instrument one. Before the merge the GSE dashboard was stock Qt on
whatever palette the host had, next to a dark plot - two half-themed halves in
one window. There is one palette now and it lives here.

Several of these exist because PyQt5 is Qt5, which is EOL and untested past
~macOS 13: combo boxes render blank text, and slider grooves and checkbox
indicators silently fail to draw, unless they are styled explicitly rather
than left to Cocoa/Aqua.
"""
from __future__ import annotations

import os

from PyQt5 import QtGui

# Repo root (assets/ lives there, and the PyInstaller bundle mirrors it).
# Forward slashes: a QSS url() with Windows backslashes does not resolve.
_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), "assets").replace(os.sep, "/")
ARROW_DOWN = f"{_ASSETS}/chevron_down.svg"
ARROW_UP = f"{_ASSETS}/chevron_up.svg"

NAVY = "#01386a"          # brand navy: headings, accent buttons, stats
PANEL_BG = "#ffffff"      # sidebar background
VIEW_BG = "#eef3f8"       # plot viewport
CARD_BG = "#eef3f8"
BORDER = "#d3dde6"
RULE = "#dde3e9"
TEXT = "#33414d"          # control labels
MUTED = "#5a6b7a"         # secondary text
SECTION = "#8a97a3"       # section headers
HINT = "#b25e00"          # 11 px italic feedback line
ORANGE = "#E8821E"        # signal colours
GREEN = "#1D9E75"
RED = "#FF2A2A"
GRAY = "#b4b2a9"
DANGER = "#b3261e"        # irreversible actions, error text

# Readout font stack. Platform-native mono first: naming a font Qt cannot
# resolve (Consolas on macOS/Linux) makes it scan every installed family to
# build the alias table - ~100 ms at startup.
MONO = "Menlo,DejaVu Sans Mono,Consolas,monospace"


def light_palette() -> QtGui.QPalette:
    """The palette every widget falls back on when no stylesheet names a
    colour. Without it macOS dark mode leaks in: an unstyled label draws
    white text on the white sidebar (the Sensors readings vanished) and an
    unstyled spin box goes black. See docs/TRAPS.md."""
    pal = QtGui.QPalette()
    c = QtGui.QColor
    for role, col in (
            (QtGui.QPalette.Window, PANEL_BG),
            (QtGui.QPalette.WindowText, TEXT),
            (QtGui.QPalette.Base, "#ffffff"),
            (QtGui.QPalette.AlternateBase, CARD_BG),
            (QtGui.QPalette.Text, TEXT),
            (QtGui.QPalette.PlaceholderText, SECTION),
            (QtGui.QPalette.Button, "#eef1f4"),
            (QtGui.QPalette.ButtonText, TEXT),
            (QtGui.QPalette.BrightText, "#ffffff"),
            (QtGui.QPalette.ToolTipBase, "#ffffff"),
            (QtGui.QPalette.ToolTipText, TEXT),
            (QtGui.QPalette.Highlight, NAVY),
            (QtGui.QPalette.HighlightedText, "#ffffff"),
            (QtGui.QPalette.Link, NAVY),
            (QtGui.QPalette.Light, "#ffffff"),
            (QtGui.QPalette.Midlight, RULE),
            (QtGui.QPalette.Mid, BORDER),
            (QtGui.QPalette.Dark, SECTION),
            (QtGui.QPalette.Shadow, MUTED)):
        pal.setColor(role, c(col))
    for role in (QtGui.QPalette.WindowText, QtGui.QPalette.Text,
                 QtGui.QPalette.ButtonText):
        pal.setColor(QtGui.QPalette.Disabled, role, c("#aebccb"))
    return pal


def primary_btn() -> str:
    return (f"QPushButton{{background:{NAVY}; color:#ffffff; font-weight:bold;"
            "border:0; border-radius:6px; padding:7px 12px;}"
            "QPushButton:hover{background:#024a8c;}"
            "QPushButton:disabled{background:#9fb3c6;}")


def flat_btn() -> str:
    return ("QPushButton{background:#eef1f4; color:#33414d; border:0;"
            "border-radius:5px; padding:6px 10px;}"
            "QPushButton:hover{background:#e2e8ee;}"
            "QPushButton:disabled{color:#aebccb;}")


def danger_btn() -> str:
    """For the irreversible ones. Outlined rather than filled: a solid block of
    red next to the ordinary commands reads as an alarm state, not as a button
    you must deliberately choose."""
    return (f"QPushButton{{background:#ffffff; color:{DANGER}; font-weight:bold;"
            f"border:1px solid {DANGER}; border-radius:5px; padding:6px 10px;}}"
            "QPushButton:hover{background:#fdf0ef;}"
            "QPushButton:disabled{color:#d9a29d; border-color:#e6c4c1;}")


def checkbox_style() -> str:
    # min-height: the macOS style sizes a checkbox from the native small
    # indicator, not the 15 px one drawn here, so rows in a grid came out
    # ~13 px tall and their boxes and descenders ran into each other.
    return ("QCheckBox{color:#33414d; spacing:8px; min-height:20px;}"
            "QCheckBox::indicator{width:15px; height:15px;"
            "border:1px solid #c3cfd9; border-radius:3px; background:#ffffff;}"
            "QCheckBox::indicator:hover{border-color:#8fa3b3;}"
            f"QCheckBox::indicator:checked{{background:{NAVY};"
            f"border-color:{NAVY};}}")


def radio_style() -> str:
    return ("QRadioButton{color:#33414d; spacing:8px;}"
            "QRadioButton::indicator{width:14px; height:14px;"
            "border:1px solid #c3cfd9; border-radius:7px; background:#ffffff;}"
            "QRadioButton::indicator:hover{border-color:#8fa3b3;}"
            f"QRadioButton::indicator:checked{{background:{NAVY};"
            f"border-color:{NAVY};}}")


def spin_style() -> str:
    """Box and step buttons both. Styling only the box leaves Qt drawing the
    buttons natively inside a stylesheet frame - two stray lines on macOS."""
    box = (f"background:#ffffff; color:{TEXT}; border:1px solid {BORDER};"
           "border-radius:5px; padding:4px 20px 4px 6px;")
    btn = ("subcontrol-origin:border; width:16px; border:0;"
           "background:transparent;")
    out = ""
    for w in ("QSpinBox", "QDoubleSpinBox"):
        out += (f"{w}{{{box}}}"
                f"{w}:disabled{{color:#aebccb; background:#f5f7f9;}}"
                f"{w}::up-button{{{btn} subcontrol-position:top right;"
                "border-top-right-radius:5px;}"
                f"{w}::down-button{{{btn} subcontrol-position:bottom right;"
                "border-bottom-right-radius:5px;}"
                f"{w}::up-button:hover, {w}::down-button:hover"
                "{background:#e2e8ee;}"
                f"{w}::up-arrow{{image:url({ARROW_UP}); width:8px; height:8px;}}"
                f"{w}::down-arrow{{image:url({ARROW_DOWN}); width:8px;"
                "height:8px;}")
    return out


def combo_style() -> str:
    return (f"QComboBox{{background:#eef1f4; color:#33414d;"
            f"border:1px solid {BORDER}; border-radius:5px;"
            "padding:5px 24px 5px 8px;}"
            "QComboBox:hover{background:#e2e8ee;}"
            "QComboBox::drop-down{border:0; width:22px;}"
            # An SVG, not the CSS border-triangle trick: Qt's QSS does not
            # draw that and it rendered as a flat bar.
            f"QComboBox::down-arrow{{image:url({ARROW_DOWN});"
            "width:10px; height:10px; margin-right:8px;}"
            f"QComboBox QAbstractItemView{{background:#ffffff; color:#33414d;"
            f"selection-background-color:{NAVY}; selection-color:#ffffff;"
            f"border:1px solid {BORDER}; outline:0;}}")


def slider_style() -> str:
    return ("QSlider::groove:horizontal{height:4px; background:#dde3e9;"
            "border-radius:2px;}"
            f"QSlider::sub-page:horizontal{{background:{NAVY};"
            "border-radius:2px;}"
            f"QSlider::handle:horizontal{{background:#ffffff;"
            f"border:2px solid {NAVY}; width:14px; height:14px;"
            "margin:-6px 0; border-radius:7px;}"
            # A stylesheet that names only the enabled sub-controls replaces the
            # native painting in every state, so a disabled slider stayed
            # indistinguishable from a live one - see window._slider_style.
            "QSlider::handle:horizontal:enabled:hover{background:#eef3f8;}"
            "QSlider::groove:horizontal:disabled{background:#e8ecf0;}"
            "QSlider::sub-page:horizontal:disabled{background:#c2ccd6;}"
            "QSlider::handle:horizontal:disabled{background:#f0f3f6;"
            "border:2px solid #c2ccd6;}")


def list_style() -> str:
    return (f"QListWidget{{background:#ffffff; color:{TEXT};"
            f"border:1px solid {BORDER}; border-radius:5px;"
            f"font-family:{MONO}; font-size:11px;}}"
            f"QListWidget::item{{padding:2px 4px;}}")
