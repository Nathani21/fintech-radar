from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from radar.news import (
    clean_title,
    collect_news,
    google_news_url,
    is_recent,
    merge_duplicates,
    newest_first,
    parse_date,
    parse_feed,
    search_query,
)

FIXTURES = Path(__file__).parent / "fixtures"
PAYSTACK_FEED = (FIXTURES / "google_news_paystack.xml").read_text(encoding="utf-8")
NOW = datetime(2026, 11, 22, 11, 0, tzinfo=timezone.utc)


def make_item(title, hours_ago=1, companies=("Paystack",)):
    """A headline dict like parse_feed returns, published `hours_ago` before NOW."""
    return {
        "title": title,
        "link": f"https://example.com/{title}",
        "source": "Example",
        "published": NOW - timedelta(hours=hours_ago),
        "companies": list(companies),
    }


def test_search_query_defaults_to_quoted_name():
    assert search_query({"name": " Paystack "}) == '"Paystack"'


def test_search_query_uses_custom_search():
    assert search_query({"name": "Kuda", "search": '"Kuda" bank'}) == '"Kuda" bank'


def test_google_news_url_encodes_query_for_nigeria():
    url = google_news_url('"Kuda" bank')
    assert url.startswith("https://news.google.com/rss/search?")
    assert "q=%22Kuda%22+bank" in url
    assert "gl=NG" in url and "ceid=NG%3Aen" in url


@pytest.mark.parametrize(
    "title, source, expected",
    [
        ("Big news - TechCabal", "TechCabal", "Big news"),
        ("Big news - TechCabal", "Other", "Big news - TechCabal"),
        ("  Big   news  ", "", "Big news"),
        ("A - B - TechCabal", "TechCabal", "A - B"),
    ],
)
def test_clean_title(title, source, expected):
    assert clean_title(title, source) == expected


def test_parse_date_gmt():
    assert parse_date("Sun, 22 Nov 2026 09:30:00 GMT") == datetime(
        2026, 11, 22, 9, 30, tzinfo=timezone.utc
    )


def test_parse_date_minus_zero_is_utc():
    assert parse_date("Sat, 21 Nov 2026 14:05:00 -0000").tzinfo == timezone.utc


@pytest.mark.parametrize("text", [None, "", "not a date"])
def test_parse_date_invalid(text):
    assert parse_date(text) is None


def test_parse_feed_reads_fixture():
    items = parse_feed(PAYSTACK_FEED, "Paystack")
    assert len(items) == 3  # the item without a link is skipped
    first = items[0]
    assert first["title"] == "Paystack launches faster payouts for small merchants"
    assert first["source"] == "TechNews NG"
    assert first["link"] == "https://news.google.com/rss/articles/sample-1"
    assert first["companies"] == ["Paystack"]
    assert items[1]["title"] == "Nigerian fintechs react to new CBN guidelines"


def test_parse_feed_invalid_xml():
    with pytest.raises(ValueError, match="not valid XML"):
        parse_feed("<rss><channel>", "Paystack")


def test_parse_feed_empty_channel():
    assert parse_feed("<rss><channel></channel></rss>", "Paystack") == []


def test_is_recent_boundaries():
    assert is_recent(make_item("a", hours_ago=24), NOW)
    assert not is_recent(make_item("a", hours_ago=24.01), NOW)
    assert not is_recent({**make_item("a"), "published": None}, NOW)


def test_merge_duplicates_ignores_case_and_punctuation():
    first = make_item("Paystack raises $10M!", companies=["Paystack"])
    second = make_item("paystack raises $10m", companies=["Flutterwave"])
    merged = merge_duplicates([first, second])
    assert len(merged) == 1
    assert merged[0]["companies"] == ["Paystack", "Flutterwave"]
    assert first["companies"] == ["Paystack"]  # the input is not changed


def test_merge_duplicates_keeps_different_stories():
    assert len(merge_duplicates([make_item("One"), make_item("Two")])) == 2


def test_newest_first():
    items = [make_item("old", hours_ago=5), make_item("new", hours_ago=1)]
    assert [item["title"] for item in newest_first(items)] == ["new", "old"]


def test_collect_news_offline():
    config = {
        "companies": [
            {"name": "Paystack", "region": "nigeria"},
            {"name": "Kuda", "region": "nigeria", "search": '"Kuda" bank'},
        ]
    }
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        if "Kuda" in url:
            raise OSError("timed out")
        return PAYSTACK_FEED

    items, errors = collect_news(config, NOW, fetch=fake_fetch)

    assert len(fetched) == 2
    # Only the two items from the last 24 hours, newest first
    assert [item["title"] for item in items] == [
        "Paystack launches faster payouts for small merchants",
        "Nigerian fintechs react to new CBN guidelines",
    ]
    assert errors == ["Kuda: timed out"]


def test_collect_news_merges_story_found_by_two_companies():
    config = {
        "companies": [
            {"name": "Paystack", "region": "nigeria"},
            {"name": "Flutterwave", "region": "nigeria"},
        ]
    }
    items, errors = collect_news(config, NOW, fetch=lambda url: PAYSTACK_FEED)
    assert errors == []
    assert len(items) == 2
    assert items[0]["companies"] == ["Paystack", "Flutterwave"]


def test_collect_news_reports_bad_xml():
    config = {"companies": [{"name": "Paystack", "region": "nigeria"}]}
    items, errors = collect_news(config, NOW, fetch=lambda url: "not xml")
    assert items == []
    assert errors[0].startswith("Paystack: feed is not valid XML")