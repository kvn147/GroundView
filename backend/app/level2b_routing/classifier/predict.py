"""Inference helpers for the Level 2b classifier.

Threshold logic intentionally lives in ``decision.decide`` — this
module is a thin wrapper around an already-fit sklearn pipeline.
"""

from __future__ import annotations

from pathlib import Path

import joblib
from sklearn.pipeline import Pipeline

from ..topics import TOPICS


def load_model(path: Path | str) -> Pipeline:
    """Load a joblib-pickled sklearn ``Pipeline``."""
    return joblib.load(Path(path))


def predict_probs(pipeline: Pipeline, claim_text: str) -> dict[str, float]:
    """Return ``{topic_id: calibrated_probability}`` for one claim.

    The fitted pipeline is an OvR classifier — ``predict_proba`` returns
    a (1, n_topics) array of per-class probabilities. Map columns back
    to canonical topic IDs in ``TOPICS`` order.
    """
    probs = pipeline.predict_proba([claim_text])[0]
    return {topic: float(probs[idx]) for idx, topic in enumerate(TOPICS)}
