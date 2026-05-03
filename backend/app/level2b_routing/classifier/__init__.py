"""Logistic-regression classifier for Level 2b multi-label routing."""

from .eval import run as run_eval
from .predict import load_model, predict_probs
from .train import build_pipeline, train_from_csv

__all__ = [
    "build_pipeline",
    "train_from_csv",
    "load_model",
    "predict_probs",
    "run_eval",
]
