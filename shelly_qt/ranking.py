"""Relevance ranking shared by every package search (combined, AUR, Flathub, prefix.dev).

Rows are ordered by, in turn:

1. how the query matches the name: exact, prefix at a word boundary (``zed`` ->
   ``zed-bin``), plain prefix, a whole word inside the name (``python-zed``), any
   substring, all query words in the name, then description-only matches;
2. a penalty for split/variant packages the query didn't ask for (``-debug``,
   ``-git``, ``-docs``, ``lib…``, ``python-…``);
3. a popularity score: official repos and installed packages get a boost, AUR
   votes, Flathub installs and prefix.dev downloads count on a log scale;
4. shorter names, then name, then source order.

:func:`rank_rows` stores the result on each row as ``_rank`` (1 = best) and
``_match`` (a short label), which tables show in a sortable "Match" column so
"sort by relevance" can be restored after sorting by another column.
"""
from __future__ import annotations

import math
import re
from typing import Iterable

EXACT, BOUNDARY_PREFIX, PREFIX, WORD, SUBSTRING, ALL_WORDS, DESCRIPTION, OTHER = range(8)
LABELS = {EXACT: "exact", BOUNDARY_PREFIX: "starts with", PREFIX: "starts with", WORD: "in name",
          SUBSTRING: "in name", ALL_WORDS: "in name", DESCRIPTION: "description", OTHER: ""}

SEP = r"[-_.+ ]"
# variants people rarely mean unless they type them
VARIANT_SUFFIXES = ("debug", "dbg", "git", "hg", "svn", "nightly", "docs", "doc", "devel", "dev",
                    "headers", "static", "i18n", "l10n", "lang", "locale", "tests", "examples")
LANG_PREFIXES = ("python", "python3", "perl", "ruby", "haskell", "lua", "node", "r", "rust", "go",
                 "ocaml", "php", "lib32")
SOURCE_ORDER = ("repo", "flatpak", "aur", "prefix")


def name_of(row: dict) -> str:
    # prefix.dev rows are served as conda-<name>; rank on the conda package name
    return str(row.get("conda_name") or row.get("Name") or row.get("name") or "").lower()


def ident_of(row: dict) -> str:
    return str(row.get("AppId") or row.get("app_id") or row.get("id") or row.get("Id") or "").lower()


def description_of(row: dict) -> str:
    return str(row.get("Description") or row.get("summary") or row.get("description") or "").lower()


def tier(row: dict, q: str) -> int:
    name, ident = name_of(row), ident_of(row)
    last = ident.rsplit(".", 1)[-1] if ident else ""
    if name == q or ident == q or last == q:
        return EXACT
    if re.match(re.escape(q) + SEP, name) or (last and re.match(re.escape(q) + SEP, last)):
        return BOUNDARY_PREFIX
    if name.startswith(q) or (last and last.startswith(q)):
        return PREFIX
    if re.search(SEP + re.escape(q) + r"(?:" + SEP + r"|$)", name) or \
            re.search(r"\." + re.escape(q) + r"(?:\.|$)", ident):
        return WORD
    if q in name or q in ident:
        return SUBSTRING
    words = q.split()
    if len(words) > 1 and all(w in name or w in ident for w in words):
        return ALL_WORDS
    desc = description_of(row)
    if words and all(w in desc for w in words):
        return DESCRIPTION
    return OTHER


def penalty(row: dict, q: str) -> int:
    """Count variant markers in the name that the query itself doesn't contain."""
    parts = re.split(SEP, name_of(row))
    asked = set(re.split(SEP, q))
    p = sum(1 for s in parts[1:] if s in VARIANT_SUFFIXES and s not in asked)
    if parts and parts[0] in LANG_PREFIXES and parts[0] not in asked and len(parts) > 1:
        p += 1
    if parts and parts[0].startswith("lib") and not q.startswith("lib") and parts[0] != q:
        p += 1
    return p


def _log(n, scale: float) -> float:
    try:
        return min(1.0, math.log10(1 + max(0.0, float(n or 0))) / scale)
    except (TypeError, ValueError):
        return 0.0


def popularity(row: dict, source: str | None = None) -> float:
    """0..~1.5: how likely this is the package people want, comparable across sources."""
    src = source or row.get("_source") or ""
    score = 0.0
    if src == "repo":
        score += 0.75 + (0.05 if row.get("Repository") in ("core", "extra") else 0.0)
    elif src == "aur":
        score += 0.8 * _log(row.get("NumVotes"), 4)  # ~10k votes -> 0.8
        score += 0.1 * min(1.0, float(row.get("Popularity") or 0) / 10)
        if row.get("OutOfDate"):
            score -= 0.2
    elif src == "flatpak":
        score += 0.8 * _log(row.get("installs_last_month") or row.get("installs"), 5)
        score += 0.1 if row.get("verification_verified") else 0.0
    elif src == "prefix":
        score += 0.6 * _log(row.get("downloads") or row.get("download_count"), 7)
    if row.get("Installed") or row.get("installed"):
        score += 0.2
    return score


def relevance(row: dict, query: str, source: str | None = None) -> tuple:
    q = query.strip().lower()
    src = source or row.get("_source") or ""
    order = SOURCE_ORDER.index(src) if src in SOURCE_ORDER else len(SOURCE_ORDER)
    name = name_of(row)
    return (tier(row, q), penalty(row, q), -round(popularity(row, src), 3), len(name), name, order)


def rank_rows(rows: Iterable[dict], query: str, source: str | None = None) -> list[dict]:
    """Sort ``rows`` by relevance to ``query`` and annotate ``_rank``/``_match`` on each."""
    q = query.strip().lower()
    out = sorted((r for r in rows if isinstance(r, dict)), key=lambda r: relevance(r, q, source))
    for i, r in enumerate(out, 1):
        r["_rank"] = i
        r["_match"] = LABELS[tier(r, q)] if q else ""
    return out


def match_column():
    """Table column showing the match kind; sorts by rank (ascending = most relevant first)."""
    return ("Match", lambda r: r.get("_match", ""), lambda r: r.get("_rank", 10**9))
