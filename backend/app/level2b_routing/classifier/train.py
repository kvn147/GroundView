"""Train the Level 2b multi-label topic classifier.

CLI:
    python -m backend.app.level2b_routing.classifier.train <path> [--out model.pkl]

``<path>`` may be either a single CSV file or a directory of
``synthetic_train*.csv`` batch files. When a directory is given, the
batches are concatenated, ``# Constraint: ...`` header lines are
skipped, and exact-duplicate ``claim_text`` rows are dropped.

CSV schema (must match the data prompt exactly):
    claim_text,immigration,healthcare,crime,economy,education
    "...",0,0,0,1,0

Pipeline:
    FeatureUnion(
        TfidfVectorizer(word, ngram=(1,2)),
        TfidfVectorizer(char_wb, ngram=(3,5)),
    )
    -> OneVsRestClassifier(CalibratedClassifierCV(LogisticRegression))

CalibratedClassifierCV gives per-class probability estimates that
play nicely with the threshold check in ``decision.decide``.

Mitigations applied by default (see ``data_prep.py``):
  * Speaker names are masked to ``<SPEAKER>`` before vectorization so
    the classifier can't memorize invented names from the synthetic
    data. Disable with ``--no-mask`` for debugging.
  * Exact-duplicate ``claim_text`` rows are dropped during load.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support
from sklearn.model_selection import train_test_split
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import FeatureUnion, Pipeline

from ..data_prep import LoadStats, load_csv_or_directory, to_xy
from ..topics import TOPICS


def build_pipeline(*, calibration_cv: int = 3) -> Pipeline:
    """Construct the untrained sklearn pipeline."""
    features = FeatureUnion(
        [
            (
                "word",
                TfidfVectorizer(
                    analyzer="word",
                    ngram_range=(1, 2),
                    min_df=1,
                    sublinear_tf=True,
                ),
            ),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    min_df=1,
                    sublinear_tf=True,
                ),
            ),
        ]
    )
    # class_weight='balanced' counters the LIAR-driven economy skew
    # (~5x more positives than immigration).
    base = LogisticRegression(max_iter=1000, class_weight="balanced")
    calibrated = CalibratedClassifierCV(base, cv=calibration_cv, method="sigmoid")
    classifier = OneVsRestClassifier(calibrated)
    return Pipeline([("features", features), ("clf", classifier)])


def _print_per_topic_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> None:
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, zero_division=0, average=None, labels=list(range(len(TOPICS)))
    )
    print("\nPer-topic validation metrics:")
    print(f"{'topic':<14}{'precision':>10}{'recall':>10}{'f1':>10}")
    for idx, topic in enumerate(TOPICS):
        print(f"{topic:<14}{precision[idx]:>10.3f}{recall[idx]:>10.3f}{f1[idx]:>10.3f}")


def _print_load_stats(stats: LoadStats, *, masked: bool) -> None:
    print(
        f"Loaded {stats.rows_raw} rows from {stats.files} file(s); "
        f"dropped {stats.duplicates_dropped} exact duplicate(s); "
        f"{stats.rows_after_dedup} rows after dedup."
    )
    print(f"Speaker masking: {'on' if masked else 'OFF (--no-mask)'}.")


def train_from_path(
    path: Path | str,
    out_path: Path | str | None = None,
    *,
    test_size: float = 0.2,
    random_state: int = 42,
    mask_speakers: bool = True,
    calibration_cv: int = 3,
) -> Pipeline:
    """Fit the pipeline on a CSV or directory, print metrics, optionally persist."""
    df, stats = load_csv_or_directory(path)
    _print_load_stats(stats, masked=mask_speakers)

    x, y = to_xy(df, mask_speakers=mask_speakers)

    x_train, x_val, y_train, y_val = train_test_split(
        x, y, test_size=test_size, random_state=random_state
    )

    pipeline = build_pipeline(calibration_cv=calibration_cv)
    pipeline.fit(x_train, y_train)
    y_pred = pipeline.predict(x_val)

    _print_per_topic_metrics(np.asarray(y_val), np.asarray(y_pred))

    if out_path is not None:
        out_path = Path(out_path)
        joblib.dump(pipeline, out_path)
        print(f"\nSaved trained pipeline to {out_path}")

    return pipeline


# Back-compat alias — older call sites and tests may import this name.
train_from_csv = train_from_path


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "data_path",
        type=Path,
        help="Path to a training CSV or a directory of synthetic_train*.csv batches",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Where to write the joblib pipeline (omit to skip persistence)",
    )
    p.add_argument("--test-size", type=float, default=0.2)
    p.add_argument("--random-state", type=int, default=42)
    p.add_argument(
        "--no-mask",
        action="store_true",
        help="Disable speaker-name masking (debugging only)",
    )
    p.add_argument(
        "--cv",
        type=int,
        default=3,
        help="Folds for CalibratedClassifierCV (default 3)",
    )
    return p


def main() -> None:
    args = _build_argparser().parse_args()
    train_from_path(
        args.data_path,
        out_path=args.out,
        test_size=args.test_size,
        random_state=args.random_state,
        mask_speakers=not args.no_mask,
        calibration_cv=args.cv,
    )


if __name__ == "__main__":
    main()
