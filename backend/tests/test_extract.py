"""Tests for the two-bucket claim extraction (Level 2a).

The LLM call itself is mocked — what we lock down here is the parsing
contract: Haiku returns a JSON object with `facts` and `opinions` lists,
and ``extract_claims`` normalizes them into ``ExtractionResult``.
"""

from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

# Stub openai BEFORE importing extract — extract.py doesn't actually use
# openai but other modules in the chain might be imported transitively.
if "openai" not in sys.modules:
    openai_stub = ModuleType("openai")

    class AsyncOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda *a, **kw: None)
            )

    openai_stub.AsyncOpenAI = AsyncOpenAI
    sys.modules["openai"] = openai_stub

from backend.core.extract import ExtractionResult, extract_claims


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload_text: str) -> None:
        self._payload_text = payload_text

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [{"message": {"content": self._payload_text}}]
        }


class _FakeAsyncClient:
    """Minimal async-context-manager that returns a canned LLM response."""

    def __init__(self, payload_text: str) -> None:
        self._payload_text = payload_text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def post(self, *args, **kwargs):
        return _FakeResponse(self._payload_text)


def _stub_httpx(payload: str | dict):
    """Patch ``httpx.AsyncClient`` with a fake that returns ``payload``."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return patch(
        "backend.core.extract.httpx.AsyncClient",
        return_value=_FakeAsyncClient(text),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_extraction_result_dataclass() -> None:
    payload = {"facts": [], "opinions": []}
    with _stub_httpx(payload):
        result = await extract_claims("hello", 0.0)
    assert isinstance(result, ExtractionResult)
    assert result.facts == []
    assert result.opinions == []


@pytest.mark.asyncio
async def test_parses_facts_only() -> None:
    payload = {
        "facts": [
            {
                "claim": "Inflation was 9 percent in 2022.",
                "raw_quote": "Inflation was 9 percent in 2022.",
                "timestamp": 12.5,
            }
        ],
        "opinions": [],
    }
    with _stub_httpx(payload):
        result = await extract_claims("…", 0.0)
    assert len(result.facts) == 1
    assert result.facts[0]["claim"] == "Inflation was 9 percent in 2022."
    assert result.facts[0]["timestamp"] == 12.5
    assert result.opinions == []


@pytest.mark.asyncio
async def test_parses_opinions_only() -> None:
    payload = {
        "facts": [],
        "opinions": [
            {
                "statement": "We need stronger borders.",
                "raw_quote": "We need stronger borders.",
                "timestamp": 23.4,
            }
        ],
    }
    with _stub_httpx(payload):
        result = await extract_claims("…", 0.0)
    assert result.facts == []
    assert len(result.opinions) == 1
    assert result.opinions[0]["statement"] == "We need stronger borders."
    assert result.opinions[0]["timestamp"] == 23.4


@pytest.mark.asyncio
async def test_parses_both_buckets() -> None:
    payload = {
        "facts": [
            {
                "claim": "Crime fell 5 percent last year.",
                "raw_quote": "Crime fell 5 percent last year.",
                "timestamp": 5.0,
            }
        ],
        "opinions": [
            {
                "statement": "We need stronger borders.",
                "raw_quote": "We need stronger borders.",
                "timestamp": 7.0,
            }
        ],
    }
    with _stub_httpx(payload):
        result = await extract_claims("…", 0.0)
    assert len(result.facts) == 1
    assert len(result.opinions) == 1


@pytest.mark.asyncio
async def test_handles_markdown_fenced_json() -> None:
    """LLMs sometimes wrap output in ```json ... ``` despite instructions."""
    inner = json.dumps({"facts": [], "opinions": []})
    payload_text = f"```json\n{inner}\n```"
    with _stub_httpx(payload_text):
        result = await extract_claims("…", 0.0)
    assert isinstance(result, ExtractionResult)


@pytest.mark.asyncio
async def test_handles_unparsable_json_returns_empty() -> None:
    with _stub_httpx("this is not json"):
        result = await extract_claims("…", 0.0)
    assert isinstance(result, ExtractionResult)
    assert result.facts == []
    assert result.opinions == []


@pytest.mark.asyncio
async def test_handles_non_dict_top_level_returns_empty() -> None:
    """Defensive: if the model returns a bare list (legacy shape), treat
    it as a parse failure rather than crashing on .get('facts')."""
    with _stub_httpx("[]"):
        result = await extract_claims("…", 0.0)
    assert result.facts == []
    assert result.opinions == []


@pytest.mark.asyncio
async def test_drops_facts_missing_required_fields() -> None:
    payload = {
        "facts": [
            {"claim": "Has both fields.", "raw_quote": "Has both fields."},
            {"claim": "Missing raw_quote."},  # dropped
            {"raw_quote": "Missing claim."},  # dropped
            "not even a dict",  # dropped
        ],
        "opinions": [],
    }
    with _stub_httpx(payload):
        result = await extract_claims("…", 0.0)
    assert len(result.facts) == 1
    assert result.facts[0]["claim"] == "Has both fields."


@pytest.mark.asyncio
async def test_drops_opinions_missing_required_fields() -> None:
    payload = {
        "facts": [],
        "opinions": [
            {"statement": "Has both fields.", "raw_quote": "Has both fields."},
            {"statement": "Missing raw_quote."},  # dropped
            {"raw_quote": "Missing statement."},  # dropped
        ],
    }
    with _stub_httpx(payload):
        result = await extract_claims("…", 0.0)
    assert len(result.opinions) == 1
    assert result.opinions[0]["statement"] == "Has both fields."


@pytest.mark.asyncio
async def test_falls_back_to_offset_when_timestamp_missing() -> None:
    payload = {
        "facts": [
            {"claim": "X.", "raw_quote": "X."},  # no timestamp
        ],
        "opinions": [],
    }
    with _stub_httpx(payload):
        result = await extract_claims("…", 42.0)
    assert result.facts[0]["timestamp"] == 42.0


@pytest.mark.asyncio
async def test_buckets_are_independent_when_one_is_invalid() -> None:
    """If `facts` is malformed but `opinions` is valid, opinions still parse."""
    payload = {
        "facts": "not a list",
        "opinions": [
            {
                "statement": "Stronger borders.",
                "raw_quote": "Stronger borders.",
                "timestamp": 1.0,
            }
        ],
    }
    with _stub_httpx(payload):
        result = await extract_claims("…", 0.0)
    assert result.facts == []
    assert len(result.opinions) == 1


@pytest.mark.asyncio
async def test_extraction_result_default_construction() -> None:
    """Empty ExtractionResult has both fields defaulted."""
    er = ExtractionResult()
    assert er.facts == []
    assert er.opinions == []
