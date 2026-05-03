"""Public Level 2b routing entry point.

Wires the keyword matcher, classifier predict function, and decision
tree. The classifier model is loaded lazily on first call and cached
in a module-level variable.

The legacy single-label LLM router lives at ``backend/core/router.py``
and is intentionally untouched — migration is a separate task.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from sklearn.pipeline import Pipeline

from .classifier.predict import load_model, predict_probs
from .data_prep import mask_speaker_names
from .decision import decide
from .keyword_matcher import score_keywords
from .topics import TOPICS
from .types import RoutingDecision

_DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "classifier" / "model.pkl"

_model_cache: Optional[Pipeline] = None


def _resolve_model_path() -> Path:
    override = os.environ.get("LEVEL2B_MODEL_PATH")
    return Path(override) if override else _DEFAULT_MODEL_PATH


def _load_model_cached() -> Pipeline:
    global _model_cache
    if _model_cache is None:
        _model_cache = load_model(_resolve_model_path())
    return _model_cache


def _zero_probs() -> dict[str, float]:
    return {topic: 0.0 for topic in TOPICS}


def route(
    claim_text: str, threshold: float | None = None, *, mask_speakers: bool = True
) -> RoutingDecision:
    """Route a claim to zero or more canonical topics.

    ``threshold=None`` (the default) means use ``TOPIC_THRESHOLDS`` from
    ``decision.py``. Pass a float to override every topic with one
    global cutoff (used by tests and the eval threshold sweep).

    ``mask_speakers`` must match the training-time setting; the default
    (True) matches ``train.py``'s default. Keyword matching always runs
    on the original text — only the classifier sees the masked form.
    """
    keyword_scores = score_keywords(claim_text)

    def predict_fn(text: str) -> dict[str, float]:
        try:
            pipeline = _load_model_cached()
        except FileNotFoundError:
            # Model artifact is gitignored; if absent, we fall back to
            # all-zero probabilities so the decision tree returns no_route
            # rather than raising. Training is a separate task.
            return _zero_probs()
        model_input = mask_speaker_names(text) if mask_speakers else text
        return predict_probs(pipeline, model_input)

    return decide(
        claim_text=claim_text,
        keyword_scores=keyword_scores,
        classifier_predict_fn=predict_fn,
        threshold=threshold,
    )
