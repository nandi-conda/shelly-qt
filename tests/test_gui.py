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
    assert d.banner.isVisible() and d.banner.tone == "error"
    assert "Build declined." in d.banner.summary.text()



def menu_texts(menu):
    return [a.text() for a in menu.actions()] if menu else []


def menu_at(table, row):
    return table.context_menu(table.view.visualRect(table.proxy.index(row, 0)).center())


def trigger(win, menu, prefix):
    n = len(win.ops)
    [a for a in menu.actions() if a.text().startswith(prefix)][0].trigger()
    return win.ops[n:]


def finish(ops):
    for d in ops:
        wait_until(lambda d=d: d.exit_code is not None)
        assert d.exit_code == 0


@pytest.fixture
def answers(monkeypatch):
    """Auto-answer the removal confirmations; tests flip .ok to decline."""
    from shelly_qt import pages

    class A:
        ok = True
    monkeypatch.setattr(pages, "confirm", lambda *a: A.ok)
    monkeypatch.setattr(pages.RemoveOptions, "exec", lambda self: A.ok)
    monkeypatch.setattr(dialogs, "ask", lambda q, parent=None:
                        dialogs.protocol.answer_transaction(q["QuestionId"], True))
    return A



def updates_loaded(win):
    up = win.pages[2]
    wait_until(lambda: up.pending.get("flatpak"))
    return up


def test_context_menu_empty_space(win):
    win.nav.setCurrentRow(1)
    t = win.pages[1].table
    wait_until(lambda: len(t.model.rows) == 3)
    assert t.context_menu(t.view.viewport().rect().bottomRight()) is None


def test_updates_tabs_offer_update_and_remove(win):
    page = updates_loaded(win)
    assert menu_texts(menu_at(page.pkgs, 0)) == ["Update firefox (partial upgrade)…", "Remove firefox…"]
    assert menu_texts(menu_at(page.aurt, 0)) == ["Update yay", "Remove yay…"]
    assert menu_texts(menu_at(page.flatt, 0)) == ["Update GIMP", "Remove GIMP…"]
    ops = trigger(win, menu_at(page.pkgs, 0), "Update")
    ops += trigger(win, menu_at(page.aurt, 0), "Update")
    ops += trigger(win, menu_at(page.flatt, 0), "Update")
    assert [d.op.args for d in ops] == [["update", "standard", "firefox"], ["update", "aur", "yay"],
                                        ["update", "flatpak", "org.gimp.GIMP"]]
    finish(ops)


def test_updates_flatpak_multi(win, answers):
    page = updates_loaded(win)
    page.flatt.view.selectAll()
    menu = menu_at(page.flatt, 1)
    assert menu_texts(menu) == ["Update 2 Flatpaks", "Remove 2 Flatpaks…"]
    ops = trigger(win, menu, "Update")
    assert sorted(d.op.args[2] for d in ops) == ["org.gimp.GIMP", "org.kde.krita"]
    finish(ops)
    ops = trigger(win, menu, "Remove")
    assert sorted(d.op.args for d in ops) == [["remove", "flatpak", "org.gimp.GIMP", "--remove-unused"],
                                              ["remove", "flatpak", "org.kde.krita", "--remove-unused"]]
    finish(ops)


def test_remove_declined_runs_nothing(win, answers):
    answers.ok = False
    page = updates_loaded(win)
    assert trigger(win, menu_at(page.flatt, 0), "Remove") == []
    assert trigger(win, menu_at(page.pkgs, 0), "Remove") == []


def test_updates_repo_and_aur_remove(win, answers):
    page = updates_loaded(win)
    ops = trigger(win, menu_at(page.pkgs, 0), "Remove")
    assert ops[0].op.args[:3] == ["remove", "standard", "firefox"]
    finish(ops)
    ops = trigger(win, menu_at(page.aurt, 0), "Remove")
    finish(ops)


def test_installed_update_only_when_pending(win, answers):
    updates_loaded(win)
    win.nav.setCurrentRow(1)
    t = win.pages[1].table
    wait_until(lambda: len(t.model.rows) == 3)
    names = [t.row_at(t.proxy.index(i, 0))["Name"] for i in range(3)]
    ff, git = names.index("firefox"), names.index("git")
    assert menu_texts(menu_at(t, ff)) == ["Update firefox (partial upgrade)…", "Remove firefox…"]
    assert menu_texts(menu_at(t, git)) == ["Remove git…"]
    t.view.selectAll()
    menu = menu_at(t, 0)
    assert menu_texts(menu) == ["Remove 3 packages…"]
    ops = trigger(win, menu, "Remove")
    assert ops[0].op.args[:2] == ["remove", "standard"] and len(ops[0].op.args) >= 5
    finish(ops)


def test_browse_offers_install_or_remove(win, answers):
    updates_loaded(win)
    t = win.pages[0].table
    wait_until(lambda: len(t.model.rows) == 5)
    rows = [t.row_at(t.proxy.index(i, 0)) for i in range(5)]
    git = next(i for i, r in enumerate(rows) if r["Name"] == "git")
    ff = next(i for i, r in enumerate(rows) if r["Name"] == "firefox")
    avail = next(i for i, r in enumerate(rows) if not r["Installed"])
    assert menu_texts(menu_at(t, git)) == ["Remove git…"]
    assert menu_texts(menu_at(t, ff)) == ["Update firefox (partial upgrade)…", "Remove firefox…"]
    assert menu_texts(menu_at(t, avail)) == [f"Install {rows[avail]['Name']}"]
    t.view.selectAll()
    assert menu_texts(menu_at(t, 0)) == []  # mixed selection: nothing applies to all
    t.view.clearSelection()
    ops = trigger(win, menu_at(t, git), "Remove")
    assert ops[0].op.args[:3] == ["remove", "standard", "git"]
    finish(ops)


def test_aur_flatpak_appimage_menus(win, answers):
    updates_loaded(win)
    for i in range(3, 6):
        win.nav.setCurrentRow(i)
    aur, flat, appimg = win.pages[3].installed, win.pages[4].installed, win.pages[5].table
    wait_until(lambda: len(aur.model.rows) == 1 and len(flat.model.rows) == 1 and len(appimg.model.rows) == 1)
    assert menu_texts(menu_at(aur, 0)) == ["Update yay", "Remove yay…"]
    assert menu_texts(menu_at(flat, 0)) == ["Update GIMP", "Remove GIMP…"]
    assert menu_texts(menu_at(appimg, 0)) == ["Remove Obsidian…"]
    win.pages[5].check()
    wait_until(lambda: win.pages[5].updates)
    assert menu_texts(menu_at(appimg, 0)) == ["Update all AppImages", "Remove Obsidian…"]

    ops = trigger(win, menu_at(aur, 0), "Remove")
    win.pages[4].remove_config.setChecked(True)
    ops += trigger(win, menu_at(flat, 0), "Remove")
    ops += trigger(win, menu_at(appimg, 0), "Remove")
    ops += trigger(win, menu_at(flat, 0), "Update")
    ops += trigger(win, menu_at(appimg, 0), "Update")
    assert [d.op.args for d in ops] == [
        ["remove", "aur", "yay"],
        ["remove", "flatpak", "org.gimp.GIMP", "--remove-config", "--remove-unused"],
        ["remove", "appimage", "obsidian"],
        ["update", "flatpak", "org.gimp.GIMP"],
        ["upgrade", "appimage"]]
    finish(ops)


def test_real_right_click_opens_menu_on_every_updates_tab(win):
    """Send an actual context-menu event, not just build the menu."""
    from PySide6.QtGui import QContextMenuEvent
    up = updates_loaded(win)
    for t in (up.pkgs, up.aurt, up.flatt):
        up.tabs.setCurrentWidget(t)
        vp = t.view.viewport()
        pos = t.view.visualRect(t.proxy.index(0, 0)).center()
        seen = {}

        def grab(seen=seen):
            m = QApplication.activePopupWidget()
            seen["texts"] = [a.text() for a in m.actions()] if m else None
            if m:
                m.close()
        QTimer.singleShot(100, grab)
        QApplication.sendEvent(vp, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, vp.mapToGlobal(pos)))
        wait_until(lambda: "texts" in seen)
        assert seen["texts"] and seen["texts"][-1].startswith("Remove")


def test_open_flatpakref_goes_to_flatpak_page_and_installs(win, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    from shelly_qt.openfile import classify
    from shelly_qt.pages import FlatpakPage

    ref = tmp_path / "org.kde.krita.flatpakref"
    ref.write_text("[Flatpak Ref]\nName=org.kde.krita\nTitle=Krita\nBranch=stable\n"
                   "Url=https://dl.flathub.org/repo/\nIsRuntime=false\n")
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text())
                        or QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(dialogs, "ask", lambda q, parent=None:
                        dialogs.protocol.answer_transaction(q["QuestionId"], True))
    win.open_target(classify(str(ref)))
    page = win.stack.currentWidget()
    assert isinstance(page, FlatpakPage) and page.tabs.currentIndex() == 1
    assert page.query.text() == "org.kde.krita"
    assert "Krita" in shown[0]
    d = win.ops[-1]
    assert d.op.args == ["install", "flatpak", "--ref-file", str(ref)]
    wait_until(lambda: d.exit_code is not None)
    assert d.exit_code == 0
    wait_until(lambda: page.results.current_row() is not None)
    assert page.results.current_row()["app_id"] == "org.kde.krita"


def test_split_error():
    s, d = dialogs.split_error("Could not complete. App x is already installed\nPackage: /a.flatpakref\n\n"
                               "Technical details: FlatpakOperationFailed\nBackend: flatpak")
    assert s == "Could not complete. App x is already installed"
    assert d.startswith("Package: /a.flatpakref") and "Backend: flatpak" in d
