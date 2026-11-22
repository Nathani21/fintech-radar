"""Build and send the digest email through Gmail, and read local settings from .env.

build_message, parse_env_file and missing_settings are pure. send_email is the only
function here that uses the network. Error messages never include setting values.
"""

import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

GMAIL_HOST = "smtp.gmail.com"
GMAIL_PORT = 465  # SSL from the first byte
REQUIRED_SETTINGS = ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD")


def build_message(subject, html, text, sender, recipient):
    """Create an email with a plain-text body and an HTML alternative."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"fintech-radar <{sender}>"
    message["To"] = recipient
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


def parse_env_file(text):
    """Parse KEY=value lines. Blank lines and # comments are skipped; surrounding quotes are removed.

    Raises ValueError naming only the line number, never its content, since it may hold a secret.
    """
    values = {}
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not key:
            raise ValueError(f".env line {number} is not in KEY=value form.")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_env_file(path, env):
    """Copy settings from a .env file into `env`, keeping any already set. A missing file is fine."""
    path = Path(path)
    if not path.exists():
        return
    # utf-8-sig also handles the invisible BOM some Windows editors add
    for key, value in parse_env_file(path.read_text(encoding="utf-8-sig")).items():
        env.setdefault(key, value)


def missing_settings(env):
    """Return the names of required settings that are unset or blank."""
    return [key for key in REQUIRED_SETTINGS if not env.get(key, "").strip()]


def send_email(message, user, password):
    """Send through Gmail's SMTP server over SSL."""
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(GMAIL_HOST, GMAIL_PORT, context=context, timeout=30) as server:
        server.login(user, password)
        server.send_message(message)