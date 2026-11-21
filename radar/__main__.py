"""Run `python -m radar` to print the last 24 hours of headlines. A manual check: no email."""

from datetime import datetime, timezone

from radar.config import load_config
from radar.news import WINDOW_HOURS, collect_news


def main():
    """Print recent headlines, then any companies whose feed could not be fetched."""
    config = load_config()
    items, errors = collect_news(config, datetime.now(timezone.utc))
    print(f"{len(items)} headlines from the last {WINDOW_HOURS} hours\n")
    for item in items:
        print(f"[{', '.join(item['companies'])}] {item['title']} ({item['source']})")
        print(f"  {item['link']}\n")
    for error in errors:
        print(f"Could not fetch {error}")


if __name__ == "__main__":
    main()