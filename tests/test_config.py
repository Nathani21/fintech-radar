import pytest

from radar.config import (
    CONFIG_PATH,
    company_names,
    load_config,
    parse_config,
)

DIGEST = """
[digest]
max_jobs = 5
max_news = 5
max_regulation = 2
max_events = 3
"""

COMPANIES = """
[[companies]]
name = "Paystack"
region = "nigeria"

[[companies]]
name = "Wave"
region = "africa"
"""


def test_real_config_is_valid():
    config = load_config(CONFIG_PATH)
    assert "Flutterwave" in company_names(config)


def test_valid_config_parses():
    config = parse_config(DIGEST + COMPANIES)
    assert config["digest"]["max_jobs"] == 5
    assert company_names(config) == ["Paystack", "Wave"]


def test_company_names_filters_by_region():
    config = parse_config(DIGEST + COMPANIES)
    assert company_names(config, "africa") == ["Wave"]
    assert company_names(config, "international") == []


def test_zero_limit_is_allowed():
    config = parse_config(DIGEST.replace("max_events = 3", "max_events = 0") + COMPANIES)
    assert config["digest"]["max_events"] == 0


def test_bad_toml():
    with pytest.raises(ValueError, match="not valid TOML"):
        parse_config("[digest")


def test_missing_digest():
    with pytest.raises(ValueError, match=r"\[digest\] section"):
        parse_config(COMPANIES)


def test_missing_limit():
    with pytest.raises(ValueError, match="max_news must be a whole number"):
        parse_config(DIGEST.replace("max_news = 5", "") + COMPANIES)


@pytest.mark.parametrize("value", ['"5"', "2.5", "true"])
def test_limit_must_be_whole_number(value):
    text = DIGEST.replace("max_jobs = 5", f"max_jobs = {value}") + COMPANIES
    with pytest.raises(ValueError, match="max_jobs must be a whole number"):
        parse_config(text)


@pytest.mark.parametrize("value", ["-1", "11"])
def test_limit_out_of_range(value):
    text = DIGEST.replace("max_jobs = 5", f"max_jobs = {value}") + COMPANIES
    with pytest.raises(ValueError, match="between 0 and 10"):
        parse_config(text)


def test_no_companies():
    with pytest.raises(ValueError, match="at least one"):
        parse_config(DIGEST)


def test_company_without_name():
    text = DIGEST + '[[companies]]\nregion = "nigeria"\n'
    with pytest.raises(ValueError, match="Company #1 needs a name"):
        parse_config(text)


def test_blank_name():
    text = DIGEST + '[[companies]]\nname = "  "\nregion = "nigeria"\n'
    with pytest.raises(ValueError, match="needs a name"):
        parse_config(text)


def test_duplicate_company_ignores_case():
    text = DIGEST + COMPANIES + '[[companies]]\nname = "paystack"\nregion = "nigeria"\n'
    with pytest.raises(ValueError, match="listed more than once"):
        parse_config(text)


def test_unknown_region():
    text = DIGEST + '[[companies]]\nname = "Kuda"\nregion = "lagos"\n'
    with pytest.raises(ValueError, match="region must be one of"):
        parse_config(text)



def test_custom_search_is_allowed():
    text = DIGEST + '[[companies]]\nname = "Kuda"\nregion = "nigeria"\nsearch = \'"Kuda" bank\'\n'
    assert parse_config(text)["companies"][0]["search"] == '"Kuda" bank'


@pytest.mark.parametrize("value", ['"  "', "5"])
def test_bad_search(value):
    text = DIGEST + f'[[companies]]\nname = "Kuda"\nregion = "nigeria"\nsearch = {value}\n'
    with pytest.raises(ValueError, match="search must be non-empty text"):
        parse_config(text)