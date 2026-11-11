from outreach import db, enrichment, export, messages
from outreach.config import NOT_FOUND
from tests.helpers import make_creator, make_video

ANGLES = [
    {"name": "Sponsorship", "offer": "a paid segment", "when": {"min_followers": 50000}},
    {"name": "Barter collaboration", "offer": "a free box", "when": {"max_followers": 15000}},
    {"name": "UGC content creation", "offer": "a paid brief", "when": {}},
]


# ---------- enrichment ----------

def test_find_emails_reads_real_addresses_and_ignores_junk():
    text = "Business: Hello@Creator-Mail.com or hello@creator-mail.com. Logo: icon@2x.png, test@example.com"
    assert enrichment.find_emails(text) == ["hello@creator-mail.com"]


def test_find_instagram_handles_links_and_mentions_but_not_post_links():
    assert enrichment.find_instagram("https://www.instagram.com/cozy.home/") == ["cozy.home"]
    assert enrichment.find_instagram("Instagram: @cozy_home") == ["cozy_home"]
    assert enrichment.find_instagram("https://instagram.com/p/Cabc123") == []


def test_find_website_skips_social_and_shopping_links():
    text = "https://instagram.com/me https://amzn.to/abc https://mycozyblog.com/about."
    assert enrichment.find_website(text) == "https://mycozyblog.com/about"


def test_email_in_one_video_only_is_not_trusted():
    creator = make_creator(recent_videos=[make_video(description="sponsor: deals@sponsor-shop.com"), make_video()])
    assert enrichment.repeated_in_videos(creator, enrichment.find_emails) == []


def test_handle_credited_in_every_video_is_not_mistaken_for_the_creator():
    credit = "Music: https://instagram.com/some.musician"
    own = "Follow me: https://instagram.com/cozy.home.diary"
    creator = make_creator(
        name="Cozy Home Diary", profile_url="https://www.youtube.com/@cozyhomediary", description="Vlogs.",
        recent_videos=[make_video(description=credit), make_video(description=credit),
                       make_video(description=f"{credit} {own}"), make_video(description=f"{credit} {own}")],
    )
    assert enrichment.own_handle(creator, enrichment.find_instagram) == "cozy.home.diary"

    creator["recent_videos"] = [make_video(description=credit)] * 3
    assert enrichment.own_handle(creator, enrichment.find_instagram) is None


def test_sponsor_link_is_not_treated_as_the_creators_website(monkeypatch):
    monkeypatch.setattr(enrichment, "email_from_website", lambda url: (None, None))  # no network in tests
    sponsor = make_creator(name="Cozy Home Diary", description="My glasses: https://tinyurl.com/abc123")
    own = make_creator(name="Cozy Home Diary", description="Blog: https://cozyhomediary.com/about")
    assert enrichment.enrich_from_text(sponsor)["website"] is None
    assert enrichment.enrich_from_text(own)["website"] == "https://cozyhomediary.com/about"


def test_email_repeated_across_videos_is_used_with_its_source():
    videos = [make_video(description="Contact: me@creator-mail.com")] * 3
    result = enrichment.enrich_from_text(make_creator(description="No contact here.", recent_videos=videos))
    assert result["email"] == "me@creator-mail.com"
    assert result["email_source"] == "YouTube video descriptions (in 3 recent videos)"


def test_missing_email_stays_empty_and_is_exported_as_not_found():
    creator = make_creator(description="Just vlogs.", status="PASS")
    creator.update(enrichment.enrich_from_text(creator))
    assert creator["email"] is None
    row = dict(zip(export.INFLUENCER_HEADERS, export.influencer_rows([creator])[0]))
    assert row["Email"] == NOT_FOUND


def test_instagram_engagement_skips_posts_with_hidden_likes():
    posts = [{"likesCount": 100, "commentsCount": 0}] * 3 + [{"likesCount": -1, "commentsCount": 5}]
    assert enrichment.instagram_engagement({"followersCount": 10000, "latestPosts": posts}) == 1.0
    assert enrichment.instagram_engagement({"followersCount": 10000, "latestPosts": posts[:2]}) is None


# ---------- messages ----------

def make_message(email_words, dm_words, subject="Your slow living vlogs"):
    return messages.Message(
        number=1, email_subject=subject,
        email_body=" ".join(["word"] * email_words), instagram_dm=" ".join(["word"] * dm_words),
    )


def test_messages_inside_the_word_limits_are_accepted():
    assert messages.find_problems(make_message(60, 15)) == []
    assert messages.find_problems(make_message(90, 30)) == []


def test_messages_outside_the_word_limits_are_rejected():
    assert len(messages.find_problems(make_message(59, 31))) == 2
    assert len(messages.find_problems(make_message(91, 14))) == 2


def test_leftover_placeholder_is_rejected():
    assert messages.find_problems(make_message(70, 20, subject="Hi [Name]")) != []


def test_collaboration_angle_is_the_first_rule_that_matches():
    assert messages.choose_angle(make_creator(followers=80000), ANGLES)["name"] == "Sponsorship"
    assert messages.choose_angle(make_creator(followers=8000), ANGLES)["name"] == "Barter collaboration"
    assert messages.choose_angle(make_creator(followers=30000), ANGLES)["name"] == "UGC content creation"


# ---------- database ----------

def test_a_channel_found_twice_is_stored_once(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    db.add_creator(conn, "UC1", "first query")
    db.add_creator(conn, "UC1", "second query")
    creators = db.get_creators(conn)
    assert len(creators) == 1 and creators[0]["found_by"] == "first query"


def test_lists_survive_a_save_and_load(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    db.add_creator(conn, "UC1", "query")
    db.save_creator(conn, "UC1", name="Channel", followers=12000, content_themes=["home", "routines"])
    creator = db.get_creators(conn)[0]
    assert creator["content_themes"] == ["home", "routines"] and creator["reasons"] == []
