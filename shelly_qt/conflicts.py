"""Work out how to get past "would remove a package that X requires" failures.

When an install replaces a package (``shelly-bin`` replacing ``shelly``),
libalpm refuses if another installed package still needs the old one with an
exact version (``shelly-flatpak-backend`` requires ``shelly=3.1.10``). Shelly
reports each such blocker as one sentence; this module turns those sentences
into structured blockers and picks fixes:

* **install together**: find a replacement for the dependent that comes from
  the same source as what is being installed. For the AUR that is a member of
  the same package base (``shelly-flatpak-backend-bin`` is built alongside
  ``shelly-bin``), or failing that a package with the same flavour suffix
  (``-bin``/``-git``) that provides the dependent. Shelly builds members of one
  base once and installs them in a single transaction, and libalpm then offers
  to replace the old dependent because the new one conflicts with it.
* **remove first**: drop the dependents, then run the original install again.

Everything here is pure so it can be tested without a CLI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

BLOCKER_RE = re.compile(
    r'Could not install "(?P<removed>[^"]+)" because it would remove a package that provides '
    r'"(?P<dependency>[^"]+)", which "(?P<dependent>[^"]+)" requires')

FLAVOURS = ("-bin", "-git", "-nightly", "-beta", "-stable", "-appimage")


@dataclass(frozen=True)
class Blocker:
    removed: str      # installed package the transaction would remove
    dependency: str   # what the dependent needs, e.g. "shelly=3.1.10"
    dependent: str    # installed package that needs it


@dataclass
class InstallRequest:
    backend: str            # "aur", "standard", ...
    targets: list[str]
    flags: list[str] = field(default_factory=list)

    def args(self, extra: list[str] = ()) -> list[str]:
        targets = self.targets + [e for e in extra if e not in self.targets]
        return ["install", self.backend, *targets, *self.flags]


def find_blockers(messages: list[str]) -> list[Blocker]:
    out: list[Blocker] = []
    for text in messages:
        for m in BLOCKER_RE.finditer(text or ""):
            b = Blocker(m["removed"], m["dependency"], m["dependent"])
            if b not in out:
                out.append(b)
    return out


def install_request(args: list[str]) -> InstallRequest | None:
    """The install an operation's argv describes, or None for other operations."""
    if len(args) < 3 or args[0] != "install" or args[1].startswith("-"):
        return None
    targets = [a for a in args[2:] if not a.startswith("-")]
    flags = [a for a in args[2:] if a.startswith("-")]
    return InstallRequest(args[1], targets, flags) if targets else None


def dep_name(dep: str) -> str:
    """``shelly=3.1.10`` -> ``shelly``; ``foo>=2: description`` -> ``foo``."""
    return re.split(r"[<>=:\s]", dep.strip(), maxsplit=1)[0]


def flavour(name: str) -> str:
    return next((f for f in FLAVOURS if name.endswith(f)), "")


def _names(values) -> set[str]:
    return {dep_name(v) for v in (values or []) if isinstance(v, str)}


def pick_replacement(blocker: Blocker, request: InstallRequest,
                     target_rows: list[dict], candidates: list[dict]) -> dict | None:
    """Choose the AUR package that should replace ``blocker.dependent``.

    ``target_rows`` are AUR rows for what is being installed (for their
    package bases); ``candidates`` are AUR rows found by searching for the
    dependent. Only a package that provides the dependent qualifies, so other
    packages needing it stay satisfied.
    """
    bases = {r.get("PackageBase") or r.get("Name") for r in target_rows
             if r.get("Name") in request.targets}
    wanted = {flavour(t) for t in request.targets} - {""}
    best, best_score = None, 0
    for c in candidates:
        name = c.get("Name") or ""
        if not name or name == blocker.dependent or name in request.targets:
            continue
        if blocker.dependent not in _names(c.get("Provides")):
            continue
        score = 0
        if (c.get("PackageBase") or name) in bases:
            score += 4
        if flavour(name) and flavour(name) in wanted:
            score += 2
        if score == 0:
            continue  # a provider from an unrelated source is a guess, not a fix
        if not c.get("OutOfDate"):
            score += 1
        if score > best_score:
            best, best_score = c, score
    return best


def removal_args(blockers: list[Blocker]) -> list[str]:
    deps = list(dict.fromkeys(b.dependent for b in blockers))
    # --no-cascade: take out only the blocking packages, not what they pulled in
    return ["remove", "standard", *deps, "--no-cascade"]
