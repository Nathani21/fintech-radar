"""Command line: `python -m radar` writes preview.html; `python -m radar --send` emails the digest."""

import argparse
import os
import smtplib
import sys
from datetime import datetime, timezone
from pathlib import Path

from radar.config import load_config
from radar.digest import build_digest
from radar.emailer import build_message, load_env_file, missing_settings, send_email
from radar.news import collect_news, fetch_url

ROOT = Path(__file__).parent.parent
PREVIEW_PATH = ROOT / "preview.html"
ENV_PATH = ROOT / ".env"


def parse_args(argv):
    """Read the command line options."""
    parser = argparse.ArgumentParser(
        prog="python -m radar", description="Build the fintech-radar daily digest."
    )
    parser.add_argument(
        "--send", action="store_true", help="email the digest (default: only write preview.html)"
    )
    return parser.parse_args(argv)


def main(
    argv=None,
    *,
    env=None,
    now=None,
    fetch=fetch_url,
    send=send_email,
    preview_path=PREVIEW_PATH,
    env_path=ENV_PATH,
):
    """Collect news, build the digest, then write a preview or send it. Returns an exit code.

    The keyword arguments let tests run everything offline without sending real email.
    """
    args = parse_args(argv)
    env = os.environ if env is None else env
    now = now or datetime.now(timezone.utc)

    if args.send:  # check settings before doing any work
        load_env_file(env_path, env)
        missing = missing_settings(env)
        if missing:
            print(
                f"Can't send: {', '.join(missing)} not set. "
                "Add them to .env locally, or to GitHub Secrets.",
                file=sys.stderr,
            )
            return 1

    config = load_config()
    news, errors = collect_news(config, now, fetch=fetch)
    for error in errors:
        print(f"Could not fetch {error}", file=sys.stderr)
    subject, html, text = build_digest(news, errors, config["digest"], now)

    if not args.send:
        Path(preview_path).write_text(html, encoding="utf-8")
        print(f"{subject}\nPreview written to {preview_path}. Nothing was sent.")
        return 0

    sender = env["GMAIL_ADDRESS"].strip()
    recipient = env.get("DIGEST_TO", "").strip() or sender
    password = env["GMAIL_APP_PASSWORD"].replace(" ", "")  # Google shows it in groups of 4
    try:
        send(build_message(subject, html, text, sender, recipient), sender, password)
    except smtplib.SMTPAuthenticationError:
        print(
            "Gmail rejected the login. Check GMAIL_ADDRESS and create a new app password.",
            file=sys.stderr,
        )
        return 1
    except (smtplib.SMTPException, OSError) as error:
        print(f"Couldn't send the email ({type(error).__name__}).", file=sys.stderr)
        return 1
    print(f"Sent: {subject}")
    return 0