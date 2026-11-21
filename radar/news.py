"""Collect fintech news headlines from Google News RSS.

Parsing, filtering and merging are pure functions. Only fetch_url touches the network.
"""

import http.client
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
WINDOW_HOURS = 24
USER_AGENT = "fintech-radar/0.1 (personal news digest)"


def search_query(company):
    """Return the Google News search text for a company: its custom search, or its quoted name."""
    search = company.get("search")
    return search.strip() if search else f'"{company["name"].strip()}"'


def google_news_url(query):
    """Build a Google News RSS search URL for Nigerian English results."""
    params = {"q": query, "hl": "en-NG", "gl": "NG", "ceid": "NG:en"}
    return f"{GOOGLE_NEWS_RSS}?{urllib.parse.urlencode(params)}"


def clean_title(title, source):
    """Collapse whitespace and remove the ' - Source' suffix Google News adds to headlines."""
    title = " ".join(title.split())
    suffix = f" - {source}"
    if source and title.endswith(suffix):
        title = title[: -len(suffix)]
    return title.strip()


def parse_date(text):
    """Turn an RSS pubDate into a timezone-aware datetime, or None if missing or invalid."""
    if not text:
        return None
    try:
        date = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if date.tzinfo is None:  # "-0000" means UTC but parses without a timezone
        date = date.replace(tzinfo=timezone.utc)
    return date


def parse_feed(xml_text, company_name):
    """Parse Google News RSS text into a list of headline dicts.

    Items without a title or link are skipped. Raises ValueError if the text is not valid XML.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise ValueError(f"feed is not valid XML ({error})") from error
    items = []
    for item in root.iter("item"):
        source = (item.findtext("source") or "").strip()
        title = clean_title(item.findtext("title") or "", source)
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        items.append(
            {
                "title": title,
                "link": link,
                "source": source,
                "published": parse_date(item.findtext("pubDate")),
                "companies": [company_name],
            }
        )
    return items


def is_recent(item, now, hours=WINDOW_HOURS):
    """Return True if the item has a publish time no older than `hours` before `now`."""
    published = item["published"]
    return published is not None and published >= now - timedelta(hours=hours)


def title_key(title):
    """Normalise a headline so the same story with different punctuation or case compares equal."""
    return re.sub(r"\W+", " ", title.casefold()).strip()


def merge_duplicates(items):
    """Combine items with the same headline: keep the first and merge their company lists.

    Returns new dicts; the input items are not changed.
    """
    merged = {}
    for item in items:
        key = title_key(item["title"])
        if key not in merged:
            merged[key] = {**item, "companies": list(item["companies"])}
            continue
        for company in item["companies"]:
            if company not in merged[key]["companies"]:
                merged[key]["companies"].append(company)
    return list(merged.values())


def newest_first(items):
    """Return the items sorted by publish time, newest first."""
    return sorted(items, key=lambda item: item["published"], reverse=True)


def fetch_url(url, timeout=20):
    """Download a URL and return its text. The only function in this module that uses the network."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def collect_news(config, now, fetch=fetch_url):
    """Fetch, filter and merge recent headlines for every company in the config.

    Returns (items, errors). A company whose feed fails is reported in errors and skipped,
    so one bad feed never stops the digest. `fetch` is swappable so tests stay offline.
    """
    items, errors = [], []
    for company in config["companies"]:
        name = company["name"].strip()
        try:
            feed = parse_feed(fetch(google_news_url(search_query(company))), name)
        # http.client errors such as IncompleteRead are not OSErrors, so catch them too
        except (OSError, ValueError, http.client.HTTPException) as error:
            errors.append(f"{name}: {error}")
            continue
        items.extend(item for item in feed if is_recent(item, now))
    return newest_first(merge_duplicates(items)), errors