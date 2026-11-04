"""Files and links handed to Shelly-Qt on the command line ("Open with…").

The desktop passes paths (%f) or URIs (%U). We accept:

* ``.flatpakref``  -> Flatpak page, ``shelly install flatpak --ref-file``
* ``.flatpak``     -> Flatpak page, ``shelly install flatpak --bundle``
* ``.flatpakrepo`` -> not installable by the CLI; we say so
* ``.AppImage``    -> AppImage page, ``shelly install appimage``
* ``.pkg.tar.*``   -> Maintenance page, ``shelly install standard`` (root)
* ``appstream://<id>`` and ``flatpak+https://…/<id>.flatpakref``
                   -> Flatpak page, Flathub search for <id>
"""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

PKG_SUFFIXES = (".pkg.tar.zst", ".pkg.tar.xz", ".pkg.tar.gz", ".pkg.tar.bz2", ".pkg.tar")


@dataclass
class Target:
    kind: str  # flatpakref | bundle | flatpakrepo | appimage | pkg | appid | unknown
    value: str  # absolute path, or the app id for "appid"
    info: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.info.get("Title") or self.info.get("Name") or Path(self.value).name


def _local_path(arg: str, cwd: str | None) -> str | None:
    if arg.startswith("file://"):
        parts = urlsplit(arg)
        if parts.netloc not in ("", "localhost"):
            return None
        return unquote(parts.path) or None
    if "://" in arg:
        return None
    base = cwd or os.environ.get("SHELLY_QT_CWD") or os.getcwd()
    return str(Path(base, os.path.expanduser(arg)).resolve())


def _app_id_from_url(arg: str) -> str | None:
    if arg.startswith("appstream://"):
        rest = urlsplit(arg)
        app_id = (rest.netloc + rest.path).strip("/")
        return app_id if app_id and "/" not in app_id else None
    if arg.startswith("flatpak+https://"):
        last = urlsplit(arg).path.rstrip("/").rsplit("/", 1)[-1]
        if last.lower().endswith(".flatpakref"):
            last = last[: -len(".flatpakref")]
        return last or None
    return None


def parse_flatpakref(path: str) -> dict[str, str]:
    """Read the [Flatpak Ref] group (Name, Title, Branch, Url, IsRuntime, …)."""
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str  # keep key case
    try:
        cp.read(path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError):
        return {}
    for group in ("Flatpak Ref", "Flatpak Repo"):
        if cp.has_section(group):
            return {k: v for k, v in cp.items(group) if k != "GPGKey"}
    return {}


def classify(arg: str, cwd: str | None = None) -> Target:
    app_id = _app_id_from_url(arg)
    if app_id:
        return Target("appid", app_id)
    path = _local_path(arg, cwd)
    if not path:
        return Target("unknown", arg)
    low = path.lower()
    if low.endswith(".flatpakref"):
        return Target("flatpakref", path, parse_flatpakref(path))
    if low.endswith(".flatpakrepo"):
        return Target("flatpakrepo", path, parse_flatpakref(path))
    if low.endswith(".flatpak"):
        return Target("bundle", path)
    if low.endswith(".appimage"):
        return Target("appimage", path)
    if low.endswith(PKG_SUFFIXES):
        return Target("pkg", path)
    return Target("unknown", path)


def targets_from_argv(argv: list[str]) -> list[Target]:
    return [classify(a) for a in argv if a and not a.startswith("-")]
