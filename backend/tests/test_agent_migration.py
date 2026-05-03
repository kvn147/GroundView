"""Smoke tests for the 5 migrated agent classes.

We don't re-test the AllowlistedAgent base class machinery here — that's
covered by ``test_allowlisted_agent.py``. These tests confirm:

  * Each subclass instantiates successfully against a fake LLM.
  * Each has the expected ``DOMAIN_NAME`` and a non-empty allowlist
    that includes the universal fact-checkers.
  * The legacy ``retrieve_evidence`` / ``verify`` shims still return
    a string of markdown (the contract ``api/video.py`` depends on).
"""

from __future__ import annotations

import json

import pytest

from backend.agents import (
    agent_crime,
    agent_economy,
    agent_education,
    agent_healthcare,
    agent_immigration,
)
from backend.agents.agent_crime import CrimeAgent
from backend.agents.agent_economy import EconomyAgent, UNIVERSAL_FACT_CHECKERS
from backend.agents.agent_education import EducationAgent
from backend.agents.agent_healthcare import HealthcareAgent
from backend.agents.agent_immigration import ImmigrationAgent
from backend.tests.test_allowlisted_agent import FakeLLM


AGENT_CLASSES = [
    (EconomyAgent, "economy"),
    (CrimeAgent, "crime"),
    (EducationAgent, "education"),
    (HealthcareAgent, "healthcare"),
    (ImmigrationAgent, "immigration"),
]


@pytest.mark.parametrize(("cls", "expected_domain"), AGENT_CLASSES)
def test_agent_class_attributes(cls, expected_domain) -> None:
    assert cls.DOMAIN_NAME == expected_domain
    assert cls.DOMAIN_DESCRIPTION  # non-empty
    assert cls.ALLOWED_SOURCES  # non-empty frozenset
    # Universal fact-checkers must be in every agent's allowlist —
    # the Tier-A probe expects to be able to cite them.
    assert UNIVERSAL_FACT_CHECKERS <= cls.ALLOWED_SOURCES


@pytest.mark.parametrize(("cls", "_"), AGENT_CLASSES)
def test_agent_constructs_with_fake_llm(cls, _) -> None:
    agent = cls(llm=FakeLLM())
    assert agent.DOMAIN_NAME


@pytest.mark.asyncio
async def test_economy_legacy_shim_returns_markdown(monkeypatch) -> None:
    """``api/video.py`` calls ``retrieve_evidence(claim) -> str``. The
    shim must still satisfy that contract after the migration."""
    fake = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": json.dumps({"checked": False}),
        "google/gemini-2.5-flash": json.dumps([
            {"source_name": "BLS", "url": "https://bls.gov", "text": "Stat."},
        ]),
    })
    # Replace the module-level singleton with one wired to the fake LLM.
    agent_economy._agent_singleton = EconomyAgent(llm=fake)

    md = await agent_economy.retrieve_evidence("Inflation hit 9%.")
    assert isinstance(md, str)
    assert "BLS" in md
    assert "Stat." in md

    # The ``verify`` alias delegates to the same path:
    md2 = await agent_economy.verify("Inflation hit 9%.")
    assert "BLS" in md2

    # Cleanup so other tests get a fresh singleton:
    agent_economy._agent_singleton = None


@pytest.mark.asyncio
async def test_immigration_legacy_shim_handles_no_evidence(monkeypatch) -> None:
    """When the LLM returns no allowlisted evidence, the shim still
    returns a string — the empty-evidence markdown — rather than crashing."""
    fake = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": json.dumps({"checked": False}),
        "google/gemini-2.5-flash": "[]",
    })
    agent_immigration._agent_singleton = ImmigrationAgent(llm=fake)

    md = await agent_immigration.retrieve_evidence("Some claim.")
    assert isinstance(md, str)
    assert "No evidence retrieved" in md

    agent_immigration._agent_singleton = None
