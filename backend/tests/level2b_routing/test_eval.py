"""Smoke tests for the eval module: train a tiny pipeline inline,
write a small CSV, and check each public function returns the right shape."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import FeatureUnion, Pipeline

from backend.app.level2b_routing.classifier import eval as eval_mod
from backend.app.level2b_routing.topics import TOPICS


_ROWS: list[tuple[str, dict[str, int]]] = [
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
    ("She wore a blue scarf to the wedding on Saturday afternoon.", {}),
    ("The novelist published her third book to wide critical acclaim.", {}),
]


def _tiny_pipeline() -> Pipeline:
    features = FeatureUnion(
        [
            ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1)),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)),
        ]
    )
    base = LogisticRegression(max_iter=1000)
    calibrated = CalibratedClassifierCV(base, cv=2, method="sigmoid")
    return Pipeline([("features", features), ("clf", OneVsRestClassifier(calibrated))])


def _build_xy() -> tuple[list[str], np.ndarray]:
    x = [r[0] for r in _ROWS]
    y = np.zeros((len(_ROWS), len(TOPICS)), dtype=int)
    for i, (_t, labels) in enumerate(_ROWS):
        for topic, val in labels.items():
            y[i, TOPICS.index(topic)] = val
    return x, y


@pytest.fixture
def trained_pipeline() -> Pipeline:
    pipeline = _tiny_pipeline()
    x, y = _build_xy()
    pipeline.fit(x, y)
    return pipeline


@pytest.fixture
def csv_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["claim_text", *TOPICS])
        for text, labels in _ROWS:
            writer.writerow([text] + [labels.get(t, 0) for t in TOPICS])
    return path


def test_build_eval_set_shapes(trained_pipeline: Pipeline, csv_path: Path) -> None:
    eval_set = eval_mod.build_eval_set(trained_pipeline, csv_path)
    n = len(_ROWS)
    assert len(eval_set.claims) == n
    assert eval_set.y_true.shape == (n, len(TOPICS))
    assert eval_set.probs.shape == (n, len(TOPICS))
    assert eval_set.keyword_scores.shape == (n, len(TOPICS))


def test_per_topic_metrics_returns_one_row_per_topic(
    trained_pipeline: Pipeline, csv_path: Path
) -> None:
    eval_set = eval_mod.build_eval_set(trained_pipeline, csv_path)
    y_pred = (eval_set.probs >= 0.5).astype(int)
    metrics = eval_mod.per_topic_metrics(eval_set.y_true, y_pred)
    assert len(metrics) == len(TOPICS)
    assert {row[0] for row in metrics} == set(TOPICS)
    for _topic, p, r, f1 in metrics:
        assert 0.0 <= p <= 1.0
        assert 0.0 <= r <= 1.0
        assert 0.0 <= f1 <= 1.0


def test_threshold_sweep_covers_all_thresholds(
    trained_pipeline: Pipeline, csv_path: Path
) -> None:
    eval_set = eval_mod.build_eval_set(trained_pipeline, csv_path)
    sweep = eval_mod.threshold_sweep(eval_set, (0.3, 0.5, 0.7))
    assert set(sweep.keys()) == set(TOPICS)
    for topic in TOPICS:
        assert set(sweep[topic].keys()) == {0.3, 0.5, 0.7}


def test_confusion_rows_returns_records_for_failures(
    trained_pipeline: Pipeline, csv_path: Path
) -> None:
    eval_set = eval_mod.build_eval_set(trained_pipeline, csv_path)
    # Force failures with an absurdly high threshold so every positive is missed.
    rows = eval_mod.confusion_rows(eval_set, threshold=0.99)
    assert len(rows) > 0
    sample = rows[0]
    assert {"claim", "true", "predicted", "missed", "spurious",
            "keyword_scores", "classifier_probs"} <= set(sample.keys())


def test_keyword_baseline_metrics_shape(
    trained_pipeline: Pipeline, csv_path: Path
) -> None:
    eval_set = eval_mod.build_eval_set(trained_pipeline, csv_path)
    metrics = eval_mod.keyword_baseline_metrics(eval_set)
    assert len(metrics) == len(TOPICS)


def test_run_smoke(
    trained_pipeline: Pipeline, csv_path: Path, tmp_path: Path, monkeypatch
) -> None:
    """End-to-end: ``run()`` should print without raising."""
    model_path = tmp_path / "model.pkl"
    import joblib
    joblib.dump(trained_pipeline, model_path)

    eval_mod.run(
        model_path=model_path,
        csv_path=csv_path,
        thresholds=(0.3, 0.5, 0.7),
        show_baseline=True,
        failure_limit=5,
    )
