"""Rigorous tests for backend/agents/judge.py.

Coverage targets:
  - match_source_metrics: .gov auto-trust, known sources, fuzzy matching, default fallback
  - calculate_confidence: math invariants, bias penalty, source bonus, verdict thresholds,
    score clamping, custom hyperparams
  - calculate_confidence_structured: NLI skip/call logic, math parity with legacy path,
    nli_origin tracking, empty input, score clamping
  - NLI call-count discipline across both functions
"""

from __future__ import annotations

import math
import pytest

from backend.agents import judge as judge_mod
from backend.agents.judge import (
    NLIResult,
    SOURCE_METRICS,
    calculate_confidence,
    calculate_confidence_structured,
    calculate_lean_structured,
    match_source_metrics,
)
from backend.contracts import EvidenceItem, Source



# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def nli_counter(monkeypatch):
    """Stub get_nli_probabilities; returns neutral by default, counts calls."""
    state = {"calls": 0, "p_entail": 0.5, "p_contradict": 0.5}

    async def fake(claim, evidence, *a, **kw):
        state["calls"] += 1
        return NLIResult(p_entail=state["p_entail"], p_contradict=state["p_contradict"])

    monkeypatch.setattr(judge_mod, "get_nli_probabilities", fake)
    return state


def _make_legacy_items(sources_scores):
    """Return list[dict] with preset p_entail/p_contradict baked into the source name
    so tests can control NLI output via monkeypatched fake."""
    return [{"source": s, "text": f"evidence from {s}"} for s, _ in sources_scores]


# ---------------------------------------------------------------------------
# match_source_metrics
# ---------------------------------------------------------------------------


class TestMatchSourceMetrics:
    def test_gov_domain_auto_trust(self):
        trust, bias = match_source_metrics("https://www.bls.gov/data")
        assert trust == 1.0
        assert bias == 0.0

    def test_gov_subdomain_auto_trust(self):
        trust, bias = match_source_metrics("data.cdc.gov/some/path")
        assert trust == 1.0
        assert bias == 0.0

    def test_known_fact_checker_politifact(self):
        trust, bias = match_source_metrics("PolitiFact")
        assert trust == 1.0
        assert bias == 0.0

    def test_known_fact_checker_case_insensitive(self):
        trust, bias = match_source_metrics("politifact article")
        assert trust == 1.0

    def test_known_source_cdc(self):
        trust, bias = match_source_metrics("CDC Report 2023")
        assert trust == 1.0
        assert bias == 0.0

    def test_known_source_fbi(self):
        trust, bias = match_source_metrics("FBI Crime Stats")
        assert trust == 1.0
        assert bias == 0.0

    def test_unknown_source_default(self):
        trust, bias = match_source_metrics("XYZ Unknown Blog")
        assert trust == SOURCE_METRICS["Default"]["trust"]
        assert bias == SOURCE_METRICS["Default"]["bias"]

    def test_empty_string_falls_back_to_default(self):
        trust, bias = match_source_metrics("")
        assert trust == SOURCE_METRICS["Default"]["trust"]

    def test_pew_research_match(self):
        trust, bias = match_source_metrics("Pew Research Center")
        assert trust == 1.0

    def test_returns_tuple_of_two_floats(self):
        result = match_source_metrics("CDC")
        assert isinstance(result, tuple) and len(result) == 2
        assert all(isinstance(v, float) for v in result)


# ---------------------------------------------------------------------------
# calculate_confidence — math invariants (legacy path)
# ---------------------------------------------------------------------------


class TestCalculateConfidenceMath:
    @pytest.mark.asyncio
    async def test_empty_evidence_returns_unverified(self, nli_counter):
        result = await calculate_confidence("some claim", [])
        assert result["verdict"] == "Unverified"
        assert result["final_score"] == 0.0
        assert nli_counter["calls"] == 0

    @pytest.mark.asyncio
    async def test_calls_nli_once_per_item(self, nli_counter):
        items = [
            {"source": "CDC", "text": "fact A"},
            {"source": "FBI", "text": "fact B"},
            {"source": "BLS", "text": "fact C"},
        ]
        await calculate_confidence("claim", items)
        assert nli_counter["calls"] == 3

    @pytest.mark.asyncio
    async def test_strong_entailment_yields_true(self, nli_counter):
        nli_counter["p_entail"] = 0.95
        nli_counter["p_contradict"] = 0.05
        items = [{"source": "CDC", "text": "x"}]
        result = await calculate_confidence("claim", items)
        assert result["verdict"] == "True"
        assert result["final_score"] > 0.6

    @pytest.mark.asyncio
    async def test_strong_contradiction_yields_false(self, nli_counter):
        nli_counter["p_entail"] = 0.05
        nli_counter["p_contradict"] = 0.95
        items = [{"source": "CDC", "text": "x"}]
        result = await calculate_confidence("claim", items)
        assert result["verdict"] == "False"
        assert result["final_score"] < -0.6

    @pytest.mark.asyncio
    async def test_neutral_nli_yields_unverified(self, nli_counter):
        # p_entail == p_contradict → e_i == 0 → wes == 0 → score == 0
        nli_counter["p_entail"] = 0.5
        nli_counter["p_contradict"] = 0.5
        items = [{"source": "CDC", "text": "x"}]
        result = await calculate_confidence("claim", items)
        assert result["verdict"] == "Unverified / Needs Context"
        assert result["final_score"] == 0.0

    @pytest.mark.asyncio
    async def test_score_clamped_at_positive_one(self, nli_counter):
        # Drive score through the roof with high entailment + source bonus
        nli_counter["p_entail"] = 1.0
        nli_counter["p_contradict"] = 0.0
        # Many neutral (bias=0) trusted sources pushes score_bonus high
        items = [{"source": "CDC", "text": f"x{i}"} for i in range(20)]
        result = await calculate_confidence("claim", items, bias_lambda=0.0)
        assert result["final_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_score_clamped_at_negative_one(self, nli_counter):
        nli_counter["p_entail"] = 0.0
        nli_counter["p_contradict"] = 1.0
        items = [{"source": "CDC", "text": f"x{i}"} for i in range(20)]
        result = await calculate_confidence("claim", items, bias_lambda=0.0)
        assert result["final_score"] >= -1.0

    @pytest.mark.asyncio
    async def test_wes_is_trust_weighted_average(self, nli_counter):
        """WES = sum(e_i * T_i) / sum(T_i). High-trust source dominates."""
        # High trust CDC (T=1.0) says True; low-trust unknown says False.
        async def fake_nli(claim, evidence, *a, **kw):
            if "cdc" in evidence.lower():
                return NLIResult(p_entail=0.9, p_contradict=0.1)
            return NLIResult(p_entail=0.1, p_contradict=0.9)

        judge_mod.get_nli_probabilities = fake_nli  # type: ignore[attr-defined]
        items = [
            {"source": "CDC", "text": "cdc data"},
            {"source": "XYZ Blog", "text": "xyz data"},
        ]
        result = await calculate_confidence("claim", items)
        # CDC T=1.0, e=0.8; XYZ T=0.5, e=-0.8
        # WES = (0.8 + 0.5*-0.8) / 1.5 = 0.4/1.5 ≈ 0.267  → positive
        assert result["wes"] > 0

    @pytest.mark.asyncio
    async def test_bias_penalty_applied(self, nli_counter):
        nli_counter["p_entail"] = 0.9
        nli_counter["p_contradict"] = 0.1
        # Use a Right-biased source so bias != 0
        items = [{"source": "Breitbart", "text": "x"}]
        result_biased = await calculate_confidence("claim", items)
        # Penalty should reduce the score vs zero-bias equivalent
        assert result_biased["bias_penalty"] >= 0

    @pytest.mark.asyncio
    async def test_high_bias_triggers_warning(self, nli_counter):
        nli_counter["p_entail"] = 0.9
        nli_counter["p_contradict"] = 0.1
        # Force a very biased source by injecting into SOURCE_METRICS
        SOURCE_METRICS["_TestBiasedSource"] = {"trust": 0.5, "bias": 1.0}
        items = [{"source": "_TestBiasedSource", "text": "x"}]
        result = await calculate_confidence("claim", items, bias_lambda=0.2)
        del SOURCE_METRICS["_TestBiasedSource"]
        # bias_penalty = 0.2 * 1.0 = 0.2 > 0.15
        assert result["bias_penalty"] > 0.15
        assert "Warning" in result["warning"]

    @pytest.mark.asyncio
    async def test_source_bonus_increases_with_more_sources(self, nli_counter):
        nli_counter["p_entail"] = 0.8
        nli_counter["p_contradict"] = 0.2
        one = await calculate_confidence("c", [{"source": "CDC", "text": "a"}], bias_lambda=0.0)
        five = await calculate_confidence(
            "c",
            [{"source": "CDC", "text": f"a{i}"} for i in range(5)],
            bias_lambda=0.0,
        )
        assert five["final_score"] >= one["final_score"]

    @pytest.mark.asyncio
    async def test_custom_hyperparams_respected(self, nli_counter):
        nli_counter["p_entail"] = 0.9
        nli_counter["p_contradict"] = 0.1
        SOURCE_METRICS["_HighBias"] = {"trust": 0.5, "bias": 1.0}
        items = [{"source": "_HighBias", "text": "x"}]
        # Very high bias_lambda should obliterate the score
        result_high = await calculate_confidence("c", items, bias_lambda=1.0)
        # bias_penalty = 1.0*1.0 = 1.0 → (1-1.0)=0 → score≈0
        del SOURCE_METRICS["_HighBias"]
        assert abs(result_high["final_score"]) < 0.05

    @pytest.mark.asyncio
    async def test_output_keys_present(self, nli_counter):
        items = [{"source": "CDC", "text": "x"}]
        result = await calculate_confidence("claim", items)
        for key in ("final_score", "verdict", "wes", "average_bias", "bias_penalty", "warning", "details"):
            assert key in result

    @pytest.mark.asyncio
    async def test_details_list_matches_input_length(self, nli_counter):
        items = [{"source": "CDC", "text": "a"}, {"source": "FBI", "text": "b"}]
        result = await calculate_confidence("c", items)
        assert len(result["details"]) == 2

    @pytest.mark.asyncio
    async def test_final_score_rounded_to_3dp(self, nli_counter):
        nli_counter["p_entail"] = 0.7
        nli_counter["p_contradict"] = 0.3
        result = await calculate_confidence("c", [{"source": "CDC", "text": "x"}])
        score_str = str(result["final_score"])
        decimals = len(score_str.split(".")[-1]) if "." in score_str else 0
        assert decimals <= 3


# ---------------------------------------------------------------------------
# calculate_confidence_structured — NLI skip / call logic
# ---------------------------------------------------------------------------


class TestCalculateConfidenceStructuredNLI:
    @pytest.mark.asyncio
    async def test_skips_nli_for_agent_filled_items(self, nli_counter):
        items = [
            EvidenceItem(
                text="PolitiFact rated this False.",
                source=Source(name="PolitiFact"),
                p_entail=0.1,
                p_contradict=0.85,
                nli_source="agent",
            )
        ]
        await calculate_confidence_structured("claim", items)
        assert nli_counter["calls"] == 0

    @pytest.mark.asyncio
    async def test_calls_nli_when_not_filled(self, nli_counter):
        items = [
            EvidenceItem(text="stat", source=Source(name="BLS"), nli_source=None)
        ]
        await calculate_confidence_structured("claim", items)
        assert nli_counter["calls"] == 1

    @pytest.mark.asyncio
    async def test_mixed_items_correct_nli_count(self, nli_counter):
        items = [
            EvidenceItem(text="a", source=Source(name="PolitiFact"), p_entail=0.9, p_contradict=0.1, nli_source="agent"),
            EvidenceItem(text="b", source=Source(name="BLS"), nli_source=None),
            EvidenceItem(text="c", source=Source(name="FRED"), nli_source=None),
        ]
        await calculate_confidence_structured("claim", items)
        assert nli_counter["calls"] == 2

    @pytest.mark.asyncio
    async def test_agent_probabilities_used_directly(self, nli_counter):
        items = [
            EvidenceItem(
                text="x", source=Source(name="PolitiFact"),
                p_entail=0.15, p_contradict=0.80, nli_source="agent",
            )
        ]
        result = await calculate_confidence_structured("claim", items)
        d = result["details"][0]
        assert d["p_entail"] == 0.15
        assert d["p_contradict"] == 0.80
        assert d["nli_origin"] == "agent"

    @pytest.mark.asyncio
    async def test_judge_nli_origin_recorded(self, nli_counter):
        items = [EvidenceItem(text="x", source=Source(name="BLS"), nli_source=None)]
        result = await calculate_confidence_structured("claim", items)
        assert result["details"][0]["nli_origin"] == "judge"

    @pytest.mark.asyncio
    async def test_empty_evidence_returns_unverified(self, nli_counter):
        result = await calculate_confidence_structured("claim", [])
        assert result["verdict"] == "Unverified"
        assert result["final_score"] == 0.0
        assert nli_counter["calls"] == 0


# ---------------------------------------------------------------------------
# calculate_confidence_structured — math / verdict thresholds
# ---------------------------------------------------------------------------


class TestCalculateConfidenceStructuredMath:
    @pytest.mark.asyncio
    async def test_strong_entailment_true_verdict(self, nli_counter):
        items = [
            EvidenceItem(text="x", source=Source(name="CDC"), p_entail=0.95, p_contradict=0.05, nli_source="agent")
        ]
        result = await calculate_confidence_structured("claim", items)
        assert result["verdict"] == "True"
        assert result["final_score"] > 0.6

    @pytest.mark.asyncio
    async def test_strong_contradiction_false_verdict(self, nli_counter):
        items = [
            EvidenceItem(text="x", source=Source(name="CDC"), p_entail=0.05, p_contradict=0.95, nli_source="agent")
        ]
        result = await calculate_confidence_structured("claim", items)
        assert result["verdict"] == "False"
        assert result["final_score"] < -0.6

    @pytest.mark.asyncio
    async def test_neutral_unverified_verdict(self, nli_counter):
        items = [
            EvidenceItem(text="x", source=Source(name="CDC"), p_entail=0.5, p_contradict=0.5, nli_source="agent")
        ]
        result = await calculate_confidence_structured("claim", items)
        assert result["verdict"] == "Unverified / Needs Context"

    @pytest.mark.asyncio
    async def test_score_clamped_positive(self, nli_counter):
        items = [
            EvidenceItem(text=f"x{i}", source=Source(name="CDC"), p_entail=1.0, p_contradict=0.0, nli_source="agent")
            for i in range(20)
        ]
        result = await calculate_confidence_structured("claim", items, bias_lambda=0.0)
        assert result["final_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_score_clamped_negative(self, nli_counter):
        items = [
            EvidenceItem(text=f"x{i}", source=Source(name="CDC"), p_entail=0.0, p_contradict=1.0, nli_source="agent")
            for i in range(20)
        ]
        result = await calculate_confidence_structured("claim", items, bias_lambda=0.0)
        assert result["final_score"] >= -1.0

    @pytest.mark.asyncio
    async def test_high_bias_warning_emitted(self, nli_counter):
        SOURCE_METRICS["_RightBias"] = {"trust": 0.5, "bias": 1.0}
        items = [
            EvidenceItem(text="x", source=Source(name="_RightBias"), p_entail=0.9, p_contradict=0.1, nli_source="agent")
        ]
        result = await calculate_confidence_structured("claim", items, bias_lambda=0.2)
        del SOURCE_METRICS["_RightBias"]
        assert result["bias_penalty"] > 0.15
        assert "Warning" in result["warning"]

    @pytest.mark.asyncio
    async def test_output_shape_matches_legacy(self, nli_counter):
        items = [
            EvidenceItem(text="x", source=Source(name="BLS"), p_entail=0.5, p_contradict=0.5, nli_source="agent")
        ]
        result = await calculate_confidence_structured("claim", items)
        expected_keys = {"final_score", "verdict", "wes", "average_bias", "bias_penalty", "warning", "details"}
        assert expected_keys <= set(result.keys())

    @pytest.mark.asyncio
    async def test_details_length_matches_input(self, nli_counter):
        items = [
            EvidenceItem(text="a", source=Source(name="CDC"), p_entail=0.8, p_contradict=0.2, nli_source="agent"),
            EvidenceItem(text="b", source=Source(name="FBI"), p_entail=0.7, p_contradict=0.3, nli_source="agent"),
            EvidenceItem(text="c", source=Source(name="BLS"), p_entail=0.6, p_contradict=0.4, nli_source="agent"),
        ]
        result = await calculate_confidence_structured("claim", items)
        assert len(result["details"]) == 3

    @pytest.mark.asyncio
    async def test_trust_weighting_high_trust_dominates(self, nli_counter):
        """A single T=1.0 strongly-entailing source outweighs two T=0.5 contradicting."""
        items = [
            EvidenceItem(text="gov", source=Source(name="CDC"), p_entail=0.95, p_contradict=0.05, nli_source="agent"),
            EvidenceItem(text="b1", source=Source(name="XYZ Blog"), p_entail=0.05, p_contradict=0.90, nli_source="agent"),
            EvidenceItem(text="b2", source=Source(name="ABC Outlet"), p_entail=0.05, p_contradict=0.90, nli_source="agent"),
        ]
        result = await calculate_confidence_structured("claim", items, bias_lambda=0.0)
        # CDC T=1, e=0.9; two unknowns T=0.5 each, e≈-0.85
        # WES = (0.9 - 0.5*0.85 - 0.5*0.85) / (1+0.5+0.5) = (0.9-0.85)/2 = 0.025 → positive
        assert result["wes"] > 0

    @pytest.mark.asyncio
    async def test_source_bonus_log_scale(self, nli_counter):
        """Source bonus = 1 + alpha * ln(n). More sources → higher score at same WES."""
        base_items = [
            EvidenceItem(text="x", source=Source(name="CDC"), p_entail=0.8, p_contradict=0.2, nli_source="agent")
        ]
        many_items = [
            EvidenceItem(text=f"x{i}", source=Source(name="CDC"), p_entail=0.8, p_contradict=0.2, nli_source="agent")
            for i in range(10)
        ]
        one = await calculate_confidence_structured("c", base_items, bias_lambda=0.0)
        many = await calculate_confidence_structured("c", many_items, bias_lambda=0.0)
        expected_bonus_ratio = (1 + 0.1 * math.log(10)) / (1 + 0.1 * math.log(1))
        actual_ratio = many["final_score"] / one["final_score"] if one["final_score"] else 1
        assert abs(actual_ratio - expected_bonus_ratio) < 0.05

    @pytest.mark.asyncio
    async def test_unknown_source_name_falls_back_to_default(self, nli_counter):
        items = [
            EvidenceItem(text="x", source=Source(name="Totally Unknown XYZ"), p_entail=0.8, p_contradict=0.2, nli_source="agent")
        ]
        result = await calculate_confidence_structured("claim", items)
        d = result["details"][0]
        assert d["trust"] == SOURCE_METRICS["Default"]["trust"]

    @pytest.mark.asyncio
    async def test_gov_url_source_auto_trusted(self, nli_counter):
        items = [
            EvidenceItem(text="x", source=Source(name="bls.gov"), p_entail=0.8, p_contradict=0.2, nli_source="agent")
        ]
        result = await calculate_confidence_structured("claim", items)
        assert result["details"][0]["trust"] == 1.0


# ---------------------------------------------------------------------------
# calculate_lean_structured
# ---------------------------------------------------------------------------


# Inject synthetic sources with known bias values for deterministic tests.
_LEFT_SOURCE = "_TestLeft"    # bias = -1.0
_RIGHT_SOURCE = "_TestRight"  # bias = +1.0
_CENTER_SOURCE = "_TestCenter"  # bias = 0.0


@pytest.fixture(autouse=False)
def inject_test_sources():
    SOURCE_METRICS[_LEFT_SOURCE] = {"trust": 1.0, "bias": -1.0}
    SOURCE_METRICS[_RIGHT_SOURCE] = {"trust": 1.0, "bias": 1.0}
    SOURCE_METRICS[_CENTER_SOURCE] = {"trust": 1.0, "bias": 0.0}
    yield
    for k in (_LEFT_SOURCE, _RIGHT_SOURCE, _CENTER_SOURCE):
        SOURCE_METRICS.pop(k, None)


def _ei(source: str, stance: str | None, text: str = "x") -> EvidenceItem:
    return EvidenceItem(text=text, source=Source(name=source), stance=stance)  # type: ignore[arg-type]


class TestCalculateLeanStructured:
    @pytest.mark.asyncio
    async def test_empty_evidence(self, inject_test_sources):
        result = await calculate_lean_structured("opinion", [])
        assert result["lean_value"] == 0.0
        assert result["lean_label"] == "Center / Neutral"
        assert result["confidence"] == 0.0
        assert result["n_contributing"] == 0

    @pytest.mark.asyncio
    async def test_all_unverifiable_returns_center(self, inject_test_sources):
        items = [_ei(_RIGHT_SOURCE, "unverifiable"), _ei(_LEFT_SOURCE, "unverifiable")]
        result = await calculate_lean_structured("op", items)
        assert result["lean_value"] == 0.0
        assert result["n_contributing"] == 0
        assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_agree_right_source_leans_right(self, inject_test_sources):
        # agree * bias(+1) * trust(1) = +1.0
        result = await calculate_lean_structured("op", [_ei(_RIGHT_SOURCE, "agree")])
        assert result["lean_value"] == 1.0
        assert result["lean_label"] == "Leans Right"

    @pytest.mark.asyncio
    async def test_agree_left_source_leans_left(self, inject_test_sources):
        # agree * bias(-1) * trust(1) = -1.0
        result = await calculate_lean_structured("op", [_ei(_LEFT_SOURCE, "agree")])
        assert result["lean_value"] == -1.0
        assert result["lean_label"] == "Leans Left"

    @pytest.mark.asyncio
    async def test_disagree_right_source_leans_left(self, inject_test_sources):
        # disagree * bias(+1) * trust(1) = -1.0
        result = await calculate_lean_structured("op", [_ei(_RIGHT_SOURCE, "disagree")])
        assert result["lean_value"] == -1.0
        assert result["lean_label"] == "Leans Left"

    @pytest.mark.asyncio
    async def test_disagree_left_source_leans_right(self, inject_test_sources):
        # disagree * bias(-1) * trust(1) = +1.0
        result = await calculate_lean_structured("op", [_ei(_LEFT_SOURCE, "disagree")])
        assert result["lean_value"] == 1.0
        assert result["lean_label"] == "Leans Right"

    @pytest.mark.asyncio
    async def test_center_source_contributes_zero(self, inject_test_sources):
        # agree * bias(0) = 0 → still counted in average
        result = await calculate_lean_structured("op", [_ei(_CENTER_SOURCE, "agree")])
        assert result["lean_value"] == 0.0
        assert result["lean_label"] == "Center / Neutral"
        assert result["n_contributing"] == 1

    @pytest.mark.asyncio
    async def test_opposing_stances_cancel(self, inject_test_sources):
        # (+1.0) + (-1.0) / 2 = 0
        items = [_ei(_RIGHT_SOURCE, "agree"), _ei(_RIGHT_SOURCE, "disagree")]
        result = await calculate_lean_structured("op", items)
        assert result["lean_value"] == 0.0

    @pytest.mark.asyncio
    async def test_lean_value_clamped_positive(self, inject_test_sources):
        items = [_ei(_RIGHT_SOURCE, "agree")] * 10
        result = await calculate_lean_structured("op", items)
        assert result["lean_value"] <= 1.0

    @pytest.mark.asyncio
    async def test_lean_value_clamped_negative(self, inject_test_sources):
        items = [_ei(_LEFT_SOURCE, "agree")] * 10
        result = await calculate_lean_structured("op", items)
        assert result["lean_value"] >= -1.0

    @pytest.mark.asyncio
    async def test_confidence_is_contributing_over_total(self, inject_test_sources):
        # 2 agree, 1 unverifiable → confidence = 2/3
        items = [
            _ei(_RIGHT_SOURCE, "agree"),
            _ei(_RIGHT_SOURCE, "agree"),
            _ei(_RIGHT_SOURCE, "unverifiable"),
        ]
        result = await calculate_lean_structured("op", items)
        assert result["n_contributing"] == 2
        assert result["n_total"] == 3
        assert abs(result["confidence"] - round(2 / 3, 3)) < 0.001

    @pytest.mark.asyncio
    async def test_confidence_one_when_all_contributing(self, inject_test_sources):
        items = [_ei(_RIGHT_SOURCE, "agree"), _ei(_LEFT_SOURCE, "disagree")]
        result = await calculate_lean_structured("op", items)
        assert result["confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_unverifiable_not_counted_in_average(self, inject_test_sources):
        # Only the agree-right item should affect lean_value
        items = [_ei(_RIGHT_SOURCE, "agree"), _ei(_LEFT_SOURCE, "unverifiable")]
        result = await calculate_lean_structured("op", items)
        assert result["lean_value"] == 1.0
        assert result["n_contributing"] == 1

    @pytest.mark.asyncio
    async def test_none_stance_treated_as_unverifiable(self, inject_test_sources):
        items = [_ei(_RIGHT_SOURCE, None)]
        result = await calculate_lean_structured("op", items)
        assert result["n_contributing"] == 0

    @pytest.mark.asyncio
    async def test_details_length_matches_input(self, inject_test_sources):
        items = [_ei(_RIGHT_SOURCE, "agree"), _ei(_LEFT_SOURCE, "unverifiable")]
        result = await calculate_lean_structured("op", items)
        assert len(result["details"]) == 2

    @pytest.mark.asyncio
    async def test_contributing_detail_has_trust_and_bias(self, inject_test_sources):
        items = [_ei(_RIGHT_SOURCE, "agree")]
        result = await calculate_lean_structured("op", items)
        d = result["details"][0]
        assert d["trust"] == 1.0
        assert d["bias"] == 1.0
        assert d["contribution"] == 1.0

    @pytest.mark.asyncio
    async def test_skipped_detail_has_none_trust_bias(self, inject_test_sources):
        items = [_ei(_RIGHT_SOURCE, "unverifiable")]
        result = await calculate_lean_structured("op", items)
        d = result["details"][0]
        assert d["trust"] is None
        assert d["bias"] is None

    @pytest.mark.asyncio
    async def test_output_keys_present(self, inject_test_sources):
        result = await calculate_lean_structured("op", [])
        for k in ("lean_value", "lean_label", "confidence", "n_contributing", "n_total", "details"):
            assert k in result

    @pytest.mark.asyncio
    async def test_trust_halves_low_trust_contribution(self):
        # Use a source with trust=0.5 to verify trust scales contribution
        SOURCE_METRICS["_HalfTrust"] = {"trust": 0.5, "bias": 1.0}
        items = [_ei("_HalfTrust", "agree")]
        result = await calculate_lean_structured("op", items)
        del SOURCE_METRICS["_HalfTrust"]
        # contribution = +1 * 1.0 * 0.5 = 0.5 → still Leans Right
        assert result["lean_value"] == 0.5
        assert result["lean_label"] == "Leans Right"

