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

# Install the launcher into ~/.local (desktop entry + shelly-qt wrapper)
install-desktop:
    mkdir -p ~/.local/share/applications ~/.local/bin
    printf '#!/bin/sh\nexec pixi run --manifest-path "%s/pixi.toml" python -m shelly_qt "$@"\n' "{{justfile_directory()}}" > ~/.local/bin/shelly-qt
    chmod +x ~/.local/bin/shelly-qt
    cp shelly-qt.desktop ~/.local/share/applications/

# Remove the pixi environment and caches
clean:
    rm -rf .pixi .pytest_cache
    find . -name __pycache__ -prune -exec rm -rf {} +
