"""Stage 5 (enrich): contact email, website and social handles for shortlisted creators.

Rule for every field: it is copied from something the creator published, and the
source is recorded. If nothing is found the field stays empty and the outputs
show "Not Found". Nothing is guessed or constructed.
"""

import re
from collections import Counter
from datetime import timedelta
from difflib import SequenceMatcher
from statistics import median
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from apify_client import ApifyClient
from bs4 import BeautifulSoup
from email_validator import EmailNotValidError, validate_email

from outreach import db

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_PATTERN = re.compile(r"https?://[^\s<>\"')\]]+")
INSTAGRAM_PATTERNS = [
    re.compile(r"instagram\.com/([A-Za-z0-9._]{2,30})", re.IGNORECASE),
    re.compile(r"\b(?:instagram|insta|ig)\s*[:\-|]?\s*@([A-Za-z0-9._]{2,30})", re.IGNORECASE),
]
TIKTOK_PATTERN = re.compile(r"tiktok\.com/@([A-Za-z0-9._]{2,24})", re.IGNORECASE)

# instagram.com/<word> paths that are not profiles
NOT_INSTAGRAM_PROFILES = {"p", "reel", "reels", "explore", "stories", "tv", "accounts"}
# Addresses that show up in page code or belong to a platform, not to the creator
JUNK_EMAIL_PARTS = ("example.", "sentry", "wixpress", "linktr.ee", "beacons.ai", "squarespace", "godaddy", "youtube.com")
JUNK_EMAIL_ENDINGS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
# Links in a channel description that are not the creator's own website
NOT_A_WEBSITE = (
    "youtube.com", "youtu.be", "instagram.com", "tiktok.com", "facebook.com", "twitter.com", "//x.com",
    "threads.net", "pinterest.", "snapchat.com", "twitch.tv", "discord", "spotify.com", "apple.com",
    "patreon.com", "paypal", "ko-fi.com", "buymeacoffee", "amazon.", "amzn.", "bit.ly", "goo.gl",
    "t.me", "whatsapp", "linkedin.com", "ltk", "liketoknow.it", "rstyle.me", "shopmy.us", "geni.us",
)
USER_AGENT = "influencer-outreach-research-bot/1.0"


# ---------- reading text the creator wrote ----------

def find_emails(text):
    """All valid email addresses written in the text, in order, without duplicates."""
    emails = []
    for match in EMAIL_PATTERN.findall(text or ""):
        email = match.strip(".").lower()
        if email.endswith(JUNK_EMAIL_ENDINGS) or any(part in email for part in JUNK_EMAIL_PARTS):
            continue
        try:
            validate_email(email, check_deliverability=False)
        except EmailNotValidError:
            continue
        if email not in emails:
            emails.append(email)
    return emails


def find_instagram(text):
    """Instagram handles mentioned in the text (profile links or 'Instagram: @name')."""
    handles = []
    for pattern in INSTAGRAM_PATTERNS:
        for handle in pattern.findall(text or ""):
            handle = handle.strip(".").lower()
            if handle and handle not in NOT_INSTAGRAM_PROFILES and handle not in handles:
                handles.append(handle)
    return handles


def find_tiktok(text):
    return [handle.strip(".").lower() for handle in TIKTOK_PATTERN.findall(text or "")]


def find_website(text):
    """The first link in the text that is not a social network or shopping link."""
    for url in URL_PATTERN.findall(text or ""):
        url = url.rstrip(".,;!")
        if not any(part in url.lower() for part in NOT_A_WEBSITE):
            return url
    return None


def repeated_in_videos(creator, finder):
    """Values found in at least two recent video descriptions, most frequent first, as (value, times).

    One-off emails and handles in a single video usually belong to a sponsor or
    a guest, so a value only counts when the creator repeats it.
    """
    counts = Counter()
    for video in creator["recent_videos"]:
        counts.update(dict.fromkeys(finder(video["description"])).keys())  # each value once per video
    return [(value, times) for value, times in counts.most_common() if times >= 2]


def shared_letters(text, creator):
    """Length of the longest run of letters the text shares with the channel's name or YouTube handle.

    Used to tell the creator's own accounts from the musicians, shops and
    friends that video descriptions also credit: 'cozy.home.diary' shares 13
    letters with the channel 'Cozy Home Diary', a credited 'some.musician' none.
    """
    def simplify(value):
        return re.sub(r"[^a-z0-9]", "", value.lower())

    text = simplify(text)
    longest = 0
    for own_name in (creator["name"], creator["profile_url"].rsplit("/", 1)[-1]):
        own_name = simplify(own_name)
        match = SequenceMatcher(None, text, own_name, autojunk=False).find_longest_match(
            0, len(text), 0, len(own_name)
        )
        longest = max(longest, match.size)
    return longest


def own_handle(creator, finder):
    """The creator's handle on another platform, or None.

    A handle in the channel description is taken as theirs. A handle that only
    appears in video descriptions must be repeated and share at least 4 letters
    in a row with the channel name; the closest match wins.
    """
    in_description = finder(creator["description"])
    if in_description:
        return in_description[0]
    candidates = [
        handle for handle, _ in repeated_in_videos(creator, finder) if shared_letters(handle, creator) >= 4
    ]
    return max(candidates, key=lambda handle: shared_letters(handle, creator), default=None)


# ---------- the creator's own website ----------

def fetch_page(url):
    """Download a page as text. Returns None if robots.txt forbids it or anything goes wrong."""
    try:
        robots_url = urljoin(url, "/robots.txt")
        robots = requests.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=10)
        if robots.status_code == 200:
            parser = RobotFileParser()
            parser.parse(robots.text.splitlines())
            if not parser.can_fetch(USER_AGENT, url):
                return None
        page = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        if page.status_code == 200 and "html" in page.headers.get("content-type", ""):
            return page.text[:500_000]
    except requests.RequestException:
        pass
    return None


def email_from_website(url):
    """Look for an email on the creator's website: the linked page first, then /contact."""
    for page_url in (url, urljoin(url, "/contact")):
        html = fetch_page(page_url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        mailto_links = " ".join(link["href"] for link in soup.select('a[href^="mailto:"]'))
        emails = find_emails(mailto_links) or find_emails(soup.get_text(" "))
        if emails:
            return emails[0], f"Creator website ({urlparse(page_url).netloc})"
    return None, None


# ---------- Instagram numbers through Apify ----------

def fetch_instagram_profiles(token, handles):
    """One Apify run for all handles. Returns {handle: public profile data}."""
    client = ApifyClient(token)
    run = client.actor("apify/instagram-profile-scraper").call(
        run_input={"usernames": handles},
        max_items=len(handles),  # also caps the cost: the actor is billed per result
        run_timeout=timedelta(minutes=15),
        logger=None,  # do not copy the actor's own log to the console
    )
    if run is None or run.status != "SUCCEEDED":
        return {}
    profiles = {}
    for item in client.dataset(run.default_dataset_id).iterate_items():
        if item.get("username") and item.get("followersCount") is not None:
            profiles[item["username"].lower()] = item
    return profiles


def instagram_engagement(profile):
    """Median (likes + comments) / followers over the latest posts, as a percentage, or None."""
    followers = profile.get("followersCount") or 0
    rates = []
    for post in profile.get("latestPosts") or []:
        likes = post.get("likesCount")
        if followers and likes is not None and likes >= 0:  # -1 means the likes are hidden
            rates.append(100 * (likes + (post.get("commentsCount") or 0)) / followers)
    return round(median(rates), 2) if len(rates) >= 3 else None


# ---------- the stage itself ----------

def enrich(settings, conn, limit=None):
    """Enrich every creator that passed the filters."""
    todo = db.get_creators(conn, "status = 'PASS' AND enriched_at IS NULL")[:limit]
    for creator in todo:
        db.save_creator(conn, creator["channel_id"], enriched_at=db.now(), **enrich_from_text(creator))
    print(f"  enrich: {len(todo)} creators enriched from their channel text and websites")

    if settings.apify_token:
        enrich_from_instagram(settings, conn)
    else:
        print("  enrich: APIFY_TOKEN is empty, Instagram numbers are skipped")

    with_email = len(db.get_creators(conn, "status = 'PASS' AND email IS NOT NULL"))
    total = len(db.get_creators(conn, "status = 'PASS'"))
    print(f"  enrich: {with_email} of {total} shortlisted creators have a contact email")


def enrich_from_text(creator):
    """Email, website and social handles found in the channel and video descriptions."""
    description = creator["description"]

    # A link only counts as the creator's website if its address resembles the channel name.
    # Otherwise it is most likely a sponsor or affiliate link.
    website = find_website(description)
    if website and shared_letters(website.split("//", 1)[-1], creator) < 6:
        website = None

    emails = find_emails(description)
    repeated_emails = repeated_in_videos(creator, find_emails)
    email, source = None, None
    if emails:
        email, source = emails[0], "YouTube channel description"
    elif repeated_emails:
        email, times = repeated_emails[0]
        source = f"YouTube video descriptions (in {times} recent videos)"
    elif website:
        email, source = email_from_website(website)

    return {
        "email": email,
        "email_source": source,
        "website": website,
        "instagram": own_handle(creator, find_instagram),
        "tiktok": own_handle(creator, find_tiktok),
    }


def enrich_from_instagram(settings, conn):
    """Add Instagram followers and engagement, and use the bio as one more place to look for an email."""
    todo = db.get_creators(conn, "status = 'PASS' AND instagram IS NOT NULL AND instagram_checked_at IS NULL")
    if not todo:
        return
    try:
        profiles = fetch_instagram_profiles(settings.apify_token, [creator["instagram"] for creator in todo])
    except Exception as error:  # Apify problems must not stop the pipeline
        print(f"  enrich: Instagram lookup failed ({type(error).__name__}); Instagram numbers stay 'Not Available'")
        return

    for creator in todo:
        fields = {"instagram_checked_at": db.now()}
        profile = profiles.get(creator["instagram"])
        if profile:
            fields["instagram_followers"] = profile["followersCount"]
            fields["instagram_engagement"] = instagram_engagement(profile)
            bio_emails = find_emails(profile.get("biography"))
            if not creator["email"] and bio_emails:
                fields["email"] = bio_emails[0]
                fields["email_source"] = "Instagram bio"
        db.save_creator(conn, creator["channel_id"], **fields)
    print(f"  enrich: Instagram data found for {len(profiles)} of {len(todo)} handles")
