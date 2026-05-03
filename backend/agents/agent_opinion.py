"""Opinion-stance agent (Level 3, opinion track).

Subclasses ``AllowlistedAgent`` to inherit the full audit posture —
allowlist enforcement, denied-source logging, prompt hashing, caching,
``AgentActivityLog``. Two structural differences from a fact-track agent:

  * Tier A (universal-fact-checker probe) is **skipped**.  Fact checkers
    don't grade opinions, so the short-circuit doesn't apply.
  * Tier B retrieves *stance* per outlet, not factual evidence.  Each
    ``EvidenceItem`` carries a populated ``stance`` field
    (``agree`` | ``disagree`` | ``unverifiable``) which the judge's
    ``calculate_lean_structured`` consumes to compute a left/right score.

The allowlist is loaded from ``backend/data/media_bias.csv`` — the same
file ``judge.py`` uses for outlet bias ratings, so allowlist + bias
registry stay in sync by construction.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from backend.contracts import (
    AgentActivityLog,
    EvidenceItem,
    Source,
    VerificationResult,
)

from .base import AllowlistedAgent, _normalize_source, _parse_json_or_none
from .llm import get_default_llm_client
from .media_bias import load_outlet_allowlist, resolve_alias


_OPINION_TIER_B_SYSTEM = """\
You are a media-stance research assistant. Given an OPINION (a subjective
political position a speaker is taking), determine which of the listed news
outlets have publicly endorsed the position, opposed it, or covered it
without taking a clear stance.

Be STRICT. Only report a stance of "agree" or "disagree" when the outlet
has EXPLICITLY taken a position on the opinion AS STATED — through
editorial board endorsements, named opinion-section pieces, or news
reporting that unambiguously frames the outlet's position. If you are
uncertain, or the outlet has only covered the topic without staking a
position, return "unverifiable".

Use the EXACT outlet name from this allowlist:

  {allowed_sources_block}

Return ONLY a JSON array. Each item:
{{"outlet": "The Atlantic",
  "stance": "agree" | "disagree" | "unverifiable",
  "summary": "One sentence describing the outlet's position or coverage,
              citing what makes the stance evident.",
  "url": "https://..."}}

If you cannot find allowlisted coverage, return [].
Do not invent outlets, do not invent URLs (use empty string when unknown).
"""


_VALID_STANCES = frozenset({"agree", "disagree", "unverifiable"})


class OpinionAgent(AllowlistedAgent):
    DOMAIN_NAME = "opinion"
    DOMAIN_DESCRIPTION = (
        "stance detection across allowlisted news outlets for subjective "
        "political opinions; produces evidence carrying a per-outlet stance "
        "consumed by judge.calculate_lean_structured"
    )
    ALLOWED_SOURCES = load_outlet_allowlist()

    # ------------------------------------------------------------------
    # Tier A — SKIPPED.
    #
    # Universal fact-checkers do not grade opinions. Returning ``None``
    # here makes the base class fall through to Tier B as if Tier A had
    # come back empty. No LLM call wasted.
    # ------------------------------------------------------------------

    async def _run_tier_a(self, claim_text: str) -> Optional[VerificationResult]:
        return None

    # ------------------------------------------------------------------
    # Tier B — stance-aware retrieval.
    #
    # Overrides the base implementation because we need a different
    # prompt, different output shape, and a stance-aware enforcement
    # path that populates ``EvidenceItem.stance``. Allowlist enforcement
    # follows the same denied-source logging pattern as fact agents.
    # ------------------------------------------------------------------

    async def _run_tier_b(self, claim_text: str) -> VerificationResult:
        allowed_block = "\n  ".join(
            f"- {s}" for s in sorted(self.ALLOWED_SOURCES)
        )
        system = _OPINION_TIER_B_SYSTEM.format(
            allowed_sources_block=allowed_block,
        )
        user = f'Opinion: "{claim_text}"'
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
        except Exception as exc:  # noqa: BLE001 — agent must not crash pipeline
            error = f"llm_error: {type(exc).__name__}: {exc}"
            raw = ""

        if error is None:
            parsed = _parse_json_or_none(raw)
            if not isinstance(parsed, list):
                error = "parse_failure"
            else:
                evidence, queried, denied = self._enforce_stance_items(parsed)

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
    # Stance-aware allowlist enforcement.
    #
    # Same shape as base._enforce_and_build but emits EvidenceItems with
    # ``stance`` set, and falls back to the alias map when the base
    # normalizer can't resolve an outlet (e.g. LLM emits "NPR" but the
    # CSV entry is "NPR (Online News)").
    # ------------------------------------------------------------------

    def _enforce_stance_items(
        self, items: list[Any]
    ) -> tuple[list[EvidenceItem], list[str], list[str]]:
        evidence: list[EvidenceItem] = []
        queried: list[str] = []
        denied: list[str] = []

        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue
            raw_outlet = (raw_item.get("outlet") or "").strip()
            stance_raw = (raw_item.get("stance") or "").strip().lower()
            summary = (raw_item.get("summary") or "").strip()
            url = (raw_item.get("url") or "").strip()

            if not raw_outlet or not summary:
                continue
            if stance_raw not in _VALID_STANCES:
                # Unknown stance string — treat as a parse-shape problem
                # at the item level. Don't fabricate a stance; drop.
                continue

            canonical = self._resolve_outlet(raw_outlet)
            if canonical is None:
                denied.append(raw_outlet)
                continue

            evidence.append(
                EvidenceItem(
                    text=summary,
                    source=Source(name=canonical, url=url or None),
                    nli_source=None,  # judge handles via stance, not NLI
                    stance=stance_raw,  # type: ignore[arg-type]
                )
            )
            if canonical not in queried:
                queried.append(canonical)

        return evidence, queried, denied

    def _resolve_outlet(self, raw_name: str) -> Optional[str]:
        """Resolve an LLM-emitted outlet name to a canonical CSV entry.

        Tries the base-class normalizer first (handles
        case/punctuation/whitespace), then falls back to the curated
        alias map for common shorthand the AllSides naming doesn't
        support (e.g. "NPR" → "NPR (Online News)").
        """
        canonical = self._allowlist_norm.get(_normalize_source(raw_name))
        if canonical is not None:
            return canonical
        return resolve_alias(_normalize_source(raw_name))


# ---------------------------------------------------------------------------
# Module-level singleton, mirrors the pattern other agents use.
# ---------------------------------------------------------------------------


_agent_singleton: OpinionAgent | None = None


def get_opinion_agent() -> OpinionAgent:
    """Return a process-wide ``OpinionAgent`` with default LLM client."""
    global _agent_singleton
    if _agent_singleton is None:
        _agent_singleton = OpinionAgent(llm=get_default_llm_client())
    return _agent_singleton
