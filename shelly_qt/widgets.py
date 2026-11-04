"""Reusable table + detail widgets."""
from __future__ import annotations

import html
from typing import Any, Callable, Sequence

from PySide6.QtCore import (QAbstractTableModel, QEvent, QItemSelectionModel, QModelIndex,
                            QSortFilterProxyModel, Qt, Signal)
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMenu, QPushButton, QSplitter, QStyleOptionViewItem, QTableView,
                               QTextBrowser, QToolTip, QVBoxLayout, QWidget)

Column = tuple[str, Callable[[dict], Any]]

SortRole = Qt.ItemDataRole.UserRole + 1


def key(name: str, default: Any = "") -> Callable[[dict], Any]:
    return lambda row: row.get(name, default) if row.get(name) is not None else default


class RowModel(QAbstractTableModel):
    """Table of dict rows with a leading checkbox column."""

    checked_changed = Signal()

    def __init__(self, columns: Sequence[Column], checkable: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.columns = list(columns)
        self.checkable = checkable
        self.rows: list[dict] = []
        self.checked: set[int] = set()

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self.rows = [r for r in rows if isinstance(r, dict)]
        self.checked = set()
        self.endResetModel()
        self.checked_changed.emit()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.columns[section][0]
        return None

    def _value(self, row: int, col: int) -> Any:
        try:
            return self.columns[col][1](self.rows[row])
        except Exception:
            return ""

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            v = self._value(r, c)
            if isinstance(v, bool):
                return "✓" if v else ""
            if isinstance(v, (list, tuple)):
                return ", ".join(map(str, v))
            return str(v)
        if role == SortRole:
            v = self._value(r, c)
            return v if isinstance(v, (int, float)) else str(v).lower()
        if role == Qt.ItemDataRole.CheckStateRole and c == 0 and self.checkable:
            return Qt.CheckState.Checked if r in self.checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ToolTipRole:
            return self.rows[r].get("Description") or self.rows[r].get("summary") or None
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            if Qt.CheckState(value) == Qt.CheckState.Checked:
                self.checked.add(index.row())
            else:
                self.checked.discard(index.row())
            self.dataChanged.emit(index, index, [role])
            self.checked_changed.emit()
            return True
        return False

    def flags(self, index):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0 and self.checkable:
            f |= Qt.ItemFlag.ItemIsUserCheckable
        return f

    def checked_rows(self) -> list[dict]:
        return [self.rows[i] for i in sorted(self.checked)]


class FilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSortRole(SortRole)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.extra: Callable[[dict], bool] | None = None
        self._needle = ""

    def refilter(self) -> None:
        if hasattr(self, "beginFilterChange"):  # Qt >= 6.9
            self.beginFilterChange()
            self.endFilterChange()
        else:
            self.invalidateFilter()

    def set_needle(self, text: str) -> None:
        self._needle = text.strip().lower()
        self.refilter()

    def filterAcceptsRow(self, source_row: int, parent) -> bool:
        model: RowModel = self.sourceModel()  # type: ignore[assignment]
        row = model.rows[source_row]
        if self.extra and not self.extra(row):
            return False
        if not self._needle:
            return True
        hay = " ".join(str(model._value(source_row, c)) for c in range(model.columnCount())).lower()
        hay += " " + str(row.get("Description") or row.get("summary") or "").lower()
        return all(part in hay for part in self._needle.split())


# Columns that hold free text and should soak up spare width, in order of preference.
STRETCH_TITLES = ("Description", "Summary", "Path")
MAX_FIT_WIDTH = 360     # auto-fit never makes a column wider than this
MIN_STRETCH_WIDTH = 160  # the stretching column never gets narrower than this
FIT_SAMPLE_ROWS = 2000


class FitTableView(QTableView):
    """QTableView that shows the full cell text as a tooltip when it is elided."""

    def viewportEvent(self, event) -> bool:
        if event.type() == QEvent.Type.ToolTip:
            idx = self.indexAt(event.pos())
            if idx.isValid():
                text = str(idx.data() or "")
                extra = idx.data(Qt.ItemDataRole.ToolTipRole)
                if text and self.sizeHintForIndex(idx).width() > self.columnWidth(idx.column()):
                    tip = html.escape(text)
                    if extra and extra != text:
                        tip += "<br><br>" + html.escape(str(extra))
                    QToolTip.showText(event.globalPos(), tip, self.viewport(), self.visualRect(idx))
                    return True
        return super().viewportEvent(event)


class PackageTable(QWidget):
    """Filter box + sortable table + detail pane."""

    current_changed = Signal(object)  # dict | None

    def __init__(self, columns: Sequence[Column], checkable: bool = True,
                 placeholder: str = "Filter…", parent=None) -> None:
        super().__init__(parent)
        self.model = RowModel(columns, checkable, self)
        self._actions: list[tuple] = []
        self.proxy = FilterProxy(self)
        self.proxy.setSourceModel(self.model)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText(placeholder)
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self.proxy.set_needle)

        self.view = FitTableView()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.verticalHeader().hide()
        self.view.verticalHeader().setDefaultSectionSize(26)
        self.view.setAlternatingRowColors(True)
        self.view.setWordWrap(False)
        hh = self.view.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        # Don't let the last column (often a short one like Size) hog the spare width; a
        # text column gets it instead (see _fill_width).
        hh.setStretchLastSection(False)
        hh.setMinimumSectionSize(36)
        titles = [c[0] for c in columns]
        self.stretch_col = next((titles.index(t) for t in STRETCH_TITLES if t in titles), 0)
        self._user_sized: set[int] = set()
        self._sizing = False
        hh.sectionResized.connect(self._section_resized)
        self.view.viewport().installEventFilter(self)
        self.view.selectionModel().currentRowChanged.connect(self._current)

        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(True)
        self.count = QLabel()

        self.toolbar = QHBoxLayout()
        self.toolbar.addWidget(self.filter, 1)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.view)
        split.addWidget(self.detail)
        split.setSizes([480, 200])

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(self.toolbar)
        lay.addWidget(split, 1)
        lay.addWidget(self.count)
        self.model.modelReset.connect(self._update_count)
        self.model.checked_changed.connect(self._update_count)
        self.proxy.layoutChanged.connect(self._update_count)
        self.proxy.rowsInserted.connect(self._update_count)
        self.proxy.rowsRemoved.connect(self._update_count)

    def add_button(self, text: str, slot, tooltip: str = "") -> QPushButton:
        b = QPushButton(text)
        if tooltip:
            b.setToolTip(tooltip)
        b.clicked.connect(slot)
        self.toolbar.addWidget(b)
        return b

    def add_context_action(self, label: str | Callable[[list[dict]], str],
                           slot: Callable[[list[dict]], None],
                           when: Callable[[list[dict]], bool] | None = None) -> None:
        """Add a right-click action. ``slot`` gets the right-clicked/selected rows."""
        if not self._actions:
            self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.view.customContextMenuRequested.connect(self._show_context_menu)
        self._actions.append((label, slot, when))

    def selected_rows(self) -> list[dict]:
        idxs = sorted(self.view.selectionModel().selectedRows(), key=lambda i: i.row())
        return [self.model.rows[self.proxy.mapToSource(i).row()] for i in idxs]

    def context_menu(self, pos) -> QMenu | None:
        """Build the right-click menu for viewport position ``pos`` (None over empty space)."""
        idx = self.view.indexAt(pos)
        if not idx.isValid() or not self._actions:
            return None
        sm = self.view.selectionModel()
        if not sm.isRowSelected(idx.row(), idx.parent()):
            self.view.selectRow(idx.row())
        sm.setCurrentIndex(idx, QItemSelectionModel.SelectionFlag.NoUpdate)
        rows = self.selected_rows()
        menu = QMenu(self.view)
        for label, slot, when in self._actions:
            if when and not when(rows):
                continue
            menu.addAction(label(rows) if callable(label) else label, lambda s=slot, r=rows: s(r))
        return menu if menu.actions() else None

    def _show_context_menu(self, pos) -> None:
        menu = self.context_menu(pos)
        if menu:
            menu.exec(self.view.viewport().mapToGlobal(pos))

    def set_rows(self, rows: list[dict]) -> None:
        self.model.set_rows(rows)
        self.fit_columns()
        self.detail.clear()

    # -- column sizing -------------------------------------------------------------------
    # QTableView.resizeColumnsToContents() only measures the rows that are currently visible
    # (and passes the filter), so loading data while the filter matched nothing, or with only
    # short names on screen, squeezed columns down to their header text ("Adw…", "org.…").
    # Measure every row of the source model ourselves instead.

    def column_fit_width(self, col: int) -> int:
        hh = self.view.horizontalHeader()
        width = hh.sectionSizeFromContents(col).width()
        opt = QStyleOptionViewItem()
        self.view.initViewItemOption(opt)
        delegate = self.view.itemDelegate()
        for r in range(min(self.model.rowCount(), FIT_SAMPLE_ROWS)):
            width = max(width, delegate.sizeHint(opt, self.model.index(r, col)).width())
        return width + 8

    def fit_columns(self) -> None:
        self._sizing = True
        try:
            for c in range(self.model.columnCount()):
                if c not in self._user_sized:
                    self.view.setColumnWidth(c, min(self.column_fit_width(c), MAX_FIT_WIDTH))
        finally:
            self._sizing = False
        self._fill_width()

    def _fill_width(self) -> None:
        """Give leftover horizontal space to the text column instead of the last one."""
        c = self.stretch_col
        if c in self._user_sized or c >= self.model.columnCount():
            return
        others = sum(self.view.columnWidth(i) for i in range(self.model.columnCount()) if i != c)
        want = max(min(self.column_fit_width(c), MAX_FIT_WIDTH), MIN_STRETCH_WIDTH,
                   self.view.viewport().width() - others)
        if want != self.view.columnWidth(c):
            self._sizing = True
            self.view.setColumnWidth(c, want)
            self._sizing = False

    def _section_resized(self, col: int, _old: int, _new: int) -> None:
        if not self._sizing:  # the user dragged a divider: keep their width from now on
            self._user_sized.add(col)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.view.viewport() and event.type() == QEvent.Type.Resize:
            self._fill_width()
        return super().eventFilter(obj, event)

    def _update_count(self, *_) -> None:
        n, shown, sel = len(self.model.rows), self.proxy.rowCount(), len(self.model.checked)
        txt = f"{shown} of {n} shown" if shown != n else f"{n} items"
        if sel:
            txt += f" · {sel} checked"
        self.count.setText(txt)

    def _current(self, cur: QModelIndex, _prev) -> None:
        row = self.row_at(cur)
        self.current_changed.emit(row)

    def row_at(self, proxy_index: QModelIndex) -> dict | None:
        if not proxy_index.isValid():
            return None
        return self.model.rows[self.proxy.mapToSource(proxy_index).row()]

    def current_row(self) -> dict | None:
        return self.row_at(self.view.currentIndex())

    def select_where(self, pred: Callable[[dict], bool]) -> dict | None:
        """Select and scroll to the first visible row matching ``pred``."""
        for r in range(self.proxy.rowCount()):
            idx = self.proxy.index(r, 0)
            row = self.row_at(idx)
            if row is not None and pred(row):
                self.view.selectRow(r)
                self.view.setCurrentIndex(idx)
                self.view.scrollTo(idx)
                return row
        return None

    def targets(self) -> list[dict]:
        """Checked rows, or the selected rows when nothing is checked."""
        rows = self.model.checked_rows()
        if rows:
            return rows
        seen, out = set(), []
        for idx in self.view.selectionModel().selectedRows():
            r = self.proxy.mapToSource(idx).row()
            if r not in seen:
                seen.add(r)
                out.append(self.model.rows[r])
        return out


def details_html(title: str, fields: list[tuple[str, Any]], body: str = "") -> str:
    parts = [f"<h3 style='margin:0'>{html.escape(str(title))}</h3>"]
    if body:
        parts.append(f"<p>{html.escape(str(body))}</p>")
    parts.append("<table cellspacing='0' cellpadding='3'>")
    for label, val in fields:
        if val in (None, "", [], 0) and label not in ("Installed",):
            continue
        if isinstance(val, (list, tuple)):
            val = ", ".join(map(str, val))
        sval = html.escape(str(val))
        if isinstance(val, str) and val.startswith(("http://", "https://")):
            sval = f"<a href='{sval}'>{sval}</a>"
        parts.append(f"<tr><td style='color:gray;padding-right:12px' valign='top'>{html.escape(label)}"
                     f"</td><td>{sval}</td></tr>")
    parts.append("</table>")
    return "".join(parts)
