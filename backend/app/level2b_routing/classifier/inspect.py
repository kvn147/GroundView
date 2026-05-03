"""Dump top-N influential tokens per class for the agent activity panel.

CLI:
    python -m backend.app.level2b_routing.classifier.inspect model.pkl [--top 20]

Inspects the *word* TF-IDF branch of the FeatureUnion. The char_wb
branch produces character n-grams that are not human-readable, so we
skip it. For each topic, prints the highest-weighted positive tokens
from the underlying ``LogisticRegression`` inside the calibrated OvR
wrapper.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from sklearn.pipeline import Pipeline

from ..topics import TOPICS
from .predict import load_model


def _word_branch_vocab(pipeline: Pipeline) -> list[str]:
    features = pipeline.named_steps["features"]
    word_vec = dict(features.transformer_list)["word"]
    return word_vec.get_feature_names_out().tolist()


def _word_branch_offset(pipeline: Pipeline) -> tuple[int, int]:
    """Return ``(start, end)`` column indices of the word branch."""
    features = pipeline.named_steps["features"]
    word_vec = dict(features.transformer_list)["word"]
    n_word = len(word_vec.get_feature_names_out())
    return 0, n_word


def _calibrated_avg_coef(estimator) -> np.ndarray:
    """Average the coefficients across CV folds inside CalibratedClassifierCV."""
    coefs = []
    for cc in estimator.calibrated_classifiers_:
        coefs.append(cc.estimator.coef_.ravel())
    return np.mean(np.vstack(coefs), axis=0)


def top_tokens(pipeline: Pipeline, top_n: int = 20) -> dict[str, list[tuple[str, float]]]:
    """Return ``{topic: [(token, weight), ...]}`` for the word branch."""
    vocab = _word_branch_vocab(pipeline)
    start, end = _word_branch_offset(pipeline)

    ovr = pipeline.named_steps["clf"]
    out: dict[str, list[tuple[str, float]]] = {}

    for idx, topic in enumerate(TOPICS):
        coef = _calibrated_avg_coef(ovr.estimators_[idx])
        word_coef = coef[start:end]
        order = np.argsort(word_coef)[::-1][:top_n]
        out[topic] = [(vocab[i], float(word_coef[i])) for i in order]

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_path", type=Path)
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    pipeline = load_model(args.model_path)
    for topic, rows in top_tokens(pipeline, top_n=args.top).items():
        print(f"\n=== {topic} ===")
        for token, weight in rows:
            print(f"  {weight:+.3f}  {token}")


if __name__ == "__main__":
    main()
