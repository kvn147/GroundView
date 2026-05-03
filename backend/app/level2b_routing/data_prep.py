"""Loading and preprocessing for Level 2b training data.

Three responsibilities:

  * ``mask_speaker_names`` — replace synthetic speaker mentions with a
    ``<SPEAKER>`` token so the classifier can't memorize invented names
    like "Senator Marquez" or "Representative Tashkentbayev". Apply
    this at *both* train and inference time to avoid skew.
  * ``load_directory`` — glob ``synthetic_train*.csv``, concatenate
    them, skip ``# Constraint: ...`` headers, drop exact-duplicate
    ``claim_text`` rows.
  * ``load_csv_or_directory`` — dispatch helper used by ``train.py``
    so the CLI accepts either a single CSV file or the data directory.

All functions are pure (no I/O side effects beyond reading the path
they're handed) and have no sklearn dependency.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .topics import TOPICS

SPEAKER_TOKEN = "<SPEAKER>"

# Title list deliberately broad — synthetic data uses a mix of formal and
# informal titles. We accept "Senator", "State Senator", "Lieutenant
# Governor", "AG", etc. The capture covers a 1- or 2-token surname,
# allowing hyphens (Whitfield-Iyer, Cervantes-Dahlquist).
_TITLE_ALT = (
    r"(?:Senator|State\s+Senator|Representative|Rep\.?|Congresswoman|Congressman|"
    r"Governor|Lieutenant\s+Governor|Lt\.?\s+Governor|Mayor|AG|"
    r"Attorney\s+General|President|Vice\s+President|Secretary|Justice|Judge|"
    r"Sheriff|Chief)"
)
_NAME_ALT = r"[A-Z][a-zA-Z\-']+(?:\s+[A-Z][a-zA-Z\-']+){0,2}"
_SPEAKER_REGEX = re.compile(rf"\b{_TITLE_ALT}\s+{_NAME_ALT}\b")


def mask_speaker_names(text: str) -> str:
    """Replace all ``<title> <name>`` mentions with ``<SPEAKER>``.

    Conservative on purpose: only fires when a known title precedes the
    name. Plain bare names ("Brown said...") are left alone — the cost
    of false positives (masking real topical nouns) outweighs the
    benefit, since the synthetic data's name-memorization risk lives
    almost entirely in titled mentions.
    """
    return _SPEAKER_REGEX.sub(SPEAKER_TOKEN, text)


def mask_speaker_names_batch(texts: list[str]) -> list[str]:
    return [mask_speaker_names(t) for t in texts]


@dataclass
class LoadStats:
    files: int
    rows_raw: int
    rows_after_dedup: int

    @property
    def duplicates_dropped(self) -> int:
        return self.rows_raw - self.rows_after_dedup


def _read_one(path: Path) -> pd.DataFrame:
    # Strip leading-'#' constraint headers ourselves. pandas' comment='#'
    # also strips any in-line '#', which silently truncates rows that
    # contain hashtags (e.g. LIAR claims with '#GOP') and produces NaN
    # topic columns.
    with open(path, encoding="utf-8") as fh:
        text = "".join(line for line in fh if not line.lstrip().startswith("#"))
    df = pd.read_csv(io.StringIO(text))
    expected = ["claim_text", *TOPICS]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(
            f"{path.name} missing required columns: {missing}. Expected: {expected}"
        )
    return df[expected]


def load_directory(
    directory: Path | str,
    pattern: str = "synthetic_train*.csv",
) -> tuple[pd.DataFrame, LoadStats]:
    """Glob, concat, and exact-dedup a directory of training CSVs."""
    directory = Path(directory)
    files = sorted(directory.glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"No files matching {pattern!r} in {directory}"
        )
    frames = [_read_one(f) for f in files]
    combined = pd.concat(frames, ignore_index=True)
    rows_raw = len(combined)
    deduped = combined.drop_duplicates(subset=["claim_text"]).reset_index(drop=True)
    return deduped, LoadStats(
        files=len(files),
        rows_raw=rows_raw,
        rows_after_dedup=len(deduped),
    )


def load_csv_or_directory(
    path: Path | str,
) -> tuple[pd.DataFrame, LoadStats]:
    """Dispatch on whether ``path`` is a file or a directory."""
    p = Path(path)
    if p.is_dir():
        return load_directory(p)
    df = _read_one(p)
    return df, LoadStats(files=1, rows_raw=len(df), rows_after_dedup=len(df))


def to_xy(
    df: pd.DataFrame, *, mask_speakers: bool = True
) -> tuple[list[str], np.ndarray]:
    """Project a loaded frame into ``(claims, label_matrix)``."""
    claims = df["claim_text"].astype(str).tolist()
    if mask_speakers:
        claims = mask_speaker_names_batch(claims)
    y = df[list(TOPICS)].to_numpy(dtype=int)
    return claims, y
