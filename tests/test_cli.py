import smtplib
from datetime import datetime, timezone
from pathlib import Path

from radar.ai import AIError
from radar.cli import main

FEED = (Path(__file__).parent / "fixtures" / "google_news_paystack.xml").read_text(encoding="utf-8")
NOW = datetime(2026, 11, 22, 11, 0, tzinfo=timezone.utc)
SECRET = "abcd efgh ijkl mnop"


def fake_fetch(url):
    """Every company gets the sample feed; no network."""
    return FEED


def run(tmp_path, argv, env, send=None):
    """Run main fully offline, recording any email it tries to send."""
    sent = []

    def fake_send(message, user, password):
        sent.append((message, user, password))
        if send:
            send()

    code = main(
        argv,
        env=env,
        now=NOW,
        fetch=fake_fetch,
        send=fake_send,
        preview_path=tmp_path / "preview.html",
        env_path=tmp_path / ".env",
    )
    return code, sent


def test_preview_writes_file_and_sends_nothing(tmp_path, capsys):
    code, sent = run(tmp_path, [], env={})
    assert code == 0
    assert sent == []
    html = (tmp_path / "preview.html").read_text(encoding="utf-8")
    assert "Paystack launches faster payouts" in html
    assert "Nothing was sent" in capsys.readouterr().out


def test_send_without_settings_fails_before_fetching(tmp_path, capsys):
    def exploding_fetch(url):
        raise AssertionError("should not fetch")

    code = main(["--send"], env={}, now=NOW, fetch=exploding_fetch, env_path=tmp_path / ".env")
    assert code == 1
    assert "GMAIL_ADDRESS, GMAIL_APP_PASSWORD not set" in capsys.readouterr().err


def test_send_uses_env_and_strips_password_spaces(tmp_path):
    env = {"GMAIL_ADDRESS": " me@gmail.com ", "GMAIL_APP_PASSWORD": SECRET}
    code, sent = run(tmp_path, ["--send"], env=env)
    assert code == 0
    message, user, password = sent[0]
    assert user == "me@gmail.com"
    assert password == "abcdefghijklmnop"
    assert message["To"] == "me@gmail.com"  # defaults to sending to yourself
    assert message["Subject"] == "fintech-radar · Sun 22 Nov · 2 headlines"
    assert not (tmp_path / "preview.html").exists()


def test_send_reads_dotenv_and_digest_to(tmp_path):
    (tmp_path / ".env").write_text(
        f"GMAIL_ADDRESS=me@gmail.com\nGMAIL_APP_PASSWORD={SECRET}\nDIGEST_TO=you@gmail.com\n",
        encoding="utf-8",
    )
    code, sent = run(tmp_path, ["--send"], env={})
    assert code == 0
    assert sent[0][0]["To"] == "you@gmail.com"


def test_rejected_login_is_reported_without_the_password(tmp_path, capsys):
    def reject():
        raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")

    env = {"GMAIL_ADDRESS": "me@gmail.com", "GMAIL_APP_PASSWORD": SECRET}
    code, _ = run(tmp_path, ["--send"], env=env, send=reject)
    output = capsys.readouterr()
    assert code == 1
    assert "Gmail rejected the login" in output.err
    assert "abcd" not in output.err + output.out


def test_network_failure_while_sending(tmp_path, capsys):
    def drop():
        raise TimeoutError("timed out")

    env = {"GMAIL_ADDRESS": "me@gmail.com", "GMAIL_APP_PASSWORD": SECRET}
    code, _ = run(tmp_path, ["--send"], env=env, send=drop)
    assert code == 1
    assert "Couldn't send the email (TimeoutError)" in capsys.readouterr().err



AI_REPLY = '{"one_thing": "Payouts got faster.", "picks": [{"id": 1, "why": "Regulation shapes product."}]}'


def run_with_ai(tmp_path, ask):
    """Preview run with a Gemini key set and a fake AI."""
    return main(
        [],
        env={"GEMINI_API_KEY": "SECRET-KEY"},
        now=NOW,
        fetch=fake_fetch,
        ask=ask,
        preview_path=tmp_path / "preview.html",
        env_path=tmp_path / ".env",
    )


def test_preview_uses_ai_ranking(tmp_path):
    code = run_with_ai(tmp_path, lambda prompt, key, model: AI_REPLY)
    html = (tmp_path / "preview.html").read_text(encoding="utf-8")
    assert code == 0
    assert "<strong>Today:</strong> Payouts got faster." in html
    assert "Regulation shapes product." in html
    assert "CBN guidelines" in html  # pick 1 is the CBN story
    assert "Paystack launches faster payouts" not in html  # not picked
    assert "showing 1 of 2" in html


def test_ai_failure_falls_back_to_newest(tmp_path, capsys):
    def broken_ask(prompt, key, model):
        raise AIError("Gemini returned HTTP 503: overloaded")

    code = run_with_ai(tmp_path, broken_ask)
    html = (tmp_path / "preview.html").read_text(encoding="utf-8")
    output = capsys.readouterr()
    assert code == 0
    assert "Paystack launches faster payouts" in html
    assert "AI ranking was unavailable today" in html
    assert "AI ranking skipped: Gemini returned HTTP 503" in output.err
    assert "SECRET-KEY" not in output.err + output.out


def test_no_key_means_no_ai_call(tmp_path, capsys):
    def exploding_ask(prompt, key, model):
        raise AssertionError("should not call the AI")

    code = main(
        [],
        env={},
        now=NOW,
        fetch=fake_fetch,
        ask=exploding_ask,
        preview_path=tmp_path / "preview.html",
        env_path=tmp_path / ".env",
    )
    assert code == 0
    assert "AI ranking off: GEMINI_API_KEY not set." in capsys.readouterr().err


def test_gemini_key_is_read_from_dotenv_for_previews(tmp_path):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=from-file\n", encoding="utf-8")
    keys = []

    def fake_ask(prompt, key, model):
        keys.append(key)
        return AI_REPLY

    main(
        [],
        env={},
        now=NOW,
        fetch=fake_fetch,
        ask=fake_ask,
        preview_path=tmp_path / "preview.html",
        env_path=tmp_path / ".env",
    )
    assert keys == ["from-file"]


def test_max_news_zero_hides_news_and_skips_ai(tmp_path, monkeypatch):
    import radar.cli as cli

    real_load_config = cli.load_config

    def config_with_no_news():
        config = real_load_config()
        config["digest"]["max_news"] = 0
        return config

    def exploding_ask(prompt, key, model):
        raise AssertionError("should not call the AI when News is hidden")

    monkeypatch.setattr(cli, "load_config", config_with_no_news)
    code = main(
        [],
        env={"GEMINI_API_KEY": "SECRET-KEY"},
        now=NOW,
        fetch=fake_fetch,
        ask=exploding_ask,
        preview_path=tmp_path / "preview.html",
        env_path=tmp_path / ".env",
    )
    html = (tmp_path / "preview.html").read_text(encoding="utf-8")
    assert code == 0
    assert "News" not in html
    assert "No new fintech headlines" not in html