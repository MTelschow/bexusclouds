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

import contextlib

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
        outer.setSpacing(4)

        self._btn = QtWidgets.QToolButton()
        # A leading gap: the arrow sits flush against the text otherwise,
        # and with letter-spacing the chevron reads as the first letter.
        self._btn.setText("  " + self._title)
        self._btn.setIconSize(QtCore.QSize(8, 8))
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
        self.body.setSpacing(8)
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


class ElidingCheckBox(QtWidgets.QCheckBox):
    """A checkbox whose label shortens instead of being cut off.

    A plain `QCheckBox` neither wraps nor elides: given less width than its
    text it draws as much as fits and the last glyph is sliced through the
    middle, which reads as a rendering fault rather than as "there is more
    here". `Dispersion motor current` is the label that does it in the
    Timeline section, and it is the same length in the plot legend and the
    session CSV, so it cannot simply be shortened.

    `sizeHint()` is left alone - it is still the full-text width, so a layout
    that *can* give the label its full width still does, and only
    `minimumSizeHint()` is allowed to shrink. That pair is what lets
    `ToggleGrid` prefer two columns and fall back to one rather than eliding
    at the first opportunity.
    """

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._full = text

    def setText(self, text: str) -> None:       # keep `_full` authoritative
        self._full = text
        super().setText(text)

    def full_text(self) -> str:
        return self._full

    def _contents_x(self, opt) -> int:
        """Left edge of the label, i.e. everything the indicator and its
        spacing take. Asked of the style rather than computed from the
        stylesheet, because the stylesheet is what answers."""
        r = self.style().subElementRect(QtWidgets.QStyle.SE_CheckBoxContents,
                                        opt, self)
        return max(r.x(), 0)

    def paintEvent(self, ev) -> None:
        opt = QtWidgets.QStyleOptionButton()
        self.initStyleOption(opt)
        avail = self.width() - self._contents_x(opt)
        if avail > 0:
            opt.text = self.fontMetrics().elidedText(
                self._full, QtCore.Qt.ElideRight, avail)
        # Through QStylePainter, so QStyleSheetStyle stays in charge and the
        # 15 px indicator from style.checkbox_style() still draws.
        QtWidgets.QStylePainter(self).drawControl(
            QtWidgets.QStyle.CE_CheckBox, opt)

    def minimumSizeHint(self) -> QtCore.QSize:
        """The indicator plus an ellipsis. Without this a layout treats the
        full text as a floor and the widget is never given the chance to
        elide - it is simply clipped by whatever contains it."""
        hint = super().minimumSizeHint()
        opt = QtWidgets.QStyleOptionButton()
        self.initStyleOption(opt)
        floor = self._contents_x(opt) + self.fontMetrics().width("…") + 2
        return QtCore.QSize(min(hint.width(), floor), hint.height())


class ToggleGrid(QtWidgets.QWidget):
    """A group of checkboxes in as many columns as its real width allows.

    The column count has to be decided from the width the widget actually
    gets, not from `SectionFlow.COL_W`: the sidebar column is 340 px only at
    its narrowest, it widens as the splitter is dragged out, and the text
    metrics differ per platform - a build-time decision taken against a
    constant is right on one machine and wrong on the next.

    Two columns when every label fits one, otherwise one. The whole group
    moves together so that the groups which stay in two columns still break
    at the same place; a group laid out per-row would step sideways down the
    section, which is the thing the equal column stretch exists to prevent.
    """

    def __init__(self, boxes, hgap: int, row_gap: int, parent=None):
        super().__init__(parent)
        self._boxes = list(boxes)
        self._hgap = hgap
        self._row_gap = row_gap
        self._ncols = 0
        self._grid = QtWidgets.QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(hgap)
        # Zero, because the row height below is explicit. Spacing on top of it
        # would be a second, invisible contribution to the same gap.
        self._grid.setVerticalSpacing(0)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        for b in self._boxes:
            b.setParent(self)
            b.ensurePolished()
        self._row_h = (max((b.sizeHint().height() for b in self._boxes),
                           default=20) + row_gap)
        self._repack(self._ncols_for(SectionFlow.COL_W))
        # Measured, not computed: Qt allocates a little more than the row
        # minimum asked for, so a height worked out from `_row_h` alone
        # under-reports and the group is handed less than it draws in. Taken
        # here because the pack above is the `COL_W` one - see `sizeHint`.
        self._pinned_h = self._grid.sizeHint().height()

    # -- geometry -----------------------------------------------------------

    def _ncols_for(self, width: int) -> int:
        if len(self._boxes) < 2:
            return 1
        half = (width - self._hgap) // 2
        return 1 if any(b.sizeHint().width() > half
                        for b in self._boxes) else 2

    def _rows_for(self, ncols: int) -> int:
        return (len(self._boxes) + ncols - 1) // ncols

    def _repack(self, ncols: int) -> None:
        if ncols == self._ncols:
            return
        self._ncols = ncols
        for b in self._boxes:
            self._grid.removeWidget(b)
        for i, b in enumerate(self._boxes):
            if ncols == 1:
                self._grid.addWidget(b, i, 0, 1, 2)
            else:
                self._grid.addWidget(b, i // 2, i % 2)
        # An explicit row height, not vertical spacing. On macOS a
        # stylesheet-styled QCheckBox paints 20 px tall while its *layout
        # item* reports 13, so a grid left to size its own rows packs them
        # 16 px apart and every row overlaps the one below it by 4 px. The
        # offscreen platform reports 20 and shows none of it - see
        # docs/TRAPS.md.
        for r in range(self._rows_for(ncols)):
            self._grid.setRowMinimumHeight(r, self._row_h)
        for r in range(self._rows_for(ncols), len(self._boxes)):
            self._grid.setRowMinimumHeight(r, 0)
        self.updateGeometry()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # Only on an actual change: `_repack` calls `updateGeometry`, which
        # can come back here, and re-adding the widgets on every pixel of a
        # splitter drag is a relayout the sidebar does not need.
        self._repack(self._ncols_for(self.width()))

    # -- what SectionFlow asks -----------------------------------------------

    #  `heightForWidth` is deliberately NOT implemented, and `hasHeightForWidth`
    #  is deliberately left False. It is the obvious thing to reach for here and
    #  it silently empties the section: Qt5's `QWidgetItem::heightForWidth` asks
    #  the *layout* of a widget that has one, never the widget, and a plain
    #  `QGridLayout` answers -1. Advertising the flag and answering -1 is worse
    #  than not advertising it, because the enclosing box layout then routes the
    #  size hint through the same path and gets 0 - the Timeline section
    #  collapsed to its header. See docs/TRAPS.md.

    def sizeHint(self) -> QtCore.QSize:
        """Pinned to the arrangement at `SectionFlow.COL_W`.

        That is the narrowest a sidebar column goes and therefore the tallest
        this group ever is, since it only ever goes one column -> two as it
        widens. `SectionFlow` packs by height and already measures at `COL_W`
        for the same reason (`relayout`), so over-reporting costs one row of
        air in one group on a dragged-out sidebar, and under-reporting would
        cost a scrollbar.
        """
        return QtCore.QSize(super().sizeHint().width(), self._pinned_h)


class SectionFlow(QtWidgets.QWidget):
    """Sidebar sections packed into as many columns as the window is short.

    The sidebar carries both halves of the interface and, with the default
    sections expanded, is about 1500 px of content - roughly twice the height
    of a laptop screen. Stacked in one column that means the operator scrolls
    to reach the half they are not looking at, and worse, cannot see both at
    once: the command they send and the housekeeping that answers it are the
    same glance in flight.

    So the sections are laid out in balanced columns sized to the height that
    is actually available. One column when the screen is tall enough, two on
    a laptop, three if it is shorter still; `MAX_COLS` is the point where the
    sidebar would cost the spectrum more width than it is worth, and past it
    the enclosing scroll area takes over again rather than the columns getting
    unreadably narrow.

    Re-packing is driven from the outside (`relayout`) with the height budget
    the caller can see - the scroll viewport - because this widget's own
    height is whatever its content needs and so says nothing about how much
    room there is.
    """

    COL_W = 340          # narrowest a column of controls goes; the command
                         # grid's floor. Columns widen past it to fill the
                         # width the operator drags the sidebar to.
    GAP = 12             # between sections, and between columns
    TIGHT_GAP = 4        # between two folded sections - a list, not blocks
    MAX_COLS = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._row = QtWidgets.QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(self.GAP)
        self._items: list[QtWidgets.QWidget] = []
        self._cols: list[QtWidgets.QVBoxLayout] = []
        self._ncols = 0
        self._budget = -1
        self._last_budget = -1
        self._max_cols = self.MAX_COLS
        self._suspended = 0
        self._col_w = self.COL_W
        self._width = -1
        self._last_width = -1

    def add(self, w: QtWidgets.QWidget) -> None:
        """Append a section. Order is preserved across every re-pack: a
        column break moves a section sideways, never past its neighbours."""
        w.setParent(self)
        # Vertically Preferred, not Maximum: Maximum caps a section at its
        # sizeHint, and a section ending in a wrapped note wants its
        # heightForWidth, which is taller - the difference was taken out of
        # the rows above, squashing the timeline checkboxes into each other.
        w.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                        QtWidgets.QSizePolicy.Preferred)
        self._items.append(w)
        if isinstance(w, Section):
            # A fold changes the content height, so it changes the packing.
            w.toggled.connect(lambda _on: self.repack())

    # -- packing -------------------------------------------------------------

    def _height(self, w: QtWidgets.QWidget) -> int:
        """Height this section wants at the current column width.

        `sizeHint()` alone is not enough: several sections end in a wrapped
        note whose height depends on the width it is given, and at 340 px
        that is two lines where the hint assumed one. Which is also why a
        wider sidebar is not only wider - dragging it out can shorten the
        columns enough to drop one.
        """
        h = w.sizeHint().height()
        if w.hasHeightForWidth():
            hfw = w.heightForWidth(self._col_w)
            if hfw > 0:
                h = max(h, hfw)
        return h

    def _gap(self, prev: int, cur: int) -> int:
        """Space above item `cur` when it follows `prev` in the same column.

        A run of folded sections is a list of one-line headings, not a
        sequence of blocks: spacing them like blocks both looks wrong and
        costs the column ~50 px that an open section could have had. So two
        adjacent folded sections sit at `TIGHT_GAP`.
        """
        a, b = self._items[prev], self._items[cur]
        if (isinstance(a, Section) and isinstance(b, Section)
                and not a.is_open() and not b.is_open()):
            return self.TIGHT_GAP
        return self.GAP

    def _pack(self, heights: list[int], budget: int) -> list[list[int]]:
        """Greedy first-fit in order: fill a column until the next section
        would overflow `budget`, then start the next one."""
        cols: list[list[int]] = [[]]
        used = 0
        for i, h in enumerate(heights):
            g = self._gap(i - 1, i) if i else 0
            if cols[-1] and used + g + h > budget:
                cols.append([])
                used = 0
            used += h + (g if cols[-1] else 0)
            cols[-1].append(i)
        return cols

    def _balanced(self, heights: list[int], budget: int) -> list[list[int]]:
        """Pack into the fewest columns that fit, then even them out.

        Packing straight to the budget fills the first columns to the brim
        and leaves the last nearly empty, which reads as a layout accident.
        So once the column count is known, the smallest per-column height
        that still yields that count is found by bisection and used instead -
        same columns, same order, evenly filled.
        """
        if not heights:
            return []
        cols = self._pack(heights, budget)
        n = len(cols)
        if n > self._max_cols:
            # Taller than the allowed columns can hold: pack to that many and
            # let the scroll area carry the overflow. Narrower columns would
            # clip controls instead of merely needing a scroll.
            n = self._max_cols
            total = sum(heights) + self.GAP * max(0, len(heights) - 1)
            lo, hi = max(heights), total
        else:
            lo, hi = max(heights), budget
        while lo < hi:
            mid = (lo + hi) // 2
            if len(self._pack(heights, mid)) <= n:
                hi = mid
            else:
                lo = mid + 1
        return self._pack(heights, lo)

    def _set_columns(self, n: int) -> None:
        """Grow or shrink the column count. Columns are kept, not rebuilt, so
        a re-pack moves widgets between existing layouts."""
        while len(self._cols) < n:
            holder = QtWidgets.QWidget()
            col = QtWidgets.QVBoxLayout(holder)
            col.setContentsMargins(0, 0, 0, 0)
            # Spacing is per pair, inserted in `relayout` - a run of folded
            # sections is tighter than the blocks around it.
            col.setSpacing(0)
            col.addStretch(1)
            holder.setFixedWidth(self._col_w)
            self._row.addWidget(holder, 0, QtCore.Qt.AlignTop)
            self._cols.append(col)
        while len(self._cols) > n:
            col = self._cols.pop()
            holder = col.parentWidget()
            self._row.removeWidget(holder)
            holder.setParent(None)
            holder.deleteLater()

    def repack(self) -> None:
        """Re-pack at the last size. Called when a section folds."""
        self._budget = -1
        if self._suspended:
            return
        self.relayout(self._last_budget, self._last_width)

    @contextlib.contextmanager
    def held(self):
        """Suspend re-packing for a batch of folds.

        `fold_for` sets fourteen sections in a row; without this each one
        would re-pack the whole sidebar, and the operator would watch the
        columns rearrange thirteen times before landing.
        """
        self._suspended += 1
        try:
            yield
        finally:
            self._suspended -= 1
        if not self._suspended:
            self.repack()

    def columns_for_width(self, width: int) -> int:
        """How many columns `width` pixels of sidebar can hold."""
        step = self.COL_W + self.GAP
        return max(1, min(self.MAX_COLS, (width + self.GAP) // step))

    def relayout(self, budget: int, width: int) -> None:
        """Lay the sections out for the space the sidebar has been given.

        `width` is the operator's: the sidebar is on a splitter, so how many
        columns there is room for is something they drag rather than
        something this decides. `budget` is the height on offer, and within
        the width's cap the flow takes the *fewest* columns that fit it - so
        a sidebar dragged wide on a tall screen collapses back to one column
        rather than spreading three columns of air.
        """
        self._last_budget = budget
        self._last_width = width
        if budget <= 0 or width <= 0 or self._suspended:
            return
        max_cols = self.columns_for_width(width)
        if max_cols != self._max_cols:
            self._max_cols = max_cols
            self._budget = -1
        # Measured at the narrowest a column goes, which is the tallest the
        # sections get: a column count chosen there still fits once the
        # columns widen to fill the sidebar.
        self._col_w = self.COL_W
        cols = self._balanced([self._height(w) for w in self._items], budget)
        n = len(cols)
        col_w = max(self.COL_W, (width - (n - 1) * self.GAP) // n)
        if col_w != self._col_w:
            self._col_w = col_w
            cols = self._balanced([self._height(w) for w in self._items],
                                  budget)
            n = len(cols)
            col_w = max(self.COL_W, (width - (n - 1) * self.GAP) // n)
            self._col_w = col_w
        if (len(cols) == self._ncols and budget == self._budget
                and width == self._width):
            return
        self._budget = budget
        self._width = width
        self._ncols = len(cols)
        self._set_columns(len(cols))
        for col in self._cols:
            # Everything but the trailing stretch, which stays put. The
            # spacers go with the widgets: they are re-inserted per pair.
            while col.count() > 1:
                item = col.takeAt(0)
                if item.widget() is not None:
                    item.widget().setParent(self)
        for ci, idx in enumerate(cols):
            col = self._cols[ci]
            at = 0
            for k, i in enumerate(idx):
                if k:
                    col.insertSpacing(at, self._gap(idx[k - 1], i))
                    at += 1
                col.insertWidget(at, self._items[i])
                self._items[i].show()
                at += 1
        for col, h in zip(self._cols, self.column_heights()):
            col.parentWidget().setFixedWidth(self._col_w)
            # A floor at what the sections want at this width. The row lays
            # the holder out AlignTop, i.e. at its sizeHint, and a box
            # layout's hint ignores heightForWidth - so a column holding a
            # wrapped note came up short and squeezed the rows above it.
            col.parentWidget().setMinimumHeight(h)
        self.setFixedWidth(len(cols) * self._col_w
                           + max(0, len(cols) - 1) * self.GAP)

    @property
    def columns(self) -> int:
        return self._ncols

    def column_heights(self) -> list[int]:
        """Height each column wants, at the width it was packed for. The
        check that the layout did its job: the tallest of these is what the
        sidebar needs on screen."""
        out = []
        for col in self._cols:
            h = 0
            for i in range(col.count()):
                item = col.itemAt(i)
                w = item.widget()
                if w is not None:
                    h += self._height(w)
                elif item.spacerItem() is not None:
                    h += item.spacerItem().sizeHint().height()
            out.append(h)
        return out
