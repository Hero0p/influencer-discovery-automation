"""Filtering: every check returns (passed, explanation), so each PASS/FAIL comes with its reason."""

from outreach import db
from outreach.metrics import days_since


def check_followers(creator, rules):
    followers = creator["followers"]
    low, high = rules["min_followers"], rules["max_followers"]
    if followers is None:
        return False, "Followers: the channel hides its subscriber count"
    if low <= followers <= high:
        return True, f"Followers: {followers:,} is inside the {low:,}-{high:,} micro-influencer range"
    return False, f"Followers: {followers:,} is outside the {low:,}-{high:,} micro-influencer range"


def check_activity(creator, rules):
    videos = creator["recent_videos"]
    if len(videos) < rules["min_recent_videos"]:
        return False, f"Activity: only {len(videos)} public videos (minimum {rules['min_recent_videos']})"
    days = days_since(creator["last_upload_at"])
    if days > rules["max_days_since_upload"]:
        return False, f"Activity: last upload was {days} days ago (maximum {rules['max_days_since_upload']})"
    return True, f"Activity: last upload was {days} days ago"


def check_engagement(creator, rules):
    rate = creator["engagement_rate"]
    minimum = rules["min_engagement_rate"]
    if rate is None:
        return False, "Engagement: could not be measured (fewer than 3 recent videos with public like counts)"
    if rate >= minimum:
        return True, f"Engagement: {rate}% meets the {minimum}% minimum"
    return False, f"Engagement: {rate}% is below the {minimum}% minimum"


def check_country(creator, rules):
    allowed = rules.get("allowed_countries") or []
    country = creator["country"]
    if not allowed:
        return True, f"Geography: no country restriction (channel country: {country or 'not stated'})"
    if country in allowed:
        return True, f"Geography: {country} is an allowed country"
    return False, f"Geography: {country or 'country not stated'} is not in the allowed list {allowed}"


def check_keywords(creator, niche):
    """Content relevance: how many distinct niche keywords appear in the channel's own text."""
    titles = " ".join(video["title"] for video in creator["recent_videos"])
    topics = " ".join(creator["topics"])
    text = f"{creator['description']} {creator['channel_keywords']} {topics} {titles}".lower()

    found = [keyword for keyword in niche["keywords"] if keyword.lower() in text]
    minimum = niche["filters"]["min_keyword_hits"]
    if len(found) >= minimum:
        return True, f"Content relevance: {len(found)} niche keywords found ({', '.join(found[:5])})"
    return False, f"Content relevance: only {len(found)} niche keywords found (minimum {minimum})"


def check_niche(creator, niche):
    """Uses the AI classification saved by the classify stage."""
    target = niche["name"]
    minimum = niche["filters"]["min_niche_confidence"]
    confidence = creator["niche_confidence"] or 0
    label = f"{creator['niche']} / {creator['sub_niche']}, confidence {confidence:.2f}"
    if creator["niche"] != target:
        return False, f"Niche: classified as {label}, not {target}. {creator['niche_reason']}"
    if confidence < minimum:
        return False, f"Niche: classified as {label}, below the {minimum} confidence minimum"
    return True, f"Niche: classified as {label}. {creator['niche_reason']}"


def check_brand_fit(creator, rules):
    score = creator["brand_fit"] or 0
    minimum = rules["min_brand_fit"]
    verdict = "meets" if score >= minimum else "is below"
    return score >= minimum, f"Brand fit: {score}/10 {verdict} the {minimum}/10 minimum. {creator['brand_fit_reason']}"


def decide(creator, niche):
    """Run every check there is data for. Returns (status, reasons).

    The cheap checks run first. A creator who fails the follower check is never
    measured, and one who fails a rule check is never sent to the AI model.
    """
    rules = niche["filters"]
    results = [check_followers(creator, rules)]
    notes = []

    if not results[0][0]:
        notes.append("INFO | Engagement, activity and niche were not evaluated because the follower check failed first")
    elif creator["measured_at"]:
        results += [
            check_activity(creator, rules),
            check_engagement(creator, rules),
            check_country(creator, rules),
            check_keywords(creator, niche),
        ]
        if all(passed for passed, _ in results) and creator["classified_at"]:
            results += [check_niche(creator, niche), check_brand_fit(creator, rules)]

    reasons = [f"{'PASS' if passed else 'FAIL'} | {text}" for passed, text in results] + notes
    if not all(passed for passed, _ in results):
        return "FAIL", reasons
    if creator["classified_at"]:
        return "PASS", reasons
    return "PENDING", reasons  # still waiting for the measure or classify stage


def apply_filters(settings, conn):
    """Recalculate the status of every creator. Cheap, so it simply redoes all of them."""
    counts = {"PASS": 0, "FAIL": 0, "PENDING": 0}
    for creator in db.get_creators(conn, "name IS NOT NULL"):
        status, reasons = decide(creator, settings.niche)
        db.save_creator(conn, creator["channel_id"], status=status, reasons=reasons)
        counts[status] += 1
    print(f"  filter: {counts['PASS']} pass, {counts['FAIL']} fail, {counts['PENDING']} waiting for the next stage")
