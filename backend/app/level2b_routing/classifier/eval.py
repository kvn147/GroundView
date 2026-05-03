"""Offline evaluation for the Level 2b classifier.

CLI:
    python -m backend.app.level2b_routing.classifier.eval \
        model.pkl test.csv [--thresholds 0.3,0.4,0.5,0.6,0.7] [--no-baseline]

Reports four things in one run:

  1. Per-topic precision/recall/F1 at the default threshold (0.5).
  2. Threshold sweep — per-topic F1 across a grid; flags the best
     threshold for each topic so you can decide whether to set
     per-topic cutoffs in ``decision.py``.
  3. Failure breakdown — for each misrouted row, dumps
     (claim, true, predicted, keyword_scores, classifier_probs).
  4. Keyword-only baseline — argmax over ``score_keywords``, scored
     the same way, so you can see whether the classifier earns its keep.

Reads the same CSV schema as ``train.py``:
    claim_text,immigration,healthcare,crime,economy,education
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, precision_recall_fscore_support
from sklearn.pipeline import Pipeline

from ..data_prep import mask_speaker_names_batch
from ..decision import TOPIC_THRESHOLDS
from ..keyword_matcher import score_keywords
from ..topics import TOPICS
from .predict import load_model

DEFAULT_THRESHOLDS: tuple[float, ...] = (0.3, 0.4, 0.5, 0.6, 0.7)


@dataclass
class EvalSet:
    claims: list[str]
    y_true: np.ndarray  # shape (n_rows, n_topics), int 0/1
    probs: np.ndarray   # shape (n_rows, n_topics), float
    keyword_scores: np.ndarray  # shape (n_rows, n_topics), float


def _load_xy(csv_path: Path) -> tuple[list[str], np.ndarray]:
    # Same handling as data_prep._read_one — pandas' comment='#' is too
    # aggressive and would corrupt rows with mid-line '#'.
    import io as _io
    with open(csv_path, encoding="utf-8") as fh:
        text = "".join(line for line in fh if not line.lstrip().startswith("#"))
    df = pd.read_csv(_io.StringIO(text))
    expected = ["claim_text", *TOPICS]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}. Expected: {expected}")
    return df["claim_text"].astype(str).tolist(), df[list(TOPICS)].to_numpy(dtype=int)


def build_eval_set(
    pipeline: Pipeline, csv_path: Path, *, mask_speakers: bool = True
) -> EvalSet:
    """Score ``pipeline`` over the rows in ``csv_path``.

    When ``mask_speakers`` is True, the same ``<SPEAKER>`` substitution
    used at training time is applied to the model input. The original
    (unmasked) claim text is still kept on ``EvalSet.claims`` so the
    failure dump remains readable. Keyword scores are computed on the
    original text — they don't depend on training-time normalization.
    """
    claims, y_true = _load_xy(csv_path)
    model_input = mask_speaker_names_batch(claims) if mask_speakers else claims
    probs = pipeline.predict_proba(model_input)
    keyword_scores = np.array(
        [[score_keywords(c)[t] for t in TOPICS] for c in claims], dtype=float
    )
    return EvalSet(claims=claims, y_true=y_true, probs=probs, keyword_scores=keyword_scores)


def per_topic_metrics(
    y_true: np.ndarray, y_pred: np.ndarray
) -> list[tuple[str, float, float, float]]:
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, zero_division=0, average=None, labels=list(range(len(TOPICS)))
    )
    return [
        (TOPICS[i], float(precision[i]), float(recall[i]), float(f1[i]))
        for i in range(len(TOPICS))
    ]


def _print_metrics_table(rows: list[tuple[str, float, float, float]], header: str) -> None:
    print(f"\n{header}")
    print(f"{'topic':<14}{'precision':>10}{'recall':>10}{'f1':>10}")
    for topic, p, r, f1 in rows:
        print(f"{topic:<14}{p:>10.3f}{r:>10.3f}{f1:>10.3f}")


def threshold_sweep(
    eval_set: EvalSet, thresholds: tuple[float, ...]
) -> dict[str, dict[float, float]]:
    """Return ``{topic: {threshold: f1}}`` for each candidate cutoff."""
    out: dict[str, dict[float, float]] = {t: {} for t in TOPICS}
    for thr in thresholds:
        y_pred = (eval_set.probs >= thr).astype(int)
        metrics = per_topic_metrics(eval_set.y_true, y_pred)
        for topic, _p, _r, f1 in metrics:
            out[topic][thr] = f1
    return out


def _print_threshold_sweep(sweep: dict[str, dict[float, float]]) -> None:
    thresholds = sorted({thr for inner in sweep.values() for thr in inner})
    print("\nThreshold sweep — per-topic F1:")
    header = f"{'topic':<14}" + "".join(f"{thr:>8.2f}" for thr in thresholds) + f"{'best':>10}"
    print(header)
    for topic in TOPICS:
        cells = "".join(f"{sweep[topic][thr]:>8.3f}" for thr in thresholds)
        best_thr = max(sweep[topic], key=lambda t: sweep[topic][t])
        print(f"{topic:<14}{cells}{best_thr:>10.2f}")


def confusion_rows(
    eval_set: EvalSet, threshold: float = 0.5
) -> list[dict]:
    """Return one record per misrouted row for failure analysis."""
    y_pred = (eval_set.probs >= threshold).astype(int)
    rows: list[dict] = []
    for i, claim in enumerate(eval_set.claims):
        true_set = {TOPICS[j] for j in range(len(TOPICS)) if eval_set.y_true[i, j] == 1}
        pred_set = {TOPICS[j] for j in range(len(TOPICS)) if y_pred[i, j] == 1}
        if true_set == pred_set:
            continue
        rows.append({
            "claim": claim,
            "true": sorted(true_set),
            "predicted": sorted(pred_set),
            "missed": sorted(true_set - pred_set),
            "spurious": sorted(pred_set - true_set),
            "keyword_scores": {TOPICS[j]: float(eval_set.keyword_scores[i, j])
                               for j in range(len(TOPICS))},
            "classifier_probs": {TOPICS[j]: float(eval_set.probs[i, j])
                                 for j in range(len(TOPICS))},
        })
    return rows


def _print_confusion_rows(rows: list[dict], limit: int = 20) -> None:
    print(f"\nFailures ({len(rows)} total, showing up to {limit}):")
    for row in rows[:limit]:
        print(f"\n  claim:     {row['claim']}")
        print(f"  true:      {row['true']}")
        print(f"  predicted: {row['predicted']}")
        if row["missed"]:
            print(f"  MISSED:    {row['missed']}")
        if row["spurious"]:
            print(f"  SPURIOUS:  {row['spurious']}")
        active_kw = {t: s for t, s in row["keyword_scores"].items() if s > 0}
        top_probs = sorted(row["classifier_probs"].items(), key=lambda x: -x[1])[:3]
        print(f"  kw>0:      {active_kw}")
        print(f"  top probs: {top_probs}")


def keyword_baseline_metrics(eval_set: EvalSet) -> list[tuple[str, float, float, float]]:
    """Argmax-over-keyword-scores baseline. Predicts at most one topic per row;
    rows where every score is 0 predict nothing."""
    y_pred = np.zeros_like(eval_set.y_true)
    for i in range(len(eval_set.claims)):
        scores = eval_set.keyword_scores[i]
        if scores.max() > 0:
            y_pred[i, int(scores.argmax())] = 1
    return per_topic_metrics(eval_set.y_true, y_pred)


def _macro_f1(rows: list[tuple[str, float, float, float]]) -> float:
    return float(np.mean([f1 for _t, _p, _r, f1 in rows]))


def _micro_f1(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(f1_score(y_true, y_pred, average="micro", zero_division=0))


def run(
    model_path: Path,
    csv_path: Path,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    *,
    show_baseline: bool = True,
    failure_limit: int = 20,
    mask_speakers: bool = True,
) -> None:
    pipeline = load_model(model_path)
    eval_set = build_eval_set(pipeline, csv_path, mask_speakers=mask_speakers)

    y_pred_default = (eval_set.probs >= 0.5).astype(int)
    metrics = per_topic_metrics(eval_set.y_true, y_pred_default)
    _print_metrics_table(metrics, "Per-topic metrics @ threshold=0.5:")
    print(f"\nMacro F1: {_macro_f1(metrics):.3f}   "
          f"Micro F1: {_micro_f1(eval_set.y_true, y_pred_default):.3f}")

    per_topic_thr = np.array([TOPIC_THRESHOLDS.get(t, 0.5) for t in TOPICS])
    y_pred_pertopic = (eval_set.probs >= per_topic_thr).astype(int)
    metrics_pertopic = per_topic_metrics(eval_set.y_true, y_pred_pertopic)
    header = "Per-topic metrics @ TOPIC_THRESHOLDS (" + ", ".join(
        f"{t}={TOPIC_THRESHOLDS.get(t, 0.5):.2f}" for t in TOPICS
    ) + "):"
    _print_metrics_table(metrics_pertopic, header)
    print(f"\nMacro F1: {_macro_f1(metrics_pertopic):.3f}   "
          f"Micro F1: {_micro_f1(eval_set.y_true, y_pred_pertopic):.3f}")

    sweep = threshold_sweep(eval_set, thresholds)
    _print_threshold_sweep(sweep)

    rows = confusion_rows(eval_set, threshold=0.5)
    _print_confusion_rows(rows, limit=failure_limit)

    if show_baseline:
        baseline = keyword_baseline_metrics(eval_set)
        _print_metrics_table(baseline, "Keyword-only baseline (argmax):")
        print(f"\nBaseline macro F1: {_macro_f1(baseline):.3f}   "
              f"Classifier macro F1: {_macro_f1(metrics):.3f}")


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("model_path", type=Path)
    p.add_argument("csv_path", type=Path)
    p.add_argument(
        "--thresholds",
        type=lambda s: tuple(float(x) for x in s.split(",")),
        default=DEFAULT_THRESHOLDS,
    )
    p.add_argument("--no-baseline", action="store_true")
    p.add_argument("--failure-limit", type=int, default=20)
    p.add_argument(
        "--no-mask",
        action="store_true",
        help="Disable speaker-name masking (must match training-time setting)",
    )
    return p


def main() -> None:
    args = _build_argparser().parse_args()
    run(
        args.model_path,
        args.csv_path,
        thresholds=args.thresholds,
        show_baseline=not args.no_baseline,
        failure_limit=args.failure_limit,
        mask_speakers=not args.no_mask,
    )


if __name__ == "__main__":
    main()
