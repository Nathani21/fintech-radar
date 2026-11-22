"""Turn collected items into the daily email: a subject, an HTML body and a plain-text body.

Pure functions only. All outside text is HTML-escaped, because headlines come from the
internet and must never be able to inject markup into the email.
"""

from datetime import timedelta, timezone
from html import escape

LAGOS = timezone(timedelta(hours=1), "WAT")  # Nigeria has no daylight saving time
MUTED = "color:#6b7280;font-size:12px"


def format_age(published, now):
    """Describe a publish time briefly: '45m ago', '3h ago', or a Lagos date and time."""
    age = now - published
    if age < timedelta(hours=1):
        return f"{max(int(age.total_seconds() // 60), 0)}m ago"
    if age < timedelta(hours=24):
        return f"{int(age.total_seconds() // 3600)}h ago"
    return published.astimezone(LAGOS).strftime("%d %b, %H:%M WAT")


def safe_link(url):
    """Return the URL only if it is http(s); anything else (e.g. javascript:) becomes None."""
    url = (url or "").strip()
    return url if url.lower().startswith(("https://", "http://")) else None


def failed_names(errors):
    """Get company names from 'Company: reason' error strings, for a short footer."""
    return [error.split(":", 1)[0].strip() for error in errors]


def build_subject(count, now):
    """Subject line with the Lagos date and how many headlines are shown."""
    day = now.astimezone(LAGOS).strftime("%a %d %b")
    if count == 0:
        return f"fintech-radar · {day} · quiet day"
    return f"fintech-radar · {day} · {count} headline{'' if count == 1 else 's'}"


def meta_line(item, now):
    """'Source · 3h ago · Company, Company' for one item."""
    parts = [item["source"], format_age(item["published"], now), ", ".join(item["companies"])]
    return " · ".join(part for part in parts if part)


def render_html(shown, total, errors, now):
    """Build the HTML email body. Inline styles, because many email apps ignore <style>."""
    date = now.astimezone(LAGOS).strftime("%A %d %B %Y")
    parts = [
        '<div style="font-family:Segoe UI,Arial,sans-serif;max-width:600px;margin:0 auto;'
        'color:#1f2933;line-height:1.4">',
        '<h1 style="font-size:20px;margin:0">fintech-radar</h1>',
        f'<p style="{MUTED};margin:2px 0 20px">{escape(date)}</p>',
    ]
    if shown:
        more = f" · showing {len(shown)} of {total}" if total > len(shown) else ""
        parts.append(
            f'<h2 style="font-size:15px;margin:0 0 10px">News'
            f'<span style="{MUTED};font-weight:normal">{escape(more)}</span></h2>'
        )
        for item in shown:
            title = escape(item["title"])
            link = safe_link(item["link"])
            if link:
                title = (
                    f'<a href="{escape(link, quote=True)}" style="color:#047857;'
                    f'text-decoration:none;font-weight:600">{title}</a>'
                )
            parts.append(
                f'<div style="margin:0 0 14px"><div style="font-size:15px">{title}</div>'
                f'<div style="{MUTED}">{escape(meta_line(item, now))}</div></div>'
            )
    else:
        parts.append("<p>No new fintech headlines in the last 24 hours.</p>")
    if errors:
        names = escape(", ".join(failed_names(errors)))
        parts.append(f'<p style="{MUTED};margin-top:24px">Couldn\'t reach today: {names}</p>')
    parts.append("</div>")
    return "\n".join(parts)


def render_text(shown, total, errors, now):
    """Build the plain-text body, for email apps that don't show HTML."""
    lines = ["fintech-radar", now.astimezone(LAGOS).strftime("%A %d %B %Y"), ""]
    if shown:
        more = f" (showing {len(shown)} of {total})" if total > len(shown) else ""
        lines += [f"NEWS{more}", ""]
        for item in shown:
            lines += [item["title"], f"  {meta_line(item, now)}"]
            if safe_link(item["link"]):
                lines.append(f"  {item['link']}")
            lines.append("")
    else:
        lines += ["No new fintech headlines in the last 24 hours.", ""]
    if errors:
        lines.append(f"Couldn't reach today: {', '.join(failed_names(errors))}")
    return "\n".join(lines).rstrip() + "\n"


def build_digest(news, errors, limits, now):
    """Build (subject, html, text). `news` is newest first; `limits` is config['digest']."""
    shown = news[: limits["max_news"]]
    return (
        build_subject(len(shown), now),
        render_html(shown, len(news), errors, now),
        render_text(shown, len(news), errors, now),
    )