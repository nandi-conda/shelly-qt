"""Open external links in the user's browser, not one launched from our env.

Under pixi the process environment points at the conda prefix (PATH,
CONDA_*, PIXI_*, XDG_DATA_DIRS, QT_*/LD_* vars, ...). conda-forge Qt has no
KDE platform plugin, so QDesktopServices falls back to spawning xdg-open,
which hands that environment to the browser. A browser started with a
different environment can fail to find/attach to the instance that is
already running and opens a new window instead of a tab.

So: ask the desktop (xdg-desktop-portal, running in the session's own env)
to open the URL; fall back to xdg-open with a cleaned environment; and only
then to QDesktopServices.
"""
from __future__ import annotations

import os
import shutil

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QUrl, Slot
from PySide6.QtGui import QDesktopServices

_DROP_PREFIXES = ("CONDA", "PIXI", "_CONDA", "QT_", "QML", "PYTHON", "LD_",
                  "SSL_CERT", "GSETTINGS_SCHEMA_DIR", "GIO_", "GDK_PIXBUF",
                  "FONTCONFIG", "XKB_CONFIG")


def clean_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of env without the pixi/conda activation leftovers."""
    env = dict(os.environ if env is None else env)
    prefix = env.get("CONDA_PREFIX") or env.get("PIXI_PROJECT_ROOT")
    for k in list(env):
        if k.startswith(_DROP_PREFIXES):
            del env[k]
    if prefix:
        for k in ("PATH", "XDG_DATA_DIRS", "XDG_CONFIG_DIRS"):
            if k in env:
                parts = [p for p in env[k].split(os.pathsep) if p and not p.startswith(prefix)]
                if parts:
                    env[k] = os.pathsep.join(parts)
                else:
                    del env[k]
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    return env


def _via_portal(url: str) -> bool:
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusMessage
    except ImportError:
        return False
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return False
    msg = QDBusMessage.createMethodCall(
        "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.OpenURI", "OpenURI")
    msg.setArguments(["", url, {}])
    reply = bus.call(msg)
    return reply.type() == QDBusMessage.MessageType.ReplyMessage


def _via_xdg_open(url: str) -> bool:
    env = clean_env()
    exe = shutil.which("xdg-open", path=env["PATH"])
    if not exe:
        return False
    proc = QProcess()
    proc.setProgram(exe)
    proc.setArguments([url])
    penv = QProcessEnvironment()
    for k, v in env.items():
        penv.insert(k, v)
    proc.setProcessEnvironment(penv)
    ok, _pid = proc.startDetached()
    return ok


_SCHEMES = ("http", "https")


class _Handler(QObject):
    @Slot(QUrl)
    def open(self, url: QUrl) -> None:
        s = url.toString()
        if _via_portal(s) or _via_xdg_open(s):
            return
        # Last resort: Qt's own handling, without recursing into ourselves.
        for sc in _SCHEMES:
            QDesktopServices.unsetUrlHandler(sc)
        try:
            QDesktopServices.openUrl(url)
        finally:
            install_url_handler()


_handler: _Handler | None = None


def install_url_handler() -> None:
    """Route every http(s) QDesktopServices.openUrl (QLabel/QTextBrowser links,
    QMessageBox text, ...) through open_url's clean path."""
    global _handler
    if _handler is None:
        _handler = _Handler()
    for sc in _SCHEMES:
        QDesktopServices.setUrlHandler(sc, _handler, "open")


def open_url(url: QUrl | str) -> None:
    qurl = url if isinstance(url, QUrl) else QUrl(url)
    if qurl.scheme() in _SCHEMES:
        if _handler is None:
            install_url_handler()
        _handler.open(qurl)
    else:
        QDesktopServices.openUrl(qurl)
