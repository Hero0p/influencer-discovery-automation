"""Small client for the official YouTube Data API v3.

Every number in the dataset (subscribers, views, likes, comments) comes from here.
Docs: https://developers.google.com/youtube/v3/docs
"""

import time

import requests

API_URL = "https://www.googleapis.com/youtube/v3"


class QuotaExceeded(Exception):
    """The daily YouTube API quota is used up. It resets at midnight Pacific time."""


def call_api(endpoint, api_key, **params):
    """GET one endpoint and return its JSON. Temporary failures are retried twice."""
    # The key travels in a header (not the URL) so it can never show up in an error message.
    headers = {"X-Goog-Api-Key": api_key}
    for attempt in range(3):
        try:
            response = requests.get(f"{API_URL}/{endpoint}", params=params, headers=headers, timeout=30)
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
            continue

        if response.status_code == 200:
            return response.json()

        error = response.json().get("error", {}) if response.content else {}
        reason = (error.get("errors") or [{}])[0].get("reason", "")
        if response.status_code == 403 and reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
            raise QuotaExceeded(reason)
        if response.status_code == 404:
            return {"items": []}  # e.g. a channel whose uploads playlist is empty or private
        if response.status_code >= 500 and attempt < 2:
            time.sleep(2 * (attempt + 1))
            continue
        raise RuntimeError(f"YouTube API error {response.status_code}: {error.get('message', reason)}")


def search_videos(api_key, query, published_after, language="", region="", duration=""):
    """One search call: up to 50 recent videos matching the query, with the channel that posted each."""
    params = {
        "part": "snippet",
        "type": "video",
        "q": query,
        "order": "relevance",
        "maxResults": 50,
        "publishedAfter": published_after,
    }
    if language:
        params["relevanceLanguage"] = language
    if region:
        params["regionCode"] = region
    if duration:
        params["videoDuration"] = duration

    data = call_api("search", api_key, **params)
    return [
        {"channel_id": item["snippet"]["channelId"], "video_title": item["snippet"]["title"]}
        for item in data.get("items", [])
    ]


def get_channels(api_key, channel_ids):
    """Details for up to 50 channels in one call."""
    data = call_api(
        "channels",
        api_key,
        part="snippet,statistics,contentDetails,topicDetails,brandingSettings",
        id=",".join(channel_ids),
        maxResults=50,
    )
    return [parse_channel(item) for item in data.get("items", [])]


def get_recent_videos(api_key, uploads_playlist, count=10):
    """The channel's latest uploads with their public statistics, newest first."""
    playlist = call_api("playlistItems", api_key, part="contentDetails", playlistId=uploads_playlist, maxResults=count)
    video_ids = [item["contentDetails"]["videoId"] for item in playlist.get("items", [])]
    if not video_ids:
        return []
    data = call_api("videos", api_key, part="snippet,statistics", id=",".join(video_ids))
    videos = [parse_video(item) for item in data.get("items", [])]
    return sorted(videos, key=lambda video: video["published_at"], reverse=True)


def parse_channel(item):
    """Turn one channels.list item into the columns stored in the database."""
    snippet = item.get("snippet", {})
    statistics = item.get("statistics", {})
    handle = snippet.get("customUrl")  # looks like "@channelname"
    topic_urls = item.get("topicDetails", {}).get("topicCategories", [])

    return {
        "channel_id": item["id"],
        "name": snippet.get("title", ""),
        "profile_url": f"https://www.youtube.com/{handle}" if handle else f"https://www.youtube.com/channel/{item['id']}",
        "description": snippet.get("description", ""),
        "country": snippet.get("country"),
        "channel_keywords": item.get("brandingSettings", {}).get("channel", {}).get("keywords", ""),
        # Topic labels arrive as Wikipedia URLs, e.g. https://en.wikipedia.org/wiki/Lifestyle_(sociology)
        "topics": [url.rsplit("/", 1)[-1].replace("_", " ") for url in topic_urls],
        "uploads_playlist": item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"),
        # YouTube rounds public subscriber counts to three significant figures.
        "followers": None if statistics.get("hiddenSubscriberCount") else to_int(statistics.get("subscriberCount")),
        "total_videos": to_int(statistics.get("videoCount")),
    }


def parse_video(item):
    """Turn one videos.list item into a small dictionary. Hidden numbers stay None."""
    snippet = item.get("snippet", {})
    statistics = item.get("statistics", {})
    return {
        "title": snippet.get("title", ""),
        "published_at": snippet.get("publishedAt", ""),
        "description": snippet.get("description", ""),
        "views": to_int(statistics.get("viewCount")),
        "likes": to_int(statistics.get("likeCount")),        # missing when the creator hides likes
        "comments": to_int(statistics.get("commentCount")),  # missing when comments are turned off
    }


def to_int(value):
    return int(value) if value is not None else None
