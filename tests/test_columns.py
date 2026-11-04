"""Column sizing of PackageTable."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from shelly_qt.widgets import PackageTable, key  # noqa: E402

app = QApplication.instance() or QApplication([])
COLS = [(n, key(n)) for n in ("Name", "Id", "Version", "Size")]
ROWS = [{"Name": "Adwaita dark theme", "Id": "org.gtk.Gtk3theme.adw-gtk3-dark",
         "Version": "freedesktop 25.08", "Size": "3 KiB"}] * 30


def _table() -> PackageTable:
    t = PackageTable(COLS)
    t.resize(900, 500)
    t.show()
    app.processEvents()
    return t


def _fits(t: PackageTable, col: int) -> bool:
    return t.view.columnWidth(col) >= t.view.sizeHintForIndex(t.proxy.index(0, col)).width()


def test_columns_fit_even_when_filter_hides_everything():
    t = _table()
    t.filter.setText("no such package")
    t.set_rows(ROWS)
    t.filter.clear()
    app.processEvents()
    assert all(_fits(t, c) for c in range(3))


def test_last_column_does_not_hog_space():
    t = _table()
    t.set_rows(ROWS)
    app.processEvents()
    assert t.view.columnWidth(3) < 100
    assert t.view.columnWidth(0) > t.view.sizeHintForIndex(t.proxy.index(0, 0)).width()


def test_user_width_survives_reload():
    t = _table()
    t.set_rows(ROWS)
    t.view.horizontalHeader().resizeSection(1, 80)
    t.set_rows(ROWS)
    assert t.view.columnWidth(1) == 80
