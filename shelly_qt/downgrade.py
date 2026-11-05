"""Downgrade installed repo packages to a cached or archived version.

``shelly downgrade <pkg> --list-options --ui-mode`` lists the candidates as
``[{Name, Filename, Location: Local|Remote, IsInstalled}]`` (oldest first).
UI mode installs one package per run with ``--target <filename>``, so a
multi-package downgrade runs one operation after another.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QLabel, QVBoxLayout)

from . import cli, protocol

LOCATIONS = {"Local": "package cache", "Remote": "archive"}


def version_of(c: dict) -> str:
    """'1.0-2' from 'demo-1.0-2-x86_64.pkg.tar.zst' (name-ver-rel-arch.pkg.tar.*)."""
    fn = str(c.get("Filename") or "")
    name = str(c.get("Name") or "")
    stem = fn.split(".pkg.tar")[0]
    if name and stem.startswith(name + "-"):
        parts = stem[len(name) + 1:].rsplit("-", 1)  # drop the architecture
        if len(parts) == 2:
            return parts[0]
    return fn


def label(c: dict) -> str:
    where = LOCATIONS.get(str(c.get("Location")), str(c.get("Location") or ""))
    text = f"{version_of(c)}  ({where})" if where else version_of(c)
    return text + " — installed" if c.get("IsInstalled") else text


def default_index(cands: list[dict]) -> int:
    """The newest version older than the installed one (the CLI's own default)."""
    inst = next((i for i, c in enumerate(cands) if c.get("IsInstalled")), None)
    if inst is not None and inst > 0:
        return inst - 1
    others = [i for i, c in enumerate(cands) if not c.get("IsInstalled")]
    return others[-1] if others else 0


def command(name: str, target: str, ignore: bool) -> list[str]:
    args = ["downgrade", name, "--target", target]
    if ignore:
        args.append("--ignore")
    return args


class DowngradeDialog(QDialog):
    """Pick a version per package; ``plan()`` gives the downgrade commands."""

    def __init__(self, names: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Downgrade packages" if len(names) > 1 else f"Downgrade {names[0]}")
        self.names = names
        self.cands: dict[str, list[dict]] = {}
        self.combos: dict[str, QComboBox] = {}
        lay = QVBoxLayout(self)
        self.info = QLabel("Looking for older versions in the package cache and the Arch archive…")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.form = QFormLayout()
        lay.addLayout(self.form)
        for n in names:
            combo = QComboBox()
            combo.setEnabled(False)
            combo.addItem("Loading…")
            self.combos[n] = combo
            self.form.addRow(n, combo)
        self.ignore = QCheckBox("Hold these versions (add to IgnorePkg)")
        self.ignore.setToolTip("Stops the next system upgrade from upgrading them straight back.")
        lay.addWidget(self.ignore)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText("Downgrade")
        self.ok.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.resize(520, self.sizeHint().height())
        for n in names:
            cli.query(["downgrade", n, "--list-options"], lambda r, e, n=n: self._loaded(n, r, e),
                      parse=lambda t: protocol.last_data(t, []))

    def _loaded(self, name: str, res, err) -> None:
        combo = self.combos[name]
        combo.clear()
        cands = [c for c in res if isinstance(c, dict) and c.get("Filename")] \
            if isinstance(res, list) and not err else []
        self.cands[name] = cands
        if err or not any(not c.get("IsInstalled") for c in cands):
            combo.addItem(str(err).strip().splitlines()[0][:120] if err else "No older versions found")
        else:
            for c in cands:
                combo.addItem(label(c), c.get("Filename"))
            combo.setCurrentIndex(default_index(cands))
            combo.setEnabled(True)
        if len(self.cands) == len(self.names):
            usable = bool(self.plan())
            self.ok.setEnabled(usable)
            self.info.setText("Choose the version to install." if usable else
                              "No older versions were found for these packages.")

    def plan(self) -> list[tuple[str, list[str]]]:
        """[(package, args)] for every package with a non-installed version chosen."""
        out = []
        for n in self.names:
            combo = self.combos[n]
            cands = self.cands.get(n) or []
            i = combo.currentIndex()
            if not combo.isEnabled() or not 0 <= i < len(cands) or cands[i].get("IsInstalled"):
                continue
            out.append((n, command(n, str(cands[i]["Filename"]), self.ignore.isChecked())))
        return out


def run_plan(run_op: Callable, plan: list[tuple[str, list[str]]], then: Callable | None) -> None:
    """Run the downgrades one after another (each waits for the previous to succeed)."""
    if not plan:
        return
    (name, args), rest = plan[0], plan[1:]
    run_op(f"Downgrading {name}", args, True,
           (lambda: run_plan(run_op, rest, then)) if rest else then)
