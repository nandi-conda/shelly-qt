"""Palette fallback for KDE color schemes that Qt's built-in KDE theme can't read.

Qt's built-in "kde" platform theme only understands ``r,g,b`` colors in kdeglobals. Schemes
that store ``#rrggbb`` values (e.g. Material You) make it fall back to its default light
palette. KDE's own plasma-integration plugin handles them, but bundling it in the AppImage
would pull in a large number of KDE Frameworks dependencies. Instead, when (and only when)
Qt would hit that fallback, this module builds the palette from the user's kdeglobals, the
same way Qt does for ``r,g,b``.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QStandardPaths
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QPalette

Colors = dict[tuple[str, str], str]

# (palette role, kdeglobals group, key), mirroring QKdeThemePrivate::readKdeSystemPalette.
ROLES = [
    (QPalette.ColorRole.Window, "Window", "BackgroundNormal"),
    (QPalette.ColorRole.WindowText, "Window", "ForegroundNormal"),
    (QPalette.ColorRole.Text, "View", "ForegroundNormal"),
    (QPalette.ColorRole.Base, "View", "BackgroundNormal"),
    (QPalette.ColorRole.AlternateBase, "View", "BackgroundAlternate"),
    (QPalette.ColorRole.Link, "View", "ForegroundLink"),
    (QPalette.ColorRole.LinkVisited, "View", "ForegroundVisited"),
    (QPalette.ColorRole.Highlight, "Selection", "BackgroundNormal"),
    (QPalette.ColorRole.HighlightedText, "Selection", "ForegroundNormal"),
    (QPalette.ColorRole.ButtonText, "Button", "ForegroundNormal"),
    (QPalette.ColorRole.ToolTipBase, "Tooltip", "BackgroundNormal"),
    (QPalette.ColorRole.ToolTipText, "Tooltip", "ForegroundNormal"),
]


def kdeglobals_paths() -> list[Path]:
    """Readable kdeglobals files, highest priority first (the order Qt searches)."""
    dirs = QStandardPaths.standardLocations(QStandardPaths.StandardLocation.GenericConfigLocation)
    return [p for p in (Path(d) / "kdeglobals" for d in dirs) if os.access(p, os.R_OK)]


def read_colors(paths: list[Path]) -> Colors:
    """The ``[Colors:*]`` entries of the given kdeglobals files; earlier files win."""
    colors: Colors = {}
    for path in paths:
        group = ""
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                group = line[1:-1]
            elif group.startswith("Colors:") and "=" in line:
                key, _, value = line.partition("=")
                colors.setdefault((group[len("Colors:"):], key.strip()), value.strip())
    return colors


def parse_color(value: str) -> QColor | None:
    """A kdeglobals color: ``r,g,b`` or ``#rrggbb``."""
    if value.startswith("#"):
        color = QColor(value)
        return color if color.isValid() else None
    try:
        r, g, b = (int(part) for part in value.split(","))
    except ValueError:
        return None
    return QColor(r, g, b)


def qt_cannot_read(colors: Colors) -> bool:
    """True if Qt's KDE theme would discard the scheme and use its default palette.

    Qt gates the whole palette on the button background being ``r,g,b``.
    """
    button = colors.get(("Button", "BackgroundNormal"))
    return button is not None and len(button.split(",")) != 3


def build_palette(colors: Colors) -> QPalette | None:
    """A palette from the scheme, laid out like Qt's own (including its disabled colors)."""
    button = parse_color(colors.get(("Button", "BackgroundNormal"), ""))
    if button is None:
        return None
    window = parse_color(colors.get(("Window", "BackgroundNormal"), "")) or button
    pal = QPalette(button, window)
    for role, group, key in ROLES:
        color = parse_color(colors.get((group, key), ""))
        if color:
            pal.setBrush(role, color)

    dark = button.value() <= 128
    darker = QBrush(button.darker(50 if dark else 200))
    darker150 = QBrush(button.darker(75 if dark else 150))
    lighter150 = QBrush(button.lighter(75 if dark else 150))
    lighter = QBrush(button.lighter(50 if dark else 200))
    plain = QBrush(button)
    disabled = QPalette.ColorGroup.Disabled
    for role, brush in [
        (QPalette.ColorRole.WindowText, darker), (QPalette.ColorRole.ButtonText, darker),
        (QPalette.ColorRole.Text, darker), (QPalette.ColorRole.Button, plain),
        (QPalette.ColorRole.Base, plain), (QPalette.ColorRole.Window, plain),
        (QPalette.ColorRole.BrightText, QBrush(QColor("white"))),
        (QPalette.ColorRole.Highlight, darker150), (QPalette.ColorRole.HighlightedText, lighter150),
    ]:
        pal.setBrush(disabled, role, brush)
    pal.setBrush(QPalette.ColorRole.Light, lighter)
    pal.setBrush(QPalette.ColorRole.Midlight, lighter150)
    pal.setBrush(QPalette.ColorRole.Mid, darker150)
    pal.setBrush(QPalette.ColorRole.Dark, darker)
    return pal


class SchemeFollower:
    """Keeps the application palette in step with kdeglobals while Qt's theme can't."""

    def __init__(self, app: QGuiApplication) -> None:
        self.app = app
        self.original = app.palette()
        self.applied = False
        self.watcher = QFileSystemWatcher(app)
        self.watcher.fileChanged.connect(self.refresh)
        self.watcher.directoryChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_) -> None:
        paths = kdeglobals_paths()
        # Plasma replaces the file when the scheme changes, which drops the watch.
        watched = set(self.watcher.files() + self.watcher.directories())
        wanted = {str(p) for p in paths} | {str(p.parent) for p in paths}
        self.watcher.addPaths(sorted(wanted - watched))
        colors = read_colors(paths)
        pal = build_palette(colors) if qt_cannot_read(colors) else None
        if pal:
            self.app.setPalette(pal)
            self.applied = True
        elif self.applied:
            self.app.setPalette(self.original)
            self.applied = False


def follow_kde_scheme(app: QGuiApplication) -> SchemeFollower | None:
    """Start following the KDE color scheme; a no-op outside a KDE session."""
    if not os.environ.get("KDE_SESSION_VERSION"):
        return None
    return SchemeFollower(app)
