# ADR-0002: Topic name canonicalization

## Decision
Topic IDs are lowercase snake_case strings, used everywhere in code, contracts, cache keys, and fixtures:

- `legislative`
- `economy`
- `historical_statements`
- `policy_outcome`

Agent class names stay PascalCase (`LegislativeAgent`, etc.) but expose `topic_id` returning the canonical string. Frontend display names live in a separate map.

## Why
Topic IDs propagate through `Claim.topics`, routing output, agent allowlists, eval ground truth, and UI. A rename later is a cross-team migration.

## Implications for contributors
- Use the canonical IDs above in all backend code and JSON fixtures.
- Do not invent new topic strings. Out-of-scope claims use the no-route path (see ADR-0003), not a new topic.
- UI strings (`"Prior Statements"`, etc.) are mapped from canonical IDs in the frontend, never hard-coded against the canonical IDs.
