from outreach import filtering, metrics, youtube
from tests.helpers import NICHE, days_ago, make_creator, make_video


# ---------- metrics ----------

def test_video_engagement_is_likes_plus_comments_over_views():
    assert metrics.video_engagement(make_video(views=1000, likes=40, comments=10)) == 5.0


def test_video_with_hidden_likes_or_no_views_is_not_measured():
    assert metrics.video_engagement(make_video(likes=None)) is None
    assert metrics.video_engagement(make_video(views=0)) is None


def test_disabled_comments_count_as_zero():
    assert metrics.video_engagement(make_video(views=1000, likes=40, comments=None)) == 4.0


def test_engagement_is_unavailable_with_fewer_than_three_measurable_videos():
    videos = [make_video(), make_video(), make_video(likes=None)]
    assert metrics.summarise(videos)["engagement_rate"] is None


def test_engagement_uses_the_median_so_one_odd_video_does_not_distort_it():
    videos = [make_video(views=1000, likes=40, comments=10)] * 4 + [make_video(views=2, likes=2, comments=0)]
    assert metrics.summarise(videos)["engagement_rate"] == 5.0


# ---------- YouTube parsing ----------

def test_hidden_subscriber_count_is_stored_as_unknown_not_zero():
    channel = youtube.parse_channel({"id": "UC1", "snippet": {"title": "X"}, "statistics": {"hiddenSubscriberCount": True}})
    assert channel["followers"] is None


def test_hidden_like_count_is_stored_as_unknown_not_zero():
    video = youtube.parse_video({"snippet": {"title": "X"}, "statistics": {"viewCount": "100"}})
    assert video["views"] == 100 and video["likes"] is None and video["comments"] is None


# ---------- filtering ----------

def test_creator_meeting_every_rule_passes_with_a_reason_per_check():
    status, reasons = filtering.decide(make_creator(), NICHE)
    assert status == "PASS"
    assert len(reasons) == 7 and all(reason.startswith("PASS | ") for reason in reasons)


def test_too_many_followers_fails_and_says_why():
    status, reasons = filtering.decide(make_creator(followers=250000), NICHE)
    assert status == "FAIL"
    assert "250,000 is outside the 5,000-100,000" in reasons[0]


def test_hidden_followers_fail():
    assert filtering.decide(make_creator(followers=None), NICHE)[0] == "FAIL"


def test_low_engagement_fails():
    status, reasons = filtering.decide(make_creator(engagement_rate=0.5), NICHE)
    assert status == "FAIL"
    assert any("FAIL | Engagement: 0.5% is below" in reason for reason in reasons)


def test_unmeasurable_engagement_fails_instead_of_being_assumed():
    assert filtering.decide(make_creator(engagement_rate=None), NICHE)[0] == "FAIL"


def test_inactive_channel_fails():
    status, _ = filtering.decide(make_creator(last_upload_at=days_ago(200)), NICHE)
    assert status == "FAIL"


def test_country_filter_only_applies_when_a_list_is_configured():
    rules = dict(NICHE["filters"], allowed_countries=["US"])
    assert filtering.check_country(make_creator(country="GB"), rules)[0] is False
    assert filtering.check_country(make_creator(country="US"), rules)[0] is True
    assert filtering.check_country(make_creator(country=None), NICHE["filters"])[0] is True


def test_creator_waits_as_pending_until_measured_and_classified():
    assert filtering.decide(make_creator(measured_at=None, classified_at=None), NICHE)[0] == "PENDING"
    assert filtering.decide(make_creator(classified_at=None), NICHE)[0] == "PENDING"


def test_wrong_niche_or_low_confidence_fails():
    assert filtering.decide(make_creator(niche="Gaming"), NICHE)[0] == "FAIL"
    assert filtering.decide(make_creator(niche_confidence=0.3), NICHE)[0] == "FAIL"


def test_low_brand_fit_fails():
    assert filtering.decide(make_creator(brand_fit=3), NICHE)[0] == "FAIL"
