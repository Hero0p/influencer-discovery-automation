"""Stage 8 (queue) and stage 9 (sync): the sending layer.

Python never sends an email itself. It adds rows to the "Email Queue" tab of
the Google Sheet. A Zapier Zap watches that tab, sends every approved row
through Gmail and writes the result back into the row. `sync` then copies those
results into the database, the "Outreach Tracker" tab and the CSV files.

Instagram DMs are not sent automatically (Instagram's API does not allow cold
DMs). They go to the "DM Queue" tab as a manual / simulated workflow.
"""

from outreach import db, export, sheets

EMAIL_TAB = "Email Queue"
DM_TAB = "DM Queue"
INFLUENCER_TAB = "Influencers"
TRACKER_TAB = "Outreach Tracker"

EMAIL_HEADERS = [
    "queue_id", "influencer", "platform", "profile_url", "creator_email", "send_to",
    "email_subject", "email_body", "review_status", "sent", "sent_at", "status",
]
DM_HEADERS = ["queue_id", "influencer", "instagram_handle", "dm_link", "dm_text", "dm_status", "dm_sent_at"]


def queue(settings, conn):
    """Add shortlisted creators to the Email Queue and DM Queue tabs, each creator only once."""
    book = sheets.open_book(settings)
    email_queue = sheets.read_rows(book, EMAIL_TAB, EMAIL_HEADERS)
    queued_ids = {row["queue_id"] for row in email_queue}
    queued_emails = {str(row["creator_email"]).lower() for row in email_queue}
    dm_ids = {row["queue_id"] for row in sheets.read_rows(book, DM_TAB, DM_HEADERS)}

    test_mode = settings.send_mode == "test"
    review_status = "Approved" if settings.auto_approve else "Pending review"
    email_rows, dm_rows, updates = [], [], []

    waiting = db.get_creators(conn, "status = 'PASS' AND message_status IS NOT NULL AND queued_at IS NULL")
    for creator in waiting:
        channel_id = creator["channel_id"]
        if creator["message_status"] != "OK":
            updates.append((channel_id, {"outreach_status": "Skipped: the generated message failed its checks"}))
            continue

        fields = {}
        if creator["instagram"] and channel_id not in dm_ids:
            dm_status = "Simulated (demo mode, not sent)" if test_mode else "Ready to send manually"
            dm_rows.append([
                channel_id, creator["name"], creator["instagram"],
                f"https://ig.me/m/{creator['instagram']}", creator["dm_text"], dm_status, "",
            ])
            fields["dm_status"] = dm_status

        if not creator["email"]:
            fields["outreach_status"] = "Skipped: no contact email found"
        elif channel_id not in queued_ids and creator["email"] in queued_emails:
            fields["outreach_status"] = "Skipped: this email address is already in the queue"
        else:
            # In test mode the email goes to the demo inbox, never to the creator.
            send_to = settings.test_inbox if test_mode else creator["email"]
            subject = f"[DEMO for {creator['name']}] {creator['email_subject']}" if test_mode else creator["email_subject"]
            if channel_id not in queued_ids:
                email_rows.append([
                    channel_id, creator["name"], "YouTube", creator["profile_url"], creator["email"], send_to,
                    subject, creator["email_body"], review_status, "", "", "Queued",
                ])
                queued_emails.add(creator["email"])
            fields.update(
                queued_at=db.now(), send_to=send_to, review_status=review_status,
                outreach_status="Queued: waiting for review",
            )
        updates.append((channel_id, fields))

    # Write to the sheet first, so the database only says "queued" for rows that really exist.
    sheets.append_rows(book, EMAIL_TAB, EMAIL_HEADERS, email_rows)
    sheets.append_rows(book, DM_TAB, DM_HEADERS, dm_rows)
    for channel_id, fields in updates:
        db.save_creator(conn, channel_id, **fields)
    print(f"  queue: {len(email_rows)} emails and {len(dm_rows)} DMs added to the Google Sheet")


def describe_status(row):
    """One readable status for an Email Queue row."""
    if str(row["sent"]).strip().lower() == "yes":
        return "Sent"
    review = str(row["review_status"]).strip().lower()
    if review == "approved":
        return "Approved: waiting for Zapier to send"
    if review == "rejected":
        return "Rejected in review"
    return "Queued: waiting for review"


def sync(settings, conn):
    """Read what Zapier (and the reviewer) wrote in the sheet, then refresh every report."""
    book = sheets.open_book(settings)

    for row in sheets.read_rows(book, EMAIL_TAB, EMAIL_HEADERS):
        db.save_creator(
            conn,
            row["queue_id"],
            review_status=str(row["review_status"]),
            sent="Yes" if str(row["sent"]).strip().lower() == "yes" else None,
            sent_at=str(row["sent_at"]) or None,
            outreach_status=describe_status(row),
        )
    for row in sheets.read_rows(book, DM_TAB, DM_HEADERS):
        db.save_creator(conn, row["queue_id"], dm_status=str(row["dm_status"]), dm_sent_at=str(row["dm_sent_at"]) or None)

    creators = db.get_creators(conn, "name IS NOT NULL")
    sheets.replace_rows(book, INFLUENCER_TAB, export.INFLUENCER_HEADERS, export.influencer_rows(creators))
    sheets.replace_rows(book, TRACKER_TAB, export.TRACKER_HEADERS, export.tracker_rows(creators))
    export.export_csv(settings, conn)

    sent = sum(1 for creator in creators if creator["sent"] == "Yes")
    print(f"  sync: sheet and CSV reports refreshed, {sent} emails marked as sent")
