# ADR-0003: No-route claims become `insufficient_coverage`

## Decision
When the Level 2b router cannot place a claim in any of the 4 topics (no keyword match and the LLM fallback returns "none fit"), the claim is **not** force-routed. It flows through with `routed_topics = []` and Level 4b classifies it as `insufficient_coverage`.

This overrides the spec line "defaults to 2 topics on low-confidence routing." Forcing 2 topics on a vague claim produces irrelevant citations and weakens the allowlist story.

## Why
The system's identity is attribution, never adjudication. Honestly surfacing "we don't have coverage for this" is consistent with that framing. Forcing a topic match pollutes agent output with off-topic claims.

## Implications for contributors
- The router output type allows `routed_topics = []`. Downstream code must handle the empty case.
- Level 3 dispatch skips agent calls when `routed_topics` is empty.
- Level 4b treats empty-routed claims as `insufficient_coverage`, not as an error.
- The frontend annotation card should still render for these claims, with a clear "no coverage" state.
