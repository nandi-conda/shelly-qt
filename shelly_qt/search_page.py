"""Combined search: one query across repo packages, the AUR, Flatpak (and any added source)."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout

from . import cli, protocol
from .pages import Page, package_details, what
from .ranking import match_column
from .search_sources import SOURCES, ranked, source
from .widgets import PackageTable, key


def source_label(row: dict) -> str:
    s = source(row.get("_source", ""))
    return s.label if s else row.get("_source", "")


class SearchPage(Page):
    title = "Search"

    def __init__(self, main) -> None:
        super().__init__(main)
        self.query = ""
        self._gen = 0
        self.results: dict[str, list[dict]] = {}
        self.errors: dict[str, str] = {}
        self.pending: set[str] = set()
        self.searched: set[str] = set()

        self.table = PackageTable([
            ("Name", key("Name")), ("Version", key("Version")), ("Source", source_label),
            ("Installed", key("Installed", False)), match_column(), ("Description", key("Description")),
        ], placeholder="Filter results…")
        self.match_col = 4
        self.toggles: dict[str, QCheckBox] = {}
        for s in SOURCES:
            cb = QCheckBox(s.label)
            cb.setChecked(True)
            cb.setToolTip(f"Include {s.label} results")
            cb.toggled.connect(lambda on, k=s.key: self._toggled(k, on))
            self.toggles[s.key] = cb
            self.table.toolbar.addWidget(cb)
        self.hide_installed = QCheckBox("Hide installed")
        self.hide_installed.toggled.connect(self._apply)
        self.table.toolbar.addWidget(self.hide_installed)
        self.flatpak_user = QCheckBox("Flatpaks for current user")
        self.flatpak_user.setToolTip("Install Flatpak results with --user")
        self.table.toolbar.addWidget(self.flatpak_user)
        self.table.add_button("Install", self.install, "Install the checked results, each from its own source")

        self.table.add_context_action(lambda rows: f"Install {what(rows)}", self.install_rows,
                                      lambda rows: not all(r.get("Installed") for r in rows))
        self.table.add_context_action("Review PKGBUILD…", self._pkgbuild,
                                      lambda rows: len(rows) == 1 and rows[0].get("_source") == "aur")
        self.table.current_changed.connect(self._show_details)

        self.summary = QLabel("Type in the search box at the top and press Enter to search every "
                              "package source at once.")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        lay = QVBoxLayout(self)
        lay.addWidget(self.summary)
        lay.addWidget(self.table, 1)
        self.sort_by_relevance()
        self._apply()

    # ---- searching -------------------------------------------------------
    def enabled(self) -> list:
        return [s for s in SOURCES if self.toggles[s.key].isChecked()]

    def search(self, query: str) -> None:
        query = query.strip()
        if not query:
            return
        self.loaded = True
        self.query = query
        self._gen += 1
        self.results, self.errors, self.searched = {}, {}, set()
        for s in list(self.pending):
            self.main.idle()
        self.pending = set()
        self.table.set_rows([])
        self.sort_by_relevance()
        for s in self.enabled():
            self._run(s)
        self._update_summary()

    def sort_by_relevance(self) -> None:
        """Most relevant first; clicking the Match header does the same."""
        self.table.view.sortByColumn(self.match_col, Qt.SortOrder.AscendingOrder)

    def _run(self, s) -> None:
        self.searched.add(s.key)
        if len(self.query) < s.min_query:
            self.errors[s.key] = f"needs at least {s.min_query} characters"
            return
        gen = self._gen
        self.pending.add(s.key)
        self.main.busy(f"Searching for “{self.query}”…")
        s.search(self.query, lambda rows, err, s=s: self._got(gen, s, rows, err))

    def _got(self, gen: int, s, rows: list[dict], err) -> None:
        if gen != self._gen:
            return  # a newer search replaced this one
        self.pending.discard(s.key)
        self.main.idle()
        if err:
            self.errors[s.key] = err.splitlines()[0] if err.strip() else "failed"
        else:
            s.mark_installed(rows, self.main)
            self.results[s.key] = rows
        self._rebuild()

    def _rebuild(self) -> None:
        checked = {(r.get("_source"), r.get("Name")) for r in self.table.model.checked_rows()}
        rows = ranked([r for rs in self.results.values() for r in rs], self.query)
        self.table.set_rows(rows)
        for i, r in enumerate(rows):
            if (r.get("_source"), r.get("Name")) in checked:
                self.table.model.checked.add(i)
        self.table.model.checked_changed.emit()
        self._update_summary()

    def refresh(self) -> None:
        if self.query:
            self.search(self.query)

    def _toggled(self, key_: str, on: bool) -> None:
        if on and self.query and key_ not in self.searched:
            s = source(key_)
            if s:
                self._run(s)
        self._apply()

    def _apply(self, *_) -> None:
        on = {k for k, cb in self.toggles.items() if cb.isChecked()}
        hide = self.hide_installed.isChecked()
        self.table.proxy.extra = lambda r: r.get("_source") in on and not (hide and r.get("Installed"))
        self.table.proxy.refilter()
        self._update_summary()

    def _update_summary(self) -> None:
        if not self.query:
            return
        parts = []
        for s in SOURCES:
            if not self.toggles[s.key].isChecked():
                continue
            if s.key in self.pending:
                parts.append(f"{escape(s.label)}: searching…")
            elif s.key in self.errors:
                parts.append(f"{escape(s.label)}: <span style='color:#c0392b'>"
                             f"{escape(self.errors[s.key])}</span>")
            elif s.key in self.results:
                parts.append(f"{escape(s.label)}: {len(self.results[s.key])}")
        self.summary.setText(f"Results for <b>{escape(self.query)}</b> — " + " · ".join(parts))

    # ---- details / actions ----------------------------------------------
    def _show_details(self, row: dict | None) -> None:
        if not row:
            return
        s = source(row.get("_source", ""))
        self.table.detail.setHtml(s.details(row) if s else "")
        if row.get("_source") != "repo" or not row.get("Name"):
            return
        name = row["Name"]

        def done(res, err):
            cur = self.table.current_row()
            if err or not isinstance(res, dict) or not cur or cur.get("Name") != name:
                return
            merged = {**cur, **{k: v for k, v in res.items() if v not in (None, "", [])}}
            self.table.detail.setHtml(package_details(merged))

        cli.query(["-Ssdi", name], done)

    def install(self) -> None:
        self.install_rows(self.table.targets())

    def install_rows(self, rows: list[dict]) -> None:
        if not self.need_selection(rows):
            return
        options = {"flatpak_user": self.flatpak_user.isChecked()}
        for s in SOURCES:
            mine = [r for r in rows if r.get("_source") == s.key]
            if mine:
                s.install(self.main, mine, options)

    def _pkgbuild(self, rows: list[dict]) -> None:
        aur = next((p for p in self.main.pages if type(p).__name__ == "AurPage"), None)
        name = rows[0].get("Name")
        if not aur or not name:
            return
        self.main.busy(f"Fetching PKGBUILD for {name}…")
        cli.query(["search", "aur", name, "--pkgbuild"], lambda r, e: aur._show_pkgbuild(name, r, e),
                  parse=lambda t: protocol.last_data(t, []))
