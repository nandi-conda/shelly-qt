# Shelly-Qt: PySide6 GUI for Shelly. Run `just` to list recipes.

set positional-arguments

default:
    @just --list

# Create/update the pixi environment
install:
    pixi install

# Run the GUI against the real `shelly` CLI
run *args:
    pixi run python -m shelly_qt "$@"

# Run the GUI against the bundled fake CLI (no Arch needed)
demo:
    pixi run demo

# Run the test suite headless
test *args:
    QT_QPA_PLATFORM=offscreen pixi run pytest -q "$@"

# Regenerate screenshots/ from the fake CLI
screenshots:
    QT_QPA_PLATFORM=offscreen SHELLY_BIN="python tests/fake_shelly.py" SHELLY_ELEVATE="" pixi run python scripts/screenshots.py

# Install the launcher into ~/.local (desktop entry, icon, shelly-qt wrapper)
install-desktop:
    mkdir -p ~/.local/share/applications ~/.local/bin ~/.local/share/icons/hicolor/scalable/apps
    cp shelly_qt/icons/shelly-qt.svg ~/.local/share/icons/hicolor/scalable/apps/shelly-qt.svg
    for s in 16 22 24 32 48 64 128 256 512; do mkdir -p ~/.local/share/icons/hicolor/${s}x${s}/apps && cp shelly_qt/icons/shelly-qt-$s.png ~/.local/share/icons/hicolor/${s}x${s}/apps/shelly-qt.png; done
    printf '#!/bin/sh\nexport SHELLY_QT_CWD="$PWD"\nexec pixi run --manifest-path "%s/pixi.toml" python -m shelly_qt "$@"\n' "{{justfile_directory()}}" > ~/.local/bin/shelly-qt
    chmod +x ~/.local/bin/shelly-qt
    cp shelly-qt.desktop ~/.local/share/applications/
    -gtk-update-icon-cache -q -t ~/.local/share/icons/hicolor
    -update-desktop-database -q ~/.local/share/applications
    just set-default

# Make Shelly-Qt the default app for Flatpak refs/bundles, AppImages and appstream:// links
set-default:
    -xdg-mime default shelly-qt.desktop application/vnd.flatpak.ref application/vnd.flatpak application/vnd.appimage application/x-iso9660-appimage x-scheme-handler/appstream x-scheme-handler/flatpak+https
    @echo "application/vnd.flatpak.ref -> $(xdg-mime query default application/vnd.flatpak.ref 2>/dev/null)"

# Regenerate the app icon (SVG + PNG sizes) in shelly_qt/icons/
icon:
    QT_QPA_PLATFORM=offscreen pixi run python scripts/make_icon.py

# Build dist/Shelly-Qt-<version>-<arch>.AppImage (+ .zsync) from the pixi `appimage` env
appimage version=`git describe --tags --exclude continuous --always --dirty 2>/dev/null | sed 's/^v//'`:
    #!/usr/bin/env bash
    set -euo pipefail
    arch=${ARCH:-$(uname -m)}
    QT_QPA_PLATFORM=offscreen packaging/appimage/build-appdir.sh build/Shelly-Qt.AppDir
    ARCH=$arch packaging/appimage/make-appimage.sh build/Shelly-Qt.AppDir \
        "dist/Shelly-Qt-{{version}}-$arch.AppImage" \
        "gh-releases-zsync|nandi-conda|shelly-qt|latest|Shelly-Qt-*-$arch.AppImage.zsync"

# Remove the pixi environment, caches and AppImage build output
clean:
    rm -rf .pixi .pytest_cache build dist
    find . -name __pycache__ -prune -exec rm -rf {} +
