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
        "border crossing",
        "border crossings",
        "illegal crossing",
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
        "fentanyl",
        "opioid",
        "opioids",
        "drug overdose",
    ],
    "regex_patterns": [
        re.compile(r"\bFBI\b"),
        re.compile(r"\bDOJ\b"),
        re.compile(r"\bUCR\b"),                       # Uniform Crime Reporting
        re.compile(r"crime\s+rate", re.IGNORECASE),
        re.compile(r"\bfentanyl\b", re.IGNORECASE),
        re.compile(r"\boverdose(?:s|d)?\b", re.IGNORECASE),
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


# ---------------------------------------------------------------------------
# legal_political — convictions, indictments, pardons, court rulings.
# Distinct from ``crime`` (which is aggregate offense statistics):
# this table targets named legal proceedings against public figures.
# ---------------------------------------------------------------------------
_LEGAL_POLITICAL: TopicTable = {
    "keywords": [
        "convicted",
        "convicted felon",
        "felon",
        "felony",
        "indicted",
        "indictment",
        "pardoned",
        "pardon",
        "prosecuted",
        "prosecution",
        "sentenced",
        "guilty plea",
        "pled guilty",
        "pleaded guilty",
        "found guilty",
        "plea deal",
        "plea bargain",
        "lawsuit",
        "subpoena",
        "subpoenaed",
        "impeached",
        "impeachment",
        "grand jury",
        "deposition",
        "court ruling",
        "settled the lawsuit",
    ],
    "regex_patterns": [
        re.compile(r"\bDOJ\b"),
        re.compile(r"\bSupreme\s+Court\b", re.IGNORECASE),
        re.compile(r"\bFEC\b"),                       # Federal Election Commission
        re.compile(r"\bDistrict\s+Attorney\b", re.IGNORECASE),
        re.compile(r"\bSpecial\s+Counsel\b", re.IGNORECASE),
        re.compile(r"\bcourt\s+ruling\b", re.IGNORECASE),
    ],
}

# ---------------------------------------------------------------------------
# elections — voting, ballots, turnout, election administration.
# Triggers on election-process language and named election bodies.
# ---------------------------------------------------------------------------
_ELECTIONS: TopicTable = {
    "keywords": [
        "ballot",
        "ballots",
        "vote",
        "voter",
        "voters",
        "voter id",
        "voter fraud",
        "voter registration",
        "election fraud",
        "rigged election",
        "stolen election",
        "turnout",
        "voter turnout",
        "mail-in ballot",
        "absentee ballot",
        "recount",
        "gerrymander",
        "gerrymandering",
        "primary election",
        "general election",
        "polling place",
        "campaign finance",
        "campaign contribution",
        "campaign contributions",
        "super pac",
        "dark money",
    ],
    "regex_patterns": [
        re.compile(r"\bFEC\b"),                       # Federal Election Commission
        re.compile(r"\bElectoral\s+College\b", re.IGNORECASE),
        re.compile(r"\bSecretary\s+of\s+State\b", re.IGNORECASE),
        re.compile(r"\bvoting\s+rights\b", re.IGNORECASE),
    ],
}

# ---------------------------------------------------------------------------
# foreign_policy — wars, treaties, sanctions, foreign aid, alliances.
# Triggers on diplomatic and military vocabulary plus named foreign
# countries/blocs that frequently appear in U.S. political claims.
# ---------------------------------------------------------------------------
_FOREIGN_POLICY: TopicTable = {
    "keywords": [
        "treaty",
        "treaties",
        "sanctions",
        "sanction",
        "foreign aid",
        "military aid",
        "ukraine",
        "russia",
        "china",
        "iran",
        "north korea",
        "israel",
        "gaza",
        "taiwan",
        "afghanistan",
        "iraq",
        "ally",
        "allies",
        "diplomacy",
        "diplomatic",
        "foreign policy",
        "intelligence agency",
    ],
    "regex_patterns": [
        re.compile(r"\bNATO\b"),
        re.compile(r"\bState\s+Department\b", re.IGNORECASE),
        re.compile(r"\bDepartment\s+of\s+Defense\b", re.IGNORECASE),
        re.compile(r"\bDoD\b"),
        re.compile(r"\bUN\b"),                        # United Nations
        re.compile(r"\bCIA\b"),
        re.compile(r"\bPentagon\b", re.IGNORECASE),
    ],
}


TABLES: dict[str, TopicTable] = {
    "immigration": _IMMIGRATION,
    "healthcare": _HEALTHCARE,
    "crime": _CRIME,
    "economy": _ECONOMY,
    "education": _EDUCATION,
    "legal_political": _LEGAL_POLITICAL,
    "elections": _ELECTIONS,
    "foreign_policy": _FOREIGN_POLICY,
}

# Sanity guard: every canonical topic must have a table.
assert set(TABLES.keys()) == set(TOPICS), (
    f"keyword_tables must cover every canonical topic; "
    f"missing={set(TOPICS) - set(TABLES.keys())}"
)
