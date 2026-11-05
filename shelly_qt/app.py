"""Main window."""
from __future__ import annotations

import os
import signal
import sys
from html import escape
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
                               QStackedWidget,
                               QStatusBar, QVBoxLayout, QWidget)

from . import __version__, cli, selfupdate
from .dialogs import OperationDialog
from .links import install_url_handler
from .openfile import Target, targets_from_argv
from .pages import (AppImagePage, AurPage, BrowsePage, FlatpakPage, InstalledPage, PrefixDevPage,
                    SettingsPage, UpdatesPage, UtilitiesPage)
from .search_page import SearchPage
from .search_sources import SOURCES

ICONS = {
    "Browse": "system-search", "Installed": "drive-harddisk", "Updates": "system-software-update",
    "AUR": "applications-development", "prefix.dev": "applications-science",
    "Flatpak": "package-x-generic", "AppImage": "application-x-executable",
    "Maintenance": "preferences-system", "Settings": "preferences-other",
}


ICON_DIR = Path(__file__).resolve().parent / "icons"


def app_icon() -> QIcon:
    """The Shelly-Qt icon: installed theme icon if present, else the bundled files."""
    icon = QIcon()
    for png in sorted(ICON_DIR.glob("shelly-qt-*.png")):
        icon.addFile(str(png))
    svg = ICON_DIR / "shelly-qt.svg"
    if svg.exists():
        icon.addFile(str(svg))
    return QIcon.fromTheme("shelly-qt", icon)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Shelly")
        self.setWindowIcon(app_icon())
        self.resize(1180, 760)
        self.ops: list[OperationDialog] = []
        self._busy = 0

        self.nav = QListWidget()
        self.nav.setFixedWidth(180)
        self.nav.setIconSize(QSize(20, 20))
        self.nav.setStyleSheet("QListWidget{border:none;font-size:14px} QListWidget::item{padding:8px}")
        self.stack = QStackedWidget()
        self.pages = [BrowsePage(self), InstalledPage(self), UpdatesPage(self), AurPage(self),
                      PrefixDevPage(self), FlatpakPage(self), AppImagePage(self), UtilitiesPage(self),
                      SettingsPage(self)]
        for p in self.pages:
            item = QListWidgetItem(QIcon.fromTheme(ICONS.get(p.title, "")), p.title)
            self.nav.addItem(item)
            self.stack.addWidget(p)
        self.nav.currentRowChanged.connect(self._switch)
        # combined search: lives in the stack but not in the sidebar
        self.search_page = SearchPage(self)
        self.stack.addWidget(self.search_page)

        self.search_box = QLineEdit()
        self.search_box.setClearButtonEnabled(True)
        self.search_box.addAction(QIcon.fromTheme("system-search"), QLineEdit.ActionPosition.LeadingPosition)
        labels = ", ".join(s.label for s in SOURCES)
        self.search_box.setPlaceholderText(f"Search all packages ({labels}) — press Enter   Ctrl+K")
        self.search_box.returnPressed.connect(lambda: self.search_all(self.search_box.text()))

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.addWidget(self.search_box)
        lay = QHBoxLayout()
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
        outer.addLayout(lay, 1)
        self.setCentralWidget(central)

        self.setStatusBar(QStatusBar())
        self.busy_label = QLabel()
        self.statusBar().addPermanentWidget(self.busy_label)
        # shown when the quiet startup check finds a newer AppImage
        self.update_button = QPushButton(QIcon.fromTheme("software-update-available"), "Update available")
        self.update_button.setFlat(True)
        self.update_button.setToolTip("A newer Shelly-Qt AppImage is available. Click to update.")
        self.update_button.clicked.connect(lambda: self.check_for_updates(update_known=True))
        self.update_button.hide()
        self.statusBar().addPermanentWidget(self.update_button)
        self.update_dialog: selfupdate.UpdateDialog | None = None
        self._update_check: selfupdate.UpdateCheck | None = None

        refresh = QAction("Refresh", self)
        refresh.setShortcut(QKeySequence.StandardKey.Refresh)
        refresh.triggered.connect(lambda: self.stack.currentWidget().refresh())
        self.addAction(refresh)
        find = QAction("Search all packages", self)
        find.setShortcuts([QKeySequence("Ctrl+K"), QKeySequence("Ctrl+Shift+F")])
        find.triggered.connect(self.focus_search)
        self.addAction(find)
        about = QAction("About", self)
        about.setShortcut("F1")
        about.triggered.connect(self.about)
        self.addAction(about)
        self.update_action = QAction(QIcon.fromTheme("system-software-update"), "Check for updates…", self)
        self.update_action.triggered.connect(lambda: self.check_for_updates())
        self.update_action.setVisible(selfupdate.available())
        self.addAction(self.update_action)
        if selfupdate.available() and not os.environ.get("SHELLY_QT_NO_UPDATE_CHECK"):
            QTimer.singleShot(3000, self._quiet_update_check)

        self.nav.setCurrentRow(0)
        # background update check so the sidebar badge is populated
        self.pages[2].activate()

    # ---- helpers used by pages -------------------------------------------
    def _switch(self, i: int) -> None:
        if i < 0:
            return
        self.stack.setCurrentIndex(i)
        self.pages[i].activate()

    def focus_search(self) -> None:
        self.search_box.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_box.selectAll()

    def search_all(self, text: str) -> None:
        """Show the combined search page with results for ``text`` from every source."""
        if not text.strip():
            return
        self.search_box.setText(text)
        self.nav.setCurrentRow(-1)
        self.stack.setCurrentWidget(self.search_page)
        self.search_page.search(text)

    def status(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 8000)

    def busy(self, msg: str) -> None:
        self._busy += 1
        self.busy_label.setText(msg)

    def idle(self, err: str | None = None) -> None:
        self._busy = max(0, self._busy - 1)
        if not self._busy:
            self.busy_label.setText("")
        if err:
            self.status("Error: " + err.splitlines()[0])
            QMessageBox.warning(self, "Shelly", err)

    def set_update_count(self, n: int) -> None:
        self.nav.item(2).setText(f"Updates ({n})" if n else "Updates")

    def refresh_all(self, *_):
        for p in self.pages:
            if p.loaded:
                p.refresh()
        if self.search_page.query:
            self.search_page.refresh()

    def run_op(self, title: str, args: list[str], privileged: bool, on_success=None) -> OperationDialog:
        d = OperationDialog(title, args, privileged)
        d.setWindowIcon(self.windowIcon())
        self.ops.append(d)

        def finished(code: int) -> None:
            self.status(f"{title}: {'done' if code == 0 else 'failed'}")
            if code == 0 and on_success:
                on_success()

        d.completed.connect(finished)
        d.run_follow_up = lambda t, a, priv, then: self.run_op(t, a, priv, then or on_success)
        d.finished.connect(lambda *_: self.ops.remove(d) if d in self.ops else None)
        d.run()
        return d

    # ---- files / links passed on the command line ("Open with…") ----------
    def go_to(self, page_cls) -> object:
        for i, p in enumerate(self.pages):
            if isinstance(p, page_cls):
                self.nav.setCurrentRow(i)
                return p
        raise LookupError(page_cls)

    def open_target(self, t: Target) -> None:
        html = escape
        if t.kind == "appid":
            self.go_to(FlatpakPage).show_app(t.value)
            return
        if t.kind in ("flatpakref", "bundle"):
            page = self.go_to(FlatpakPage)
            if t.kind == "flatpakref" and t.info.get("Name") and t.info.get("IsRuntime", "").lower() != "true":
                page.show_app(t.info["Name"], search=self._from_flathub(t))
            rows = [("Name", t.info.get("Title")), ("App ID", t.info.get("Name")),
                    ("Branch", t.info.get("Branch")), ("Source", t.info.get("Url")),
                    ("Homepage", t.info.get("Homepage")), ("File", t.value)]
            info = "".join(f"<tr><td><b>{k}</b>&nbsp;</td><td>{html(v)}</td></tr>" for k, v in rows if v)
            desc = t.info.get("Comment") or t.info.get("Description")
            kind = "Flatpak bundle" if t.kind == "bundle" else "Flatpak"
            text = (f"<p>Install the {kind} <b>{html(t.name)}</b>?</p><table>{info}</table>"
                    + (f"<p>{html(desc)}</p>" if desc else ""))
            box = QMessageBox(QMessageBox.Icon.Question, f"Install {kind}", text,
                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
            box.setTextFormat(Qt.TextFormat.RichText)
            box.button(QMessageBox.StandardButton.Yes).setText("Install")
            user = QCheckBox("Install for current user only")
            user.setChecked(page.user_scope.isChecked())
            box.setCheckBox(user)
            if box.exec() != QMessageBox.StandardButton.Yes:
                return
            args = ["install", "flatpak", "--ref-file" if t.kind == "flatpakref" else "--bundle", t.value]
            if user.isChecked():
                args.append("--user")
            self.run_op(f"Installing {t.name}", args, False, page.refresh)
            return
        if t.kind == "appimage":
            page = self.go_to(AppImagePage)
            if self._ask("Install AppImage", f"Install the AppImage <b>{html(t.name)}</b>?",
                         t.value):
                self.run_op(f"Installing {t.name}", ["install", "appimage", t.value], False, page.refresh)
            return
        if t.kind == "pkg":
            self.go_to(UtilitiesPage)
            if self._ask("Install local package", f"Install the package <b>{html(t.name)}</b>?",
                         t.value):
                self.run_op(f"Installing {t.name}", ["install", "standard", t.value], True,
                            self.refresh_all)
            return
        if t.kind == "flatpakrepo":
            self.go_to(FlatpakPage)
            QMessageBox.information(self, "Flatpak repository",
                                    f"{t.name} is a Flatpak repository file. Shelly can't add "
                                    "remotes yet; run <code>flatpak remote-add --if-not-exists "
                                    f"{html(Path(t.value).stem)} {html(t.value)}</code> instead.")
            return
        QMessageBox.warning(self, "Shelly", f"Shelly-Qt doesn't know how to open {html(t.value)}.")

    @staticmethod
    def _from_flathub(t: Target) -> bool:
        return "flathub" in (t.info.get("Url", "") + t.info.get("RuntimeRepo", "")).lower()

    def _ask(self, title: str, text: str, path: str) -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, title,
                          f"<p>{text}</p><p><small>{escape(path)}</small></p>",
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.button(QMessageBox.StandardButton.Yes).setText("Install")
        return box.exec() == QMessageBox.StandardButton.Yes

    # ---- AppImage self-update ----------------------------------------------
    def check_for_updates(self, update_known: bool = False) -> None:
        """Open the update dialog (only meaningful when running from an AppImage)."""
        path = selfupdate.appimage_path()
        if not path or not selfupdate.available():
            QMessageBox.information(self, "Check for updates",
                                    "Shelly-Qt updates itself only when run from its AppImage. "
                                    "Update this copy the way you installed it.")
            return
        if self.update_dialog and self.update_dialog.isVisible():
            self.update_dialog.raise_()
            self.update_dialog.activateWindow()
            return
        self.update_dialog = selfupdate.UpdateDialog(path, self, update_known=update_known)
        self.update_dialog.setWindowIcon(self.windowIcon())
        self.update_dialog.finished.connect(self._update_dialog_closed)
        self.update_dialog.show()

    def _update_dialog_closed(self, *_):
        d = self.update_dialog
        if d and d.state in ("current", "updated"):
            self.update_button.hide()

    def _quiet_update_check(self) -> None:
        path = selfupdate.appimage_path()
        if not path:
            return
        self._update_check = selfupdate.UpdateCheck(path, self)
        self._update_check.done.connect(self._quiet_update_done)
        self._update_check.start()

    def _quiet_update_done(self, avail: bool, err: str) -> None:
        if avail:
            self.update_button.show()
            self.status("A newer Shelly-Qt is available")

    def about(self) -> None:
        QMessageBox.about(self, "About Shelly-Qt",
                          f"<b>Shelly-Qt {__version__}</b><p>A PySide6 front end for the "
                          "<a href='https://github.com/Seafoam-Labs/Shelly-ALPM'>Shelly</a> package "
                          f"manager.</p><p>CLI: <code>{' '.join(cli.shelly_bin())}</code></p>")


def desktop_entry_installed(app_id: str) -> bool:
    """True if <app_id>.desktop is in an XDG applications dir (as the portal sees it)."""
    import os
    home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    dirs = [home, *(os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":"),
            "/usr/local/share", "/usr/share"]
    return any((Path(d) / "applications" / f"{app_id}.desktop").is_file() for d in dirs if d)


def install_sigint_handler(app: QApplication) -> QTimer:
    """Quit cleanly on Ctrl+C in the launching terminal.

    Python only runs signal handlers between bytecodes, and Qt's C++ event loop
    never returns to Python on its own, so a SIGINT would sit unhandled. A cheap
    periodic timer hands control back to the interpreter so the handler fires.
    """
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    timer = QTimer(app)
    timer.timeout.connect(lambda: None)
    timer.start(200)
    return timer


def main() -> int:
    if "--version" in sys.argv[1:]:
        print(f"shelly-qt {__version__}")
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName("Shelly-Qt")
    if desktop_entry_installed("shelly-qt"):
        # Only claim the app id when its .desktop file exists; otherwise the
        # xdg-desktop-portal registry rejects it with a startup warning.
        app.setDesktopFileName("shelly-qt")
    install_url_handler()
    app.setWindowIcon(app_icon())
    install_sigint_handler(app)
    w = MainWindow()
    w.show()
    for t in targets_from_argv(app.arguments()[1:]):
        QTimer.singleShot(0, lambda t=t: w.open_target(t))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
