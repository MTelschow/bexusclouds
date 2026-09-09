"""Collapsible sidebar sections.

One sidebar carries both halves of the operator interface now - flight
housekeeping and commanding above, instrument control below - which is more
than fits on a laptop screen at once. A section collapses as a unit
(docs/UI_STYLE.md's `_heading` + hideable `sec_*` pattern), so the operator
keeps the two or three groups they are working with open and the rest folded
away.

Collapsing is display only. A folded section's widgets keep their state and
keep updating, so folding the housekeeping grid away never means ground stops
tracking it - only that it is not on screen.
"""
from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from . import style


class Section(QtWidgets.QWidget):
    """A titled, collapsible group of sidebar controls.

    Add content with `body` as the parent layout. `set_open()` is the
    programmatic route, used by the entry point to expand whichever half the
    operator asked for.
    """

    toggled = QtCore.pyqtSignal(bool)

    def __init__(self, title: str, parent=None, open_: bool = True):
        super().__init__(parent)
        self._title = title.upper()
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self._btn = QtWidgets.QToolButton()
        self._btn.setText(self._title)
        self._btn.setCheckable(True)
        self._btn.setChecked(open_)
        self._btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self._btn.setArrowType(QtCore.Qt.DownArrow if open_
                               else QtCore.Qt.RightArrow)
        self._btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn.setStyleSheet(
            f"QToolButton{{color:{style.SECTION}; font-size:10px;"
            "letter-spacing:3px; border:0; background:transparent;"
            "padding:0; text-align:left;}"
            f"QToolButton:hover{{color:{style.MUTED};}}")
        self._btn.toggled.connect(self._on_toggled)
        outer.addWidget(self._btn)

        self._content = QtWidgets.QWidget()
        self.body = QtWidgets.QVBoxLayout(self._content)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(10)
        outer.addWidget(self._content)
        self._content.setVisible(open_)

    @property
    def title_key(self) -> str:
        """Upper-case title, for code that wants to name a section."""
        return self._title

    def _on_toggled(self, on: bool) -> None:
        # `setVisible`, not a layout swap: the widgets stay alive and keep
        # taking updates while folded.
        self._content.setVisible(on)
        self._btn.setArrowType(QtCore.Qt.DownArrow if on
                               else QtCore.Qt.RightArrow)
        self.toggled.emit(on)

    def add(self, w) -> None:
        """Add a widget or a nested layout to the section body."""
        if isinstance(w, QtWidgets.QLayout):
            self.body.addLayout(w)
        else:
            self.body.addWidget(w)

    def is_open(self) -> bool:
        return self._btn.isChecked()

    def set_open(self, on: bool) -> None:
        self._btn.setChecked(on)


def group_label(text: str) -> QtWidgets.QLabel:
    """A heading one level below a Section - "Membrane solenoid" inside
    Actuators. Without it a heading is indistinguishable from a widget's own
    label."""
    lab = QtWidgets.QLabel(text)
    lab.setStyleSheet(f"color:{style.SECTION}; font-weight:bold;"
                      "font-size:11px;")
    return lab


def rule() -> QtWidgets.QFrame:
    line = QtWidgets.QFrame()
    line.setFrameShape(QtWidgets.QFrame.HLine)
    line.setStyleSheet(f"color:{style.RULE};")
    return line
