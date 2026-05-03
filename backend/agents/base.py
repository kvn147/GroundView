"""``AllowlistedAgent`` — the L3 base class with hard permission enforcement.

This is the ConductorOne-thesis-as-code layer. Every concrete agent
subclasses ``AllowlistedAgent`` and declares three class attributes:

    class EconomyAgent(AllowlistedAgent):
        DOMAIN_NAME = "economy"
        DOMAIN_DESCRIPTION = "macroeconomic indicators, fiscal policy, jobs"
        ALLOWED_SOURCES = frozenset({"BLS", "FRED", "BEA", ...})

Everything else — caching, Tier-A probe, Tier-B retrieval, allowlist
enforcement, activity logging, parse-failure handling — is in this base.
Subclasses do not override methods.

Pipeline a single ``verify(claim)`` call walks through:

    1. ``prompt_hash`` cache lookup → return cached result on hit (no LLM).
    2. Tier A: probe universal fact-checkers via Haiku (cheap, strict).
       If a verdict exists, return early with ``nli_source="agent"``.
    3. Tier B: domain retrieval via Gemini, structured-JSON output.
       Drop any cited source not in ``ALLOWED_SOURCES``; log denials.
    4. Build ``VerificationResult`` + ``AgentActivityLog``.
    5. Cache the result; return.

Failure modes (all non-crashing):

  * LLM parse failure → log ``error="parse_failure"``, empty evidence.
  * LLM network error → log ``error="llm_error: <details>"``, empty evidence.
  * Missing API key → same as network error.

Tests inject mock LLM clients and caches; nothing here depends on
network or API keys to be importable.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from abc import ABC
from typing import Any, Optional, Protocol

from backend.contracts import (
    AgentActivityLog,
    EvidenceItem,
    Source,
    VerificationResult,
)


# ---------------------------------------------------------------------------
# LLM client protocol — narrow, mockable in tests
# ---------------------------------------------------------------------------


class LlmClient(Protocol):
    """Minimal async LLM client. Real impl is OpenRouter via AsyncOpenAI;
    tests pass a fake."""

    async def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
    ) -> str:
        ...


# ---------------------------------------------------------------------------
# Cache protocol — defaults to in-memory; swap for diskcache later
# ---------------------------------------------------------------------------


class Cache(Protocol):
    def get(self, key: str) -> Optional[VerificationResult]:
        ...

    def set(self, key: str, value: VerificationResult) -> None:
        ...


class InMemoryCache:
    """Default cache. Lost on restart, fine for the demo."""

    def __init__(self) -> None:
        self._store: dict[str, VerificationResult] = {}

    def get(self, key: str) -> Optional[VerificationResult]:
        return self._store.get(key)

    def set(self, key: str, value: VerificationResult) -> None:
        self._store[key] = value


# ---------------------------------------------------------------------------
# Source normalization — Gemini returns names inconsistently
# ---------------------------------------------------------------------------


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalize_source(name: str) -> str:
    """Lowercase, strip non-alphanumerics. ``"Bureau of Labor Statistics"``
    and ``"bureau-of-labor-statistics"`` and ``"BLS"`` will not match each
    other under this — exact-name discipline is intentional. The allowlist
    is a contract, not a fuzzy set."""
    return _NON_ALNUM.sub("", name.lower())


def _allowlist_index(allowed_sources: frozenset[str]) -> dict[str, str]:
    """Build ``{normalized_name: canonical_name}`` so we can resolve a
    Gemini-returned name back to the canonical allowlist entry."""
    return {_normalize_source(s): s for s in allowed_sources}


# ---------------------------------------------------------------------------
# JSON parsing — Gemini occasionally wraps in code fences
# ---------------------------------------------------------------------------


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_json_or_none(raw: str) -> Optional[Any]:
    """Robust JSON parser for LLM output. Strips markdown code fences,
    returns ``None`` on parse failure (caller logs ``error``)."""
    cleaned = _FENCE_RE.sub("", raw).strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------


_TIER_A_SYSTEM = """\
You determine whether a political claim has been EXPLICITLY fact-checked
by one of these universal fact-checkers:
  PolitiFact, FactCheck.org, Snopes, Associated Press, Reuters,
  Washington Post Fact Checker.

If yes, respond with JSON of the form:
{{"checked": true, "fact_checker": "PolitiFact",
  "verdict_text": "...", "url": "https://...",
  "p_entail": 0.0-1.0, "p_contradict": 0.0-1.0}}

The two probabilities reflect the fact-checker's verdict:
  - "True" / "Mostly True"   → p_entail high, p_contradict low
  - "False" / "Mostly False" → p_entail low, p_contradict high
  - "Mixed"                  → both around 0.5

If you are NOT sure the claim has been explicitly fact-checked by one of
those organizations, respond with: {{"checked": false}}

Do not invent a fact-check. If unsure, return {{"checked": false}}.
"""


_TIER_B_SYSTEM = """\
You are a research assistant for the {domain_name} domain
({domain_description}).

Return ONLY a JSON array of evidence items. Each item must cite a source
from this allowlist (use the EXACT name as written):

  {allowed_sources_block}

Format each item as:
{{"source_name": "BLS",
  "url": "https://...",
  "text": "Concise factual statement attributed to that source."}}

If you cannot cite an allowlisted source for a fact, omit it. Do not
fabricate URLs; if you don't know the URL, use an empty string.
Return an empty array [] if no allowlisted evidence is available.
"""


# ---------------------------------------------------------------------------
# The base class
# ---------------------------------------------------------------------------


class AllowlistedAgent(ABC):
    """Base class for L3 domain agents.

    Subclass class attributes (override in each concrete agent):
      * ``DOMAIN_NAME`` — short slug, e.g. ``"economy"``.
      * ``DOMAIN_DESCRIPTION`` — one-line natural-language description.
      * ``ALLOWED_SOURCES`` — ``frozenset[str]`` of canonical source names.
        This is the permission allowlist. Hard, immutable.

    Optional class attributes:
      * ``TIER_A_MODEL`` — defaults to Anthropic Haiku 4.5 (strict
        non-fabrication on "does this fact-check exist" probes).
      * ``TIER_B_MODEL`` — defaults to Gemini 2.5 Flash.
    """

    # Subclasses MUST override these. Empty defaults so attribute access
    # doesn't crash before the subclass is fully defined; instances fail
    # fast in ``__init__`` if the override is missing.
    DOMAIN_NAME: str = ""
    DOMAIN_DESCRIPTION: str = ""
    ALLOWED_SOURCES: frozenset[str] = frozenset()

    TIER_A_MODEL: str = "anthropic/claude-haiku-4-5"
    TIER_B_MODEL: str = "google/gemini-2.5-flash"

    def __init__(self, llm: LlmClient, cache: Optional[Cache] = None) -> None:
        if not self.DOMAIN_NAME:
            raise ValueError(
                f"{type(self).__name__} must set DOMAIN_NAME"
            )
        if not self.ALLOWED_SOURCES:
            raise ValueError(
                f"{type(self).__name__} must set ALLOWED_SOURCES "
                "(non-empty frozenset). An empty allowlist is never "
                "intentional — it would silently drop every citation."
            )
        self._llm = llm
        self._cache: Cache = cache if cache is not None else InMemoryCache()
        self._allowlist_norm = _allowlist_index(self.ALLOWED_SOURCES)

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------

    async def verify(self, claim_text: str) -> VerificationResult:
        cache_key = self._make_cache_key(claim_text)
        cached = self._cache.get(cache_key)
        if cached is not None:
            # Re-emit with cache_hit=True so the activity log is honest.
            return cached.model_copy(update={"cache_hit": True})

        start = time.monotonic()
        tier_a = await self._run_tier_a(claim_text)
        if tier_a is not None:
            tier_a = self._finalize(
                tier_a,
                start=start,
                cache_key=cache_key,
            )
            return tier_a

        result = await self._run_tier_b(claim_text)
        result = self._finalize(result, start=start, cache_key=cache_key)
        return result

    # ------------------------------------------------------------------
    # Tier A — universal fact-checker probe
    # ------------------------------------------------------------------

    async def _run_tier_a(self, claim_text: str) -> Optional[VerificationResult]:
        """Returns a fully-populated ``VerificationResult`` on hit, or
        ``None`` on miss / error (caller falls through to Tier B)."""
        prompt_user = f'Claim: "{claim_text}"'
        prompt_hash = self._hash_prompt(self.TIER_A_MODEL, _TIER_A_SYSTEM, prompt_user)

        try:
            raw = await self._llm.complete(
                model=self.TIER_A_MODEL,
                system=_TIER_A_SYSTEM,
                user=prompt_user,
            )
        except Exception as exc:  # noqa: BLE001 — agent must not crash pipeline
            return None

        data = _parse_json_or_none(raw)
        if not isinstance(data, dict) or not data.get("checked"):
            return None

        fact_checker = data.get("fact_checker", "")
        if not fact_checker:
            return None

        # The fact-checker name itself must be in the allowlist for
        # this agent — universal checkers are added to every agent's
        # allowlist by convention.
        canonical = self._resolve_to_allowlist(fact_checker)
        if canonical is None:
            return None  # not allowlisted; treat as a miss

        verdict_text = (data.get("verdict_text") or "").strip()
        url = (data.get("url") or "").strip()
        p_entail = _coerce_prob(data.get("p_entail"))
        p_contradict = _coerce_prob(data.get("p_contradict"))

        evidence = [
            EvidenceItem(
                text=verdict_text or f"{canonical} reviewed this claim.",
                source=Source(name=canonical, url=url or None),
                p_entail=p_entail,
                p_contradict=p_contradict,
                nli_source="agent",
            )
        ]

        return VerificationResult(
            agent=type(self).__name__,
            claim_text=claim_text,
            allowed_sources=sorted(self.ALLOWED_SOURCES),
            queried_sources=[canonical],
            evidence_items=evidence,
            activity_log=AgentActivityLog(
                agent=type(self).__name__,
                claim_text=claim_text,
                allowed_sources=sorted(self.ALLOWED_SOURCES),
                queried_sources=[canonical],
                model_used=self.TIER_A_MODEL,
                prompt_hash=prompt_hash,
            ),
        )

    # ------------------------------------------------------------------
    # Tier B — domain retrieval with hard allowlist
    # ------------------------------------------------------------------

    async def _run_tier_b(self, claim_text: str) -> VerificationResult:
        allowed_block = "\n  ".join(
            f"- {s}" for s in sorted(self.ALLOWED_SOURCES)
        )
        system = _TIER_B_SYSTEM.format(
            domain_name=self.DOMAIN_NAME,
            domain_description=self.DOMAIN_DESCRIPTION,
            allowed_sources_block=allowed_block,
        )
        user = f'Claim: "{claim_text}"'
        prompt_hash = self._hash_prompt(self.TIER_B_MODEL, system, user)

        error: Optional[str] = None
        evidence: list[EvidenceItem] = []
        queried: list[str] = []
        denied: list[str] = []

        try:
            raw = await self._llm.complete(
                model=self.TIER_B_MODEL,
                system=system,
                user=user,
            )
        except Exception as exc:  # noqa: BLE001
            error = f"llm_error: {type(exc).__name__}: {exc}"
            raw = ""

        if error is None:
            parsed = _parse_json_or_none(raw)
            if not isinstance(parsed, list):
                error = "parse_failure"
            else:
                evidence, queried, denied = self._enforce_and_build(parsed)

        return VerificationResult(
            agent=type(self).__name__,
            claim_text=claim_text,
            allowed_sources=sorted(self.ALLOWED_SOURCES),
            queried_sources=queried,
            evidence_items=evidence,
            activity_log=AgentActivityLog(
                agent=type(self).__name__,
                claim_text=claim_text,
                allowed_sources=sorted(self.ALLOWED_SOURCES),
                queried_sources=queried,
                denied_sources=denied,
                model_used=self.TIER_B_MODEL,
                prompt_hash=prompt_hash,
                error=error,
            ),
        )

    # ------------------------------------------------------------------
    # Allowlist enforcement (the moneyshot)
    # ------------------------------------------------------------------

    def _enforce_and_build(
        self, items: list[Any]
    ) -> tuple[list[EvidenceItem], list[str], list[str]]:
        """Walk LLM-returned items, drop non-allowlisted citations,
        return (evidence, queried_sources, denied_sources). Each is a
        list of canonical names; ``denied_sources`` includes the *raw*
        names the LLM returned for transparency in the activity panel."""
        evidence: list[EvidenceItem] = []
        queried: list[str] = []
        denied: list[str] = []
        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue
            raw_source = (raw_item.get("source_name") or "").strip()
            text = (raw_item.get("text") or "").strip()
            url = (raw_item.get("url") or "").strip()
            if not raw_source or not text:
                continue
            canonical = self._resolve_to_allowlist(raw_source)
            if canonical is None:
                # Not allowlisted: dropped from evidence, recorded
                # in the audit log so the activity panel can surface
                # "this source was requested but denied".
                denied.append(raw_source)
                continue
            evidence.append(
                EvidenceItem(
                    text=text,
                    source=Source(name=canonical, url=url or None),
                    nli_source=None,  # judge fills NLI later
                )
            )
            if canonical not in queried:
                queried.append(canonical)
        return evidence, queried, denied

    def _resolve_to_allowlist(self, raw_name: str) -> Optional[str]:
        """Return canonical allowlist name, or ``None`` if not allowed."""
        return self._allowlist_norm.get(_normalize_source(raw_name))

    # ------------------------------------------------------------------
    # Bookkeeping helpers
    # ------------------------------------------------------------------

    def _finalize(
        self,
        result: VerificationResult,
        *,
        start: float,
        cache_key: str,
    ) -> VerificationResult:
        duration_ms = int((time.monotonic() - start) * 1000)
        log = result.activity_log
        if log is not None:
            log = log.model_copy(update={"duration_ms": duration_ms})
        result = result.model_copy(
            update={"duration_ms": duration_ms, "activity_log": log}
        )
        # Only cache successful results — failures shouldn't poison
        # the cache. A failure has either an empty evidence list with
        # an ``error`` set, or no evidence at all.
        log_has_error = log is not None and log.error is not None
        if not log_has_error and result.evidence_items:
            self._cache.set(cache_key, result)
        return result

    def _make_cache_key(self, claim_text: str) -> str:
        # Cache key includes the agent class, model strings, and claim.
        # A model swap correctly invalidates.
        material = "|".join(
            [
                type(self).__name__,
                self.TIER_A_MODEL,
                self.TIER_B_MODEL,
                claim_text.strip(),
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_prompt(model: str, system: str, user: str) -> str:
        material = "|".join([model, system, user])
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def _coerce_prob(value: Any) -> Optional[float]:
    """Coerce LLM-returned probability into ``[0, 1]`` or ``None``."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return max(0.0, min(1.0, f))
