import pytest

from radar.emailer import build_message, load_env_file, missing_settings, parse_env_file


def test_build_message_has_text_and_html():
    message = build_message("Subject", "<p>Hi</p>", "Hi", "me@gmail.com", "you@gmail.com")
    assert message["Subject"] == "Subject"
    assert message["From"] == "fintech-radar <me@gmail.com>"
    assert message["To"] == "you@gmail.com"
    assert message.get_body(("plain",)).get_content().strip() == "Hi"
    assert message.get_body(("html",)).get_content().strip() == "<p>Hi</p>"


def test_parse_env_file():
    text = """
# a comment
GMAIL_ADDRESS = me@gmail.com
GMAIL_APP_PASSWORD="abcd efgh ijkl mnop"
DIGEST_TO='other@gmail.com'
EMPTY=
"""
    assert parse_env_file(text) == {
        "GMAIL_ADDRESS": "me@gmail.com",
        "GMAIL_APP_PASSWORD": "abcd efgh ijkl mnop",
        "DIGEST_TO": "other@gmail.com",
        "EMPTY": "",
    }


def test_parse_env_file_keeps_equals_in_value():
    assert parse_env_file("KEY=a=b")["KEY"] == "a=b"


@pytest.mark.parametrize("line", ["no-equals-secret", "=secret123"])
def test_parse_env_file_bad_line_hides_content(line):
    with pytest.raises(ValueError, match="line 2") as error:
        parse_env_file(f"OK=1\n{line}")
    assert line not in str(error.value)


def test_load_env_file_does_not_overwrite(tmp_path):
    path = tmp_path / ".env"
    path.write_text("\ufeffGMAIL_ADDRESS=file@gmail.com\nDIGEST_TO=x@gmail.com\n", encoding="utf-8")
    env = {"GMAIL_ADDRESS": "already@gmail.com"}
    load_env_file(path, env)
    assert env == {"GMAIL_ADDRESS": "already@gmail.com", "DIGEST_TO": "x@gmail.com"}


def test_load_env_file_missing_is_fine(tmp_path):
    env = {}
    load_env_file(tmp_path / "nope.env", env)
    assert env == {}


def test_missing_settings():
    assert missing_settings({}) == ["GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"]
    assert missing_settings({"GMAIL_ADDRESS": "a", "GMAIL_APP_PASSWORD": "  "}) == [
        "GMAIL_APP_PASSWORD"
    ]
    assert missing_settings({"GMAIL_ADDRESS": "a", "GMAIL_APP_PASSWORD": "b"}) == []