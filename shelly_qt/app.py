"""Main window."""
from __future__ import annotations

import sys

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QStackedWidget, QStatusBar, QWidget)

from . import __version__, cli
from .dialogs import OperationDialog
from .pages import (AppImagePage, AurPage, BrowsePage, FlatpakPage, InstalledPage, SettingsPage,
                    UpdatesPage, UtilitiesPage)

ICONS = {
    "Browse": "system-search", "Installed": "drive-harddisk", "Updates": "system-software-update",
    "AUR": "applications-development", "Flatpak": "package-x-generic", "AppImage": "application-x-executable",
    "Maintenance": "preferences-system", "Settings": "preferences-other",
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Shelly")
        self.resize(1180, 760)
        self.ops: list[OperationDialog] = []
        self._busy = 0

        self.nav = QListWidget()
        self.nav.setFixedWidth(180)
        self.nav.setIconSize(QSize(20, 20))
        self.nav.setStyleSheet("QListWidget{border:none;font-size:14px} QListWidget::item{padding:8px}")
        self.stack = QStackedWidget()
        self.pages = [BrowsePage(self), InstalledPage(self), UpdatesPage(self), AurPage(self),
                      FlatpakPage(self), AppImagePage(self), UtilitiesPage(self), SettingsPage(self)]
        for p in self.pages:
            item = QListWidgetItem(QIcon.fromTheme(ICONS.get(p.title, "")), p.title)
            self.nav.addItem(item)
            self.stack.addWidget(p)
        self.nav.currentRowChanged.connect(self._switch)

        central = QWidget()
        lay = QHBoxLayout(central)
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.setStatusBar(QStatusBar())
        self.busy_label = QLabel()
        self.statusBar().addPermanentWidget(self.busy_label)

        refresh = QAction("Refresh", self)
        refresh.setShortcut(QKeySequence.StandardKey.Refresh)
        refresh.triggered.connect(lambda: self.stack.currentWidget().refresh())
        self.addAction(refresh)
        about = QAction("About", self)
        about.setShortcut("F1")
        about.triggered.connect(self.about)
        self.addAction(about)

        self.nav.setCurrentRow(0)
        # background update check so the sidebar badge is populated
        self.pages[2].activate()

    # ---- helpers used by pages -------------------------------------------
    def _switch(self, i: int) -> None:
        self.stack.setCurrentIndex(i)
        self.pages[i].activate()

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

    def run_op(self, title: str, args: list[str], privileged: bool, on_success=None) -> OperationDialog:
        d = OperationDialog(title, args, privileged)
        d.setWindowIcon(self.windowIcon())
        self.ops.append(d)

        def finished(code: int) -> None:
            self.status(f"{title}: {'done' if code == 0 else 'failed'}")
            if code == 0 and on_success:
                on_success()

        d.completed.connect(finished)
        d.finished.connect(lambda *_: self.ops.remove(d) if d in self.ops else None)
        d.run()
        return d

    def about(self) -> None:
        QMessageBox.about(self, "About Shelly-Qt",
                          f"<b>Shelly-Qt {__version__}</b><p>A PySide6 front end for the "
                          "<a href='https://github.com/Seafoam-Labs/Shelly-ALPM'>Shelly</a> package "
                          f"manager.</p><p>CLI: <code>{' '.join(cli.shelly_bin())}</code></p>")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Shelly-Qt")
    app.setDesktopFileName("shelly-qt")
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
