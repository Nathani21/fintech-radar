"""Load and check fintech-radar's settings from config.toml.

Pure logic: no network calls, no email, no secrets.
"""

import tomllib
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.toml"
LIMIT_KEYS = ("max_jobs", "max_news", "max_regulation", "max_events")
MAX_LIMIT = 10
REGIONS = ("nigeria", "africa", "international")
AI_DEFAULTS = {"model": "gemini-3.1-flash-lite", "max_candidates": 40}
MAX_CANDIDATES = 100


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
    check_ai(data.get("ai"))
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
    """Check each company: a unique name, a known region, and an optional non-empty search."""
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
        search = company.get("search")
        if search is not None and (not isinstance(search, str) or not search.strip()):
            raise ValueError(f"{name.strip()}: search must be non-empty text if given.")

def check_ai(ai):
    """Check the optional [ai] section: a model ID and how many headlines the AI chooses from."""
    if ai is None:
        return
    if not isinstance(ai, dict):
        raise ValueError("[ai] must be a section.")
    model = ai.get("model", AI_DEFAULTS["model"])
    if not isinstance(model, str) or not model.strip():
        raise ValueError("[ai] model must be non-empty text.")
    count = ai.get("max_candidates", AI_DEFAULTS["max_candidates"])
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_CANDIDATES:
        raise ValueError(f"[ai] max_candidates must be a whole number from 1 to {MAX_CANDIDATES}.")


def ai_settings(config):
    """The [ai] settings with defaults filled in."""
    settings = {**AI_DEFAULTS, **config.get("ai", {})}
    settings["model"] = settings["model"].strip()
    return settings

    
def company_names(config, region=None):
    """Return company names in config order, optionally only those in one region."""
    return [
        company["name"].strip()
        for company in config["companies"]
        if region is None or company["region"] == region
    ]