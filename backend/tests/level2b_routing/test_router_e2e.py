"""End-to-end router test using a tiny inline-trained classifier.

We do NOT load the real model.pkl (it is gitignored and may be absent).
Instead we train a small pipeline on hand-written rows, monkeypatch
the cached model into ``router._model_cache``, and call ``route``.
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import FeatureUnion, Pipeline

from backend.app.level2b_routing import router as router_mod
from backend.app.level2b_routing.topics import TOPICS
from backend.app.level2b_routing.types import RoutingDecision


def _tiny_pipeline() -> Pipeline:
    """Mirror of ``classifier.train.build_pipeline`` but with cv=2 so it
    fits the small inline corpus below. Production training uses cv=3."""
    features = FeatureUnion(
        [
            ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1)),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)),
        ]
    )
    base = LogisticRegression(max_iter=1000)
    calibrated = CalibratedClassifierCV(base, cv=2, method="sigmoid")
    classifier = OneVsRestClassifier(calibrated)
    return Pipeline([("features", features), ("clf", classifier)])


# Hand-written rows: ≥2 positives per topic so cv=2 calibration is happy,
# plus a couple of negatives so each label also has ≥2 zeros.
_TRAIN_ROWS: list[tuple[str, dict[str, int]]] = [
    ("Border Patrol arrested 500 migrants seeking asylum at the southern border.",
     {"immigration": 1}),
    ("ICE conducted a raid in three sanctuary cities, deporting 200 people.",
     {"immigration": 1}),
    ("Medicare premiums for prescription drugs rose under the new ACA rule.",
     {"healthcare": 1}),
    ("The CDC reported a sharp increase in hospital admissions among uninsured patients.",
     {"healthcare": 1}),
    ("The FBI said the violent crime rate fell while homicides rose in major cities.",
     {"crime": 1}),
    ("Police arrested twelve people on robbery and assault charges last weekend.",
     {"crime": 1}),
    ("Inflation reached 8% as the Federal Reserve hiked interest rates again.",
     {"economy": 1}),
    ("GDP grew $1.2 trillion last quarter, BLS data show, and unemployment fell.",
     {"economy": 1}),
    ("Student loan forgiveness reached forty million borrowers at public universities.",
     {"education": 1}),
    ("The Dept. of Education expanded Pell Grants for K-12 charter schools.",
     {"education": 1}),
    ("She wore a blue scarf to the wedding on Saturday afternoon.",
     {}),
    ("The novelist published her third book to wide critical acclaim.",
     {}),
]


def _build_xy() -> tuple[list[str], np.ndarray]:
    x = [row[0] for row in _TRAIN_ROWS]
    y = np.zeros((len(_TRAIN_ROWS), len(TOPICS)), dtype=int)
    for i, (_text, labels) in enumerate(_TRAIN_ROWS):
        for topic, val in labels.items():
            y[i, TOPICS.index(topic)] = val
    return x, y


@pytest.fixture
def trained_pipeline():
    pipeline = _tiny_pipeline()
    x, y = _build_xy()
    pipeline.fit(x, y)
    return pipeline


@pytest.fixture(autouse=True)
def reset_router_cache():
    router_mod._model_cache = None
    yield
    router_mod._model_cache = None


def _route_with(pipeline, claim: str, threshold: float = 0.5) -> RoutingDecision:
    router_mod._model_cache = pipeline
    return router_mod.route(claim, threshold=threshold)


def test_keyword_path_strong_immigration(trained_pipeline) -> None:
    decision = _route_with(
        trained_pipeline,
        "ICE deported 1,200 migrants at the border under Title 42 last month.",
    )
    assert "immigration" in decision.routed_topics
    assert decision.routing_method in {"keyword", "classifier"}
    # keyword path is preferred when 1-2 topics have score >= 2; this
    # claim should hit that branch given the immigration table.
    assert decision.routing_method == "keyword"


def test_off_topic_claim_routes_nowhere(trained_pipeline) -> None:
    # Note: with only 12 inline rows, the calibrated classifier produces
    # noisy probabilities across all classes. We use a high threshold so
    # the assertion exercises the no_route branch deterministically;
    # production training has many more rows and a calibrated 0.5 cutoff.
    decision = _route_with(
        trained_pipeline,
        "She wore a blue scarf to the wedding on Saturday afternoon.",
        threshold=0.99,
    )
    assert decision.routed_topics == []
    assert decision.routing_method == "no_route"


def test_routing_decision_shape(trained_pipeline) -> None:
    decision = _route_with(
        trained_pipeline,
        "Inflation reached 8% as the Federal Reserve hiked interest rates again.",
    )
    assert isinstance(decision, RoutingDecision)
    assert set(decision.keyword_scores.keys()) == set(TOPICS)
    # classifier_probs is populated whenever the classifier contributed
    # to the decision: ``classifier`` (sole driver) and ``hybrid``
    # (added topics on top of keyword). Pure ``keyword`` and
    # ``no_route`` leave it empty.
    if decision.routing_method in ("classifier", "hybrid"):
        assert set(decision.classifier_probs.keys()) == set(TOPICS)
    else:
        assert decision.classifier_probs == {}
    assert 0.0 <= decision.routing_confidence <= 1.0


def test_no_model_pkl_yields_no_route_via_classifier_fallback(monkeypatch) -> None:
    """If model.pkl is absent and keyword path doesn't fire, route() must
    not raise — it should silently fall through to no_route."""

    def boom(_path):
        raise FileNotFoundError("simulated missing model.pkl")

    monkeypatch.setattr(router_mod, "load_model", boom)
    router_mod._model_cache = None

    decision = router_mod.route("She wore a blue scarf to the wedding.")
    assert decision.routing_method == "no_route"
    assert decision.routed_topics == []
