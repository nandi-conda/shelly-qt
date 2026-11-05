"""The application's pages: one per Shelly feature area."""
from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget, QDialog,
                               QDialogButtonBox)

from . import cli, downgrade, protocol, selfupdate
from .ranking import match_column, rank_rows
from .widgets import PackageTable, details_html, key

if TYPE_CHECKING:
    from .app import MainWindow

size = lambda name: (lambda r: protocol.human_size(r.get(name)) if r.get(name) else "")  # noqa: E731


def ts(v) -> str:
    try:
        return dt.datetime.fromtimestamp(int(v)).strftime("%Y-%m-%d") if v else ""
    except Exception:
        return str(v)


def what(rows: list[dict], noun: str = "packages") -> str:
    """'firefox' for one row, '3 packages' for several."""
    if len(rows) == 1:
        r = rows[0]
        return str(r.get("DesktopName") or r.get("Name") or r.get("name") or r.get("Id")
                   or r.get("app_id") or "")
    return f"{len(rows)} {noun}"


def confirm(parent, title: str, text: str) -> bool:
    return QMessageBox.question(parent, title, text,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes


def remove_packages(page: "Page", rows: list[dict], backend: str = "standard") -> None:
    """Remove repo (``standard``) or ``aur`` packages after asking for removal options."""
    if not page.need_selection(rows):
        return
    opts = RemoveOptions(page.names(rows), page, aur=backend == "aur")
    if opts.exec():
        kind = "AUR package(s)" if backend == "aur" else "package(s)"
        page.main.run_op(f"Removing {len(rows)} {kind}",
                         ["remove", backend, *page.names(rows), *opts.flags()], True,
                         page.main.refresh_all)


def update_packages(page: "Page", rows: list[dict], backend: str) -> None:
    """Update just these packages: ``standard`` (partial upgrade, the CLI warns), ``aur`` or ``flatpak``."""
    if not page.need_selection(rows):
        return
    if backend == "flatpak":
        for r in rows:
            target = r.get("Id") or r.get("Name")
            if target:
                page.main.run_op(f"Updating {what([r])}", ["update", "flatpak", target], True,
                                 page.main.refresh_all)
        return
    page.main.run_op(f"Updating {what(rows)}", ["update", backend, *page.names(rows)], True,
                     page.main.refresh_all)


def has_update(page: "Page", backend: str) -> Callable[[list[dict]], bool]:
    """Predicate: every row has a pending update, per the Updates page's last check."""
    field = "Id" if backend == "flatpak" else "Name"

    def check(rows: list[dict]) -> bool:
        pending = page.main.pages[2].pending.get(backend, set())
        return bool(rows) and all(r.get(field) in pending for r in rows)
    return check


def remove_flatpaks(page: "Page", rows: list[dict], remove_config: bool = False) -> None:
    if not page.need_selection(rows):
        return
    if not confirm(page, "Remove Flatpak", f"Remove {', '.join(what([r]) for r in rows)}?\n"
                   "Unused runtimes will be removed too."):
        return
    for r in rows:
        target = r.get("Id") or r.get("Name")
        if not target:
            continue
        args = ["remove", "flatpak", target]
        if remove_config:
            args.append("--remove-config")
        args.append("--remove-unused")
        page.main.run_op(f"Removing {what([r])}", args, False, page.main.refresh_all)


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
        self.table.add_context_action(lambda rows: f"Install {what(rows)}", self.install_rows,
                                      lambda rows: not any(r.get("Installed") for r in rows))
        self.table.add_context_action(lambda rows: f"Update {what(rows)} (partial upgrade)…",
                                      lambda rows: update_packages(self, rows, "standard"),
                                      has_update(self, "standard"))
        self.table.add_context_action(lambda rows: f"Remove {what(rows)}…",
                                      lambda rows: remove_packages(self, rows),
                                      lambda rows: all(r.get("Installed") for r in rows))
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
        self.install_rows(self.table.targets())

    def install_rows(self, rows: list[dict]) -> None:
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
        self.table.add_button("Downgrade…", lambda: self.downgrade_rows(self.table.targets()),
                              "Install an older version from the package cache or the Arch archive")
        self.table.add_button("Refresh", self.refresh)
        self.table.add_context_action(lambda rows: f"Update {what(rows)} (partial upgrade)…",
                                      lambda rows: update_packages(self, rows, "standard"),
                                      has_update(self, "standard"))
        self.table.add_context_action(lambda rows: f"Downgrade {what(rows)}…", self.downgrade_rows)
        self.table.add_context_action(lambda rows: f"Remove {what(rows)}…",
                                      lambda rows: remove_packages(self, rows))
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
        remove_packages(self, self.table.targets())

    def downgrade_rows(self, rows: list[dict]) -> None:
        if not self.need_selection(rows):
            return
        d = downgrade.DowngradeDialog(self.names(rows), self)
        if d.exec() and (plan := d.plan()):
            downgrade.run_plan(self.main.run_op, plan, self.main.refresh_all)


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

def replaced(r: dict) -> str:
    """The installed package a repo update replaces (Shelly 3.2+ ``OldName``), or ''."""
    old = r.get("OldName") or ""
    return old if old and old != r.get("Name") else ""


def update_label(r: dict) -> str:
    old = replaced(r)
    return f"{old} → {r.get('Name', '')}" if old else str(r.get("Name", ""))


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
            ("Name", update_label), ("Current", key("CurrentVersion")), ("New", key("NewVersion")),
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
            update_label(r), [("Replaces", replaced(r)),
                              ("Current", r.get("CurrentVersion")), ("New", r.get("NewVersion")),
                              ("Repository", r.get("Repository")), ("URL", r.get("Url")),
                              ("Depends on", r.get("Depends"))], r.get("Description", ""))))
        self.aurt.current_changed.connect(lambda r: r and self.aurt.detail.setHtml(details_html(
            r.get("Name", ""), [("Current", r.get("Version")), ("New", r.get("NewVersion")),
                                ("URL", r.get("Url"))], r.get("Description", ""))))
        self.flatt.current_changed.connect(lambda r: r and self.flatt.detail.setHtml(details_html(
            r.get("Name", ""), [("Id", r.get("Id")), ("Ref", r.get("FullRef")),
                                ("Permissions", r.get("Permissions"))], r.get("Summary", ""))))
        self.pending: dict[str, set] = {}
        self.pkgs.add_context_action(lambda rows: f"Update {what(rows)} (partial upgrade)…",
                                     lambda rows: update_packages(self, rows, "standard"))
        self.pkgs.add_context_action(lambda rows: f"Remove {what(rows)}…",
                                     lambda rows: remove_packages(self, rows))
        self.aurt.add_context_action(lambda rows: f"Update {what(rows)}",
                                     lambda rows: update_packages(self, rows, "aur"))
        self.aurt.add_context_action(lambda rows: f"Remove {what(rows)}…",
                                     lambda rows: remove_packages(self, rows, "aur"))
        self.flatt.add_context_action(lambda rows: f"Update {what(rows, 'Flatpaks')}",
                                      lambda rows: update_packages(self, rows, "flatpak"))
        self.flatt.add_context_action(lambda rows: f"Remove {what(rows, 'Flatpaks')}…",
                                      lambda rows: remove_flatpaks(self, rows))

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
        # a replacement is pending under both the installed (old) and the new name
        self.pending = {"standard": {n for r in p for n in (r.get("Name"), r.get("OldName")) if n}, "aur": {r.get("Name") for r in a},
                        "flatpak": {r.get("Id") for r in f}}
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
        self.results = PackageTable(AUR_COLS[:-1] + [match_column()] + AUR_COLS[-1:],
                                    placeholder="Filter results…")
        self.results.view.sortByColumn(len(AUR_COLS) - 1, Qt.SortOrder.AscendingOrder)  # relevance
        self.results.add_button("Review PKGBUILD", lambda: self.preview(self.results))
        self.results.add_button("Install", self.install)
        self.results.add_context_action("Review PKGBUILD", lambda rows: self.preview(self.results),
                                        lambda rows: len(rows) == 1)
        self.results.add_context_action(lambda rows: f"Install {what(rows)}", self.install_rows,
                                        lambda rows: not any(map(self.is_installed, rows)))
        self.results.add_context_action(lambda rows: f"Update {what(rows)}",
                                        lambda rows: update_packages(self, rows, "aur"),
                                        lambda rows: all(map(self.is_installed, rows))
                                        and has_update(self, "aur")(rows))
        self.results.add_context_action(lambda rows: f"Remove {what(rows)}…",
                                        lambda rows: remove_packages(self, rows, "aur"),
                                        lambda rows: all(map(self.is_installed, rows)))
        self.results.current_changed.connect(lambda r: r and self.results.detail.setHtml(aur_details(r)))
        sl.addWidget(self.results, 1)
        # installed tab
        self.installed = PackageTable(AUR_COLS, placeholder="Filter installed AUR packages…")
        self.installed.add_button("Review PKGBUILD", lambda: self.preview(self.installed))
        self.installed.add_button("Remove…", self.remove)
        self.installed.add_button("Refresh", self.refresh)
        self.installed.add_context_action("Review PKGBUILD", lambda rows: self.preview(self.installed),
                                          lambda rows: len(rows) == 1)
        self.installed.add_context_action(lambda rows: f"Update {what(rows)}",
                                          lambda rows: update_packages(self, rows, "aur"),
                                          has_update(self, "aur"))
        self.installed.add_context_action(lambda rows: f"Remove {what(rows)}…",
                                          lambda rows: remove_packages(self, rows, "aur"))
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
            self.results.set_rows(rank_rows(res or [], self.query.text(), "aur"))

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

    def is_installed(self, row: dict) -> bool:
        return any(r.get("Name") == row.get("Name") for r in self.installed.model.rows)

    def install(self) -> None:
        self.install_rows(self.results.targets())

    def install_rows(self, rows: list[dict]) -> None:
        if self.need_selection(rows):
            self.main.run_op(f"Building and installing {len(rows)} AUR package(s)",
                             ["install", "aur", *self.names(rows)], True, self.main.refresh_all)

    def remove(self) -> None:
        remove_packages(self, self.installed.targets(), "aur")


# ----------------------------------------------------------------- prefix.dev

def prefix_details(r: dict) -> str:
    conda = r.get("conda_name") or r.get("name", "")
    channel = r.get("channel") or "conda-forge"
    url = f"https://prefix.dev/channels/{channel}/packages/{conda}"
    if r.get("installed"):
        state = f"installed ({r['installed']})"
    elif r.get("available"):
        state = f"in the [prefix] repo ({r['available']})"
    elif r.get("shadowed_by"):
        state = (f"the [prefix] repo serves {r.get('name', '')} from {r['shadowed_by']}; "
                 f"Install switches it to {channel}")
    elif r.get("offline"):
        state = "prefix-alpm server not running: search only"
    else:
        state = "not added yet; Install adds it and its dependencies"
    return details_html(r.get("name", ""), [
        ("Channel", channel),
        ("conda name", conda),
        ("Latest on prefix.dev", r.get("latest")),
        ("Status", state),
        ("Dependencies from", "conda-forge first" + ("" if channel == "conda-forge" else f", then {channel}")),
        ("Installs to", "/opt/prefix (bin/ is appended to PATH)"),
        ("Page", url),
    ], r.get("summary") or "")


class PrefixDevPage(Page):
    """Live search of conda-forge on prefix.dev, installed through a prefix-alpm server."""

    title = "prefix.dev"

    def __init__(self, main) -> None:
        super().__init__(main)
        from PySide6.QtCore import QTimer

        from .prefixdev import Client, server_url

        self.client = Client(self)
        self.installed: dict[str, str] = {}
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search every public channel on prefix.dev…")
        self.query.setClearButtonEnabled(True)
        row.addWidget(self.query, 1)
        lay.addLayout(row)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setTextFormat(Qt.TextFormat.RichText)
        self.banner.hide()
        lay.addWidget(self.banner)
        self.results = PackageTable([
            ("Name", key("name")), ("Channel", key("channel")), ("Latest", key("latest")),
            ("In repo", lambda r: r.get("available") or ""),
            ("Installed", lambda r: r.get("installed") or ""),
            match_column(), ("Summary", key("summary")),
        ], placeholder="Filter results…")
        self.results.add_button("Install", self.install, "Add to the [prefix] repo and install")
        self.results.add_context_action(lambda rows: f"Install {what(rows)}", self.install_rows,
                                        lambda rows: not any(r.get("installed") for r in rows))
        self.results.add_context_action(lambda rows: f"Remove {what(rows)}…",
                                        lambda rows: remove_packages(self, [{"Name": r["name"]} for r in rows]),
                                        lambda rows: all(r.get("installed") for r in rows))
        self.results.current_changed.connect(lambda r: r and self.results.detail.setHtml(prefix_details(r)))
        # most relevant first; click the Match header to get back to it
        self.results.view.sortByColumn(5, Qt.SortOrder.AscendingOrder)
        lay.addWidget(self.results, 1)
        self.hint = QLabel(f"Packages come from prefix.dev channels via the prefix-alpm server at "
                           f"<code>{server_url()}</code> and install under <code>/opt/prefix</code>.")
        self.hint.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.hint)
        # search as you type, debounced
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.search)
        self.query.textChanged.connect(lambda *_: self.timer.start())
        self.query.returnPressed.connect(self.search)

    def refresh(self) -> None:
        cli.query(["-Ls"], self._installed_loaded, parse=lambda t: protocol.last_data(t, []))
        self.client.status(self._status)

    def _status(self, res, err) -> None:
        from .prefixdev import server_url

        if err:
            self.banner.setText(
                f"<b>prefix-alpm isn't running</b> at <code>{server_url()}</code>, so you can search "
                "but not install. Start it with <code>just serve</code> in the prefix-alpm checkout and "
                "add <code>[prefix]</code> to pacman.conf (<code>just enable</code>).")
            self.banner.setStyleSheet("QLabel{background:palette(alternate-base);padding:8px;border-radius:6px}")
            self.banner.show()
        else:
            self.banner.hide()

    def _installed_loaded(self, res, err) -> None:
        if err or not isinstance(res, list):
            return
        self.installed = {str(p.get("Name")): str(p.get("Version", "")) for p in res if p.get("Name")}
        self._annotate(self.results.model.rows)
        getattr(self.main, "search_page", None) and self.main.search_page.remark()

    def _annotate(self, rows: list[dict]) -> None:
        for r in rows:
            # pacman knows one package per name: only the channel the repo serves is "installed"
            mine = not r.get("shadowed_by")
            r["installed"] = self.installed.get(r.get("name", ""), "") if mine else ""
        self.results.set_rows(list(rows))

    def search(self) -> None:
        self.timer.stop()
        q = self.query.text().strip()
        if len(q) < 2:
            return
        self.main.busy(f"Searching prefix.dev for “{q}”…")
        self.client.search(q, lambda res, err, q=q: self._searched(q, res, err))

    def _searched(self, q: str, res, err) -> None:
        self.main.idle()
        if q != self.query.text().strip():
            return  # a newer search is on its way
        if err:
            self.main.status("prefix.dev search failed: " + err)
            return
        rows = rank_rows(res or [], q, "prefix")
        offline = any(r.get("offline") for r in rows)
        self._status(None, "offline" if offline else None)
        self._annotate(rows)

    def install(self) -> None:
        self.install_rows(self.results.targets())

    def install_rows(self, rows: list[dict]) -> None:
        if not self.need_selection(rows):
            return
        if any(r.get("offline") for r in rows):
            QMessageBox.information(self, "Shelly", "Installing from prefix.dev needs the prefix-alpm "
                                    "server; start it with <code>just serve</code>.")
            return
        from .prefixdev import add_name

        by_name: dict[str, dict] = {}
        for r in rows:  # one package per name: the last checked channel wins
            by_name[r["name"]] = r
        names = list(by_name)
        self.main.busy(f"Adding {what(rows)} to the [prefix] repo…")
        self.client.add([add_name(r) for r in by_name.values()], lambda res, err: self._added(names, res, err))

    def _added(self, names: list[str], res, err) -> None:
        self.main.idle(err)
        if err:
            return
        failed = (res or {}).get("failed") or []
        if failed:
            QMessageBox.warning(self, "Shelly", "Couldn't resolve on conda-forge: " + ", ".join(failed)
                                + "\n" + "\n".join((res or {}).get("conflicts") or []))
            return
        added = (res or {}).get("added") or []
        self.main.status(f"[prefix] repo now offers {len(added)} new package(s)")

        def install() -> None:
            self.main.run_op(f"Installing {len(names)} prefix.dev package(s)",
                             ["install", "standard", *names], True,
                             lambda: (self.main.refresh_all(), self.refresh()))

        # the db changed on the server, so sync it before installing
        self.main.run_op("Synchronizing package databases", ["sync", "--force"], True, install)


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
        self.installed.add_context_action(lambda rows: f"Update {what(rows, 'Flatpaks')}",
                                          lambda rows: update_packages(self, rows, "flatpak"),
                                          has_update(self, "flatpak"))
        self.installed.add_context_action(
            lambda rows: f"Remove {what(rows, 'Flatpaks')}…",
            lambda rows: remove_flatpaks(self, rows, self.remove_config.isChecked()))

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
            ("License", key("project_license")), match_column(), ("Summary", key("summary")),
        ], placeholder="Filter results…")
        self.results.view.sortByColumn(5, Qt.SortOrder.AscendingOrder)  # relevance
        self.user_scope = QCheckBox("Install for current user only")
        self.results.toolbar.addWidget(self.user_scope)
        self.results.add_button("Install", self.install)
        installed_rows = lambda rows: [self.installed_row(r) for r in rows]  # noqa: E731
        self.results.add_context_action(lambda rows: f"Install {what(rows, 'apps')}", self.install_rows,
                                        lambda rows: not any(installed_rows(rows)))
        self.results.add_context_action(lambda rows: f"Update {what(rows, 'apps')}",
                                        lambda rows: update_packages(self, installed_rows(rows), "flatpak"),
                                        lambda rows: all(installed_rows(rows))
                                        and has_update(self, "flatpak")(installed_rows(rows)))
        self.results.add_context_action(lambda rows: f"Remove {what(rows, 'apps')}…",
                                        lambda rows: remove_flatpaks(self, installed_rows(rows),
                                                                     self.remove_config.isChecked()),
                                        lambda rows: all(installed_rows(rows)))
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
            getattr(self.main, "search_page", None) and self.main.search_page.remark()  # Flatpak rows there are marked from this list

    def search(self) -> None:
        q = self.query.text().strip()
        if not q:
            return
        self.main.busy(f"Searching Flathub for “{q}”…")
        cli.query(["search", "flatpak", q, "--limit", "50"], self._searched,
                  parse=lambda t: protocol.last_data(t, {}))

    def show_app(self, app_id: str, search: bool = True) -> None:
        """Open the Search tab on <app_id> (from a .flatpakref or appstream:// link)."""
        self.tabs.setCurrentIndex(1)
        self.query.setText(app_id)
        self._select_id = app_id
        if search:
            self.search()

    def _searched(self, res, err) -> None:
        self.main.idle(err)
        if not err:
            hits = (res or {}).get("hits", []) if isinstance(res, dict) else res or []
            self.results.set_rows(rank_rows(hits, self.query.text(), "flatpak"))
            want, self._select_id = getattr(self, "_select_id", None), None
            if want:
                self.results.select_where(lambda r: (r.get("app_id") or r.get("id")) == want)

    def installed_row(self, result: dict) -> dict | None:
        """The installed Flatpak matching a Flathub search hit, if any."""
        app_id = result.get("app_id") or result.get("id")
        return next((r for r in self.installed.model.rows if r.get("Id") == app_id), None)

    def install(self) -> None:
        self.install_rows(self.results.targets())

    def install_rows(self, rows: list[dict]) -> None:
        if not self.need_selection(rows):
            return
        for r in rows:
            app_id = r.get("app_id") or r.get("id")
            args = ["install", "flatpak", app_id]
            if self.user_scope.isChecked():
                args.append("--user")
            self.main.run_op(f"Installing {r.get('name') or app_id}", args, False, self.refresh)

    def remove(self) -> None:
        remove_flatpaks(self, self.installed.targets(), self.remove_config.isChecked())

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
        self.table.add_context_action("Update all AppImages", lambda rows: self.upgrade(),
                                      lambda rows: any(r.get("Name") in self.updates for r in rows))
        self.table.add_context_action("Set update source…", lambda rows: self.set_source(rows[0]),
                                      lambda rows: len(rows) == 1)
        self.table.add_context_action(lambda rows: f"Remove {what(rows, 'AppImages')}…", self.remove_rows)
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
        m = self.table.model
        if m.rowCount():  # refresh the Update column (layoutChanged alone crashes with a selection)
            m.dataChanged.emit(m.index(0, 2), m.index(m.rowCount() - 1, 2))
        self.main.status(f"{len(self.updates)} AppImage update(s) available.")

    def install(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose an AppImage", "",
                                              "AppImage (*.AppImage *.appimage);;All files (*)")
        if path:
            self.main.run_op("Installing AppImage", ["install", "appimage", path], False, self.refresh)

    def remove(self) -> None:
        self.remove_rows(self.table.targets())

    def remove_rows(self, rows: list[dict]) -> None:
        if not self.need_selection(rows):
            return
        if not confirm(self, "Remove AppImage", f"Remove {', '.join(what([r]) for r in rows)}?"):
            return
        for r in rows:
            self.main.run_op(f"Removing {what([r])}", ["remove", "appimage", r.get("Name", "")],
                             False, self.refresh)

    def upgrade(self) -> None:
        self.main.run_op("Upgrading AppImages", ["upgrade", "appimage"], False, self.refresh)

    def set_source(self, row: dict) -> None:
        d = UpdateSourceDialog(row, self)
        if d.exec():
            self.main.run_op(f"Setting the update source for {what([row])}",
                             d.command(str(row.get("Name", ""))), False, self.refresh)


# AppImage update providers `shelly sync appimage <name> <url> <type>` accepts,
# with the hint shown for each. Zsync arrived in Shelly 3.2.0.
UPDATE_SOURCES = [
    ("GitHub", "GitHub releases", "owner/repo"),
    ("GitLab", "GitLab releases", "owner/repo"),
    ("Codeberg", "Codeberg releases", "owner/repo"),
    ("Forgejo", "Forgejo releases", "https://host/owner/repo"),
    ("Zsync", "zsync control file", "https://example.org/latest/App.AppImage.zsync"),
    ("StaticUrl", "Static download URL", "https://example.org/App.AppImage"),
    ("None", "No updates", ""),
]


def guess_source(row: dict) -> tuple[str, str]:
    """(type, url) prefilled from what Shelly knows about the AppImage."""
    raw = str(row.get("RawUpdateInfo") or "")
    if raw.startswith("zsync|"):
        return "Zsync", raw
    parts = raw.split("|")
    if parts[0] == "gh-releases-zsync" and len(parts) >= 3:
        return "GitHub", f"{parts[1]}/{parts[2]}"
    if row.get("RepoOwner") and row.get("RepoName"):
        return "GitHub", f"{row['RepoOwner']}/{row['RepoName']}"
    url = str(row.get("UpdateURl") or row.get("UpdateUrl") or "")
    return ("Zsync" if url.endswith(".zsync") else "StaticUrl", url) if url else ("GitHub", "")


class UpdateSourceDialog(QDialog):
    def __init__(self, row: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Update source for {what([row])}")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.kind = QComboBox()
        for value, text, _ in UPDATE_SOURCES:
            self.kind.addItem(text, value)
        self.url = QLineEdit()
        self.pre = QCheckBox("Include prereleases")
        form.addRow("Provider", self.kind)
        form.addRow("Location", self.url)
        form.addRow("", self.pre)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.save = bb.button(QDialogButtonBox.StandardButton.Save)
        lay.addWidget(bb)
        kind, url = guess_source(row)
        self.kind.setCurrentIndex(max(0, self.kind.findData(kind)))
        self.url.setText(url)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.url.textChanged.connect(self._validate)
        self._kind_changed()
        self.resize(480, self.sizeHint().height())

    def value(self) -> str:
        return str(self.kind.currentData())

    def _kind_changed(self) -> None:
        hint = next(h for v, _, h in UPDATE_SOURCES if v == self.value())
        none = self.value() == "None"
        self.url.setPlaceholderText(hint)
        self.url.setEnabled(not none)
        self.pre.setEnabled(self.value() in ("GitHub", "GitLab", "Codeberg", "Forgejo"))
        self._validate()

    def _validate(self) -> None:
        self.save.setEnabled(self.value() == "None" or bool(self.url.text().strip()))

    def command(self, name: str) -> list[str]:
        url = "" if self.value() == "None" else self.url.text().strip()
        args = ["sync", "appimage", name, url, self.value()]
        if self.pre.isEnabled() and self.pre.isChecked():
            args.append("--prerelease")
        return args


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
        row = QHBoxLayout()
        row.addStretch(1)
        if selfupdate.available():
            upd = QPushButton(QIcon.fromTheme("system-software-update"), "Check for Shelly-Qt updates…")
            upd.setToolTip("Update this AppImage in place (downloads only what changed)")
            upd.clicked.connect(lambda: self.main.check_for_updates())
            row.addWidget(upd)
        b = QPushButton("Reload")
        b.clicked.connect(self.refresh)
        row.addWidget(b)
        lay.addLayout(row)
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
