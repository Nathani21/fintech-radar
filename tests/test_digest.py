from datetime import datetime, timedelta, timezone

import pytest

from radar.digest import (
    build_digest,
    build_subject,
    failed_names,
    format_age,
    safe_link,
)

NOW = datetime(2026, 11, 22, 11, 0, tzinfo=timezone.utc)  # 12:00 in Lagos
LIMITS = {"max_jobs": 5, "max_news": 2, "max_regulation": 2, "max_events": 3}


def make_item(title, hours_ago=1, link="https://example.com/a", companies=("Paystack",)):
    """A news item like collect_news returns."""
    return {
        "title": title,
        "link": link,
        "source": "TechCabal",
        "published": NOW - timedelta(hours=hours_ago),
        "companies": list(companies),
    }


@pytest.mark.parametrize(
    "age, expected",
    [
        (timedelta(minutes=45), "45m ago"),
        (timedelta(hours=3, minutes=59), "3h ago"),
        (timedelta(minutes=-5), "0m ago"),  # a slightly-future time from clock drift
        (timedelta(hours=30), "21 Nov, 06:00 WAT"),
    ],
)
def test_format_age(age, expected):
    assert format_age(NOW - age, NOW) == expected


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://news.google.com/x", "https://news.google.com/x"),
        (" HTTP://example.com ", "HTTP://example.com"),
        ("javascript:alert(1)", None),
        ("", None),
        (None, None),
    ],
)
def test_safe_link(url, expected):
    assert safe_link(url) == expected


def test_failed_names():
    assert failed_names(["Kuda: timed out", "Carbon: feed is not valid XML (x: y)"]) == [
        "Kuda",
        "Carbon",
    ]


def test_subject_uses_lagos_date_and_plural():
    late_night_utc = datetime(2026, 11, 22, 23, 30, tzinfo=timezone.utc)  # already 23 Nov in Lagos
    assert build_subject(2, late_night_utc) == "fintech-radar · Mon 23 Nov · 2 headlines"
    assert build_subject(1, NOW) == "fintech-radar · Sun 22 Nov · 1 headline"
    assert build_subject(0, NOW) == "fintech-radar · Sun 22 Nov · quiet day"


def test_digest_shows_count_of_total():
    shown = [make_item("One"), make_item("Two")]
    subject, html, text = build_digest(shown, 3, [], NOW)
    assert subject.endswith("2 headlines")
    assert "One" in html and "Two" in html
    assert "showing 2 of 3" in html
    assert "(showing 2 of 3)" in text


def test_digest_hides_count_when_all_shown():
    _, html, _ = build_digest([make_item("One")], 1, [], NOW)
    assert "showing" not in html


def test_digest_escapes_untrusted_text():
    shown = [make_item('<script>alert("x")</script> & co', link='https://e.com/?a=1&b="2"')]
    _, html, _ = build_digest(shown, 1, [], NOW)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert 'href="https://e.com/?a=1&amp;b=&quot;2&quot;"' in html


def test_digest_drops_unsafe_links():
    _, html, text = build_digest([make_item("Sneaky", link="javascript:alert(1)")], 1, [], NOW)
    assert "javascript" not in html
    assert "javascript" not in text
    assert "Sneaky" in html


def test_digest_shows_meta_line():
    shown = [make_item("One", hours_ago=3, companies=["Paystack", "Kuda"])]
    _, html, text = build_digest(shown, 1, [], NOW)
    assert "TechCabal · 3h ago · Paystack, Kuda" in text
    assert "TechCabal · 3h ago · Paystack, Kuda" in html


def test_digest_shows_one_thing_and_why_escaped():
    item = {**make_item("One"), "why": "Matters for <payments> & you"}
    _, html, text = build_digest([item], 1, [], NOW, one_thing="CBN <rules> changed")
    assert "<strong>Today:</strong> CBN &lt;rules&gt; changed" in html
    assert "Matters for &lt;payments&gt; &amp; you" in html
    assert "TODAY: CBN <rules> changed" in text
    assert "  Matters for <payments> & you" in text


def test_digest_without_ai_has_no_today_line():
    _, html, text = build_digest([make_item("One")], 1, [], NOW)
    assert "Today:" not in html
    assert "TODAY" not in text


def test_digest_shows_notes():
    _, html, text = build_digest([make_item("One")], 1, [], NOW, notes=["AI was down."])
    assert "AI was down." in html
    assert "AI was down." in text


def test_quiet_day_with_errors():
    subject, html, text = build_digest([], 0, ["Kuda: timed out"], NOW)
    assert subject.endswith("quiet day")
    assert "No new fintech headlines" in html
    assert "Couldn't reach today: Kuda" in text
    assert "timed out" not in html  # error details stay in the logs, not the email