from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


DB_PATH = Path(__file__).resolve().parent / "data" / "clip_fact_checks.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_video_id(video_url: str) -> str:
    parsed = urlparse(video_url)
    query_v = parse_qs(parsed.query).get("v", [""])[0]
    if query_v:
        return query_v

    path_parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc.endswith("youtu.be") and path_parts:
        return path_parts[0]
    if "embed" in path_parts:
        embed_index = path_parts.index("embed")
        if embed_index + 1 < len(path_parts):
            return path_parts[embed_index + 1]
    return ""


def get_embed_url(video_url: str) -> str:
    video_id = extract_video_id(video_url)
    return f"https://www.youtube.com/embed/{video_id}" if video_id else ""


@dataclass
class StoredClip:
    clip_id: int
    video_url: str
    video_id: str
    start_time: float
    end_time: float
    claim: str
    verdict: str
    explanation: str
    sources: list[dict[str, str]]
    session_id: str
    published_at: str
    upvotes: int
    downvotes: int
    total_votes: int
    score: int
    user_vote: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.clip_id,
            "videoUrl": self.video_url,
            "videoId": self.video_id,
            "embedUrl": get_embed_url(self.video_url),
            "startTime": self.start_time,
            "endTime": self.end_time,
            "claim": self.claim,
            "verdict": self.verdict,
            "explanation": self.explanation,
            "sources": self.sources,
            "sessionId": self.session_id,
            "publishedAt": self.published_at,
            "upvotes": self.upvotes,
            "downvotes": self.downvotes,
            "totalVotes": self.total_votes,
            "score": self.score,
            "userVote": self.user_vote,
        }


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS published_clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_url TEXT NOT NULL,
                video_id TEXT NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL,
                claim TEXT NOT NULL,
                verdict TEXT NOT NULL,
                explanation TEXT NOT NULL,
                sources_json TEXT NOT NULL,
                session_id TEXT NOT NULL,
                published_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_published_clips_video_id
            ON published_clips (video_id);

            CREATE INDEX IF NOT EXISTS idx_published_clips_video_url
            ON published_clips (video_url);

            CREATE TABLE IF NOT EXISTS clip_votes (
                clip_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                vote INTEGER NOT NULL CHECK (vote IN (-1, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (clip_id, session_id),
                FOREIGN KEY (clip_id) REFERENCES published_clips(id) ON DELETE CASCADE
            );
            """
        )


def publish_clip(
    *,
    video_url: str,
    start_time: float,
    end_time: float,
    claim: str,
    verdict: str,
    explanation: str,
    sources: list[dict[str, str]],
    session_id: str,
) -> dict[str, Any]:
    video_id = extract_video_id(video_url)
    now = utc_now()
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO published_clips (
                video_url,
                video_id,
                start_time,
                end_time,
                claim,
                verdict,
                explanation,
                sources_json,
                session_id,
                published_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_url,
                video_id,
                start_time,
                end_time,
                claim,
                verdict,
                explanation,
                json.dumps(sources),
                session_id,
                now,
            ),
        )
        clip_id = int(cursor.lastrowid)
    return get_clip(clip_id, session_id=session_id)


def set_vote(clip_id: int, session_id: str, vote: int) -> dict[str, Any]:
    with _connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM published_clips WHERE id = ?",
            (clip_id,),
        ).fetchone()
        if exists is None:
            raise KeyError(f"clip {clip_id} not found")

    now = utc_now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO clip_votes (clip_id, session_id, vote, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(clip_id, session_id)
            DO UPDATE SET vote = excluded.vote, updated_at = excluded.updated_at
            """,
            (clip_id, session_id, vote, now, now),
        )
    return get_clip(clip_id, session_id=session_id)


def get_clip(clip_id: int, session_id: str | None = None) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                pc.*,
                COALESCE(SUM(CASE WHEN cv.vote = 1 THEN 1 ELSE 0 END), 0) AS upvotes,
                COALESCE(SUM(CASE WHEN cv.vote = -1 THEN 1 ELSE 0 END), 0) AS downvotes,
                COALESCE(SUM(ABS(cv.vote)), 0) AS total_votes,
                COALESCE(SUM(cv.vote), 0) AS score,
                COALESCE((
                    SELECT vote
                    FROM clip_votes self_vote
                    WHERE self_vote.clip_id = pc.id AND self_vote.session_id = ?
                ), 0) AS user_vote
            FROM published_clips pc
            LEFT JOIN clip_votes cv ON cv.clip_id = pc.id
            WHERE pc.id = ?
            GROUP BY pc.id
            """,
            (session_id or "", clip_id),
        ).fetchone()
    if row is None:
        raise KeyError(f"clip {clip_id} not found")
    return _row_to_clip(row).to_dict()


def list_clips(video_url: str, session_id: str | None = None) -> dict[str, Any]:
    video_id = extract_video_id(video_url)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                pc.*,
                COALESCE(SUM(CASE WHEN cv.vote = 1 THEN 1 ELSE 0 END), 0) AS upvotes,
                COALESCE(SUM(CASE WHEN cv.vote = -1 THEN 1 ELSE 0 END), 0) AS downvotes,
                COALESCE(SUM(ABS(cv.vote)), 0) AS total_votes,
                COALESCE(SUM(cv.vote), 0) AS score,
                COALESCE((
                    SELECT vote
                    FROM clip_votes self_vote
                    WHERE self_vote.clip_id = pc.id AND self_vote.session_id = ?
                ), 0) AS user_vote
            FROM published_clips pc
            LEFT JOIN clip_votes cv ON cv.clip_id = pc.id
            WHERE pc.video_id = ?
            GROUP BY pc.id
            ORDER BY total_votes DESC, score DESC, pc.published_at DESC
            """,
            (session_id or "", video_id),
        ).fetchall()
    return {
        "videoUrl": video_url,
        "videoId": video_id,
        "embedUrl": get_embed_url(video_url),
        "clips": [_row_to_clip(row).to_dict() for row in rows],
    }


def _row_to_clip(row: sqlite3.Row) -> StoredClip:
    return StoredClip(
        clip_id=int(row["id"]),
        video_url=row["video_url"],
        video_id=row["video_id"],
        start_time=float(row["start_time"]),
        end_time=float(row["end_time"]),
        claim=row["claim"],
        verdict=row["verdict"],
        explanation=row["explanation"],
        sources=json.loads(row["sources_json"]),
        session_id=row["session_id"],
        published_at=row["published_at"],
        upvotes=int(row["upvotes"]),
        downvotes=int(row["downvotes"]),
        total_votes=int(row["total_votes"]),
        score=int(row["score"]),
        user_vote=int(row["user_vote"]),
    )
