"""Shared pytest setup for the backend test suite.

Sets a dummy ``OPENROUTER_API_KEY`` before any test module is collected.
``backend/agents/judge.py`` and ``backend/agents/base_agent.py``
construct an ``AsyncOpenAI`` client at module-import time; without an
API key the constructor raises and tests fail to even collect.

Tests that need real LLM behaviour mock the client at the call-site
level (see ``test_allowlisted_agent.FakeLLM``); the env var here is
purely to satisfy the import-time constructor.
"""

from __future__ import annotations

import os

os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy-key")
os.environ.setdefault("OPENAI_API_KEY", "test-dummy-key")
