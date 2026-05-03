"""Cross-level data contracts for the BeaverHacks fact-check pipeline.

This module is the single source of truth for the shapes that cross
level boundaries in ``docs/AGENTIC_WORKFLOW.md``:

  * ``Claim``                — Level 2a output, consumed by Levels 2b/3.
  * ``Source``               — a citation + optional trust/bias.
  * ``EvidenceItem``         — one factual statement + its source + NLI.
  * ``VerificationResult``   — one agent's response for one claim
                               (Level 3 output, consumed by Level 4a/4b).
  * ``AgentActivityLog``     — audit record for the activity panel
                               (the "ConductorOne thesis as code" surface).
  * ``Annotation``           — per-claim aggregated record after Level 4a.
  * ``AnalyzeVideoResponse`` /
    ``AnalyzeClipResponse``  — the frontend-facing shapes.

Adapter helpers near the bottom translate a ``VerificationResult`` into
the legacy shapes that ``backend/agents/judge.py`` and the chrome
extension currently consume. This lets us migrate consumers
incrementally without breaking either side.

Design notes (worth keeping):
  * Agents emit *structured* ``EvidenceItem`` lists alongside their
    free-form ``summary_markdown``. The structured form replaces
    ``judge.extract_evidence_items`` (one fewer LLM call per claim).
    The markdown form remains for the UI's "explanation" field.
  * ``Source.trust`` and ``Source.bias`` are optional. Agents may fill
    them when known (e.g. allowlisted government sources); ``judge``'s
    registry resolves the rest.
  * ``VerificationResult.allowed_sources`` is the agent's static
    allowlist. ``queried_sources`` is what it actually hit. The
    delta is the audit signal — anything queried-but-not-allowed is
    a permission violation that the base class will refuse.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, computed_field


# ---------------------------------------------------------------------------
# Level 2a → Level 2b / 3
# ---------------------------------------------------------------------------


ClaimType = Literal[
    "voting_record",
    "statistic",
    "prior_statement",
    "policy_outcome",
    "biographical",
]

Verifiability = Literal["structured_data", "fact_checker_likely"]


class Claim(BaseModel):
    """A single verifiable assertion extracted from a caption window."""

    claim_text: str
    raw_quote: str
    speaker: Optional[str] = None
    start_time: float
    end_time: float
    claim_type: Optional[ClaimType] = None
    topics: list[str] = Field(default_factory=list)
    verifiability: Optional[Verifiability] = None
    extraction_confidence: float = 1.0


# ---------------------------------------------------------------------------
# Sources and evidence (Level 3 building blocks)
# ---------------------------------------------------------------------------


class Source(BaseModel):
    """A citation as emitted by an *agent*.

    Agents emit only ``name`` and ``url``. Trust and bias scores live
    in the registry (``backend/agents/judge.py``'s ``SOURCE_METRICS``);
    they are not in the agent-facing contract because the agent is not
    the source of truth for source credibility. Letting agents claim
    a source is more trusted than the registry says it is would be a
    self-attestation attack vector. See ``ScoredSource`` for the
    judge-side shape that *does* carry trust/bias.
    """

    name: str
    url: Optional[str] = None


class ScoredSource(Source):
    """A ``Source`` enriched with registry-resolved trust/bias scores.

    Produced by ``judge.py``, never by an agent. The fields mirror the
    AllSides bias scale (``bias``: -1.0 left → 0.0 neutral → +1.0 right)
    and a 0.0–1.0 trust scale where 1.0 means a curated allowlisted
    primary source (BLS, FRED, .gov, etc.) and 0.5 is the default for
    sources resolved from the AllSides news-bias dataset.
    """

    trust: float
    bias: float


NliSource = Literal["agent", "judge"]


class EvidenceItem(BaseModel):
    """One factual statement attributed to one source.

    ``p_entail`` and ``p_contradict`` may be filled by:
      * the agent itself, when the source is verdict-bearing
        (PolitiFact, FactCheck.org, etc.) — ``nli_source = "agent"``
      * ``judge.py``'s NLI step, otherwise — ``nli_source = "judge"``

    The ``nli_source`` discriminator is the LLM-call-saving lever:
    the judge skips items where ``nli_source`` is already set, since
    the verdict from a fact-checker IS the NLI signal — re-running
    Gemini on it would only add noise and cost.
    """

    text: str
    source: Source
    p_entail: Optional[float] = None
    p_contradict: Optional[float] = None
    nli_source: Optional[NliSource] = None
    stance: Optional[Literal["agree", "disagree", "unverifiable"]] = None


# ---------------------------------------------------------------------------
# Level 3 output
# ---------------------------------------------------------------------------


class AgentActivityLog(BaseModel):
    """Audit record for one agent invocation, surfaced in the chrome
    extension's activity panel. The point is *visibility* — the user
    can see the allowlist, what got queried, what got denied, and
    which model produced the answer.

    A non-empty ``denied_sources`` is a permission violation that the
    base class refused; it is logged so the UI can show "this source
    was requested but not allowed" without the request actually
    hitting the network.

    ``model_used`` and ``prompt_hash`` together make every verdict
    *replayable*: same hash + same model = same call.
    """

    agent: str
    claim_text: str
    allowed_sources: list[str]
    queried_sources: list[str] = Field(default_factory=list)
    denied_sources: list[str] = Field(default_factory=list)
    cache_hit: bool = False
    duration_ms: int = 0
    model_used: str = ""
    prompt_hash: str = ""
    error: Optional[str] = None
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


def render_evidence_markdown(items: list[EvidenceItem]) -> str:
    """Deterministic, LLM-free rendering of evidence items into markdown.

    Used by ``VerificationResult.summary_markdown``. The point is that
    every byte the user reads in the chrome extension's explanation
    field traces back to a structured ``EvidenceItem`` with an
    attributed ``Source`` — no agent prose, no hallucination surface.
    """
    if not items:
        return "_No evidence retrieved._"
    lines = ["### Evidence"]
    for item in items:
        if item.source.url:
            cite = f"**{item.source.name}** ([source]({item.source.url}))"
        else:
            cite = f"**{item.source.name}**"
        lines.append(f"- {cite}: {item.text}")
    return "\n".join(lines)


class VerificationResult(BaseModel):
    """One agent's response to one claim.

    Agents fill only ``evidence_items`` (and the audit fields).
    ``summary_markdown`` is *derived* from the structured evidence by
    a deterministic renderer — agents cannot author free prose. This
    is the security posture: every word the user reads ties back to a
    structured ``EvidenceItem`` with an allowlisted source.
    """

    agent: str
    claim_text: str
    allowed_sources: list[str]
    queried_sources: list[str] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    cache_hit: bool = False
    duration_ms: int = 0
    activity_log: Optional[AgentActivityLog] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def summary_markdown(self) -> str:
        # Read-only property. Agents cannot assign or mutate this; any
        # ``summary_markdown=...`` passed at construction is silently
        # dropped (it is not a writable field). Combined with the
        # render function being LLM-free, this guarantees every word
        # the user reads ties back to a structured ``EvidenceItem``.
        return render_evidence_markdown(self.evidence_items)


# ---------------------------------------------------------------------------
# Level 4a / 4b output
# ---------------------------------------------------------------------------


ConfidenceState = Literal[
    "verified",
    "contradicted",
    "insufficient_coverage",
    "sources_disagree",
]


class Annotation(BaseModel):
    """Per-claim aggregated record after fan-out and confidence rules.

    This is what Level 5 (rendering) consumes. The frontend response
    models below adapt it into the chrome extension's expected shape.
    """

    claim: Claim
    results: list[VerificationResult]
    confidence_state: ConfidenceState = "insufficient_coverage"
    final_score: float = 0.0
    bias_warning: Optional[str] = None


class Opinion(BaseModel):
    """A single subjective statement extracted from a caption window."""

    statement: str
    raw_quote: str
    speaker: Optional[str] = None
    start_time: float
    end_time: float


class OpinionAnnotation(BaseModel):
    """Per-opinion aggregated record after the opinion-bias engine runs.

    ``results`` always contains exactly one element (the OpinionAgent).
    ``lean_value`` in ``[-1.0, +1.0]``: negative = left, positive = right.
    ``confidence`` in ``[0, 1]`` reflects the fraction of evidence items
    that had a clear stance (``agree`` or ``disagree``) vs. ``unverifiable``.
    """

    opinion: Opinion
    results: list[VerificationResult]
    lean_value: float = 0.0
    lean_label: str = "Center / Neutral"
    reasoning: str = ""
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Frontend-facing response shapes (must match docs/API_CONTRACT.md)
# ---------------------------------------------------------------------------


class FrontendSource(BaseModel):
    """The shape the chrome extension renders per-claim."""

    name: str
    url: str = ""


class FrontendActivity(BaseModel):
    """Per-agent audit row rendered in the chrome extension's activity
    panel. Slimmer than the full ``AgentActivityLog`` — only the
    user-facing fields are surfaced. Internal fields (``prompt_hash``,
    ``timestamp``) stay backend-side."""

    agent: str
    allowed_sources: list[str]
    queried_sources: list[str] = Field(default_factory=list)
    denied_sources: list[str] = Field(default_factory=list)
    cache_hit: bool = False
    model_used: str = ""
    duration_ms: int = 0
    error: Optional[str] = None


class FrontendOpinionEvidence(BaseModel):
    """One outlet's stance evidence for an opinion claim."""

    outlet: str
    stance: Literal["agree", "disagree", "unverifiable"]
    summary: str


class FrontendOpinionLean(BaseModel):
    """Political-lean score for a single opinion statement."""

    value: float      # -1.0 (left) .. +1.0 (right)
    label: str
    reasoning: str
    confidence: float  # 0..1


class FrontendOpinion(BaseModel):
    """Chrome-extension shape for one opinion statement."""

    # Field names mirror ``FrontendClaim`` (camelCase ``startTime`` /
    # ``endTime``) so the chrome extension's ``normalizeAnalysisItem``
    # reads timestamps the same way for both kinds. Earlier shape used
    # ``start_time`` and dropped ``end_time`` entirely, which silently
    # broke the timestamp button on opinion rows.
    statement: str
    raw_quote: str
    startTime: Optional[float] = None
    endTime: Optional[float] = None
    lean: FrontendOpinionLean
    evidence: list[FrontendOpinionEvidence] = Field(default_factory=list)
    activity: Optional[FrontendActivity] = None


class FrontendClaim(BaseModel):
    id: str
    text: str
    startTime: Optional[float] = None
    endTime: Optional[float] = None
    verdict: str
    explanation: str
    sources: list[FrontendSource] = Field(default_factory=list)
    activity: list[FrontendActivity] = Field(default_factory=list)


class FrontendAggregatedSource(FrontendSource):
    citedCount: int = 1


class PoliticalLean(BaseModel):
    label: str = "Unknown"
    value: float = 0.5


class AnalyzeVideoResponse(BaseModel):
    summary: str = ""
    trustworthinessScore: int = 3
    maxScore: int = 5
    trustworthinessLabel: str = "Mixed Accuracy"
    politicalLean: PoliticalLean = Field(default_factory=PoliticalLean)
    claims: list[FrontendClaim] = Field(default_factory=list)
    aggregatedSources: list[FrontendAggregatedSource] = Field(default_factory=list)
    opinions: list[FrontendOpinion] = Field(default_factory=list)


class AnalyzeClipResponse(BaseModel):
    startTime: float
    endTime: float
    claim: str = ""
    verdict: str = "Pending"
    explanation: str = ""
    sources: list[FrontendSource] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Adapters — translate canonical contract shapes into legacy consumer shapes.
# Pure functions, no I/O. Kept here so consumers don't grow ad-hoc adapters.
# ---------------------------------------------------------------------------


def to_judge_evidence_items(result: VerificationResult) -> list[dict]:
    """Shape consumed by ``judge.calculate_confidence`` today.

    *Transitional.* Once ``judge.py`` is migrated to consume
    ``EvidenceItem`` directly (and skip its NLI call when
    ``nli_source`` is set), this adapter can be deleted.
    """
    return [
        {"source": item.source.name, "text": item.text}
        for item in result.evidence_items
    ]


def to_frontend_activity(result: VerificationResult) -> Optional[FrontendActivity]:
    """Convert an agent's ``AgentActivityLog`` to the slimmer
    ``FrontendActivity`` row the activity panel renders. Returns
    ``None`` if the result has no activity log (unusual — every
    agent invocation should produce one)."""
    log = result.activity_log
    if log is None:
        return None
    return FrontendActivity(
        agent=log.agent,
        allowed_sources=log.allowed_sources,
        queried_sources=log.queried_sources,
        denied_sources=log.denied_sources,
        cache_hit=log.cache_hit,
        model_used=log.model_used,
        duration_ms=log.duration_ms,
        error=log.error,
    )


def to_frontend_sources(result: VerificationResult) -> list[FrontendSource]:
    """Per-claim ``sources`` array for the chrome extension.

    Deduplicates by source name, preferring the first non-empty URL.
    """
    seen: dict[str, FrontendSource] = {}
    for item in result.evidence_items:
        existing = seen.get(item.source.name)
        if existing is None:
            seen[item.source.name] = FrontendSource(
                name=item.source.name,
                url=item.source.url or "",
            )
        elif not existing.url and item.source.url:
            seen[item.source.name] = FrontendSource(
                name=item.source.name, url=item.source.url
            )
    return list(seen.values())


def aggregate_frontend_sources(
    annotations: list[Annotation],
) -> list[FrontendAggregatedSource]:
    """Top-level ``aggregatedSources`` list across all annotations."""
    counts: dict[str, FrontendAggregatedSource] = {}
    for ann in annotations:
        for result in ann.results:
            for fe_source in to_frontend_sources(result):
                key = fe_source.name
                if key in counts:
                    counts[key].citedCount += 1
                    if not counts[key].url and fe_source.url:
                        counts[key].url = fe_source.url
                else:
                    counts[key] = FrontendAggregatedSource(
                        name=fe_source.name,
                        url=fe_source.url,
                        citedCount=1,
                    )
    return list(counts.values())
