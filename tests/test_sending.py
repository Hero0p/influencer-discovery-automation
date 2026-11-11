"""The sending layer, tested against an in-memory stand-in for the Google Sheet."""

from types import SimpleNamespace

import pytest

from outreach import db, export, sending

SETTINGS = SimpleNamespace(send_mode="test", test_inbox="demo-inbox@example.org", auto_approve=False)


class FakeSheets:
    """Keeps the tabs in a dictionary instead of calling Google."""

    def __init__(self):
        self.tabs = {}

    def open_book(self, settings):
        return self

    def read_rows(self, book, title, headers):
        return [dict(zip(headers, row)) for row in self.tabs.get(title, [])]

    def append_rows(self, book, title, headers, rows):
        self.tabs.setdefault(title, []).extend(rows)

    def replace_rows(self, book, title, headers, rows):
        self.tabs[title] = list(rows)


@pytest.fixture
def sheet(monkeypatch, tmp_path):
    fake = FakeSheets()
    monkeypatch.setattr(sending, "sheets", fake)
    monkeypatch.setattr(export, "DATA_DIR", tmp_path)
    return fake


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "test.db")


def add_shortlisted(conn, channel_id, email, instagram=None):
    db.add_creator(conn, channel_id, "test query")
    db.save_creator(
        conn, channel_id, name=f"Channel {channel_id}", profile_url=f"https://www.youtube.com/channel/{channel_id}",
        followers=20000, status="PASS", message_status="OK", email=email, instagram=instagram,
        email_subject="Your home routine videos", email_body="Hello there.", dm_text="Hi, loved your vlog.",
    )


def email_queue(sheet):
    return sheet.read_rows(sheet, sending.EMAIL_TAB, sending.EMAIL_HEADERS)


def test_in_test_mode_the_email_goes_to_the_demo_inbox_not_the_creator(sheet, conn):
    add_shortlisted(conn, "UC1", "real@creator-mail.com")
    sending.queue(SETTINGS, conn)
    row = email_queue(sheet)[0]
    assert row["send_to"] == "demo-inbox@example.org"
    assert row["creator_email"] == "real@creator-mail.com"
    assert row["email_subject"].startswith("[DEMO for Channel UC1]")
    assert row["review_status"] == "Pending review" and row["sent"] == ""


def test_running_queue_twice_does_not_add_a_creator_twice(sheet, conn):
    add_shortlisted(conn, "UC1", "real@creator-mail.com")
    sending.queue(SETTINGS, conn)
    sending.queue(SETTINGS, conn)
    assert len(email_queue(sheet)) == 1


def test_two_channels_sharing_one_email_are_queued_once(sheet, conn):
    add_shortlisted(conn, "UC1", "shared@creator-mail.com")
    add_shortlisted(conn, "UC2", "shared@creator-mail.com")
    sending.queue(SETTINGS, conn)
    assert len(email_queue(sheet)) == 1
    statuses = {creator["outreach_status"] for creator in db.get_creators(conn)}
    assert "Skipped: this email address is already in the queue" in statuses


def test_creator_without_an_email_is_skipped_and_logged(sheet, conn):
    add_shortlisted(conn, "UC1", None)
    sending.queue(SETTINGS, conn)
    assert email_queue(sheet) == []
    assert db.get_creators(conn)[0]["outreach_status"] == "Skipped: no contact email found"


def test_dm_goes_to_the_manual_queue_as_simulated_only_when_a_handle_is_known(sheet, conn):
    add_shortlisted(conn, "UC1", None, instagram="cozy.home")
    add_shortlisted(conn, "UC2", None)
    sending.queue(SETTINGS, conn)
    dm_rows = sheet.read_rows(sheet, sending.DM_TAB, sending.DM_HEADERS)
    assert len(dm_rows) == 1
    assert dm_rows[0]["dm_link"] == "https://ig.me/m/cozy.home"
    assert dm_rows[0]["dm_status"] == "Simulated (demo mode, not sent)"


def test_sync_copies_the_send_result_into_the_tracker(sheet, conn):
    add_shortlisted(conn, "UC1", "real@creator-mail.com")
    sending.queue(SETTINGS, conn)
    # What the Zap does after sending: mark the row.
    row = sheet.tabs[sending.EMAIL_TAB][0]
    row[sending.EMAIL_HEADERS.index("sent")] = "Yes"
    row[sending.EMAIL_HEADERS.index("sent_at")] = "2026-11-10 15:00"
    sending.sync(SETTINGS, conn)

    tracker = dict(zip(export.TRACKER_HEADERS, sheet.tabs[sending.TRACKER_TAB][0]))
    assert tracker["Sent"] == "Yes" and tracker["Status"] == "Sent"
    assert tracker["Date"] == "2026-11-10 15:00" and tracker["Delivered To"] == "demo-inbox@example.org"
