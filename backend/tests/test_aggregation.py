"""Tests for backend/core/aggregation.py — bifurcated aggregation."""

from __future__ import annotations

import pytest

from backend.contracts import (
    Annotation,
    Claim,
    ConfidenceState,
    Opinion,
    OpinionAnnotation,
    PoliticalLean,
)
from backend.core.aggregation import (
    aggregate,
    bias_to_lean,
    political_lean_from_opinions,
    score_to_trust,
    trustworthiness_from_facts,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _claim(text: str = "test claim") -> Claim:
    return Claim(claim_text=text, raw_quote=text, start_time=0.0, end_time=5.0)


def _opinion_obj(text: str = "an opinion") -> Opinion:
    return Opinion(statement=text, raw_quote=text, start_time=0.0, end_time=5.0)


def _annotation(
    final_score: float,
    confidence_state: ConfidenceState = "verified",
    bias_warning: str | None = None,
) -> Annotation:
    return Annotation(
        claim=_claim(),
        results=[],
        confidence_state=confidence_state,
        final_score=final_score,
        bias_warning=bias_warning,
    )


def _opinion_ann(lean_value: float, lean_label: str = "Center / Neutral") -> OpinionAnnotation:
    return OpinionAnnotation(
        opinion=_opinion_obj(),
        results=[],
        lean_value=lean_value,
        lean_label=lean_label,
        reasoning="",
        confidence=0.8,
    )


# ---------------------------------------------------------------------------
# score_to_trust
# ---------------------------------------------------------------------------


class TestScoreToTrust:
    def test_perfect_positive(self):
        assert score_to_trust(1.0) == (5, "Highly Accurate")

    def test_perfect_negative(self):
        assert score_to_trust(-1.0) == (1, "Mostly False")

    def test_neutral(self):
        score, _ = score_to_trust(0.0)
        assert score == 3

    def test_clamped_above_5(self):
        assert score_to_trust(1.0)[0] <= 5

    def test_clamped_below_1(self):
        assert score_to_trust(-1.0)[0] >= 1

    def test_leans_true(self):
        assert score_to_trust(0.6)[0] >= 4

    def test_leans_false(self):
        assert score_to_trust(-0.6)[0] <= 2

    def test_returns_int_and_str(self):
        s, l = score_to_trust(0.0)
        assert isinstance(s, int) and isinstance(l, str)


# ---------------------------------------------------------------------------
# trustworthiness_from_facts
# ---------------------------------------------------------------------------


class TestTrustworthinessFromFacts:
    def test_empty_returns_neutral(self):
        assert trustworthiness_from_facts([])[0] == 3

    def test_single_perfect(self):
        assert trustworthiness_from_facts([_annotation(1.0)])[0] == 5

    def test_single_false(self):
        assert trustworthiness_from_facts([_annotation(-1.0)])[0] == 1

    def test_averages_multiple(self):
        # avg 0.0 → trust 3
        assert trustworthiness_from_facts([_annotation(1.0), _annotation(-1.0)])[0] == 3

    def test_opinions_irrelevant(self):
        # Function only accepts Annotations; opinions excluded by design
        assert trustworthiness_from_facts([_annotation(1.0)])[0] == 5


# ---------------------------------------------------------------------------
# bias_to_lean
# ---------------------------------------------------------------------------


class TestBiasToLean:
    def test_far_left(self):
        assert bias_to_lean(-1.0) == ("Leans Left", 0.0)

    def test_far_right(self):
        assert bias_to_lean(1.0) == ("Leans Right", 1.0)

    def test_center(self):
        label, value = bias_to_lean(0.0)
        assert label == "Center / Neutral" and value == 0.5

    def test_boundary_left_exclusive(self):
        assert bias_to_lean(-0.31)[0] == "Leans Left"

    def test_boundary_right_exclusive(self):
        assert bias_to_lean(0.31)[0] == "Leans Right"

    def test_boundary_center_at_minus_03(self):
        assert bias_to_lean(-0.3)[0] == "Center / Neutral"

    def test_boundary_center_at_plus_03(self):
        assert bias_to_lean(0.3)[0] == "Center / Neutral"

    def test_value_in_unit_interval(self):
        for b in [-1.0, -0.5, 0.0, 0.5, 1.0]:
            _, v = bias_to_lean(b)
            assert 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# political_lean_from_opinions
# ---------------------------------------------------------------------------


class TestPoliticalLeanFromOpinions:
    def test_empty_returns_unknown(self):
        lean = political_lean_from_opinions([])
        assert lean.label == "Unknown" and lean.value == 0.5

    def test_single_left(self):
        assert political_lean_from_opinions([_opinion_ann(-1.0)]).label == "Leans Left"

    def test_single_right(self):
        assert political_lean_from_opinions([_opinion_ann(1.0)]).label == "Leans Right"

    def test_averaged_center(self):
        assert political_lean_from_opinions([_opinion_ann(-1.0), _opinion_ann(1.0)]).label == "Center / Neutral"

    def test_returns_political_lean(self):
        assert isinstance(political_lean_from_opinions([_opinion_ann(0.5)]), PoliticalLean)

    def test_leans_right_majority(self):
        result = political_lean_from_opinions([_opinion_ann(0.5), _opinion_ann(0.8)])
        assert result.label == "Leans Right"


# ---------------------------------------------------------------------------
# aggregate — separation invariants
# ---------------------------------------------------------------------------


class TestAggregateTopLevel:
    def test_trust_unaffected_by_negative_opinions(self):
        facts = [_annotation(1.0)]
        result_no_op = aggregate(facts, [])
        result_with_op = aggregate(facts, [_opinion_ann(-1.0), _opinion_ann(-1.0)])
        assert result_no_op.trustworthinessScore == result_with_op.trustworthinessScore

    def test_lean_unaffected_by_contradicting_facts(self):
        opinions = [_opinion_ann(1.0)]
        result_no_facts = aggregate([], opinions)
        result_with_facts = aggregate([_annotation(-1.0)], opinions)
        assert result_no_facts.politicalLean.label == result_with_facts.politicalLean.label

    def test_empty_facts_neutral_trust(self):
        assert aggregate([], [_opinion_ann(0.5)]).trustworthinessScore == 3

    def test_empty_opinions_unknown_lean(self):
        assert aggregate([_annotation(1.0)], []).politicalLean.label == "Unknown"

    def test_both_empty_complete_response(self):
        r = aggregate([], [])
        assert r.trustworthinessScore == 3
        assert r.politicalLean.label == "Unknown"
        assert r.claims == [] and r.opinions == []

    def test_fact_claims_prefixed_fact(self):
        r = aggregate([_annotation(1.0)], [])
        assert r.claims[0].id.startswith("fact-")

    def test_opinions_not_in_claims(self):
        r = aggregate([], [_opinion_ann(0.5)])
        assert r.claims == []

    def test_opinions_in_opinions_list(self):
        r = aggregate([], [_opinion_ann(0.5)])
        assert len(r.opinions) == 1

    def test_total_claim_count(self):
        r = aggregate([_annotation(0.5), _annotation(-0.2)], [_opinion_ann(0.4)])
        assert len(r.claims) == 2
        assert len(r.opinions) == 1

    def test_trust_5_from_all_true_facts(self):
        r = aggregate([_annotation(1.0)] * 5, [])
        assert r.trustworthinessScore == 5 and r.trustworthinessLabel == "Highly Accurate"

    def test_lean_right_from_all_right_opinions(self):
        r = aggregate([], [_opinion_ann(0.8)] * 3)
        assert r.politicalLean.label == "Leans Right"

    def test_summary_mentions_both_counts(self):
        r = aggregate([_annotation(0.5)], [_opinion_ann(0.2)])
        assert "1 factual claim" in r.summary
        assert "1 opinion statement" in r.summary

    def test_summary_empty(self):
        assert "No verifiable" in aggregate([], []).summary

    def test_max_score_always_5(self):
        assert aggregate([], []).maxScore == 5

    def test_verdict_true_for_verified(self):
        r = aggregate([_annotation(1.0, confidence_state="verified")], [])
        assert r.claims[0].verdict == "True"

    def test_verdict_false_for_contradicted(self):
        r = aggregate([_annotation(-1.0, confidence_state="contradicted")], [])
        assert r.claims[0].verdict == "False"

    def test_verdict_mixed_for_disagree(self):
        r = aggregate([_annotation(0.0, confidence_state="sources_disagree")], [])
        assert r.claims[0].verdict == "Mixed"

    def test_verdict_unverified_for_insufficient(self):
        r = aggregate([_annotation(0.0, confidence_state="insufficient_coverage")], [])
        assert r.claims[0].verdict == "Unverified"

    def test_opinion_lean_label_in_frontend(self):
        op = OpinionAnnotation(
            opinion=_opinion_obj(), results=[], lean_value=0.8,
            lean_label="Leans Right", reasoning="test", confidence=0.9,
        )
        r = aggregate([], [op])
        assert r.opinions[0].lean.label == "Leans Right"
        assert r.opinions[0].lean.value == 0.8
        assert r.opinions[0].lean.confidence == 0.9

    def test_opinion_statement_in_frontend(self):
        op = OpinionAnnotation(
            opinion=Opinion(statement="Taxes are too high", raw_quote="Taxes are too high",
                            start_time=10.0, end_time=15.0),
            results=[], lean_value=0.5, lean_label="Leans Right",
            reasoning="r", confidence=0.7,
        )
        r = aggregate([], [op])
        assert r.opinions[0].statement == "Taxes are too high"
        assert r.opinions[0].start_time == 10.0

    def test_political_lean_value_in_range(self):
        for b in [-1.0, -0.5, 0.0, 0.5, 1.0]:
            assert 0.0 <= aggregate([], [_opinion_ann(b)]).politicalLean.value <= 1.0

    def test_aggregated_sources_list_type(self):
        assert isinstance(aggregate([_annotation(1.0)], []).aggregatedSources, list)
