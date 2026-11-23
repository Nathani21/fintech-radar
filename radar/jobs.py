"""Collect recent entry-level jobs in Nigeria from companies' public job boards.

Supported boards: Greenhouse and Workable. Parsing and filtering are pure functions; only
fetching uses the network, and `fetch` is swappable so tests stay offline. Field names
come from real responses saved in tests/fixtures/, not just from the docs.
"""

import http.client
import json
import re
import urllib.parse
from datetime import date, datetime, time, timedelta

from radar.digest import LAGOS
from radar.news import fetch_url

BOARD_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{id}/jobs",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{id}",
}
ENTRY_LEVELS = {"internship", "entry level", "associate"}  # Workable "experience" values


def board_url(board):
    """The public API address for a board in config."""
    return BOARD_URLS[board["source"]].format(id=urllib.parse.quote(board["id"], safe=""))


def clean(text):
    """Collapse whitespace; anything that isn't text becomes ''."""
    return " ".join(text.split()) if isinstance(text, str) else ""


def parse_timestamp(text):
    """An ISO timestamp with a timezone ('2026-11-17T13:07:33-05:00'), or None."""
    try:
        moment = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else None


def parse_day(text):
    """A date like '2026-10-02' as midnight in Lagos, or None."""
    try:
        return datetime.combine(date.fromisoformat(text), time(0), tzinfo=LAGOS)
    except (TypeError, ValueError):
        return None


def job_list(data, key):
    """The list of jobs under `key`, or ValueError if the response isn't shaped as expected."""
    jobs = data.get(key) if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        raise ValueError(f"unexpected response (no '{key}' list)")
    return [job for job in jobs if isinstance(job, dict)]


def parse_greenhouse(data, company):
    """Jobs from a Greenhouse board response. Jobs missing a title, link or date are skipped."""
    jobs = []
    for job in job_list(data, "jobs"):
        title, link = clean(job.get("title")), clean(job.get("absolute_url"))
        posted = parse_timestamp(job.get("first_published")) or parse_timestamp(
            job.get("updated_at")
        )
        location = job.get("location")
        name = clean(location.get("name")) if isinstance(location, dict) else ""
        if not title or not link or posted is None:
            continue
        jobs.append(
            {
                # One role is often posted once per location with the same internal_job_id
                "key": f"greenhouse:{job.get('internal_job_id') or job.get('id')}",
                "title": title,
                "company": company,
                "link": link,
                "locations": [part.strip() for part in name.split(";") if part.strip()],
                "level": "",
                "posted": posted,
            }
        )
    return jobs


def workable_locations(job):
    """Readable location strings for a Workable job, prefixed 'Remote, ' if it is remote."""
    entries = [loc for loc in job.get("locations") or [] if isinstance(loc, dict)]
    entries = [loc for loc in entries if not loc.get("hidden")] or [job]
    names = []
    for loc in entries:
        parts = []
        for part in (loc.get("city"), loc.get("region") or loc.get("state"), loc.get("country")):
            part = clean(part)
            if part and part not in parts:  # "Lagos, Lagos, Nigeria" -> "Lagos, Nigeria"
                parts.append(part)
        if parts:
            names.append(("Remote, " if job.get("telecommuting") else "") + ", ".join(parts))
    return names


def parse_workable(data, company):
    """Jobs from a Workable widget response. Jobs missing a title, link or date are skipped."""
    jobs = []
    for job in job_list(data, "jobs"):
        title = clean(job.get("title"))
        link = clean(job.get("url")) or clean(job.get("shortlink"))
        posted = parse_day(job.get("published_on")) or parse_day(job.get("created_at"))
        if not title or not link or posted is None:
            continue
        jobs.append(
            {
                # Workable repeats a job once per location with the same shortcode
                "key": f"workable:{job.get('shortcode') or link}",
                "title": title,
                "company": company,
                "link": link,
                "locations": workable_locations(job),
                "level": clean(job.get("experience")),
                "posted": posted,
            }
        )
    return jobs


PARSERS = {"greenhouse": parse_greenhouse, "workable": parse_workable}


def has_word(text, words):
    """True if any of `words` appears in `text` as a whole word, ignoring case."""
    return any(
        re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text, re.IGNORECASE) for word in words
    )


def is_entry_level(job, exclude_titles):
    """Entry level unless the board says otherwise or the title has a seniority word."""
    level = job["level"].casefold()
    if level and level not in ENTRY_LEVELS:
        return False
    return not has_word(job["title"], exclude_titles)


def nigerian_place(job, places):
    """The first of the job's locations that is in Nigeria and names one of `places`, or None."""
    for location in job["locations"]:
        if has_word(location, ["Nigeria"]) and has_word(location, places):
            return location
    return None


def posted_label(posted, now):
    """'posted today', 'posted yesterday' or 'posted 3 days ago', by Lagos calendar day."""
    days = (now.astimezone(LAGOS).date() - posted.astimezone(LAGOS).date()).days
    if days <= 0:
        return "posted today"
    return "posted yesterday" if days == 1 else f"posted {days} days ago"


def select_jobs(jobs, settings, now):
    """Keep recent, entry-level jobs in the configured Nigerian places.

    One job per role (the same role posted in several places counts once), newest first.
    """
    cutoff = now - timedelta(days=settings["max_age_days"])
    chosen, seen = [], set()
    for job in sorted(jobs, key=lambda job: job["posted"], reverse=True):
        place = nigerian_place(job, settings["places"])
        if job["key"] in seen or place is None or job["posted"] < cutoff:
            continue
        if not is_entry_level(job, settings["exclude_titles"]):
            continue
        seen.add(job["key"])
        chosen.append({**job, "location": place})
    return chosen


def job_item(job, now):
    """A job in the shape the email uses: title, link and one meta line."""
    return {
        "title": job["title"],
        "link": job["link"],
        "meta": f"{job['company']} · {job['location']} · {posted_label(job['posted'], now)}",
    }


def collect_jobs(settings, now, fetch=fetch_url):
    """Fetch every board in settings and return (chosen jobs, errors).

    A board that fails is reported in errors and skipped, so one bad board never stops
    the email.
    """
    jobs, errors = [], []
    for board in settings["boards"]:
        try:
            data = json.loads(fetch(board_url(board)))
            jobs.extend(PARSERS[board["source"]](data, board["company"]))
        except (OSError, ValueError, http.client.HTTPException) as error:
            errors.append(f"{board['company']} jobs: {error}")
    return select_jobs(jobs, settings, now), errors
