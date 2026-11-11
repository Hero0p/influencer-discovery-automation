"""Stage 1 (discover) and stage 2 (measure): find channels and collect their real numbers."""

from datetime import datetime, timedelta, timezone

from outreach import db, filtering, metrics, youtube


def discover(settings, conn):
    """Search YouTube for recent videos in the niche and store the channels that posted them."""
    search = settings.niche["discovery"]
    since = datetime.now(timezone.utc) - timedelta(days=search["published_within_days"])
    published_after = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    for query in search["queries"]:
        if db.search_done(conn, query):
            continue  # already searched on an earlier run
        try:
            videos = youtube.search_videos(
                settings.youtube_api_key,
                query,
                published_after,
                language=search.get("relevance_language", ""),
                region=search.get("region_code", ""),
                duration=search.get("video_duration", ""),
            )
        except youtube.QuotaExceeded:
            print("  YouTube search quota is used up for today. Run 'discover' again tomorrow for the remaining queries.")
            break
        for video in videos:
            db.add_creator(conn, video["channel_id"], found_by=query)
        db.log_search(conn, query, len(videos))
        print(f"  searched '{query}': {len(videos)} videos")

    fetch_channel_details(settings, conn)


def fetch_channel_details(settings, conn):
    """Fill in name, subscribers, description and so on for channels that are still bare IDs."""
    new_ids = [creator["channel_id"] for creator in db.get_creators(conn, "name IS NULL")]
    for start in range(0, len(new_ids), 50):
        batch = new_ids[start:start + 50]
        channels = youtube.get_channels(settings.youtube_api_key, batch)
        for channel in channels:
            db.save_creator(conn, channel.pop("channel_id"), **channel)
    # Channels the API did not return (deleted or suspended) are dropped.
    for creator in db.get_creators(conn, "name IS NULL"):
        db.delete_creator(conn, creator["channel_id"])

    total = len(db.get_creators(conn))
    print(f"  discover: {total} channels stored ({len(new_ids)} new)")


def measure(settings, conn, limit=None):
    """Fetch the latest videos of every channel inside the follower range and compute engagement.

    Channels outside the range are skipped: they fail the filter anyway, and
    skipping them saves two API calls per channel.
    """
    rules = settings.niche["filters"]
    todo = [
        creator
        for creator in db.get_creators(conn, "name IS NOT NULL AND measured_at IS NULL")
        if filtering.check_followers(creator, rules)[0]
    ][:limit]

    for done, creator in enumerate(todo, start=1):
        videos = youtube.get_recent_videos(settings.youtube_api_key, creator["uploads_playlist"])
        db.save_creator(
            conn,
            creator["channel_id"],
            recent_videos=videos,
            measured_at=db.now(),
            **metrics.summarise(videos),
        )
        if done % 25 == 0:
            print(f"  measured {done}/{len(todo)} channels")
    print(f"  measure: {len(todo)} channels measured")
