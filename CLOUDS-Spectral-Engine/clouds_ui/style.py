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
    return ("QCheckBox{color:#33414d; spacing:8px;}"
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
    return (f"QSpinBox{{background:#ffffff; color:{TEXT};"
            f"border:1px solid {BORDER}; border-radius:5px; padding:4px 6px;}}"
            f"QDoubleSpinBox{{background:#ffffff; color:{TEXT};"
            f"border:1px solid {BORDER}; border-radius:5px; padding:4px 6px;}}")


def combo_style() -> str:
    return (f"QComboBox{{background:#eef1f4; color:#33414d;"
            f"border:1px solid {BORDER}; border-radius:5px;"
            "padding:5px 24px 5px 8px;}"
            "QComboBox:hover{background:#e2e8ee;}"
            "QComboBox::drop-down{border:0; width:22px;}"
            "QComboBox::down-arrow{image:none; width:0; height:0;"
            "border-left:4px solid transparent;"
            "border-right:4px solid transparent;"
            "border-top:5px solid #5a6b7a; margin-right:8px;}"
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
            "QSlider::handle:horizontal:hover{background:#eef3f8;}")


def list_style() -> str:
    return (f"QListWidget{{background:#ffffff; color:{TEXT};"
            f"border:1px solid {BORDER}; border-radius:5px;"
            f"font-family:{MONO}; font-size:11px;}}"
            f"QListWidget::item{{padding:2px 4px;}}")
