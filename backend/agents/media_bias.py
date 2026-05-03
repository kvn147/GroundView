"""Media-bias allowlist loader.

Single source of truth for the OpinionAgent's ``ALLOWED_SOURCES``.
Reads the same ``backend/data/media_bias.csv`` that ``judge.py`` parses
for source bias scores, so allowlist + bias registry stay in sync by
construction. Adding an outlet to the CSV picks it up in both places.
"""

from __future__ import annotations

import csv
import os
from functools import lru_cache


_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "media_bias.csv"
)


@lru_cache(maxsize=1)
def load_outlet_allowlist() -> frozenset[str]:
    """Return the canonical outlet names for the OpinionAgent allowlist.

    Cached at module load: the CSV is static within a process. If the
    CSV is missing, returns an empty frozenset — caller is responsible
    for failing fast rather than silently allowing nothing.
    """
    if not os.path.exists(_CSV_PATH):
        return frozenset()

    names: set[str] = set()
    with open(_CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("News Source") or "").strip()
            if name:
                names.add(name)
    return frozenset(names)


# ---------------------------------------------------------------------------
# Outlet alias map
# ---------------------------------------------------------------------------
#
# AllSides splits some outlets by section ("NPR (Online News)" vs
# "NPR (Opinion)"). The LLM is overwhelmingly likely to emit just "NPR".
# Without aliasing, every such citation lands in ``denied_sources`` even
# though the underlying outlet IS allowlisted.
#
# Strategy: when the agent's normalizer can't resolve a name, we try
# a small set of curated aliases. Aliases resolve to the *News* variant
# by default (the editorial position is what the speaker would be
# referencing); the *Opinion* variant is reachable only by the LLM
# emitting the literal parenthetical name.

# Alias keys must already be in the base-class normalized form:
# lowercased + non-alphanumerics stripped. ``_normalize`` below mirrors
# ``backend.agents.base._normalize_source`` exactly so we can call it
# without circular imports.
_ALIASES: dict[str, str] = {
    "npr": "NPR (Online News)",
    "wallstreetjournal": "Wall Street Journal (News)",
    "wsj": "Wall Street Journal (News)",
    "wallstreetjournalnews": "Wall Street Journal (News)",
    "foxnews": "Fox News Digital",
    "fox": "Fox News Digital",
    "newyorktimes": "New York Times (News)",
    "nyt": "New York Times (News)",
    "nytimes": "New York Times (News)",
    "newyorkpost": "New York Post (News)",
    "nypost": "New York Post (News)",
    "nationalreview": "National Review (News)",
    "newsmax": "Newsmax (News)",
    "abcnews": "ABC News (Online)",
    "abc": "ABC News (Online)",
    "cbsnews": "CBS News (Online)",
    "cbs": "CBS News (Online)",
    "cnn": "CNN Digital",
    "nbcnews": "NBC News Digital",
    "nbc": "NBC News Digital",
    "bbc": "BBC News",
    "ap": "Associated Press",
    "theassociatedpress": "Associated Press",
    "associatedpressfactcheck": "Associated Press Fact Check",
    "factcheck": "FactCheck.org",
    "factcheckorg": "FactCheck.org",
    "thepost": "Washington Post",
    "wapo": "Washington Post",
    "thewashingtonpost": "Washington Post",
    "wsjopinion": "Wall Street Journal (Opinion)",
    "foxopinion": "Fox News (Opinion)",
    "foxnewsopinion": "Fox News (Opinion)",
    "nytopinion": "New York Times (Opinion)",
    "nationalreviewopinion": "National Review (Opinion)",
}


def resolve_alias(normalized: str) -> str | None:
    """Resolve a normalized outlet name to a canonical CSV entry, if any.

    ``normalized`` should already be lowercased and stripped of
    non-alphanumerics by the caller (i.e. the same normalization the
    base agent's ``_normalize_source`` applies). Returns ``None`` if no
    alias matches.
    """
    return _ALIASES.get(normalized)
