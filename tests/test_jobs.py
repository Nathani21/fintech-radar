import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from radar.jobs import (
    board_url,
    collect_jobs,
    days_ago,
    has_word,
    is_entry_level,
    job_item,
    nigerian_place,
    parse_day,
    parse_greenhouse,
    parse_timestamp,
    parse_workable,
    posted_label,
    select_jobs,
)

# Real responses, trimmed (see the fixture files)
FIXTURES = Path(__file__).parent / "fixtures"
GREENHOUSE = (FIXTURES / "greenhouse_moniepoint.json").read_text(encoding="utf-8")
WORKABLE = (FIXTURES / "workable_kuda.json").read_text(encoding="utf-8")
WORKABLE_EMPTY = (FIXTURES / "workable_piggyvest.json").read_text(encoding="utf-8")

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
SETTINGS = {
    "boards": [
        {"company": "Moniepoint", "source": "greenhouse", "id": "moniepoint"},
        {"company": "Kuda", "source": "workable", "id": "kuda"},
        {"company": "PiggyVest", "source": "workable", "id": "piggyvest"},
    ],
    "max_age_days": 7,
    "places": ["Lagos", "Abuja", "FCT", "Remote"],
    "exclude_titles": ["senior", "lead", "head", "manager"],
}
FOREVER = {**SETTINGS, "max_age_days": 100_000}  # ignore age, to test the other filters


def greenhouse_jobs():
    return parse_greenhouse(json.loads(GREENHOUSE), "Moniepoint")


def workable_jobs():
    return parse_workable(json.loads(WORKABLE), "Kuda")


def fake_fetch(url):
    """Answer each board's URL with its saved response; no network."""
    if "greenhouse" in url:
        return GREENHOUSE
    if url.endswith("/kuda"):
        return WORKABLE
    if url.endswith("/piggyvest"):
        return WORKABLE_EMPTY
    raise AssertionError(f"unexpected URL {url}")


# --- addresses and dates


def test_board_urls():
    assert board_url(SETTINGS["boards"][0]) == (
        "https://boards-api.greenhouse.io/v1/boards/moniepoint/jobs"
    )
    assert board_url(SETTINGS["boards"][1]) == (
        "https://apply.workable.com/api/v1/widget/accounts/kuda"
    )


def test_parse_timestamp_needs_a_timezone():
    assert parse_timestamp("2026-11-17T13:07:33-05:00").utcoffset().total_seconds() == -5 * 3600
    assert parse_timestamp("2026-11-17T13:07:33") is None
    assert parse_timestamp(None) is None
    assert parse_timestamp("soon") is None


def test_parse_day_is_lagos_midnight():
    assert parse_day("2026-10-02").isoformat() == "2026-10-02T00:00:00+01:00"
    assert parse_day("") is None
    assert parse_day(None) is None


# --- Greenhouse


def test_parse_greenhouse_reads_real_response():
    jobs = greenhouse_jobs()
    assert len(jobs) == 9
    first = jobs[0]
    assert first["title"] == "State Inventory Officer (Lagos)"
    assert first["company"] == "Moniepoint"
    assert first["link"] == "https://job-boards.eu.greenhouse.io/moniepoint/jobs/5040606101"
    assert first["locations"] == ["Lagos, Nigeria"]
    assert first["key"] == "greenhouse:4514032101"  # internal_job_id groups locations
    assert first["posted"] == parse_timestamp("2026-11-17T13:07:33-05:00")


def test_parse_greenhouse_cleans_titles_and_splits_locations():
    jobs = {job["link"].rsplit("/", 1)[1]: job for job in greenhouse_jobs()}
    assert jobs["4355709101"]["title"] == "Financial Planning Analyst"  # had a leading space
    assert "Remote, Lagos, Nigeria" in jobs["4874410101"]["locations"]
    assert len(jobs["4874410101"]["locations"]) == 7


def test_parse_greenhouse_skips_incomplete_jobs():
    data = {
        "jobs": [
            {"title": "No link", "first_published": "2026-11-17T13:07:33-05:00"},
            {"title": "No date", "absolute_url": "https://x.test/1"},
            {"title": "Fallback date", "absolute_url": "https://x.test/2",
             "updated_at": "2026-11-17T13:07:33-05:00", "location": {"name": "Lagos, Nigeria"}},
            "not a job",
        ]
    }
    jobs = parse_greenhouse(data, "Moniepoint")
    assert [job["title"] for job in jobs] == ["Fallback date"]


@pytest.mark.parametrize("data", [[], {"jobs": "nope"}, {}, "text"])
def test_parse_greenhouse_rejects_wrong_shape(data):
    with pytest.raises(ValueError, match="unexpected response"):
        parse_greenhouse(data, "Moniepoint")


# --- Workable


def test_parse_workable_reads_real_response():
    jobs = workable_jobs()
    assert len(jobs) == 7  # duplicates are removed later, after filtering
    admin = next(job for job in jobs if job["title"].startswith("Information Systems"))
    assert admin["locations"] == ["Abuja, Federal Capital Territory, Nigeria"]
    assert admin["level"] == "Entry level"
    assert admin["key"] == "workable:619B513D12"
    assert admin["link"] == "https://apply.workable.com/j/619B513D12"
    assert admin["posted"] == parse_day("2026-10-02")


def test_parse_workable_locations():
    jobs = workable_jobs()
    assert jobs[0]["locations"] == ["Lagos, Nigeria"]  # "Lagos, Lagos, Nigeria" collapsed
    assert jobs[1]["locations"] == ["Remote, Cape Town, Western Cape, South Africa"]


def test_parse_workable_empty_board():
    assert parse_workable(json.loads(WORKABLE_EMPTY), "PiggyVest") == []


@pytest.mark.parametrize("data", [[], {"jobs": None}, {"name": "x"}])
def test_parse_workable_rejects_wrong_shape(data):
    with pytest.raises(ValueError, match="unexpected response"):
        parse_workable(data, "Kuda")


# --- filters


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Field Sales Lead (Rivers)", True),
        ("Head, IT Audit", True),
        ("Leadership Programme Intern", False),  # whole words only
        ("SENIOR Data Analyst", True),
        ("Data Analyst", False),
    ],
)
def test_has_word(text, expected):
    assert has_word(text, ["lead", "head", "senior"]) is expected


@pytest.mark.parametrize(
    "title, level, expected",
    [
        ("Data Analyst", "", True),
        ("Data Analyst", "Entry level", True),
        ("Data Analyst", "Internship", True),
        ("Data Analyst - Credit", "Mid-Senior level", False),
        ("Senior Data Analyst", "", False),
        ("Senior Data Analyst", "Entry level", False),
    ],
)
def test_is_entry_level(title, level, expected):
    job = {"title": title, "level": level}
    assert is_entry_level(job, SETTINGS["exclude_titles"]) is expected


@pytest.mark.parametrize(
    "locations, expected",
    [
        (["Lagos, Nigeria"], "Lagos, Nigeria"),
        (["Remote, Nigeria"], "Remote, Nigeria"),
        (["FCT, Nigeria"], "FCT, Nigeria"),
        (["Remote, Portugal", "Remote, Lagos, Nigeria"], "Remote, Lagos, Nigeria"),
        (["Imo, Nigeria"], None),
        (["Remote, Portugal"], None),
        (["Lagos, Portugal"], None),
        ([], None),
    ],
)
def test_nigerian_place(locations, expected):
    assert nigerian_place({"locations": locations}, SETTINGS["places"]) == expected


@pytest.mark.parametrize(
    "posted, expected",
    [
        ("2026-11-21T09:00:00+00:00", "posted today"),
        ("2026-11-20T23:30:00+00:00", "posted today"),  # already the 21st in Lagos
        ("2026-11-20T12:00:00+00:00", "posted yesterday"),
        ("2026-11-17T12:00:00+00:00", "posted 4 days ago"),
    ],
)
def test_posted_label(posted, expected):
    assert posted_label(datetime.fromisoformat(posted), NOW) == expected


def test_select_jobs_last_week():
    chosen = select_jobs(greenhouse_jobs() + workable_jobs(), SETTINGS, NOW)
    assert [job["title"] for job in chosen] == ["State Inventory Officer (Lagos)"]
    assert chosen[0]["location"] == "Lagos, Nigeria"


def test_select_jobs_all_filters_on_real_data():
    chosen = select_jobs(greenhouse_jobs() + workable_jobs(), FOREVER, NOW)
    assert [(job["company"], job["title"], job["location"]) for job in chosen] == [
        ("Moniepoint", "State Inventory Officer (Lagos)", "Lagos, Nigeria"),
        ("Kuda", "Information Systems Administrator (Abuja)",
         "Abuja, Federal Capital Territory, Nigeria"),
        ("Moniepoint", "Engineering Relations Partner", "Remote, Lagos, Nigeria"),
        ("Moniepoint", "Financial Planning Analyst", "Remote, Nigeria"),
        ("Moniepoint", "POS Technician (Federal Capital Territory)", "FCT, Nigeria"),
    ]


def test_select_jobs_one_per_role():
    job = greenhouse_jobs()[0]
    copy = {**job, "link": "https://x.test/other", "locations": ["Remote, Nigeria"]}
    assert len(select_jobs([job, copy], FOREVER, NOW)) == 1


def test_job_item():
    job = select_jobs(greenhouse_jobs(), SETTINGS, NOW)[0]
    assert job_item(job, NOW) == {
        "title": "State Inventory Officer (Lagos)",
        "link": "https://job-boards.eu.greenhouse.io/moniepoint/jobs/5040606101",
        "meta": "Moniepoint · Lagos, Nigeria · posted 4 days ago",
    }


# --- collect_jobs


def test_collect_jobs_offline():
    jobs, errors = collect_jobs(SETTINGS, NOW, fetch=fake_fetch)
    assert errors == []
    assert [job["title"] for job in jobs] == ["State Inventory Officer (Lagos)"]


def test_collect_jobs_reports_a_failing_board_and_keeps_the_rest():
    def flaky_fetch(url):
        if url.endswith("/kuda"):
            raise TimeoutError("timed out")
        return fake_fetch(url)

    jobs, errors = collect_jobs(FOREVER, NOW, fetch=flaky_fetch)
    assert errors == ["Kuda jobs: timed out"]
    assert all(job["company"] == "Moniepoint" for job in jobs)
    assert len(jobs) == 4


@pytest.mark.parametrize("body, message", [("<html>", "Expecting value"), ("[]", "unexpected")])
def test_collect_jobs_reports_bad_responses(body, message):
    settings = {**SETTINGS, "boards": SETTINGS["boards"][:1]}
    jobs, errors = collect_jobs(settings, NOW, fetch=lambda url: body)
    assert jobs == []
    assert errors[0].startswith("Moniepoint jobs: ") and message in errors[0]


# --- review fixes from #12


def workable_job(published_on, **extra):
    """A minimal Workable job in Lagos."""
    return {
        "title": "Data Analyst",
        "shortcode": published_on,
        "url": f"https://apply.workable.com/j/{published_on}",
        "published_on": published_on,
        "locations": [{"city": "Lagos", "country": "Nigeria"}],
        **extra,
    }


def test_age_cutoff_matches_the_label_in_lagos_days():
    settings = {**SETTINGS, "max_age_days": 3}
    jobs = parse_workable(
        {"jobs": [workable_job("2026-11-18"), workable_job("2026-11-17")]}, "Kuda"
    )
    chosen = select_jobs(jobs, settings, NOW)  # NOW is 21 Nov
    assert [job_item(job, NOW)["meta"] for job in chosen] == [
        "Kuda · Lagos, Nigeria · posted 3 days ago"
    ]


def test_age_cutoff_ignores_the_hour_of_posting():
    settings = {**SETTINGS, "max_age_days": 3, "boards": []}
    early = {**greenhouse_jobs()[0], "posted": parse_timestamp("2026-11-18T00:30:00+01:00")}
    late = {**early, "key": "late", "posted": parse_timestamp("2026-11-18T23:30:00+01:00")}
    assert len(select_jobs([early, late], settings, NOW)) == 2  # both 18 Nov in Lagos


def test_days_ago_uses_lagos_dates():
    assert days_ago(parse_timestamp("2026-11-20T23:30:00+00:00"), NOW) == 0  # 21 Nov in Lagos
    assert days_ago(parse_day("2026-11-18"), NOW) == 3


@pytest.mark.parametrize("locations", [5, "Lagos", None, {"city": "Lagos"}])
def test_workable_odd_locations_fall_back_to_the_top_level(locations):
    job = workable_job("2026-11-20", locations=locations, city="Abuja", country="Nigeria")
    parsed = parse_workable({"jobs": [job]}, "Kuda")
    assert parsed[0]["locations"] == ["Abuja, Nigeria"]


def test_parser_surprise_is_reported_not_raised(monkeypatch):
    import radar.jobs as jobs_module

    def broken_parser(data, company):
        raise TypeError("'int' object is not iterable")

    monkeypatch.setitem(jobs_module.PARSERS, "workable", broken_parser)
    jobs, errors = collect_jobs(FOREVER, NOW, fetch=fake_fetch)
    assert errors == [
        "Kuda jobs: unexpected response (TypeError)",
        "PiggyVest jobs: unexpected response (TypeError)",
    ]
    assert jobs and all(job["company"] == "Moniepoint" for job in jobs)
