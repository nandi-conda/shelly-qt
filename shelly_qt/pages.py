"""The application's pages: one per Shelly feature area."""
from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget, QDialog,
                               QDialogButtonBox, QMenu)

from . import cli, protocol
from .widgets import PackageTable, details_html, key

if TYPE_CHECKING:
    from .app import MainWindow

size = lambda name: (lambda r: protocol.human_size(r.get(name)) if r.get(name) else "")  # noqa: E731


def ts(v) -> str:
    try:
        return dt.datetime.fromtimestamp(int(v)).strftime("%Y-%m-%d") if v else ""
    except Exception:
        return str(v)


class Page(QWidget):
    title = ""
    icon = ""

    def __init__(self, main: "MainWindow") -> None:
        super().__init__()
        self.main = main
        self.loaded = False

    def activate(self) -> None:
        if not self.loaded:
            self.loaded = True
            self.refresh()

    def refresh(self) -> None:
        pass

    def names(self, rows: list[dict], field: str = "Name") -> list[str]:
        return [str(r.get(field)) for r in rows if r.get(field)]

    def need_selection(self, rows: list) -> bool:
        if not rows:
            QMessageBox.information(self, "Shelly", "Check or select at least one item first.")
            return False
        return True


# --------------------------------------------------------------------- repos

def package_details(p: dict) -> str:
    return details_html(f"{p.get('Name', '')} {p.get('Version', '')}", [
        ("Repository", p.get("Repository")),
        ("URL", p.get("Url")),
        ("Installed", "yes" if p.get("Installed") else "no"),
        ("Install reason", p.get("InstallReason")),
        ("Licenses", p.get("Licenses")),
        ("Groups", p.get("Groups")),
        ("Provides", p.get("Provides")),
        ("Depends on", p.get("Depends")),
        ("Optional deps", p.get("OptDepends")),
        ("Required by", p.get("RequiredBy")),
        ("Optional for", p.get("OptionalFor")),
        ("Conflicts", p.get("Conflicts")),
        ("Replaces", p.get("Replaces")),
        ("Download size", protocol.human_size(p.get("DownloadSize")) if p.get("DownloadSize") else ""),
        ("Installed size", protocol.human_size(p.get("InstalledSize") or p.get("Size")) if (p.get("InstalledSize") or p.get("Size")) else ""),
        ("Build date", p.get("BuildDate")),
        ("Install date", p.get("InstallDate")),
    ], p.get("Description", ""))


class _DetailMixin:
    table: PackageTable

    def _show_details(self, row: dict | None) -> None:
        if not row:
            return
        self.table.detail.setHtml(package_details(row))
        name = row.get("Name")
        if not name:
            return

        def done(res, err, name=name):
            cur = self.table.current_row()
            if err or not isinstance(res, dict) or not cur or cur.get("Name") != name:
                return
            merged = {**cur, **{k: v for k, v in res.items() if v not in (None, "", [])}}
            self.table.detail.setHtml(package_details(merged))

        cli.query(["-Ssdi", name], done)


class BrowsePage(_DetailMixin, Page):
    title = "Browse"

    def __init__(self, main) -> None:
        super().__init__(main)
        self.table = PackageTable([
            ("Name", key("Name")), ("Version", key("Version")), ("Repository", key("Repository")),
            ("Installed", key("Installed", False)), ("Size", size("Size")),
            ("Description", key("Description")),
        ], placeholder="Search repository packages…")
        self.not_installed = QCheckBox("Hide installed")
        self.table.toolbar.addWidget(self.not_installed)
        self.not_installed.toggled.connect(self._apply)
        self.table.add_button("Install", self.install, "Install checked packages from the repositories")
        self.table.add_button("Refresh", self.refresh)
        self.table.current_changed.connect(self._show_details)
        QVBoxLayout(self).addWidget(self.table)

    def _apply(self) -> None:
        self.table.proxy.extra = (lambda r: not r.get("Installed")) if self.not_installed.isChecked() else None
        self.table.proxy.refilter()

    def refresh(self) -> None:
        self.main.busy("Loading repository packages…")
        cli.query(["-Ssv"], self._loaded, parse=lambda t: protocol.last_data(t, []))

    def _loaded(self, res, err) -> None:
        self.main.idle(err)
        if not err:
            self.table.set_rows(res or [])

    def install(self) -> None:
        rows = self.table.targets()
        if self.need_selection(rows):
            self.main.run_op(f"Installing {len(rows)} package(s)",
                             ["install", "standard", *self.names(rows)], True, self.main.refresh_all)


class InstalledPage(_DetailMixin, Page):
    title = "Installed"

    def __init__(self, main) -> None:
        super().__init__(main)
        self.table = PackageTable([
            ("Name", key("Name")), ("Version", key("Version")), ("Repository", key("Repository")),
            ("Explicit", key("Explicit", False)), ("Size", size("InstalledSize")),
            ("Description", key("Description")),
        ], placeholder="Filter installed packages…")
        self.explicit = QCheckBox("Explicit only")
        self.explicit.toggled.connect(self._apply)
        self.table.toolbar.addWidget(self.explicit)
        self.table.add_button("Remove…", self.remove)
        self.table.add_button("Refresh", self.refresh)
        self.table.current_changed.connect(self._show_details)
        QVBoxLayout(self).addWidget(self.table)

    def _apply(self) -> None:
        self.table.proxy.extra = (lambda r: r.get("Explicit") or r.get("InstallReason") == "Explicit") \
            if self.explicit.isChecked() else None
        self.table.proxy.refilter()

    def refresh(self) -> None:
        self.main.busy("Loading installed packages…")
        cli.query(["-Ls"], self._loaded, parse=lambda t: protocol.last_data(t, []))

    def _loaded(self, res, err) -> None:
        self.main.idle(err)
        if not err:
            self.table.set_rows(res or [])

    def remove(self) -> None:
        rows = self.table.targets()
        if not self.need_selection(rows):
            return
        opts = RemoveOptions(self.names(rows), self)
        if opts.exec():
            self.main.run_op(f"Removing {len(rows)} package(s)",
                             ["remove", "standard", *self.names(rows), *opts.flags()], True,
                             self.main.refresh_all)


class RemoveOptions(QDialog):
    def __init__(self, names: list[str], parent=None, aur: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("Remove packages")
        lay = QVBoxLayout(self)
        lbl = QLabel("Remove: " + ", ".join(names))
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        self.cascade = QCheckBox("Also remove dependencies no longer needed (cascade)")
        self.cascade.setChecked(True)
        self.optdeps = QCheckBox("Also remove optional dependencies")
        self.configs = QCheckBox("Remove configuration files")
        lay.addWidget(self.cascade)
        if not aur:
            lay.addWidget(self.optdeps)
            lay.addWidget(self.configs)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def flags(self) -> list[str]:
        f = []
        if not self.cascade.isChecked():
            f.append("--no-cascade")
        if self.optdeps.isChecked():
            f.append("--opt-deps")
        if self.configs.isChecked():
            f.append("--remove-config")
        return f


# ------------------------------------------------------------------- updates

class UpdatesPage(Page):
    title = "Updates"

    def __init__(self, main) -> None:
        super().__init__(main)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.summary = QLabel("Press “Check for updates”.")
        top.addWidget(self.summary, 1)
        self.repo = QCheckBox("Repositories")
        self.aur = QCheckBox("AUR")
        self.flat = QCheckBox("Flatpak")
        for c in (self.repo, self.aur, self.flat):
            c.setChecked(True)
            top.addWidget(c)
        b_sync = QPushButton("Sync databases")
        b_sync.clicked.connect(self.sync)
        b_check = QPushButton("Check for updates")
        b_check.clicked.connect(self.refresh)
        self.b_up = QPushButton("Upgrade all")
        self.b_up.clicked.connect(self.upgrade)
        for b in (b_sync, b_check, self.b_up):
            top.addWidget(b)
        lay.addLayout(top)
        self.tabs = QTabWidget()
        self.pkgs = PackageTable([
            ("Name", key("Name")), ("Current", key("CurrentVersion")), ("New", key("NewVersion")),
            ("Repository", key("Repository")), ("Download", size("DownloadSize")),
            ("Δ Size", size("SizeDifference")),
        ], checkable=False)
        self.aurt = PackageTable([
            ("Name", key("Name")), ("Current", key("Version")), ("New", key("NewVersion")),
            ("Base", key("PackageBase")), ("Description", key("Description")),
        ], checkable=False)
        self.flatt = PackageTable([
            ("Name", key("Name")), ("Id", key("Id")), ("Current", key("Version")),
            ("New", key("NewVersion")), ("Branch", key("Branch")), ("Remote", key("Remote")),
            ("Download", size("DownloadSize")),
        ], checkable=False)
        self.tabs.addTab(self.pkgs, "Repositories")
        self.tabs.addTab(self.aurt, "AUR")
        self.tabs.addTab(self.flatt, "Flatpak")
        lay.addWidget(self.tabs, 1)
        self.pkgs.current_changed.connect(lambda r: r and self.pkgs.detail.setHtml(details_html(
            r.get("Name", ""), [("Current", r.get("CurrentVersion")), ("New", r.get("NewVersion")),
                                ("Repository", r.get("Repository")), ("URL", r.get("Url")),
                                ("Depends on", r.get("Depends"))], r.get("Description", ""))))
        self.aurt.current_changed.connect(lambda r: r and self.aurt.detail.setHtml(details_html(
            r.get("Name", ""), [("Current", r.get("Version")), ("New", r.get("NewVersion")),
                                ("URL", r.get("Url"))], r.get("Description", ""))))
        self.flatt.current_changed.connect(lambda r: r and self.flatt.detail.setHtml(details_html(
            r.get("Name", ""), [("Id", r.get("Id")), ("Ref", r.get("FullRef")),
                                ("Permissions", r.get("Permissions"))], r.get("Summary", ""))))
        self.flatt.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.flatt.view.customContextMenuRequested.connect(
            lambda pos: (m := self.flatpak_menu(pos)) and m.exec(self.flatt.view.viewport().mapToGlobal(pos)))

    def flatpak_menu(self, pos) -> QMenu | None:
        """Context menu for the Flatpak updates table at viewport position ``pos``."""
        view = self.flatt.view
        idx = view.indexAt(pos)
        if not idx.isValid():
            return None
        if not view.selectionModel().isRowSelected(idx.row(), idx.parent()):
            view.selectRow(idx.row())
        view.selectionModel().setCurrentIndex(idx, QItemSelectionModel.SelectionFlag.NoUpdate)
        rows = self.flatt.targets()
        if not rows:
            return None
        menu = QMenu(view)
        label = (f"Update {rows[0].get('Name') or rows[0].get('Id')}" if len(rows) == 1
                 else f"Update {len(rows)} Flatpaks")
        menu.addAction(label, lambda: self.update_flatpaks(rows))
        return menu

    def update_flatpaks(self, rows: list[dict]) -> None:
        for r in rows:
            target = r.get("Id") or r.get("Name")
            if target:
                self.main.run_op(f"Updating {r.get('Name') or target}", ["update", "flatpak", target],
                                 True, self.refresh)

    def refresh(self) -> None:
        self.main.busy("Checking for updates…")
        self.summary.setText("Checking…")
        cli.query(["-P"], self._loaded, parse=lambda t: protocol.last_data(t, {}))

    def _loaded(self, res, err) -> None:
        self.main.idle(err)
        if err:
            self.summary.setText("Could not check for updates.")
            return
        res = res if isinstance(res, dict) else {}
        p, a, f = res.get("Packages") or [], res.get("Aur") or [], res.get("Flatpak") or []
        self.pkgs.set_rows(p)
        self.aurt.set_rows(a)
        self.flatt.set_rows(f)
        self.tabs.setTabText(0, f"Repositories ({len(p)})")
        self.tabs.setTabText(1, f"AUR ({len(a)})")
        self.tabs.setTabText(2, f"Flatpak ({len(f)})")
        total = len(p) + len(a) + len(f)
        self.summary.setText(f"{total} update(s) available." if total else "System is up to date.")
        self.main.set_update_count(total)

    def sync(self) -> None:
        self.main.run_op("Synchronizing package databases", ["sync", "--force"], True, self.refresh)

    def upgrade(self) -> None:
        args = ["upgrade", "all"]
        if not self.flat.isChecked():
            args.append("--no-flatpak")
        if not self.aur.isChecked():
            args.append("--no-aur")
        if not self.repo.isChecked():
            args.append("--no-repo")
        self.main.run_op("Upgrading system", args, True, self.main.refresh_all)


# ----------------------------------------------------------------------- AUR

def aur_details(r: dict) -> str:
    return details_html(f"{r.get('Name', '')} {r.get('Version', '')}", [
        ("Package base", r.get("PackageBase")), ("URL", r.get("Url")),
        ("AUR page", f"https://aur.archlinux.org/packages/{r.get('Name', '')}"),
        ("Maintainer", r.get("Maintainer") or "orphan"),
        ("Votes", r.get("NumVotes")), ("Popularity", r.get("Popularity")),
        ("Out of date", ts(r.get("OutOfDate"))), ("Submitted", ts(r.get("FirstSubmitted"))),
        ("Modified", ts(r.get("LastModified"))), ("Licenses", r.get("License")),
        ("Depends on", r.get("Depends")), ("Make deps", r.get("MakeDepends")),
        ("Optional deps", r.get("OptDepends")), ("Provides", r.get("Provides")),
        ("Conflicts", r.get("Conflicts")), ("Keywords", r.get("Keywords")),
    ], r.get("Description") or "")


AUR_COLS = [
    ("Name", key("Name")), ("Version", key("Version")), ("Votes", key("NumVotes", 0)),
    ("Popularity", lambda r: round(float(r.get("Popularity") or 0), 2)),
    ("Maintainer", lambda r: r.get("Maintainer") or "orphan"),
    ("Out of date", lambda r: "yes" if r.get("OutOfDate") else ""),
    ("Description", key("Description")),
]


class AurPage(Page):
    title = "AUR"

    def __init__(self, main) -> None:
        super().__init__(main)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        # search tab
        search = QWidget()
        sl = QVBoxLayout(search)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search the AUR (press Enter)…")
        self.query.returnPressed.connect(self.search)
        go = QPushButton("Search")
        go.clicked.connect(self.search)
        row.addWidget(self.query, 1)
        row.addWidget(go)
        sl.addLayout(row)
        self.results = PackageTable(AUR_COLS, placeholder="Filter results…")
        self.results.add_button("Review PKGBUILD", lambda: self.preview(self.results))
        self.results.add_button("Install", self.install)
        self.results.current_changed.connect(lambda r: r and self.results.detail.setHtml(aur_details(r)))
        sl.addWidget(self.results, 1)
        # installed tab
        self.installed = PackageTable(AUR_COLS, placeholder="Filter installed AUR packages…")
        self.installed.add_button("Review PKGBUILD", lambda: self.preview(self.installed))
        self.installed.add_button("Remove…", self.remove)
        self.installed.add_button("Refresh", self.refresh)
        self.installed.current_changed.connect(lambda r: r and self.installed.detail.setHtml(aur_details(r)))
        self.tabs.addTab(search, "Search")
        self.tabs.addTab(self.installed, "Installed")
        lay.addWidget(self.tabs)

    def refresh(self) -> None:
        self.main.busy("Loading installed AUR packages…")
        cli.query(["list", "aur"], self._installed, parse=lambda t: protocol.last_data(t, []))

    def _installed(self, res, err) -> None:
        self.main.idle(err)
        if not err:
            self.installed.set_rows(res or [])

    def search(self) -> None:
        q = self.query.text().strip()
        if len(q) < 2:
            return
        self.main.busy(f"Searching the AUR for “{q}”…")
        cli.query(["search", "aur", q], self._searched, parse=lambda t: protocol.last_data(t, []))

    def _searched(self, res, err) -> None:
        self.main.idle(err)
        if not err:
            self.results.set_rows(res or [])

    def preview(self, table: PackageTable) -> None:
        row = table.current_row() or (table.targets() or [None])[0]
        if not row:
            return self.need_selection([])
        name = row.get("Name")
        self.main.busy(f"Fetching PKGBUILD for {name}…")
        cli.query(["search", "aur", name, "--pkgbuild"], lambda r, e: self._show_pkgbuild(name, r, e),
                  parse=lambda t: protocol.last_data(t, []))

    def _show_pkgbuild(self, name, res, err) -> None:
        self.main.idle(err)
        if err:
            return
        items = res if isinstance(res, list) else [res]
        d = QDialog(None, Qt.WindowType.Window)  # standalone, non-blocking viewer
        d.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        d.setWindowTitle(f"PKGBUILD — {name}")
        d.resize(860, 620)
        lay = QVBoxLayout(d)
        tabs = QTabWidget()
        for it in items:
            if not isinstance(it, dict):
                continue
            ed = QPlainTextEdit(it.get("PkgBuild", ""))
            ed.setReadOnly(True)
            ed.setStyleSheet("font-family: monospace;")
            tabs.addTab(ed, it.get("Name", name))
        lay.addWidget(tabs)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(d.close)
        lay.addWidget(bb)
        self._viewers = [v for v in getattr(self, "_viewers", []) if v.isVisible()] + [d]
        d.show()

    def install(self) -> None:
        rows = self.results.targets()
        if self.need_selection(rows):
            self.main.run_op(f"Building and installing {len(rows)} AUR package(s)",
                             ["install", "aur", *self.names(rows)], True, self.main.refresh_all)

    def remove(self) -> None:
        rows = self.installed.targets()
        if not self.need_selection(rows):
            return
        opts = RemoveOptions(self.names(rows), self, aur=True)
        if opts.exec():
            self.main.run_op(f"Removing {len(rows)} AUR package(s)",
                             ["remove", "aur", *self.names(rows), *opts.flags()], True,
                             self.main.refresh_all)


# ------------------------------------------------------------------- Flatpak

class FlatpakPage(Page):
    title = "Flatpak"

    def __init__(self, main) -> None:
        super().__init__(main)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.installed = PackageTable([
            ("Name", key("Name")), ("Id", key("Id")), ("Version", key("Version")),
            ("Remote", key("Remote")),
            ("Kind", lambda r: {0: "app", 1: "runtime"}.get(r.get("Kind"), r.get("Kind", ""))),
            ("Scope", lambda r: {0: "system", 1: "user"}.get(r.get("InstallLevel"), r.get("InstallLevel", ""))),
            ("Size", size("InstalledSize")),
        ], placeholder="Filter installed Flatpaks…")
        self.remove_config = QCheckBox("Remove app data")
        self.installed.toolbar.addWidget(self.remove_config)
        self.installed.add_button("Remove", self.remove)
        self.installed.add_button("Update all", self.update_all)
        self.installed.add_button("Refresh", self.refresh)

        search = QWidget()
        sl = QVBoxLayout(search)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search Flathub (press Enter)…")
        self.query.returnPressed.connect(self.search)
        go = QPushButton("Search")
        go.clicked.connect(self.search)
        row.addWidget(self.query, 1)
        row.addWidget(go)
        sl.addLayout(row)
        self.results = PackageTable([
            ("Name", key("name")), ("App ID", lambda r: r.get("app_id") or r.get("id", "")),
            ("Developer", key("developer_name")),
            ("Verified", key("verification_verified", False)),
            ("License", key("project_license")), ("Summary", key("summary")),
        ], placeholder="Filter results…")
        self.user_scope = QCheckBox("Install for current user only")
        self.results.toolbar.addWidget(self.user_scope)
        self.results.add_button("Install", self.install)
        self.results.current_changed.connect(lambda r: r and self.results.detail.setHtml(details_html(
            r.get("name", ""), [("App ID", r.get("app_id") or r.get("id")),
                                ("Developer", r.get("developer_name")),
                                ("License", r.get("project_license")),
                                ("Categories", r.get("main_categories")),
                                ("Keywords", r.get("keywords"))],
            r.get("description") or r.get("summary", ""))))
        sl.addWidget(self.results, 1)

        self.tabs.addTab(self.installed, "Installed")
        self.tabs.addTab(search, "Search Flathub")
        lay.addWidget(self.tabs)

    def refresh(self) -> None:
        self.main.busy("Loading installed Flatpaks…")
        cli.query(["-Lf"], self._loaded, parse=lambda t: protocol.last_data(t, []))

    def _loaded(self, res, err) -> None:
        self.main.idle(err)
        if not err:
            self.installed.set_rows(res or [])

    def search(self) -> None:
        q = self.query.text().strip()
        if not q:
            return
        self.main.busy(f"Searching Flathub for “{q}”…")
        cli.query(["search", "flatpak", q, "--limit", "50"], self._searched,
                  parse=lambda t: protocol.last_data(t, {}))

    def _searched(self, res, err) -> None:
        self.main.idle(err)
        if not err:
            self.results.set_rows((res or {}).get("hits", []) if isinstance(res, dict) else res or [])

    def install(self) -> None:
        rows = self.results.targets()
        if not self.need_selection(rows):
            return
        for r in rows:
            app_id = r.get("app_id") or r.get("id")
            args = ["install", "flatpak", app_id]
            if self.user_scope.isChecked():
                args.append("--user")
            self.main.run_op(f"Installing {r.get('name') or app_id}", args, False, self.refresh)

    def remove(self) -> None:
        rows = self.installed.targets()
        if not self.need_selection(rows):
            return
        for r in rows:
            args = ["remove", "flatpak", r.get("Id", "")]
            if self.remove_config.isChecked():
                args.append("--remove-config")
            args.append("--remove-unused")
            self.main.run_op(f"Removing {r.get('Name') or r.get('Id')}", args, False, self.refresh)

    def update_all(self) -> None:
        self.main.run_op("Updating Flatpaks", ["upgrade", "flatpak"], False, self.refresh)


# ------------------------------------------------------------------ AppImage

class AppImagePage(Page):
    title = "AppImage"

    def __init__(self, main) -> None:
        super().__init__(main)
        self.table = PackageTable([
            ("Name", lambda r: r.get("DesktopName") or r.get("Name", "")), ("Version", key("Version")),
            ("Update", lambda r: self.updates.get(r.get("Name"), "")), ("Size", size("SizeOnDisk")),
            ("Path", key("Path")), ("Description", key("Description")),
        ], placeholder="Filter AppImages…")
        self.updates: dict[str, str] = {}
        self.table.add_button("Install file…", self.install)
        self.table.add_button("Remove", self.remove)
        self.table.add_button("Check updates", self.check)
        self.table.add_button("Upgrade all", self.upgrade)
        self.table.add_button("Refresh", self.refresh)
        self.table.current_changed.connect(lambda r: r and self.table.detail.setHtml(details_html(
            r.get("DesktopName") or r.get("Name", ""), [
                ("Version", r.get("Version")), ("Path", r.get("Path")),
                ("Update source", r.get("UpdateURl") or r.get("RawUpdateInfo")),
                ("Repository", "/".join(x for x in (r.get("RepoOwner"), r.get("RepoName")) if x)),
                ("Arguments", r.get("CommandLineArgs"))], r.get("Description", ""))))
        QVBoxLayout(self).addWidget(self.table)

    def refresh(self) -> None:
        self.main.busy("Loading AppImages…")
        cli.query(["list", "appimage"], self._loaded, parse=lambda t: protocol.last_data(t, []))

    def _loaded(self, res, err) -> None:
        self.main.idle(err)
        if not err:
            self.table.set_rows(res or [])

    def check(self) -> None:
        self.main.busy("Checking AppImage updates…")
        cli.query(["list-updates", "appimage"], self._checked, parse=lambda t: protocol.last_data(t, []))

    def _checked(self, res, err) -> None:
        self.main.idle(err)
        if err:
            return
        self.updates = {u.get("Name"): u.get("Version", "") for u in res or []
                        if isinstance(u, dict) and u.get("IsUpdateAvailable")}
        self.table.model.layoutChanged.emit()
        self.main.status(f"{len(self.updates)} AppImage update(s) available.")

    def install(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose an AppImage", "",
                                              "AppImage (*.AppImage *.appimage);;All files (*)")
        if path:
            self.main.run_op("Installing AppImage", ["install", "appimage", path], False, self.refresh)

    def remove(self) -> None:
        for r in self.table.targets() or []:
            self.main.run_op(f"Removing {r.get('Name')}", ["remove", "appimage", r.get("Name", "")],
                             False, self.refresh)

    def upgrade(self) -> None:
        self.main.run_op("Upgrading AppImages", ["upgrade", "appimage"], False, self.refresh)


# ----------------------------------------------------------------- utilities

class UtilitiesPage(Page):
    title = "Maintenance"

    def __init__(self, main) -> None:
        super().__init__(main)
        lay = QVBoxLayout(self)

        def card(title: str, text: str, button: str, slot) -> None:
            box = QGroupBox(title)
            bl = QHBoxLayout(box)
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            bl.addWidget(lbl, 1)
            b = QPushButton(button)
            b.clicked.connect(slot)
            bl.addWidget(b)
            lay.addWidget(box)

        card("Synchronize databases", "Refresh package databases from your mirrors (shelly sync --force).",
             "Sync", lambda: main.run_op("Synchronizing databases", ["sync", "--force"], True))
        card("Remove orphans", "Remove packages installed as dependencies that nothing needs anymore.",
             "Remove orphans", lambda: main.run_op("Removing orphans", ["purify", "standard", "--orphans"],
                                                   True, main.refresh_all))
        self.keep = QSpinBox()
        self.keep.setRange(0, 10)
        self.keep.setValue(3)
        box = QGroupBox("Clean package cache")
        bl = QHBoxLayout(box)
        lbl = QLabel("Delete cached package archives, keeping this many versions of each, "
                     "and clear Shelly's AUR build cache.")
        lbl.setWordWrap(True)
        bl.addWidget(lbl, 1)
        bl.addWidget(QLabel("Keep:"))
        bl.addWidget(self.keep)
        b = QPushButton("Clean cache")
        b.clicked.connect(lambda: main.run_op(
            "Cleaning package cache",
            ["purify", "standard", "--cache", str(self.keep.value()), "--aur-cache"], True))
        bl.addWidget(b)
        lay.addWidget(box)
        card("Repair database", "Repair a corrupted local package database (shelly utility --repair-db).",
             "Repair", lambda: main.run_op("Repairing database", ["utility", "--repair-db"], True))
        card("Fix permissions", "Repair ownership of Shelly's cache and config directories for your user.",
             "Fix", lambda: main.run_op("Fixing permissions", ["utility", "--fix-permissions"], False))
        card("Install local package", "Install a package archive (.pkg.tar.zst) from disk.",
             "Choose file…", self.install_local)
        lay.addStretch()

    def install_local(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a package", "",
                                              "Arch packages (*.pkg.tar.zst *.pkg.tar.xz *.pkg.tar.gz);;All files (*)")
        if path:
            self.main.run_op("Installing local package", ["install", "standard", path], True,
                             self.main.refresh_all)


# ------------------------------------------------------------------ settings

class SettingsPage(Page):
    title = "Settings"

    def __init__(self, main) -> None:
        super().__init__(main)
        lay = QVBoxLayout(self)
        info = QLabel("Shelly's configuration (shelly config list). Double-click a value to change it; "
                      "changes are saved with shelly config set.")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter settings…")
        self.filter.textChanged.connect(self._filter)
        lay.addWidget(self.filter)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Setting", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.itemChanged.connect(self._changed)
        lay.addWidget(self.table, 1)
        b = QPushButton("Reload")
        b.clicked.connect(self.refresh)
        lay.addWidget(b, 0, Qt.AlignmentFlag.AlignRight)
        self._loading = False
        self._values: dict[str, str] = {}

    def refresh(self) -> None:
        cli.query(["config", "list"], self._loaded, parse=lambda t: protocol.last_data(t, {}))

    @staticmethod
    def _fmt(v) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (dict, list)):
            return json.dumps(v)
        return "" if v is None else str(v)

    def _loaded(self, res, err) -> None:
        if err:
            self.main.idle(err)
            return
        self._loading = True
        items = sorted((res or {}).items()) if isinstance(res, dict) else []
        self.table.setRowCount(len(items))
        self._values = {}
        for i, (k, v) in enumerate(items):
            ki = QTableWidgetItem(k)
            ki.setFlags(ki.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 0, ki)
            self.table.setItem(i, 1, QTableWidgetItem(self._fmt(v)))
            self._values[k] = self._fmt(v)
        self._loading = False
        self._filter(self.filter.text())

    def _filter(self, text: str) -> None:
        t = text.lower()
        for i in range(self.table.rowCount()):
            self.table.setRowHidden(i, t not in self.table.item(i, 0).text().lower())

    def _changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 1:
            return
        k = self.table.item(item.row(), 0).text()
        v = item.text()
        if self._values.get(k) == v:
            return

        def done(_res, err):
            if err:
                QMessageBox.warning(self, "Shelly", f"Could not set {k}:\n{err}")
                self.refresh()
            else:
                self._values[k] = v
                self.main.status(f"Saved {k} = {v}")

        cli.query(["config", "set", k, v], done, parse=lambda t: None)
