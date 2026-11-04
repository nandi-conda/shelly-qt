"""Drive the real window against tests/fake_shelly.py, offscreen."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
FAKE = Path(__file__).with_name("fake_shelly.py")
os.environ["SHELLY_BIN"] = f"{sys.executable} {FAKE}"
os.environ["SHELLY_ELEVATE"] = ""

from PySide6.QtCore import QEventLoop, QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from shelly_qt import dialogs  # noqa: E402
from shelly_qt.app import MainWindow  # noqa: E402

app = QApplication.instance() or QApplication([])


def wait_until(pred, timeout=10000):
    loop_ms = 0
    while not pred():
        if loop_ms > timeout:
            raise AssertionError("timed out")
        loop = QEventLoop()
        QTimer.singleShot(25, loop.quit)
        loop.exec()
        loop_ms += 25


@pytest.fixture
def win(monkeypatch):
    w = MainWindow()
    w.show()
    yield w
    w.close()


def test_pages_load(win):
    browse = win.pages[0]
    wait_until(lambda: len(browse.table.model.rows) == 5)
    win.nav.setCurrentRow(1)
    wait_until(lambda: len(win.pages[1].table.model.rows) == 3)
    wait_until(lambda: win.nav.item(2).text() == "Updates (4)")
    for i in range(3, 8):
        win.nav.setCurrentRow(i)
    wait_until(lambda: len(win.pages[3].installed.model.rows) == 1)
    wait_until(lambda: len(win.pages[4].installed.model.rows) == 1)
    wait_until(lambda: len(win.pages[5].table.model.rows) == 1)
    wait_until(lambda: win.pages[7].table.rowCount() == 5)


def test_filter(win):
    t = win.pages[0].table
    wait_until(lambda: len(t.model.rows) == 5)
    t.filter.setText("editor")
    assert t.proxy.rowCount() == 1


def test_install_answers_transaction(win, monkeypatch):
    seen = []

    def fake_ask(q, parent=None):
        seen.append(q["$kind"])
        return dialogs.protocol.answer_transaction(q["QuestionId"], True)

    monkeypatch.setattr(dialogs, "ask", fake_ask)
    t = win.pages[0].table
    wait_until(lambda: len(t.model.rows) == 5)
    t.model.setData(t.model.index(2, 0), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
    win.pages[0].install()
    d = win.ops[-1]
    assert d.op.args == ["install", "standard", "zed"]
    wait_until(lambda: d.exit_code is not None)
    assert d.exit_code == 0
    assert seen == ["q.transaction"]
    assert "Done." in d.logview.toPlainText()


def test_declined_aur_build_fails(win, monkeypatch):
    monkeypatch.setattr(dialogs, "ask", lambda q, parent=None:
                        dialogs.protocol.answer_pkgbuild(q["QuestionId"], False))
    d = win.run_op("x", ["install", "aur", "yay"], True)
    wait_until(lambda: d.exit_code is not None)
    assert d.exit_code == 1
    assert "Build declined." in d.status.text()


def test_flatpak_update_context_menu(win):
    page = win.pages[2]
    win.nav.setCurrentRow(2)
    wait_until(lambda: len(page.flatt.model.rows) == 2)
    view = page.flatt.view
    assert view.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    assert page.flatpak_menu(view.viewport().rect().bottomRight()) is None  # empty area
    pos = view.visualRect(page.flatt.proxy.index(0, 0)).center()
    menu = page.flatpak_menu(pos)
    acts = menu.actions()
    assert [a.text() for a in acts] == ["Update GIMP"]
    acts[0].trigger()
    d = win.ops[-1]
    assert d.op.args == ["update", "flatpak", "org.gimp.GIMP"]
    wait_until(lambda: d.exit_code is not None)
    assert d.exit_code == 0


def test_flatpak_update_context_menu_multi(win):
    page = win.pages[2]
    win.nav.setCurrentRow(2)
    wait_until(lambda: len(page.flatt.model.rows) == 2)
    view = page.flatt.view
    view.selectAll()
    menu = page.flatpak_menu(view.visualRect(page.flatt.proxy.index(1, 0)).center())
    assert [a.text() for a in menu.actions()] == ["Update 2 Flatpaks"]
    n = len(win.ops)
    menu.actions()[0].trigger()
    assert sorted(d.op.args[2] for d in win.ops[n:]) == ["org.gimp.GIMP", "org.kde.krita"]
    for d in win.ops[n:]:
        wait_until(lambda d=d: d.exit_code is not None)
