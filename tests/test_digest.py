from datetime import datetime, timedelta, timezone

import pytest

from radar.digest import (
    build_digest,
    build_subject,
    failed_names,
    format_age,
    jobs_section,
    news_section,
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


def news(items, total=None):
    """A one-section list: News with `items`, collected total defaulting to len(items)."""
    return [news_section(items, len(items) if total is None else total)]


def jobs_like_section(items):
    """A second section, to check the email handles more than one."""
    return {
        "title": "Jobs",
        "items": items,
        "total": len(items),
        "noun": ("job", "jobs"),
        "empty": "No new jobs.",
    }


def test_subject_uses_lagos_date_and_plural():
    late_night_utc = datetime(2026, 11, 22, 23, 30, tzinfo=timezone.utc)  # already 23 Nov in Lagos
    two = news([make_item("A"), make_item("B")])
    assert build_subject(two, late_night_utc) == "fintech-radar · Mon 23 Nov · 2 headlines"
    assert build_subject(news([make_item("A")]), NOW) == "fintech-radar · Sun 22 Nov · 1 headline"
    assert build_subject(news([]), NOW) == "fintech-radar · Sun 22 Nov · quiet day"
    assert build_subject([], NOW) == "fintech-radar · Sun 22 Nov · quiet day"


def test_subject_counts_each_section():
    sections = news([make_item("A"), make_item("B")]) + [jobs_like_section([make_item("J")])]
    assert build_subject(sections, NOW) == "fintech-radar · Sun 22 Nov · 2 headlines, 1 job"


def test_subject_skips_empty_sections():
    sections = news([]) + [jobs_like_section([make_item("J")])]
    assert build_subject(sections, NOW) == "fintech-radar · Sun 22 Nov · 1 job"


def test_digest_shows_count_of_total():
    subject, html, text = build_digest(news([make_item("One"), make_item("Two")], 3), [], NOW)
    assert subject.endswith("2 headlines")
    assert "One" in html and "Two" in html
    assert "showing 2 of 3" in html
    assert "NEWS (showing 2 of 3)" in text


def test_digest_hides_count_when_all_shown():
    _, html, _ = build_digest(news([make_item("One")]), [], NOW)
    assert "showing" not in html


def test_digest_escapes_untrusted_text():
    shown = [make_item('<script>alert("x")</script> & co', link='https://e.com/?a=1&b="2"')]
    _, html, _ = build_digest(news(shown), [], NOW)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert 'href="https://e.com/?a=1&amp;b=&quot;2&quot;"' in html


def test_digest_drops_unsafe_links():
    _, html, text = build_digest(news([make_item("Sneaky", link="javascript:alert(1)")]), [], NOW)
    assert "javascript" not in html
    assert "javascript" not in text
    assert "Sneaky" in html


def test_digest_shows_meta_line():
    shown = [make_item("One", hours_ago=3, companies=["Paystack", "Kuda"])]
    _, html, text = build_digest(news(shown), [], NOW)
    assert "TechCabal · 3h ago · Paystack, Kuda" in text
    assert "TechCabal · 3h ago · Paystack, Kuda" in html


def test_digest_shows_one_thing_and_why_escaped():
    item = {**make_item("One"), "why": "Matters for <payments> & you"}
    _, html, text = build_digest(news([item]), [], NOW, one_thing="CBN <rules> changed")
    assert "<strong>Today:</strong> CBN &lt;rules&gt; changed" in html
    assert "Matters for &lt;payments&gt; &amp; you" in html
    assert "TODAY: CBN <rules> changed" in text
    assert "  Matters for <payments> & you" in text


def test_digest_without_ai_has_no_today_line():
    _, html, text = build_digest(news([make_item("One")]), [], NOW)
    assert "Today:" not in html
    assert "TODAY" not in text


def test_digest_shows_notes():
    _, html, text = build_digest(news([make_item("One")]), [], NOW, notes=["AI was down."])
    assert "AI was down." in html
    assert "AI was down." in text


def test_quiet_day_with_errors():
    subject, html, text = build_digest(news([]), ["Kuda: timed out"], NOW)
    assert subject.endswith("quiet day")
    assert "No new fintech headlines" in html
    assert "Couldn't reach today: Kuda" in text
    assert "timed out" not in html  # error details stay in the logs, not the email


def test_sections_render_in_order_with_their_own_empty_line():
    sections = news([make_item("Headline")]) + [jobs_like_section([])]
    _, html, text = build_digest(sections, [], NOW)
    assert html.index(">News<") < html.index(">Jobs<")
    assert "No new jobs." in html
    assert text.index("NEWS") < text.index("JOBS")


def test_hidden_section_is_not_mentioned():
    _, html, text = build_digest([], [], NOW)
    assert "News" not in html
    assert "No new fintech headlines" not in html
    assert "NEWS" not in text


def test_jobs_section_uses_each_jobs_own_meta_line():
    job = {
        "title": "Data <Analyst>",
        "link": "https://apply.workable.com/j/1",
        "meta": "Kuda · Lagos, Nigeria · posted today",
    }
    subject, html, text = build_digest([jobs_section([job], 3, 3)], [], NOW)
    assert subject.endswith("1 job")
    assert "Data &lt;Analyst&gt;" in html
    assert "Kuda · Lagos, Nigeria · posted today" in html
    assert "JOBS (showing 1 of 3)" in text
    assert "  Kuda · Lagos, Nigeria · posted today" in text


def test_empty_jobs_section_says_how_far_back_it_looked():
    _, html, _ = build_digest([jobs_section([], 0, 3)], [], NOW)
    assert "No new entry-level jobs in the last 3 days." in html
