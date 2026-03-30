"""
Main orchestrator for the baseball promotions scraper.

This is the entry point — run it with:
    python -m python.baseball_promos.src.main

PIPELINE:
    1. SCRAPE:   Visit all 3 team websites → extract promotion data
    2. STORE:    Upsert promotions into BigQuery (idempotent)
    3. SYNC:     Create/update Google Calendar events (idempotent)
    4. LINK:     Save calendar event IDs back to BigQuery

Each step is idempotent — running the pipeline multiple times is safe.
New promos get added, existing ones get updated, nothing gets duplicated.

COMMAND LINE OPTIONS:
    --scrape-only:    Just scrape and print results (no BQ or Calendar)
    --no-calendar:    Scrape and store in BQ, but skip Calendar sync
    --team <slug>:    Only scrape a specific team (yankees, mets, brooklyn)
"""

import argparse
import asyncio
import logging
import sys

from .calendar_sync import sync_promotions_to_calendar
from .config import SCRAPE_TARGETS
from .models import Promotion
from .scrapers import SCRAPERS
from .storage import (
    ensure_dataset_and_table,
    get_existing_calendar_event_ids,
    update_calendar_event_id,
    upsert_promotions,
)

logger = logging.getLogger(__name__)


async def scrape_all(team_filter: str | None = None) -> list[Promotion]:
    """Scrape promotions from all (or specified) teams.

    Each scraper runs sequentially because Playwright launches a separate
    browser process for each. Running them in parallel would work but
    uses more memory for minimal time savings (each page takes ~15s).
    """
    all_promotions = []

    targets = SCRAPE_TARGETS
    if team_filter:
        if team_filter not in targets:
            logger.error(
                f"Unknown team '{team_filter}'. "
                f"Available: {', '.join(targets.keys())}"
            )
            return []
        targets = {team_filter: targets[team_filter]}

    for slug in targets:
        scraper_class = SCRAPERS[slug]
        scraper = scraper_class()
        try:
            promos = await scraper.scrape()
            all_promotions.extend(promos)
        except Exception:
            logger.exception(f"Failed to scrape {slug}, continuing with others")

    return all_promotions


def print_summary(promotions: list[Promotion]) -> None:
    """Print a nice summary of scraped promotions, grouped by team."""
    # Group by team
    by_team: dict[str, list[Promotion]] = {}
    for p in promotions:
        by_team.setdefault(p.team_name, []).append(p)

    print(f"\n{'='*60}")
    print(f"  Scraped {len(promotions)} promotions from {len(by_team)} teams")
    print(f"{'='*60}")

    for team_name, promos in sorted(by_team.items()):
        print(f"\n  {team_name} ({len(promos)} promotions)")
        print(f"  {'-'*40}")
        for p in sorted(promos, key=lambda x: x.game_date):
            img_indicator = " [img]" if p.promo_image_url else ""
            print(
                f"    {p.game_date} | {p.game_time or 'TBD':>8} | "
                f"vs {p.opponent:20s} | {p.promo_name}{img_indicator}"
            )


async def main() -> None:
    """Run the full scrape → store → sync pipeline."""
    parser = argparse.ArgumentParser(description="Baseball Promotions Scraper")
    parser.add_argument(
        "--scrape-only",
        action="store_true",
        help="Only scrape and print results (no BigQuery or Calendar)",
    )
    parser.add_argument(
        "--no-calendar",
        action="store_true",
        help="Scrape and store in BigQuery, but skip Calendar sync",
    )
    parser.add_argument(
        "--team",
        choices=list(SCRAPE_TARGETS.keys()),
        help="Only scrape a specific team",
    )
    args = parser.parse_args()

    # Step 1: Scrape
    print("Scraping promotions...")
    promotions = await scrape_all(args.team)
    print_summary(promotions)

    if args.scrape_only:
        return

    # Step 2: Store in BigQuery
    print("\nStoring in BigQuery...")
    ensure_dataset_and_table()
    count = upsert_promotions(promotions)
    print(f"  Upserted {count} promotions")

    if args.no_calendar:
        return

    # Step 3: Sync to Google Calendar
    print("\nSyncing to Google Calendar...")
    existing_ids = get_existing_calendar_event_ids()
    event_ids = sync_promotions_to_calendar(promotions, existing_ids)
    print(f"  Synced {len(event_ids)} events")

    # Step 4: Save calendar event IDs back to BigQuery
    # This closes the loop: BQ now knows which promo maps to which calendar event
    print("  Saving event IDs to BigQuery...")
    for promo_id, event_id in event_ids.items():
        update_calendar_event_id(promo_id, event_id)
    print("  Done!")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(main())
