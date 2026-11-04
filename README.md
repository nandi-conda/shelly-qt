# Shelly-Qt

A PySide6 desktop front end for [Shelly](https://github.com/Seafoam-Labs/Shelly-ALPM), the Arch Linux
package manager. It drives the `shelly` CLI the same way the official GTK app does: every command runs
with `--ui-mode`, results come back as base64 JSON frames on stdout, and interactive questions
(transaction review, optional deps, provider choice, PKGBUILD review) are answered on stdin.

## Features

| Page | What it does | CLI used |
|---|---|---|
| Browse | All repo packages, filter, details, install | `-Ssv`, `-Ssdi`, `install standard` |
| Installed | Installed packages, explicit filter, remove (cascade / optdeps / configs) | `-Ls`, `remove standard` |
| Updates | Repo + AUR + Flatpak updates, sync DBs, upgrade all, right-click a Flatpak to update just it | `-P`, `sync --force`, `upgrade all`, `update flatpak <id>` |
| AUR | Search, PKGBUILD preview, build+install, installed list, remove | `search aur`, `list aur`, `install/remove aur` |
| Flatpak | Installed apps, Flathub search, install (system/user), remove, update | `-Lf`, `search flatpak`, `install/remove flatpak` |
| AppImage | List, check/upgrade, install from file, remove | `list appimage`, `list-updates appimage`, … |
| Maintenance | Sync, remove orphans, clean cache, repair DB, fix permissions, install local package | `purify`, `utility` |
| Settings | View/edit `config.json` keys | `config list`, `config set` |

Privileged operations run through `pkexec`, as the GTK app does.

## Setup

The project is managed with [pixi](https://pixi.sh) (environment) and [just](https://just.systems)
(commands). Install both (`sudo pacman -S pixi just`), then:

```bash
just install        # pixi install: Python + PySide6 + pytest from conda-forge
just run            # start the GUI against the real `shelly` CLI
just demo           # start it against tests/fake_shelly.py (no Arch needed)
just test           # headless test suite
just screenshots    # regenerate screenshots/
just install-desktop  # add a shelly-qt launcher, .desktop entry and icon under ~/.local
just icon          # regenerate shelly_qt/icons/ (SVG + PNG sizes) from scripts/make_icon.py
```

`just` with no arguments lists every recipe. Without pixi, `pip install .` then `shelly-qt`
works too.

Environment overrides:

- `SHELLY_BIN` — command used for the CLI (default `shelly`), may include args.
- `SHELLY_ELEVATE` — privilege helper (default `pkexec`; set to empty to disable).
