"""Client for a prefix-alpm server (prefix.dev conda packages as a pacman repo).

prefix-alpm (https://fileapi.fastapicloud.dev/git/smelly/prefix-alpm.git) serves
conda-forge packages as the pacman repo ``[prefix]``. Its HTTP API:

* ``/search?q=``  live search on prefix.dev's GraphQL API, annotated with what the
  repo already offers (``available``)
* ``/add?name=a,b`` resolve packages + dependencies into the repo's db
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
        if self._search_reply is not None and self._search_reply.isRunning():
            self._search_reply.abort()

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
            "query($q: String!, $n: Int!) { channel(name: \"conda-forge\") { packages("
            "filters: {name: {contains: $q}}, limit: $n) { page { name summary latestVersion { version } } } } }"
        )
        req = QNetworkRequest(QUrl(GRAPHQL))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        req.setTransferTimeout(15000)
        body = QByteArray(json.dumps({"query": query, "variables": {"q": text, "n": min(limit, 50)}}).encode())

        def got(res, err):
            if err:
                return done(None, err)
            page = (((res or {}).get("data") or {}).get("channel") or {}).get("packages", {}).get("page", [])
            done([{"name": name_prefix() + p["name"], "conda_name": p["name"], "summary": p.get("summary"),
                   "latest": (p.get("latestVersion") or {}).get("version"), "available": None,
                   "offline": True} for p in page], None)

        return self._wire(self.nam.post(req, body), got)
