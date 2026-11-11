"""Made-up creators for the unit tests.

Everything in this file is synthetic test data. It is used only by pytest and
never reaches the database, the CSV files or the Google Sheet.
"""

from datetime import datetime, timedelta, timezone


def days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_video(title="A cozy day in my life", views=1000, likes=50, comments=10, description="", days=5):
    return {
        "title": title, "published_at": days_ago(days), "description": description,
        "views": views, "likes": likes, "comments": comments,
    }


def make_creator(**overrides):
    """A creator that passes every check, unless a field is overridden."""
    creator = {
        "channel_id": "UC_test_channel", "found_by": "day in my life vlog", "name": "Test Channel",
        "profile_url": "https://www.youtube.com/@testchannel",
        "description": "Slow living vlogs and home routines.", "country": "GB",
        "channel_keywords": "lifestyle vlog", "topics": ["Lifestyle (sociology)"],
        "followers": 25000, "total_videos": 80,
        "recent_videos": [make_video(), make_video(), make_video()],
        "engagement_rate": 6.0, "avg_views": 1000, "last_upload_at": days_ago(5), "measured_at": days_ago(0),
        "status": None, "reasons": [],
        "niche": "Lifestyle", "sub_niche": "slow living vlogs", "niche_confidence": 0.9,
        "niche_reason": "Titles are daily vlogs.", "content_themes": ["home routines", "slow living"],
        "tone": "calm and cozy", "brand_fit": 8, "brand_fit_reason": "Home content suits the brand.",
        "classified_by": "test-model", "classified_at": days_ago(0), "written_by": None,
        "email": None, "email_source": None, "website": None, "instagram": None,
        "instagram_followers": None, "instagram_engagement": None, "tiktok": None, "enriched_at": None,
        "collab_angle": None, "email_subject": None, "email_body": None, "dm_text": None,
        "message_status": None, "queued_at": None, "send_to": None, "review_status": None,
        "sent": None, "sent_at": None, "outreach_status": None, "dm_status": None, "dm_sent_at": None,
    }
    creator.update(overrides)
    return creator


NICHE = {
    "name": "Lifestyle",
    "keywords": ["lifestyle", "vlog", "routine", "slow living", "cozy", "home"],
    "filters": {
        "min_followers": 5000, "max_followers": 100000, "max_days_since_upload": 60,
        "min_recent_videos": 3, "min_engagement_rate": 2.0, "allowed_countries": [],
        "min_keyword_hits": 3, "min_niche_confidence": 0.6, "min_brand_fit": 6,
    },
}
