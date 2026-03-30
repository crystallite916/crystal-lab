"""
Mets promotion scraper.

PAGE STRUCTURE (as of 2026):
The Mets giveaways page uses a grid list (p-forge-list) with one item per promo.
Each promo item has this DOM structure:

    div.p-forge-list-item (id = date like "3-29-26")
      div.l-grid__content-title  →  Promo name (e.g., "5-BOROUGH RACE KIDS PUZZLE")
      div.p-image
        img[srcset]  →  Promo item photo at multiple resolutions
      h1.p-heading__text  →  Eligibility (e.g., "First 5,000 Kids 12 and Under")
      div[data-testid="TicketGridWrapper"]
        script[type="application/ld+json"]  →  Opponent, time, game ID

KEY DIFFERENCE FROM YANKEES:
- Promo name is in div.l-grid__content-title (not a heading before the card)
- Eligibility is in h1.p-heading__text (not p tags in wysiwyg)
- The list item ID is the date in M-DD-YY format (e.g., "3-29-26")
"""

import logging
import re
from datetime import date, datetime

from playwright.async_api import Page

from ..models import Promotion
from .base import BaseScraper

logger = logging.getLogger(__name__)

CURRENT_SEASON_YEAR = datetime.now().year


class MetsScraper(BaseScraper):
    """Scraper for Mets giveaway promotions."""

    def __init__(self) -> None:
        super().__init__(
            team_slug="mets",
            team_name="Mets",
            url="https://www.mlb.com/mets/tickets/promotions/giveaways",
        )

    async def _wait_for_content(self, page: Page) -> None:
        """Wait for the promo list items to render."""
        await page.wait_for_selector(
            "div.p-forge-list-item", timeout=15000
        )

    async def _parse_promotions(self, page: Page) -> list[Promotion]:
        """Parse all giveaway items from the Mets page.

        Similar approach to Yankees:
        1. Build date -> event lookup from JSON-LD
        2. Find all list items and extract promo data
        3. Match to JSON-LD by date for opponent/time
        """
        # Step 1: JSON-LD event lookup
        json_ld_events = await self._extract_json_ld(page)
        events_by_date: dict[str, dict] = {}
        for event in json_ld_events:
            if event.get("@type") == "SportsEvent" and "startDate" in event:
                events_by_date[event["startDate"]] = event

        # Step 2: Find all promo list items
        # Each item has an id like "3-29-26" (month-day-year)
        items = await page.query_selector_all("div.p-forge-list-item")
        promotions = []

        for item in items:
            try:
                promo = await self._parse_single_item(item, events_by_date)
                if promo:
                    promotions.append(promo)
            except Exception:
                logger.warning("Failed to parse a Mets promo item", exc_info=True)

        return promotions

    async def _parse_single_item(
        self, item, events_by_date: dict[str, dict]
    ) -> Promotion | None:
        """Parse a single Mets promo list item into a Promotion."""
        # --- Promo Name ---
        # Found in div.l-grid__content-title, the title of the grid cell
        title_el = await item.query_selector("div.l-grid__content-title")
        promo_name = None
        if title_el:
            promo_name = (await title_el.inner_text()).strip()

        if not promo_name:
            return None

        # --- Date ---
        # The list item's id attribute is the date in M-DD-YY format.
        # e.g., id="3-29-26" means March 29, 2026.
        # This is actually more reliable than parsing text!
        item_id = await item.get_attribute("id")
        game_date = self._parse_item_id_date(item_id)

        if not game_date:
            logger.warning(f"No date for Mets promo: {promo_name}")
            return None

        # --- Image ---
        img_el = await item.query_selector("div.p-image img")
        image_url = None
        if img_el:
            srcset = await img_el.get_attribute("srcset")
            image_url = self._extract_image_url(srcset)

        # --- Eligibility / Details ---
        # The heading under the image shows eligibility info
        heading_el = await item.query_selector("h1.p-heading__text")
        description = ""
        if heading_el:
            description = (await heading_el.inner_text()).strip()

        # --- Opponent and Time (from JSON-LD) ---
        date_str = game_date.isoformat()
        event = events_by_date.get(date_str, {})
        opponent = self._extract_opponent(event.get("name", ""))
        game_time = self._extract_time(event.get("description", ""))

        return Promotion(
            team_slug=self.team_slug,
            team_name=self.team_name,
            game_date=game_date,
            game_time=game_time,
            opponent=opponent,
            promo_name=promo_name,
            promo_description=description,
            promo_image_url=image_url,
            source_url=self.url,
        )

    def _parse_item_id_date(self, item_id: str | None) -> date | None:
        """Parse a date from the list item's id attribute.

        The id format is 'M-DD-YY' (e.g., '3-29-26' for March 29, 2026).
        This is handy because it's a stable, unambiguous identifier that
        doesn't require us to parse natural language dates.
        """
        if not item_id:
            return None
        try:
            parsed = datetime.strptime(item_id, "%m-%d-%y")
            return parsed.date()
        except ValueError:
            # Might not be a date-formatted id
            logger.debug(f"Item id '{item_id}' is not a date")
            return None

    def _extract_opponent(self, event_name: str) -> str:
        """Extract opponent from 'Opponent at Mets' format."""
        if " at " in event_name:
            return event_name.split(" at ")[0].strip()
        return event_name or "TBD"

    def _extract_time(self, description: str) -> str | None:
        """Extract game time from JSON-LD description string."""
        match = re.search(r"at (\d{1,2}:\d{2}\s*[AP]M)", description, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None
