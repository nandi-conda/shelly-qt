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
| Updates | Repo + AUR + Flatpak updates, sync DBs, upgrade all | `-P`, `sync --force`, `upgrade all` |
| AUR | Search, PKGBUILD preview, build+install, installed list, remove | `search aur`, `list aur`, `install/remove aur` |
| Flatpak | Installed apps, Flathub search, install (system/user), remove, update | `-Lf`, `search flatpak`, `install/remove flatpak` |
| AppImage | List, check/upgrade, install from file, remove | `list appimage`, `list-updates appimage`, … |
| Maintenance | Sync, remove orphans, clean cache, repair DB, fix permissions, install local package | `purify`, `utility` |
| Settings | View/edit `config.json` keys | `config list`, `config set` |

Right-click any list item for **Update** and **Remove**, wherever they apply: Update shows on the Updates tabs and on installed items with a pending update (`update standard|aur|flatpak <name>`; repo packages are a partial upgrade, which the CLI warns about), Remove on anything installed. The menu acts on the clicked row, or all selected rows.

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

## Opening files

After `just install-desktop`, Shelly-Qt is offered under "Open with" for `.flatpakref`, `.flatpak`
bundles, `.AppImage` files, `.pkg.tar.*` packages and `appstream://` / `flatpak+https://` links
(or run `shelly-qt <file>`). It also makes Shelly-Qt the default for Flatpak refs/bundles, AppImages
and those links (`just set-default`), so double-clicking them opens Shelly-Qt rather than the GTK Shelly app. A `.flatpakref` opens the Flatpak page on that app and asks to install
it with `shelly install flatpak --ref-file`.

Environment overrides:

- `SHELLY_BIN` — command used for the CLI (default `shelly`), may include args.
- `SHELLY_ELEVATE` — privilege helper (default `pkexec`; set to empty to disable).
