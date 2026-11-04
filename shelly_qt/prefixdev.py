"""Client for a prefix-alpm server (prefix.dev conda packages as a pacman repo).

prefix-alpm (https://fileapi.fastapicloud.dev/git/smelly/prefix-alpm.git) serves
conda-forge packages as the pacman repo ``[prefix]``. Its HTTP API:

* ``/search?q=``  live search across every public prefix.dev channel (GraphQL),
  annotated with each row's ``channel``, what the repo already offers (``available``)
  and the ``add`` value (``channel::name``)
* ``/add?name=a,b`` resolve packages + dependencies into the repo's db (``channel::name``
  takes a package from that channel)
* ``/status``

When no server runs, search falls back to prefix.dev's GraphQL API directly
(read-only: installing needs the server).
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

from PySide6.QtCore import QByteArray, QObject, QUrl, QUrlQuery
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

GRAPHQL = "https://prefix.dev/api/graphql"
Done = Callable[[Any, str | None], None]


def add_name(row: dict) -> str:
    """What to pass to /add for a search row: `channel::name` when the row has a channel."""
    if row.get("add"):
        return row["add"]
    if row.get("channel") and row.get("conda_name"):
        return f"{row['channel']}::{row['conda_name']}"
    return row.get("name", "")


def server_url() -> str:
    return os.environ.get("PREFIX_ALPM_URL", "http://127.0.0.1:8787").rstrip("/")


def name_prefix() -> str:
    return os.environ.get("PREFIX_ALPM_NAME_PREFIX", "conda-")


class Client(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.nam = QNetworkAccessManager(self)
        self._search_reply: QNetworkReply | None = None

    # ---- plumbing ----------------------------------------------------------
    def _get(self, path: str, params: dict[str, str], done: Done, timeout_ms: int) -> QNetworkReply:
        url = QUrl(server_url() + path)
        q = QUrlQuery()
        for k, v in params.items():
            q.addQueryItem(k, v)
        url.setQuery(q)
        req = QNetworkRequest(url)
        req.setTransferTimeout(timeout_ms)
        return self._wire(self.nam.get(req), done)

    def _wire(self, reply: QNetworkReply, done: Done) -> QNetworkReply:
        def finished() -> None:
            reply.deleteLater()
            if reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
                return
            body = bytes(reply.readAll().data())
            try:
                data = json.loads(body) if body else None
            except ValueError:
                data = None
            if reply.error() != QNetworkReply.NetworkError.NoError:
                msg = (data or {}).get("error") if isinstance(data, dict) else None
                done(None, msg or reply.errorString())
            elif isinstance(data, dict) and data.get("error"):
                done(None, str(data["error"]))
            else:
                done(data, None)

        reply.finished.connect(finished)
        return reply

    # ---- API ---------------------------------------------------------------
    def search(self, text: str, done: Done, limit: int = 50, fallback: bool = True) -> None:
        """Live search; on a missing server, ask prefix.dev directly (done gets offline=True rows)."""
        try:
            if self._search_reply is not None and self._search_reply.isRunning():
                self._search_reply.abort()  # a newer query supersedes it
        except RuntimeError:  # already finished and deleted
            pass
        self._search_reply = None

        def via_server(res, err):
            if err is None:
                return done(res or [], None)
            if not fallback:
                return done(None, err)
            self._search_reply = self._graphql_search(text, limit, done)

        self._search_reply = self._get("/search", {"q": text, "limit": str(limit)}, via_server, 15000)

    def add(self, names: list[str], done: Done) -> None:
        # resolving a big stack can take a while the first time (shard downloads)
        self._get("/add", {"name": ",".join(names)}, done, 300000)

    def status(self, done: Done) -> None:
        self._get("/status", {}, done, 3000)

    def _graphql_search(self, text: str, limit: int, done: Done) -> QNetworkReply:
        query = (
            "query($q: String!, $n: Int!) { packages("
            "filters: {name: {contains: $q}}, limit: $n, "
            "orderBy: {bySimilarity: {field: NAME, direction: DESC, matches: $q}}) "
            "{ page { name summary latestVersion { version } channel { name isPublic } } } }"
        )
        req = QNetworkRequest(QUrl(GRAPHQL))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        req.setTransferTimeout(15000)
        body = QByteArray(json.dumps({"query": query, "variables": {"q": text, "n": min(limit, 50)}}).encode())

        def got(res, err):
            if err:
                return done(None, err)
            page = (((res or {}).get("data") or {}).get("packages") or {}).get("page", [])
            rows = []
            for p in page:
                ch = p.get("channel") or {}
                if ch.get("isPublic") is False:
                    continue
                rows.append({"name": name_prefix() + p["name"], "conda_name": p["name"],
                             "channel": ch.get("name", ""), "add": f"{ch.get('name', '')}::{p['name']}",
                             "summary": p.get("summary"), "latest": (p.get("latestVersion") or {}).get("version"),
                             "available": None, "offline": True})
            done(rows, None)

        return self._wire(self.nam.post(req, body), got)
