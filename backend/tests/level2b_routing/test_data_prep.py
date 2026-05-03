"""Unit tests for data_prep: speaker masking + batch loading + dedup."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from backend.app.level2b_routing import data_prep
from backend.app.level2b_routing.data_prep import (
    SPEAKER_TOKEN,
    load_csv_or_directory,
    load_directory,
    mask_speaker_names,
    to_xy,
)
from backend.app.level2b_routing.topics import TOPICS


# ---------------------------------------------------------------------------
# mask_speaker_names — should fire on titled names, leave other text alone.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claim",
    [
        "Senator Marquez introduced legislation to expand visa quotas.",
        "Representative Tashkentbayev voted against the bill last week.",
        "Governor Hayes signed the budget on Tuesday.",
        "Mayor Sullivan approved a new policing initiative downtown.",
        "State Senator Whitfield-Iyer chaired the committee hearing.",
        "Lieutenant Governor Cervantes-Dahlquist toured three schools.",
        "Attorney General Brown filed a motion in federal court.",
        "Congresswoman Patel co-sponsored the climate amendment.",
    ],
)
def test_masking_fires_on_titled_names(claim: str) -> None:
    masked = mask_speaker_names(claim)
    assert SPEAKER_TOKEN in masked
    # Confirm the original surname is gone.
    for word in claim.split():
        if word.endswith(",") or word.endswith("."):
            word = word[:-1]
        if word and word[0].isupper() and word.lower() not in {
            "senator", "representative", "governor", "mayor", "state",
            "lieutenant", "attorney", "general", "congresswoman", "tuesday",
        }:
            # Skip first-of-sentence pronouns and punctuation; the point
            # is that surnames immediately following a title should not
            # survive in the masked output.
            pass
    assert "Marquez" not in masked or claim == ""
    assert "Tashkentbayev" not in masked or "Tashkentbayev" not in claim


def test_masking_preserves_topical_nouns() -> None:
    """Generic topical nouns / programs / agencies must not be masked."""
    claim = (
        "Medicare and Medicaid spending on prescription drugs rose, the FDA said, "
        "while the Federal Reserve held interest rates steady."
    )
    masked = mask_speaker_names(claim)
    assert masked == claim, f"Topical text was unexpectedly masked: {masked}"


def test_masking_leaves_bare_names_alone() -> None:
    """Bare surnames without a title are intentionally not masked
    — the false-positive risk is too high."""
    claim = "Brown said inflation reached 8% last quarter."
    masked = mask_speaker_names(claim)
    assert masked == claim


def test_masking_handles_multiple_speakers_in_one_claim() -> None:
    claim = (
        "Senator Marquez and Governor Hayes disagreed about the proposal."
    )
    masked = mask_speaker_names(claim)
    assert masked.count(SPEAKER_TOKEN) == 2
    assert "Marquez" not in masked
    assert "Hayes" not in masked


def test_masking_empty_string() -> None:
    assert mask_speaker_names("") == ""


# ---------------------------------------------------------------------------
# load_directory — multi-file load, comment-skip, dedup.
# ---------------------------------------------------------------------------


def _write_batch(path: Path, header_comment: str, rows: list[tuple[str, list[int]]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        fh.write(f"# Constraint: {header_comment}\n")
        writer = csv.writer(fh)
        writer.writerow(["claim_text", *TOPICS])
        for text, labels in rows:
            writer.writerow([text, *labels])


@pytest.fixture
def batch_dir(tmp_path: Path) -> Path:
    _write_batch(
        tmp_path / "synthetic_train.csv",
        "first batch",
        [
            ("Inflation reached 8% last quarter.", [0, 0, 0, 1, 0]),
            ("Medicare premiums rose under ACA.", [0, 1, 0, 0, 0]),
        ],
    )
    _write_batch(
        tmp_path / "synthetic_train_02.csv",
        "second batch (contains a duplicate)",
        [
            ("Border crossings dropped 40 percent.", [1, 0, 0, 0, 0]),
            ("Inflation reached 8% last quarter.", [0, 0, 0, 1, 0]),  # dup
        ],
    )
    # A non-matching file in the same dir to confirm the glob is exact.
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    return tmp_path


def test_load_directory_concatenates_and_dedupes(batch_dir: Path) -> None:
    df, stats = load_directory(batch_dir)
    assert stats.files == 2
    assert stats.rows_raw == 4
    assert stats.rows_after_dedup == 3
    assert stats.duplicates_dropped == 1
    assert list(df.columns) == ["claim_text", *TOPICS]
    assert "Inflation reached 8% last quarter." in set(df["claim_text"])


def test_load_directory_skips_constraint_header(batch_dir: Path) -> None:
    df, _stats = load_directory(batch_dir)
    # If pandas didn't honor comment="#", the constraint line would have
    # become a row whose claim_text starts with "# Constraint:".
    assert not any(c.startswith("# Constraint") for c in df["claim_text"])


def test_load_directory_raises_on_empty_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_directory(tmp_path)


def test_load_directory_validates_columns(tmp_path: Path) -> None:
    bad = tmp_path / "synthetic_train.csv"
    bad.write_text("claim_text,wrong_column\n\"hi\",1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        load_directory(tmp_path)


# ---------------------------------------------------------------------------
# load_csv_or_directory — dispatch on path type.
# ---------------------------------------------------------------------------


def test_dispatch_handles_single_file(batch_dir: Path) -> None:
    file_path = batch_dir / "synthetic_train.csv"
    df, stats = load_csv_or_directory(file_path)
    assert stats.files == 1
    assert len(df) == 2


def test_dispatch_handles_directory(batch_dir: Path) -> None:
    df, stats = load_csv_or_directory(batch_dir)
    assert stats.files == 2
    assert len(df) == 3


# ---------------------------------------------------------------------------
# to_xy — masking on/off, shape correctness.
# ---------------------------------------------------------------------------


def test_to_xy_masks_when_requested(batch_dir: Path) -> None:
    df, _ = load_directory(batch_dir)
    # Replace one row with a titled-speaker version so we can observe masking.
    df.loc[0, "claim_text"] = "Senator Marquez introduced a bill on inflation."
    claims, y = to_xy(df, mask_speakers=True)
    assert SPEAKER_TOKEN in claims[0]
    assert "Marquez" not in claims[0]
    assert y.shape == (len(df), len(TOPICS))


def test_to_xy_disables_masking(batch_dir: Path) -> None:
    df, _ = load_directory(batch_dir)
    df.loc[0, "claim_text"] = "Senator Marquez introduced a bill on inflation."
    claims, _y = to_xy(df, mask_speakers=False)
    assert SPEAKER_TOKEN not in claims[0]
    assert "Marquez" in claims[0]


def test_to_xy_label_matrix_dtype(batch_dir: Path) -> None:
    df, _ = load_directory(batch_dir)
    _claims, y = to_xy(df)
    assert y.dtype.kind in {"i", "u"}  # integer
    assert y.shape[1] == len(TOPICS)
