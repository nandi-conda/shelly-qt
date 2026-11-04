#!/usr/bin/env python3
"""Shrink a PySide6 AppDir built from a conda/pixi env.

Usage: trim.py <AppDir> [QtModule ...]

Keeps only the PySide6 modules named on the command line (QtCore, QtGui and
QtWidgets are always kept), the Qt plugins a desktop widgets app needs, and the
shared libraries they and the Python interpreter actually link against
(followed through DT_NEEDED). Everything else in usr/lib is deleted.

The host's GL/EGL/Vulkan/DRM stack is used instead of the bundled copies, since
those must match the host's GPU driver (same as the AppImage excludelist).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ALWAYS = {"QtCore", "QtGui", "QtWidgets"}
PLUGIN_DIRS = {
    "platforms", "platformthemes", "platforminputcontexts", "imageformats", "iconengines",
    "tls", "networkinformation", "xcbglintegrations", "egldeviceintegrations", "generic",
    "wayland-decoration-client", "wayland-graphics-integration-client",
    "wayland-shell-integration",
}
# Platform plugins worth shipping: X11, Wayland, and offscreen for headless tests.
PLATFORMS = {"libqxcb.so", "libqwayland.so", "libqoffscreen.so", "libqminimal.so"}
# Loaded with dlopen(), so not visible as DT_NEEDED; keep if present.
DLOPENED = re.compile(r"^lib(ssl|crypto|xkbcommon-x11|xcb-cursor)\.so")
# Take these from the host (driver-specific).
HOST = re.compile(r"^lib(GL|EGL|GLX|GLdispatch|OpenGL|GLESv[12]_CM|GLESv2|gbm|drm|vulkan)\.so")
RM_DIRS = [
    "lib/qt6/qml", "lib/qt6/bin", "lib/qt6/metatypes", "lib/qt6/mkspecs", "lib/qt6/modules",
    "lib/qt6/libexec", "lib/qt6/sbom", "lib/clang", "lib/gtk-3.0", "lib/gio",
    "share/qt6/json_schema", "share/qt6/phrasebooks", "share/qt6/webchannel",
    "share/gir-1.0", "share/locale", "share/terminfo", "share/PySide6", "share/examples",
    "share/gtk-doc", "share/aclocal", "share/bash-completion", "share/licenses", "share/zoneinfo",
    "share/tsearch_data", "share/timezonesets", "share/gettext", "share/icu", "share/cups",
    "share/alsa", "share/et", "share/extension", "share/xml", "share/tabset",
    "lib/python3*/site-packages/shiboken6_generator", "lib/python3*/test",
    "lib/python3*/idlelib", "lib/python3*/tkinter", "lib/python3*/ensurepip",
    "lib/python3*/lib2to3", "lib/python3*/turtledemo",
]


def needed(path: Path) -> list[str]:
    out = subprocess.run(["readelf", "-d", str(path)], capture_output=True, text=True).stdout
    return re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", out)


def is_elf(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


def rm(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    elif p.exists() or p.is_symlink():
        p.unlink()


def main() -> int:
    appdir = Path(sys.argv[1]).resolve()
    keep_mods = ALWAYS | set(sys.argv[2:])
    usr = appdir / "usr"
    lib = usr / "lib"
    site = next(lib.glob("python3*/site-packages"))
    pyside = site / "PySide6"

    for pattern in RM_DIRS:
        for p in usr.glob(pattern):
            rm(p)

    # PySide6: drop unused bindings and the bundled Qt tools.
    for p in pyside.iterdir():
        m = re.match(r"^(Qt\w+?)(\.cpython.*\.so|\.abi3\.so|\.pyi)$", p.name)
        if m and m.group(1) not in keep_mods:
            rm(p)
        elif p.name in {"QtAsyncio", "scripts", "examples", "glue", "include", "typesystems",
                        "Qt", "doc"} or (p.is_file() and os.access(p, os.X_OK) and not p.suffix):
            rm(p)

    # Qt plugins.
    plugins = lib / "qt6" / "plugins"
    for d in plugins.iterdir():
        if d.name not in PLUGIN_DIRS:
            rm(d)
    for p in (plugins / "platforms").iterdir():
        if p.name not in PLATFORMS:
            rm(p)

    # Executables: only the interpreter.
    for p in (usr / "bin").iterdir():
        if not re.match(r"^python3?(\.\d+)?$", p.name):
            rm(p)

    # Follow DT_NEEDED from every ELF we keep outside usr/lib's top level.
    roots = [p for p in (usr / "bin").iterdir() if is_elf(p.resolve())]
    roots += [p for p in site.parent.rglob("*.so") if is_elf(p)]
    roots += [p for p in plugins.rglob("*.so") if is_elf(p)]
    by_name = {p.name: p for p in lib.iterdir() if ".so" in p.name}
    keep: set[str] = {n for n in by_name if DLOPENED.match(n)}
    todo = [n for r in roots for n in needed(r.resolve())] + list(keep)
    while todo:
        n = todo.pop()
        if n in keep or n not in by_name:
            continue
        keep.add(n)
        todo += needed(by_name[n].resolve())

    # Keep the real files behind kept sonames, plus their symlink chains.
    keep_files: set[str] = set()
    for n in keep:
        p = by_name[n]
        keep_files.add(p.name)
        while p.is_symlink():
            p = p.parent / os.readlink(p)
            keep_files.add(p.name)
    removed = 0
    for name, p in by_name.items():
        if HOST.match(name) or (name not in keep_files and not p.is_dir()):
            rm(p)
            removed += 1
    # Leftover static archives / python files belonging to removed libs.
    for p in lib.iterdir():
        if p.is_dir() and p.name not in {"qt6", "gdk-pixbuf-2.0"} and not p.name.startswith("python"):
            rm(p)

    print(f"trim: kept {len(keep)} libs, removed {removed} files; Qt modules: {sorted(keep_mods)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
