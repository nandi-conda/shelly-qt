# Shelly-Qt

A PySide6 desktop front end for [Shelly](https://github.com/Seafoam-Labs/Shelly-ALPM), the Arch Linux
package manager. It drives the `shelly` CLI the same way the official GTK app does: every command runs
with `--ui-mode`, results come back as base64 JSON frames on stdout, and interactive questions
(transaction review, optional deps, provider choice, PKGBUILD review) are answered on stdin.

## Features

| Page | What it does | CLI used |
|---|---|---|
| Search (top bar, Ctrl+K) | One query across repo packages, the AUR, Flatpak and prefix.dev at once; merged, ranked results with a Source column, per-source toggles, Hide installed, and Install that runs the right command for each source | `search standard`, `search aur`, `search flatpak` |
| Browse | All repo packages, filter, details, install | `-Ssv`, `-Ssdi`, `install standard` |
| Installed | Installed packages, explicit filter, remove (cascade / optdeps / configs) | `-Ls`, `remove standard` |
| Updates | Repo + AUR + Flatpak updates, sync DBs, upgrade all | `-P`, `sync --force`, `upgrade all` |
| AUR | Search, PKGBUILD preview, build+install, installed list, remove | `search aur`, `list aur`, `install/remove aur` |
| prefix.dev | Live search of every public prefix.dev channel as you type (relevance-ranked, Channel column; installs from the chosen channel), shows what the `[prefix]` repo offers and what's installed, Install adds the package to a [prefix-alpm](https://fileapi.fastapicloud.dev/git/smelly/prefix-alpm.git) server, syncs and installs under `/opt/prefix`. Without a server it still searches prefix.dev directly | prefix-alpm `/search`, `/add`; `sync --force`, `install standard` |
| Flatpak | Installed apps, Flathub search, install (system/user), remove, update | `-Lf`, `search flatpak`, `install/remove flatpak` |
| AppImage | List, check/upgrade, install from file, remove | `list appimage`, `list-updates appimage`, … |
| Maintenance | Sync, remove orphans, clean cache, repair DB, fix permissions, install local package | `purify`, `utility` |
| Settings | View/edit `config.json` keys | `config list`, `config set` |

Right-click any list item for **Update** and **Remove**, wherever they apply: Update shows on the Updates tabs and on installed items with a pending update (`update standard|aur|flatpak <name>`; repo packages are a partial upgrade, which the CLI warns about), Remove on anything installed. The menu acts on the clicked row, or all selected rows.

Search results are ranked by relevance (`shelly_qt/ranking.py`), used by the combined search and the
AUR, Flathub and prefix.dev pages: exact name, then name prefix, then a word in the name, then substring,
then description-only matches; `-debug`/`-git`/`-docs`/`lib…`/`python-…` variants you didn't type sink;
official repos, installed packages, AUR votes, Flathub installs and prefix.dev downloads break ties. The
**Match** column shows why a row matched; click its header to get back to relevance order after sorting
by another column.

New search sources (e.g. prefix.dev) plug in through `shelly_qt/search_sources.py`: subclass `Source`
and append it to `SOURCES`. AppImages aren't a source because Shelly has no AppImage catalogue search.

When an install fails because it would replace a package that something else pins to an exact version
(installing `shelly-bin` over `shelly` while `shelly-flatpak-backend` needs `shelly=3.1.10`), the failed
operation window offers fixes (`shelly_qt/conflicts.py`): **Install with …** adds the matching replacement
from the same AUR package base (here `shelly-flatpak-backend-bin`, built alongside `shelly-bin`) or the
same `-bin`/`-git` flavour, so both go in one transaction; **Remove … and retry** removes the dependents
(`remove standard --no-cascade`) and runs the original install again.

Privileged operations run through `pkexec`, as the GTK app does.

prefix.dev needs a running prefix-alpm server (`just serve` in its checkout, `[prefix]` in pacman.conf); point Shelly-Qt at another one with `PREFIX_ALPM_URL` (default `http://127.0.0.1:8787`).

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
just appimage      # build dist/Shelly-Qt-<version>-<arch>.AppImage (+ .zsync)
just icon          # regenerate shelly_qt/icons/ (SVG + PNG sizes) from scripts/make_icon.py
```

`just` with no arguments lists every recipe. Without pixi, `pip install .` then `shelly-qt`
works too.

## AppImage

Tagged releases (`v*`) and manual runs of the **AppImage** workflow publish
`Shelly-Qt-<version>-<arch>.AppImage` for x86_64 and aarch64 on the
[Releases](https://github.com/nandi-conda/shelly-qt/releases) page. Tags go to that release
(update channel `latest`); manual runs replace the rolling `continuous` prerelease.

```bash
chmod +x Shelly-Qt-*-x86_64.AppImage
./Shelly-Qt-*-x86_64.AppImage
```

**The `shelly` CLI is not bundled.** The AppImage only contains the GUI (Python, PySide6/Qt);
it runs the host's `shelly` (and `pkexec`, `flatpak`), so install Shelly on the system first.
The GPU stack (libGL/libEGL) also comes from the host.

Each AppImage embeds `gh-releases-zsync` update info and ships with a `.zsync` file, so
`appimageupdatetool Shelly-Qt-*.AppImage` (or AppImageUpdate, AppImageLauncher, Gear Lever)
downloads only the changed blocks of a newer release.

The AppImage can also update itself. It bundles `appimageupdatetool`
(`packaging/appimage/bundle-updater.sh`, about 6 MB), checks quietly a few seconds after
start and shows **Update available** in the status bar when a newer build is out. Click it,
or use **Check for Shelly-Qt updates…** on the Settings page, to download the delta, replace
the AppImage in place (same path, so launchers keep working) and restart into it. The folder
holding the AppImage must be writable. Set `SHELLY_QT_NO_UPDATE_CHECK=1` to skip the startup
check. None of this appears when Shelly-Qt runs from source or a distro package.

Build one locally with `just appimage` (output in `dist/`); the packaging scripts live in
`packaging/appimage/`.

## Opening files

After `just install-desktop`, Shelly-Qt is offered under "Open with" for `.flatpakref`, `.flatpak`
bundles, `.AppImage` files, `.pkg.tar.*` packages and `appstream://` / `flatpak+https://` links
(or run `shelly-qt <file>`). It also makes Shelly-Qt the default for Flatpak refs/bundles, AppImages
and those links (`just set-default`), so double-clicking them opens Shelly-Qt rather than the GTK Shelly app. A `.flatpakref` opens the Flatpak page on that app and asks to install
it with `shelly install flatpak --ref-file`.

Environment overrides:

- `SHELLY_BIN` — command used for the CLI (default `shelly`), may include args.
- `SHELLY_ELEVATE` — privilege helper (default `pkexec`; set to empty to disable).
