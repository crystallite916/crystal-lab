"""
Yankees promotion scraper.

PAGE STRUCTURE (as of 2026):
The Yankees promo page renders a list of "featured content" cards, one per promotion.
Each card has this DOM structure:

    h1/h4.p-heading__text  →  Promo name (e.g., "Calendar Night")
    div.p-featured-content
      div.p-featured-content__media  →  Contains the promo image
        img[srcset]  →  Multiple resolutions of the promo item photo
      div.p-featured-content__body
        div.p-wysiwyg
          h4  →  Date (e.g., "Saturday, April 4")
          p   →  Eligibility (e.g., "1st 40,000 Guests")
          p   →  Sponsor (e.g., "Presented by Mastercard")
    div[data-testid="TicketGridWrapper"]
      script[type="application/ld+json"]  →  JSON-LD with opponent, time, game ID

SCRAPING STRATEGY:
1. Find all p-featured-content cards
2. For each card, extract: promo name (from preceding heading), image, date, details
3. Match each card to its JSON-LD block (by date) to get opponent and game time
"""

import logging
import re
from datetime import date, datetime

from playwright.async_api import Page

from ..models import Promotion
from .base import BaseScraper

logger = logging.getLogger(__name__)

# Year to assume for dates that don't include a year (e.g., "April 4")
CURRENT_SEASON_YEAR = datetime.now().year


class YankeesScraper(BaseScraper):
    """Scraper for Yankees promotional schedule."""

    def __init__(self) -> None:
        super().__init__(
            team_slug="yankees",
            team_name="Yankees",
            url="https://www.mlb.com/yankees/tickets/promotions/schedule",
        )

    async def _wait_for_content(self, page: Page) -> None:
        """Wait for the promo cards to render.

        We look for the featured-content cards — if these are in the DOM,
        React has finished rendering the promotion list.
        """
        await page.wait_for_selector(
            "div.p-featured-content", timeout=15000
        )

    async def _parse_promotions(self, page: Page) -> list[Promotion]:
        """Parse all promotion cards from the Yankees page.

        The approach:
        1. First, collect all JSON-LD events into a lookup dict keyed by date.
           This gives us opponent + game time for each date.
        2. Then iterate through each featured-content card and extract the
           promo-specific info (name, image, date, eligibility).
        3. Match each promo card to its JSON-LD event by date.
        """
        # Step 1: Build a date -> event lookup from JSON-LD
        # JSON-LD is the most reliable source for opponent/time info because
        # it's structured data (schema.org), not brittle CSS-dependent text.
        json_ld_events = await self._extract_json_ld(page)
        events_by_date: dict[str, dict] = {}
        for event in json_ld_events:
            if event.get("@type") == "SportsEvent" and "startDate" in event:
                events_by_date[event["startDate"]] = event

        # Step 2: Find all promo cards
        # Each card is a div.p-featured-content, but the promo NAME is in a
        # heading element BEFORE the card (a sibling in the parent container).
        cards = await page.query_selector_all("div.p-featured-content")
        promotions = []

        for card in cards:
            try:
                promo = await self._parse_single_card(card, events_by_date)
                if promo:
                    promotions.append(promo)
            except Exception:
                logger.warning("Failed to parse a Yankees promo card", exc_info=True)

        return promotions

    async def _parse_single_card(
        self, card, events_by_date: dict[str, dict]
    ) -> Promotion | None:
        """Parse a single featured-content card into a Promotion.

        Returns None if we can't extract enough data to be useful.
        """
        # --- Promo Name ---
        # The promo name is in a heading element that's a SIBLING of this card,
        # placed just before it in the DOM. We navigate to the parent container
        # and look for the heading there.
        parent = await card.evaluate_handle("el => el.closest('.l-grid__content')")
        promo_name = None
        if parent:
            heading_el = await parent.query_selector(
                ".p-heading__text"
            )
            if heading_el:
                promo_name = (await heading_el.inner_text()).strip()

        if not promo_name:
            # Skip cards without a name — likely not a real promo
            return None

        # --- Image ---
        # The promo image is inside the media section of the card.
        # We extract from srcset to get the 1024w version.
        img_el = await card.query_selector(
            "div.p-featured-content__media img"
        )
        image_url = None
        if img_el:
            srcset = await img_el.get_attribute("srcset")
            image_url = self._extract_image_url(srcset)

        # --- Date and Details ---
        # The date is in an h4 inside the wysiwyg content area.
        # Additional paragraphs contain eligibility and sponsor info.
        body = await card.query_selector("div.p-featured-content__body")
        game_date = None
        details_parts = []

        if body:
            date_el = await body.query_selector("h4")
            if date_el:
                date_text = (await date_el.inner_text()).strip()
                game_date = self._parse_date(date_text)

            # Collect all <p> text as extra details (eligibility, sponsor)
            p_elements = await body.query_selector_all("p")
            for p_el in p_elements:
                text = (await p_el.inner_text()).strip()
                if text:
                    details_parts.append(text)

        if not game_date:
            logger.warning(f"No date found for promo: {promo_name}")
            return None

        # --- Opponent and Time (from JSON-LD) ---
        # The JSON-LD events are keyed by ISO date (e.g., "2026-04-04").
        # The "name" field has format "Opponent at Yankees".
        date_str = game_date.isoformat()
        event = events_by_date.get(date_str, {})
        opponent = self._extract_opponent(event.get("name", ""))
        game_time = self._extract_time(event.get("description", ""))

        description = " | ".join(details_parts) if details_parts else ""

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

    def _parse_date(self, text: str) -> date | None:
        """Parse a date string like 'Saturday, April 4' into a date object.

        The page only shows month and day (no year), so we assume the current
        baseball season year. If the date is before the season starts and we're
        past that month, it might be next year — but for simplicity we just
        use the current year since promos are always for the upcoming/current season.
        """
        # Remove day-of-week prefix: "Saturday, April 4" -> "April 4"
        text = re.sub(r"^\w+,\s*", "", text.strip())
        try:
            parsed = datetime.strptime(f"{text} {CURRENT_SEASON_YEAR}", "%B %d %Y")
            return parsed.date()
        except ValueError:
            logger.warning(f"Could not parse date: '{text}'")
            return None

    def _extract_opponent(self, event_name: str) -> str:
        """Extract opponent name from JSON-LD event name.

        Format is 'Opponent at Yankees' (e.g., 'Marlins at Yankees').
        We want just 'Marlins'.
        """
        if " at " in event_name:
            return event_name.split(" at ")[0].strip()
        return event_name or "TBD"

    def _extract_time(self, description: str) -> str | None:
        """Extract game time from JSON-LD event description.

        Format: 'Miami Marlins at New York Yankees on April 4, 2026 at 7:05PM EDT'
        We want '7:05 PM'.
        """
        match = re.search(r"at (\d{1,2}:\d{2}\s*[AP]M)", description, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None
