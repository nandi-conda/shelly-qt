"""Package sources for the combined "search everything" page.

Each :class:`Source` knows how to search one kind of package and how to install
its results. The Search page queries every enabled source at once and merges
their rows. To add a source (e.g. prefix.dev), subclass :class:`Source` (or
:class:`CliSource` when a ``shelly`` command does the search) and append an
instance to :data:`SOURCES`.

Rows a source returns keep the backend's own fields and gain a few common ones:
``Name``, ``Version``, ``Description``, ``Installed`` (bool) and ``_source``
(the source key). The page shows those plus a Source column.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from . import cli, protocol
from .ranking import rank_rows

if TYPE_CHECKING:
    from .app import MainWindow

Done = Callable[[list[dict], "str | None"], None]


class Source:
    key = ""            # stable id, stored on rows as ``_source``
    label = ""          # shown in the Source column and on the filter toggle
    privileged = False  # whether install needs pkexec
    min_query = 1

    def search(self, query: str, done: Done) -> None:
        """Search for ``query`` and call ``done(rows, error)`` once, on the GUI thread."""
        raise NotImplementedError

    def normalize(self, raw: dict) -> dict:
        """Map one backend result to a row with Name/Version/Description."""
        return dict(raw)

    def mark_installed(self, rows: list[dict], main: "MainWindow") -> None:
        """Set ``Installed`` on rows using what the app already knows."""

    def install(self, main: "MainWindow", rows: list[dict], options: dict) -> None:
        raise NotImplementedError

    def details(self, row: dict) -> str:
        from .widgets import details_html
        return details_html(f"{row.get('Name', '')} {row.get('Version', '')}",
                            [("Source", self.label)], row.get("Description") or "")


class CliSource(Source):
    """A source searched with one ``shelly ... --ui-mode`` command."""

    def args(self, query: str) -> list[str]:
        raise NotImplementedError

    def parse(self, text: str) -> list[dict]:
        data = protocol.last_data(text, [])
        return data if isinstance(data, list) else []

    def search(self, query: str, done: Done) -> None:
        def finished(res, err):
            if err:
                done([], err)
                return
            done([self._tag(self.normalize(r)) for r in (res or []) if isinstance(r, dict)], None)
        cli.query(self.args(query), finished, parse=self.parse)

    def _tag(self, row: dict) -> dict:
        row["_source"] = self.key
        row["Installed"] = bool(row.get("Installed"))
        return row


def _page(main: "MainWindow", cls_name: str):
    for p in getattr(main, "pages", []):
        if type(p).__name__ == cls_name:
            return p
    return None


def _installed_names(main: "MainWindow", cls_name: str, table_attr: str, field: str) -> set[str]:
    page = _page(main, cls_name)
    table = getattr(page, table_attr, None) if page else None
    rows = table.model.rows if table is not None else []
    return {str(r.get(field)) for r in rows if r.get(field)}


class RepoSource(CliSource):
    key, label, privileged = "repo", "Repos", True

    def args(self, query: str) -> list[str]:
        return ["search", "standard", query, "--limit", "200"]

    def parse(self, text: str) -> list[dict]:
        return cli.merged_data(text)  # standard search may stream several pages

    def install(self, main, rows, options) -> None:
        names = [r["Name"] for r in rows if r.get("Name")]
        main.run_op(f"Installing {len(names)} package(s)", ["install", "standard", *names], True,
                    main.refresh_all)

    def details(self, row: dict) -> str:
        from .pages import package_details
        return package_details(row)


class AurSource(CliSource):
    key, label, privileged, min_query = "aur", "AUR", True, 2

    def args(self, query: str) -> list[str]:
        return ["search", "aur", *query.split()]

    def mark_installed(self, rows, main) -> None:
        have = _installed_names(main, "AurPage", "installed", "Name")
        for r in rows:
            r["Installed"] = r["Installed"] or r.get("Name") in have

    def install(self, main, rows, options) -> None:
        names = [r["Name"] for r in rows if r.get("Name")]
        main.run_op(f"Building and installing {len(names)} AUR package(s)",
                    ["install", "aur", *names], True, main.refresh_all)

    def details(self, row: dict) -> str:
        from .pages import aur_details
        return aur_details(row)



class FlatpakSource(CliSource):
    key, label = "flatpak", "Flatpak"

    def args(self, query: str) -> list[str]:
        return ["search", "flatpak", query, "--limit", "50"]

    def parse(self, text: str) -> list[dict]:
        data = protocol.last_data(text, {})
        if isinstance(data, dict):
            data = data.get("hits", [])
        return data if isinstance(data, list) else []

    def normalize(self, raw: dict) -> dict:
        row = dict(raw)
        app_id = raw.get("app_id") or raw.get("id") or raw.get("Id") or ""
        row["AppId"] = app_id
        row["Name"] = raw.get("name") or raw.get("Name") or app_id
        row["Version"] = raw.get("version") or raw.get("Version") or ""
        row["Description"] = raw.get("summary") or raw.get("Description") or ""
        return row

    def mark_installed(self, rows, main) -> None:
        have = _installed_names(main, "FlatpakPage", "installed", "Id")
        for r in rows:
            r["Installed"] = r["Installed"] or r.get("AppId") in have

    def install(self, main, rows, options) -> None:
        refresh = getattr(_page(main, "FlatpakPage"), "refresh", None)
        for r in rows:
            if not r.get("AppId"):
                continue
            args = ["install", "flatpak", r["AppId"]]
            if options.get("flatpak_user"):
                args.append("--user")
            main.run_op(f"Installing {r['Name']}", args, False, refresh)

    def details(self, row: dict) -> str:
        from .widgets import details_html
        return details_html(row.get("Name", ""), [
            ("Source", "Flatpak"), ("App ID", row.get("AppId")),
            ("Developer", row.get("developer_name")), ("License", row.get("project_license")),
            ("Verified", "yes" if row.get("verification_verified") else ""),
            ("Categories", row.get("main_categories")), ("Keywords", row.get("keywords")),
        ], row.get("description") or row.get("Description") or "")


class PrefixSource(Source):
    """Every public prefix.dev channel, installed through a prefix-alpm server ([prefix] repo).

    Only offered while the server answers: without it nothing can be installed, so the
    combined search stays quiet instead of listing rows it can't act on (the prefix.dev
    page still searches prefix.dev directly in that case).
    """

    key, label, privileged, min_query = "prefix", "prefix.dev", True, 2

    def __init__(self) -> None:
        self._client = None

    def search(self, query: str, done: Done) -> None:
        from .prefixdev import Client

        if self._client is None:
            self._client = Client()

        def got(res, err):
            rows = [r for r in (res or []) if isinstance(r, dict) and not r.get("offline")]
            done([self._row(r) for r in rows], None)  # offline/unreachable: no rows, no error

        self._client.search(query, got, limit=30, fallback=False)

    def _row(self, r: dict) -> dict:
        row = dict(r)
        ch = r.get("channel") or ""
        tag = f"[{ch}] " if ch and ch != "conda-forge" else ""
        row.update(Name=r.get("name", ""), Version=r.get("available") or r.get("latest") or "",
                   Description=tag + (r.get("summary") or ""), _source=self.key, Installed=False)
        return row

    def mark_installed(self, rows, main) -> None:
        page = _page(main, "PrefixDevPage")
        have = set(getattr(page, "installed", {}) or {})
        have |= _installed_names(main, "InstalledPage", "table", "Name")
        for r in rows:
            r["Installed"] = r["Installed"] or (r.get("Name") in have and not r.get("shadowed_by"))
            r["installed"] = "yes" if r["Installed"] else ""

    def install(self, main, rows, options) -> None:
        page = _page(main, "PrefixDevPage")
        if page is not None:
            page.install_rows(rows)

    def details(self, row: dict) -> str:
        from .pages import prefix_details
        return prefix_details(row)


# Shelly has no AppImage catalogue search (only list/install from a file or URL),
# so AppImages are not a search source.
SOURCES: list[Source] = [RepoSource(), AurSource(), FlatpakSource(), PrefixSource()]


def source(key: str) -> Source | None:
    return next((s for s in SOURCES if s.key == key), None)


def ranked(rows: list[dict], query: str) -> list[dict]:
    """Rows from any mix of sources, most relevant first (see :mod:`.ranking`)."""
    return rank_rows(rows, query)
