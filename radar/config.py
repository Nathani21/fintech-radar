"""Load and check fintech-radar's settings from config.toml.

Pure logic: no network calls, no email, no secrets.
"""

import tomllib
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.toml"
LIMIT_KEYS = ("max_jobs", "max_news", "max_regulation", "max_events")
MAX_LIMIT = 10
REGIONS = ("nigeria", "africa", "international")


def parse_config(text):
    """Parse TOML text into a checked settings dict.

    Raises ValueError with a message that says what to fix.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"config.toml is not valid TOML: {error}") from error
    check_digest(data.get("digest"))
    check_companies(data.get("companies"))
    return data


def load_config(path=CONFIG_PATH):
    """Read a config file from disk and return the checked settings."""
    return parse_config(Path(path).read_text(encoding="utf-8"))


def check_digest(digest):
    """Check that [digest] has every limit as a whole number from 0 to MAX_LIMIT."""
    if not isinstance(digest, dict):
        raise ValueError("config.toml needs a [digest] section.")
    for key in LIMIT_KEYS:
        value = digest.get(key)
        # bool is a subclass of int in Python, so rule it out explicitly
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"[digest] {key} must be a whole number.")
        if not 0 <= value <= MAX_LIMIT:
            raise ValueError(f"[digest] {key} must be between 0 and {MAX_LIMIT}.")


def check_companies(companies):
    """Check that each company has a unique name and a known region."""
    if not isinstance(companies, list) or not companies:
        raise ValueError("config.toml needs at least one [[companies]] entry.")
    seen = set()
    for number, company in enumerate(companies, start=1):
        name = company.get("name") if isinstance(company, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Company #{number} needs a name.")
        key = name.strip().casefold()
        if key in seen:
            raise ValueError(f"{name.strip()} is listed more than once.")
        seen.add(key)
        if company.get("region") not in REGIONS:
            raise ValueError(
                f"{name.strip()}: region must be one of {', '.join(REGIONS)}."
            )


def company_names(config, region=None):
    """Return company names in config order, optionally only those in one region."""
    return [
        company["name"].strip()
        for company in config["companies"]
        if region is None or company["region"] == region
    ]