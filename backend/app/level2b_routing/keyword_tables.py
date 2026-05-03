"""Per-topic keyword and regex tables.

Each entry has two lists:
  * ``keywords``     — plain lowercased substrings; case-insensitive matches.
  * ``regex_patterns`` — pre-compiled regexes for higher-precision signals
    (numeric magnitudes, named bills/agencies, dollar amounts, etc.).

Tune these freely — they are the deterministic first pass of the router.
Hits are aggregated in ``keyword_matcher.score_keywords``: 1 point per
distinct keyword hit, 2 points per regex hit.
"""

from __future__ import annotations

import re
from typing import Pattern, TypedDict

from .topics import TOPICS


class TopicTable(TypedDict):
    keywords: list[str]
    regex_patterns: list[Pattern[str]]


# ---------------------------------------------------------------------------
# immigration — border, deportation, visas, asylum, migration agencies.
# Triggers on policy/process language and named immigration agencies.
# ---------------------------------------------------------------------------
_IMMIGRATION: TopicTable = {
    "keywords": [
        "border",
        "border wall",
        "deportation",
        "deport",
        "asylum",
        "asylum seeker",
        "migrant",
        "migrants",
        "immigrant",
        "immigration",
        "visa",
        "green card",
        "refugee",
        "ice raid",
        "uscis",
    ],
    "regex_patterns": [
        re.compile(r"\bICE\b"),                       # Immigration & Customs Enforcement
        re.compile(r"\bCBP\b"),                       # Customs and Border Protection
        re.compile(r"\bDACA\b", re.IGNORECASE),
        re.compile(r"\bTitle\s*42\b", re.IGNORECASE),
    ],
}

# ---------------------------------------------------------------------------
# healthcare — insurance, federal health programs, hospitals, regulators.
# Triggers on program names (Medicare/Medicaid/ACA) and clinical terms.
# ---------------------------------------------------------------------------
_HEALTHCARE: TopicTable = {
    "keywords": [
        "medicare",
        "medicaid",
        "obamacare",
        "affordable care act",
        "health insurance",
        "insurance premium",
        "prescription drug",
        "hospital",
        "hospitals",
        "patient",
        "patients",
        "uninsured",
        "preexisting condition",
    ],
    "regex_patterns": [
        re.compile(r"\bACA\b"),
        re.compile(r"\bFDA\b"),
        re.compile(r"\bCDC\b"),
        re.compile(r"\bNIH\b"),
    ],
}

# ---------------------------------------------------------------------------
# crime — violent/property crime, criminal justice, policing, incarceration.
# Triggers on offense vocabulary and named justice agencies.
# ---------------------------------------------------------------------------
_CRIME: TopicTable = {
    "keywords": [
        "crime",
        "crimes",
        "violent crime",
        "homicide",
        "homicides",
        "murder",
        "murders",
        "robbery",
        "burglary",
        "assault",
        "police",
        "policing",
        "prison",
        "incarceration",
        "criminal justice",
    ],
    "regex_patterns": [
        re.compile(r"\bFBI\b"),
        re.compile(r"\bDOJ\b"),
        re.compile(r"\bUCR\b"),                       # Uniform Crime Reporting
        re.compile(r"crime\s+rate", re.IGNORECASE),
    ],
}

# ---------------------------------------------------------------------------
# economy — macroeconomic indicators, fiscal/monetary policy, jobs, taxes.
# Triggers on numeric magnitudes, named indicators, and economic agencies.
# ---------------------------------------------------------------------------
_ECONOMY: TopicTable = {
    "keywords": [
        "inflation",
        "unemployment",
        "unemployment rate",
        "jobs report",
        "gdp",
        "recession",
        "federal reserve",
        "interest rate",
        "interest rates",
        "tax cut",
        "tax cuts",
        "tax hike",
        "deficit",
        "national debt",
        "trade deficit",
    ],
    "regex_patterns": [
        re.compile(r"\$[\d.,]+\s*(billion|trillion|million)", re.IGNORECASE),
        re.compile(r"\bGDP\b"),
        re.compile(r"\bBLS\b"),
        re.compile(r"\bFRED\b"),
        re.compile(r"\bBEA\b"),
    ],
}

# ---------------------------------------------------------------------------
# education — K-12, higher ed, student debt, education funding/agencies.
# Triggers on schooling vocabulary and named education agencies.
# ---------------------------------------------------------------------------
_EDUCATION: TopicTable = {
    "keywords": [
        "school",
        "schools",
        "public school",
        "charter school",
        "teacher",
        "teachers",
        "student loan",
        "student loans",
        "student debt",
        "college tuition",
        "university",
        "universities",
        "pell grant",
        "k-12",
    ],
    "regex_patterns": [
        re.compile(r"\bNCES\b"),                      # National Center for Education Statistics
        re.compile(r"\bDept\.?\s+of\s+Education\b", re.IGNORECASE),
        re.compile(r"\bTitle\s*IX\b", re.IGNORECASE),
    ],
}


TABLES: dict[str, TopicTable] = {
    "immigration": _IMMIGRATION,
    "healthcare": _HEALTHCARE,
    "crime": _CRIME,
    "economy": _ECONOMY,
    "education": _EDUCATION,
}

# Sanity guard: every canonical topic must have a table.
assert set(TABLES.keys()) == set(TOPICS), (
    f"keyword_tables must cover every canonical topic; "
    f"missing={set(TOPICS) - set(TABLES.keys())}"
)
