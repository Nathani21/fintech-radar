"""Turn collected items into the daily email: a subject, an HTML body and a plain-text body.

The email is a list of sections (News now, Jobs and others later). Pure functions only.
All outside text is HTML-escaped, because it comes from the internet and must never be
able to inject markup into the email.
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
    """Get names from 'Name: reason' error strings, for a short footer."""
    return [error.split(":", 1)[0].strip() for error in errors]


def news_section(items, total):
    """The News section: `items` are the chosen headlines, `total` how many were collected."""
    return {
        "title": "News",
        "items": items,
        "total": total,
        "noun": ("headline", "headlines"),
        "empty": "No new fintech headlines in the last 24 hours.",
    }


def count_label(count, noun):
    """'1 headline', '3 headlines'."""
    return f"{count} {noun[0] if count == 1 else noun[1]}"


def build_subject(sections, now):
    """Subject line with the Lagos date and how many items each section shows."""
    day = now.astimezone(LAGOS).strftime("%a %d %b")
    counts = [
        count_label(len(section["items"]), section["noun"])
        for section in sections
        if section["items"]
    ]
    return f"fintech-radar · {day} · {', '.join(counts) if counts else 'quiet day'}"


def meta_line(item, now):
    """'Source · 3h ago · Company, Company' for one item."""
    parts = [item["source"], format_age(item["published"], now), ", ".join(item["companies"])]
    return " · ".join(part for part in parts if part)


def showing(section):
    """' · showing 5 of 14' when some items were left out, otherwise ''."""
    shown, total = len(section["items"]), section["total"]
    return f"showing {shown} of {total}" if total > shown else ""


def item_html(item, now):
    """One item: linked title, optional why-it-matters line, then the meta line."""
    title = escape(item["title"])
    link = safe_link(item["link"])
    if link:
        title = (
            f'<a href="{escape(link, quote=True)}" style="color:#047857;'
            f'text-decoration:none;font-weight:600">{title}</a>'
        )
    why = item.get("why")
    why_html = f'<div style="font-size:14px;color:#374151">{escape(why)}</div>' if why else ""
    return (
        f'<div style="margin:0 0 14px"><div style="font-size:15px">{title}</div>'
        f'{why_html}<div style="{MUTED}">{escape(meta_line(item, now))}</div></div>'
    )


def section_html(section, now):
    """A section heading and its items, or its 'nothing new' line."""
    more = showing(section)
    more_html = f'<span style="{MUTED};font-weight:normal"> · {escape(more)}</span>' if more else ""
    parts = [
        f'<h2 style="font-size:15px;margin:0 0 10px">{escape(section["title"])}{more_html}</h2>'
    ]
    if section["items"]:
        parts += [item_html(item, now) for item in section["items"]]
    else:
        parts.append(f'<p style="margin:0 0 14px">{escape(section["empty"])}</p>')
    return "\n".join(parts)


def render_html(sections, errors, now, one_thing="", notes=()):
    """Build the HTML email body. Inline styles, because many email apps ignore <style>."""
    date = now.astimezone(LAGOS).strftime("%A %d %B %Y")
    parts = [
        '<div style="font-family:Segoe UI,Arial,sans-serif;max-width:600px;margin:0 auto;'
        'color:#1f2933;line-height:1.4">',
        '<h1 style="font-size:20px;margin:0">fintech-radar</h1>',
        f'<p style="{MUTED};margin:2px 0 20px">{escape(date)}</p>',
    ]
    if one_thing:
        parts.append(
            '<p style="background:#ecfdf5;border-left:3px solid #047857;padding:10px 12px;'
            f'margin:0 0 20px"><strong>Today:</strong> {escape(one_thing)}</p>'
        )
    parts += [section_html(section, now) for section in sections]
    if errors:
        names = escape(", ".join(failed_names(errors)))
        parts.append(f'<p style="{MUTED};margin-top:24px">Couldn\'t reach today: {names}</p>')
    parts += [f'<p style="{MUTED}">{escape(note)}</p>' for note in notes]
    parts.append("</div>")
    return "\n".join(parts)


def section_text(section, now):
    """Plain-text lines for one section."""
    more = showing(section)
    lines = [section["title"].upper() + (f" ({more})" if more else ""), ""]
    if not section["items"]:
        return lines + [section["empty"], ""]
    for item in section["items"]:
        lines.append(item["title"])
        if item.get("why"):
            lines.append(f"  {item['why']}")
        lines.append(f"  {meta_line(item, now)}")
        if safe_link(item["link"]):
            lines.append(f"  {item['link']}")
        lines.append("")
    return lines


def render_text(sections, errors, now, one_thing="", notes=()):
    """Build the plain-text body, for email apps that don't show HTML."""
    lines = ["fintech-radar", now.astimezone(LAGOS).strftime("%A %d %B %Y"), ""]
    if one_thing:
        lines += [f"TODAY: {one_thing}", ""]
    for section in sections:
        lines += section_text(section, now)
    if errors:
        lines.append(f"Couldn't reach today: {', '.join(failed_names(errors))}")
    lines += list(notes)
    return "\n".join(lines).rstrip() + "\n"


def build_digest(sections, errors, now, one_thing="", notes=()):
    """Build (subject, html, text) from the sections to show.

    A section hidden by its config limit should simply not be passed in.
    `notes` are short lines for the footer.
    """
    return (
        build_subject(sections, now),
        render_html(sections, errors, now, one_thing, notes),
        render_text(sections, errors, now, one_thing, notes),
    )
