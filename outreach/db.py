"""SQLite storage: one row per YouTube channel, filled in stage by stage.

Because every stage saves its result here, the pipeline can stop at any point
(quota used up, network error) and continue later without repeating work.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from outreach.config import DB_PATH

# Column name -> SQLite type, grouped by the stage that fills it in.
# A NULL value always means "not collected (yet)". Nothing is filled with guesses.
COLUMNS = {
    # discover
    "found_by": "TEXT",            # the search query that surfaced the channel
    "discovered_at": "TEXT",
    "name": "TEXT",
    "profile_url": "TEXT",
    "description": "TEXT",
    "country": "TEXT",
    "channel_keywords": "TEXT",
    "topics": "TEXT",              # JSON list of YouTube topic labels
    "uploads_playlist": "TEXT",
    "followers": "INTEGER",        # NULL when the channel hides its subscriber count
    "total_videos": "INTEGER",
    # measure
    "recent_videos": "TEXT",       # JSON list of the latest videos with their statistics
    "engagement_rate": "REAL",     # percent; NULL when it cannot be measured
    "avg_views": "INTEGER",
    "last_upload_at": "TEXT",
    "measured_at": "TEXT",
    # filter
    "status": "TEXT",              # PASS, FAIL or PENDING
    "reasons": "TEXT",             # JSON list, one line per check
    # classify
    "niche": "TEXT",
    "sub_niche": "TEXT",
    "niche_confidence": "REAL",
    "niche_reason": "TEXT",
    "content_themes": "TEXT",      # JSON list
    "tone": "TEXT",
    "brand_fit": "INTEGER",
    "brand_fit_reason": "TEXT",
    "classified_by": "TEXT",       # the Gemini model that made the judgement
    "classified_at": "TEXT",
    # enrich
    "email": "TEXT",
    "email_source": "TEXT",
    "website": "TEXT",
    "instagram": "TEXT",
    "instagram_followers": "INTEGER",
    "instagram_engagement": "REAL",
    "instagram_checked_at": "TEXT",
    "tiktok": "TEXT",
    "enriched_at": "TEXT",
    # messages
    "collab_angle": "TEXT",
    "email_subject": "TEXT",
    "email_body": "TEXT",
    "dm_text": "TEXT",
    "message_status": "TEXT",      # "OK" or the reason the message was rejected
    "written_by": "TEXT",          # the Gemini model that wrote the messages
    "messages_at": "TEXT",
    # queue / sync (the sending layer)
    "queued_at": "TEXT",
    "send_to": "TEXT",
    "review_status": "TEXT",
    "sent": "TEXT",
    "sent_at": "TEXT",
    "outreach_status": "TEXT",
    "dm_status": "TEXT",
    "dm_sent_at": "TEXT",
}

JSON_COLUMNS = {"topics", "recent_videos", "reasons", "content_themes"}


def now():
    """Current UTC time as text, for example 2026-11-10T14:03:22Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path=DB_PATH):
    """Open the database and create the tables (or any new columns) if needed."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    column_sql = ", ".join(f"{name} {kind}" for name, kind in COLUMNS.items())
    conn.execute(f"CREATE TABLE IF NOT EXISTS creators (channel_id TEXT PRIMARY KEY, {column_sql})")
    conn.execute("CREATE TABLE IF NOT EXISTS searches (query TEXT PRIMARY KEY, results INTEGER, searched_at TEXT)")

    existing = {row["name"] for row in conn.execute("PRAGMA table_info(creators)")}
    for name, kind in COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE creators ADD COLUMN {name} {kind}")
    conn.commit()
    return conn


def add_creator(conn, channel_id, found_by):
    """Store a newly discovered channel. A channel that is already stored is left untouched."""
    conn.execute(
        "INSERT OR IGNORE INTO creators (channel_id, found_by, discovered_at) VALUES (?, ?, ?)",
        (channel_id, found_by, now()),
    )
    conn.commit()


def save_creator(conn, channel_id, **fields):
    """Update the given columns of one creator."""
    assignments = ", ".join(f"{name} = ?" for name in fields)
    values = [
        json.dumps(value) if name in JSON_COLUMNS and value is not None else value
        for name, value in fields.items()
    ]
    conn.execute(f"UPDATE creators SET {assignments} WHERE channel_id = ?", [*values, channel_id])
    conn.commit()


def get_creators(conn, where="1=1", params=()):
    """Return creators as dictionaries, largest first. JSON columns come back as lists."""
    rows = conn.execute(f"SELECT * FROM creators WHERE {where} ORDER BY followers DESC, channel_id", params)
    creators = []
    for row in rows:
        creator = dict(row)
        for name in JSON_COLUMNS:
            creator[name] = json.loads(creator[name]) if creator[name] else []
        creators.append(creator)
    return creators


def delete_creator(conn, channel_id):
    conn.execute("DELETE FROM creators WHERE channel_id = ?", (channel_id,))
    conn.commit()


def search_done(conn, query):
    """True when this search query has already been run (so it is not paid for twice)."""
    return conn.execute("SELECT 1 FROM searches WHERE query = ?", (query,)).fetchone() is not None


def log_search(conn, query, results):
    conn.execute("INSERT OR REPLACE INTO searches VALUES (?, ?, ?)", (query, results, now()))
    conn.commit()
