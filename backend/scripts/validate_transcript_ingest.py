#!/usr/bin/env python3
"""Validate that the backend accepts browser-extracted transcripts.

Run with the FastAPI server running locally:
    python backend/scripts/validate_transcript_ingest.py
"""

from __future__ import annotations

import argparse
import sys

import httpx


SAMPLE_TRANSCRIPT = [
    {
        "timestamp": 0.0,
        "text": "This is a backend transcript ingest smoke test.",
    },
    {
        "timestamp": 12.5,
        "text": "Inflation was three percent in this sample caption.",
    },
    {
        "timestamp": 70.0,
        "text": "This later line forces the chunker to create another chunk.",
    },
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="FastAPI server base URL.",
    )
    parser.add_argument(
        "--video-url",
        default="https://www.youtube.com/watch?v=transcript-smoke-test",
        help="Video URL to associate with the uploaded transcript.",
    )
    args = parser.parse_args()

    api_base = args.base_url.rstrip("/") + "/api"

    with httpx.Client(timeout=10.0) as client:
        upload = client.post(
            f"{api_base}/transcripts",
            json={"url": args.video_url, "transcript": SAMPLE_TRANSCRIPT},
        )
        upload.raise_for_status()
        upload_payload = upload.json()

        transcript_id = upload_payload["transcriptId"]
        inspect = client.get(f"{api_base}/transcripts/{transcript_id}")
        inspect.raise_for_status()
        inspect_payload = inspect.json()

    expected_preview = SAMPLE_TRANSCRIPT[0]["text"]
    if expected_preview not in inspect_payload.get("preview", ""):
        print("Transcript upload succeeded, but preview did not match.", file=sys.stderr)
        print(inspect_payload, file=sys.stderr)
        return 1

    if upload_payload.get("chunkCount", 0) < 1:
        print("Backend reported zero transcript chunks.", file=sys.stderr)
        print(upload_payload, file=sys.stderr)
        return 1

    print("Transcript ingest validated.")
    print(f"transcriptId: {transcript_id}")
    print(f"chunkCount: {upload_payload['chunkCount']}")
    print(f"totalCharacters: {upload_payload['totalCharacters']}")
    print(f"preview: {inspect_payload['preview']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
