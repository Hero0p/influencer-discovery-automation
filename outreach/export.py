"""Stage 7 (export): turn the database into the three deliverable tables and write them as CSV.

The same rows are also pushed to Google Sheets by sending.py.
"""

import csv

from outreach import db
from outreach.config import DATA_DIR, NOT_AVAILABLE, NOT_FOUND

INFLUENCER_HEADERS = [
    "Name", "Platform", "Followers", "Engagement Rate (%)", "Niche", "Sub-niche", "Content Themes",
    "Email", "Email Source", "Profile URL", "Status", "Filter Reasons", "Brand Fit (0-10)", "Country",
    "Website", "Instagram", "Instagram Followers", "Instagram Engagement (%)", "TikTok",
    "Audience Age", "Audience Gender", "Audience Geography", "Last Upload", "Found By Search", "AI Model",
]
MESSAGE_HEADERS = [
    "Influencer", "Profile URL", "Niche", "Collaboration Angle", "Email", "Email Subject", "Email Pitch",
    "Email Words", "Instagram", "Instagram DM", "DM Words", "Message Check", "AI Model",
]
TRACKER_HEADERS = [
    "Influencer", "Email", "Message Generated", "Sent", "Date", "Status", "Delivered To", "DM Status",
]

STATUS_ORDER = {"PASS": 0, "PENDING": 1, "FAIL": 2}


def shown(value, missing=NOT_AVAILABLE):
    """A value for the output, or a clear label when it was never collected."""
    return missing if value is None or value == "" else value


def influencer_rows(creators):
    """The dataset: every discovered channel with its status and the reasons for it."""
    creators = sorted(creators, key=lambda creator: STATUS_ORDER.get(creator["status"], 3))
    rows = []
    for creator in creators:
        shortlisted = creator["status"] == "PASS"
        rows.append([
            creator["name"],
            "YouTube",
            shown(creator["followers"], "Hidden by channel"),
            shown(creator["engagement_rate"]),
            shown(creator["niche"], "Not Classified"),
            shown(creator["sub_niche"], "Not Classified"),
            shown(", ".join(creator["content_themes"]), "Not Classified"),
            # Emails are only looked up for shortlisted creators.
            shown(creator["email"], NOT_FOUND) if shortlisted else "Not Collected (not shortlisted)",
            shown(creator["email_source"]),
            creator["profile_url"],
            creator["status"],
            " || ".join(creator["reasons"]),
            shown(creator["brand_fit"]),
            shown(creator["country"]),
            shown(creator["website"], NOT_FOUND) if shortlisted else NOT_AVAILABLE,
            shown(creator["instagram"], NOT_FOUND) if shortlisted else NOT_AVAILABLE,
            shown(creator["instagram_followers"]),
            shown(creator["instagram_engagement"]),
            shown(creator["tiktok"], NOT_FOUND) if shortlisted else NOT_AVAILABLE,
            # Audience demographics are private to the creator on every platform.
            NOT_AVAILABLE,
            NOT_AVAILABLE,
            NOT_AVAILABLE,
            shown((creator["last_upload_at"] or "")[:10]),
            creator["found_by"],
            shown(creator["classified_by"], "Not Classified"),
        ])
    return rows


def message_rows(creators):
    """The generated email pitch and Instagram DM for each shortlisted creator."""
    rows = []
    for creator in creators:
        if creator["status"] != "PASS" or not creator["message_status"]:
            continue
        rows.append([
            creator["name"],
            creator["profile_url"],
            f"{creator['niche']} / {creator['sub_niche']}",
            creator["collab_angle"],
            shown(creator["email"], NOT_FOUND),
            creator["email_subject"],
            creator["email_body"],
            len(creator["email_body"].split()),
            shown(creator["instagram"], NOT_FOUND),
            creator["dm_text"],
            len(creator["dm_text"].split()),
            creator["message_status"],
            creator["written_by"],
        ])
    return rows


def tracker_rows(creators):
    """The outreach log: one row per shortlisted creator."""
    rows = []
    for creator in creators:
        if creator["status"] != "PASS":
            continue
        no_dm = "Not queued yet" if creator["instagram"] else "Not queued: no Instagram handle found"
        rows.append([
            creator["name"],
            shown(creator["email"], NOT_FOUND),
            "Yes" if creator["message_status"] == "OK" else "No",
            "Yes" if creator["sent"] == "Yes" else "No",
            shown(creator["sent_at"] or creator["queued_at"], ""),
            shown(creator["outreach_status"], "Not queued yet"),
            shown(creator["send_to"], ""),
            shown(creator["dm_status"], no_dm),
        ])
    return rows


def write_csv(name, headers, rows):
    DATA_DIR.mkdir(exist_ok=True)
    # utf-8-sig lets Excel open names with accents or emoji correctly.
    with open(DATA_DIR / name, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(rows)


def export_csv(settings, conn):
    """Write data/influencers.csv, data/messages.csv and data/outreach_tracker.csv."""
    creators = db.get_creators(conn, "name IS NOT NULL")
    write_csv("influencers.csv", INFLUENCER_HEADERS, influencer_rows(creators))
    write_csv("messages.csv", MESSAGE_HEADERS, message_rows(creators))
    write_csv("outreach_tracker.csv", TRACKER_HEADERS, tracker_rows(creators))
    shortlisted = sum(1 for creator in creators if creator["status"] == "PASS")
    print(f"  export: {len(creators)} influencers ({shortlisted} shortlisted) written to the data folder")
