"""Engagement maths. Pure functions: real video statistics in, numbers out."""

from datetime import datetime, timezone
from statistics import median

# Fewer measurable videos than this and the engagement rate is reported as unavailable.
MIN_VIDEOS_FOR_ENGAGEMENT = 3


def video_engagement(video):
    """(likes + comments) / views for one video, as a percentage.

    Returns None when the video cannot be measured: no views yet, or likes hidden.
    Comments that are turned off count as zero.
    """
    if not video["views"] or video["likes"] is None:
        return None
    return 100 * (video["likes"] + (video["comments"] or 0)) / video["views"]


def summarise(videos):
    """Channel-level numbers computed from its latest videos."""
    rates = [rate for rate in map(video_engagement, videos) if rate is not None]
    views = [video["views"] for video in videos if video["views"]]
    dates = [video["published_at"] for video in videos if video["published_at"]]

    return {
        # The median is used so one unusual video cannot distort the result.
        "engagement_rate": round(median(rates), 2) if len(rates) >= MIN_VIDEOS_FOR_ENGAGEMENT else None,
        "avg_views": round(sum(views) / len(views)) if views else None,
        "last_upload_at": max(dates) if dates else None,
    }


def days_since(iso_time):
    """Whole days between an ISO timestamp such as 2026-11-01T10:00:00Z and now."""
    then = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - then).days
