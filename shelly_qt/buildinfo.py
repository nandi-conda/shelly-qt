"""What build of Shelly-Qt is running.

Packaged builds (the AppImage) get a generated ``shelly_qt/_build.py`` holding
the commit, channel and build date; see packaging/appimage/build-appdir.sh.
A source checkout falls back to asking git.
"""
from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

from . import __version__

# The canonical repo is on fileapi (git: smelly/shelly-qt); GitHub is a mirror.
REPO_URL = "https://fileapi.fastapicloud.dev/forge/#nandi.uk/shelly-qt"


@lru_cache(maxsize=1)
def info() -> dict:
    try:
        from ._build import BUILD  # type: ignore[import-not-found]
        data = dict(BUILD)
    except ImportError:
        data = {}
    data.setdefault("version", __version__)
    if not data.get("commit"):
        data["commit"] = _git_commit()
        if data["commit"]:
            data.setdefault("channel", "source")
    return data


def _git_commit() -> str:
    root = Path(__file__).resolve().parent.parent
    if not (root / ".git").exists():
        return ""
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def short_commit() -> str:
    return info().get("commit", "")[:7]


def version_string() -> str:
    """e.g. ``0.1.0 (continuous, abc1234)`` or plain ``0.1.0``."""
    d = info()
    c = short_commit()
    extra = [x for x in (d.get("channel"), c if c not in d["version"] else "") if x]
    return f"{d['version']} ({', '.join(extra)})" if extra else d["version"]


def commit_url() -> str:
    """Where to look at the build's commit. The forge has no per-commit deep link,
    so this opens the repo (its log lists the commit)."""
    return REPO_URL if info().get("commit") else ""
