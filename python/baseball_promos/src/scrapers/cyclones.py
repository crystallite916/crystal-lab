"""
Brooklyn Cyclones (MiLB) promotion scraper.

PAGE STRUCTURE (as of 2026):
The Cyclones page is completely different from the MLB.com pages. Instead of
dedicated promo cards, it uses a "single-game-tickets" (SGT) component that
lists ALL home games in a schedule format. Promotions are listed as accordion
items WITHIN each game's row.

DOM Structure:
    div.sgt-event.game-XXXXXX  →  One game row
      div.sgt__event-info
        Day of week, date, time  →  In text nodes
        Team name  →  Opponent info
      div.p-accordion  →  Expandable section for each promo/highlight/offer
        span.p-accordion__title
          strong  →  Category (e.g., "Promotion:", "Game Highlight:", "Ticket Offer:")
          text    →  Item name (e.g., "Star Trek Jersey Giveaway")
        div.p-wysiwyg  →  Expanded description text

IMPORTANT DIFFERENCES FROM MLB.COM:
1. Promos are mixed in with "Game Highlights" and "Ticket Offers" — we only
   want items where the category starts with "Promotion"
2. One game can have MULTIPLE promotions (e.g., a giveaway + a theme night)
3. There are no individual promo images — the page has a single header image
4. The JSON-LD block contains ALL games (not just promo games), so we use it
   as a lookup for opponent/time data
"""

import logging
import re
from datetime import date, datetime

from playwright.async_api import Page

from ..models import Promotion
from .base import BaseScraper

logger = logging.getLogger(__name__)


class CyclonesScraper(BaseScraper):
    """Scraper for Brooklyn Cyclones promotions."""

    def __init__(self) -> None:
        super().__init__(
            team_slug="brooklyn",
            team_name="Brooklyn Cyclones",
            url="https://www.milb.com/brooklyn/tickets/promotions",
        )

    async def _wait_for_content(self, page: Page) -> None:
        """Wait for the single-game-tickets grid to render."""
        await page.wait_for_selector("div.sgt-event", timeout=15000)

    async def _parse_promotions(self, page: Page) -> list[Promotion]:
        """Parse promotions from the Cyclones schedule grid.

        LESSON LEARNED: The Cyclones JSON-LD only covers ~10 games (the ones
        with ticket grid widgets), not all 61 home games. So we can't rely on
        JSON-LD for game info the way we do for Yankees/Mets.

        Instead, we parse date, time, and opponent directly from the visible
        text in each game row's event-info section. This is the format:
            'Friday\nApr 3\n6:40 PM\n \nHudson Valley\nRenegades\nBuy Tickets'
        """
        game_rows = await page.query_selector_all("div.sgt-event")
        promotions = []

        for row in game_rows:
            try:
                row_promos = await self._parse_game_row(row)
                promotions.extend(row_promos)
            except Exception:
                logger.warning(
                    "Failed to parse a Cyclones game row", exc_info=True
                )

        return promotions

    async def _parse_event_info(self, row) -> tuple[date | None, str | None, str]:
        """Parse date, time, and opponent from the event info text.

        The .sgt__event-info div contains text in this format:
            'Friday\\nApr 3\\n6:40 PM\\n \\nHudson Valley\\nRenegades\\nBuy Tickets'

        We split by newlines and parse:
            Line 0: Day of week (skip)
            Line 1: Abbreviated date (e.g., 'Apr 3')
            Line 2: Time (e.g., '6:40 PM')
            Lines after blank: City + Team name (e.g., 'Hudson Valley' + 'Renegades')
        """
        info_el = await row.query_selector(".sgt__event-info")
        if not info_el:
            return None, None, "TBD"

        text = (await info_el.inner_text()).strip()
        lines = [line.strip() for line in text.split("\n")]

        # Parse date from line 1 (abbreviated month: "Apr 3", "May 29")
        game_date = None
        game_time = None
        opponent = "TBD"

        for i, line in enumerate(lines):
            # Date: look for "Mon DD" pattern (abbreviated month)
            date_match = re.match(
                r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})$",
                line,
            )
            if date_match:
                try:
                    parsed = datetime.strptime(
                        f"{date_match.group(1)} {date_match.group(2)} "
                        f"{datetime.now().year}",
                        "%b %d %Y",
                    )
                    game_date = parsed.date()
                except ValueError:
                    pass

            # Time: look for "H:MM PM" pattern
            time_match = re.match(r"\d{1,2}:\d{2}\s*[AP]M$", line, re.IGNORECASE)
            if time_match:
                game_time = line

        # Opponent: the team name comes after the time and a blank line.
        # We look for the lines between the time and "Buy Tickets".
        # Typically: city name + team name on consecutive lines.
        team_parts = []
        found_time = False
        for line in lines:
            if re.match(r"\d{1,2}:\d{2}\s*[AP]M$", line, re.IGNORECASE):
                found_time = True
                continue
            if found_time and line and line != "Buy Tickets":
                team_parts.append(line)
            elif line == "Buy Tickets":
                break

        if team_parts:
            opponent = " ".join(team_parts)

        return game_date, game_time, opponent

    async def _parse_game_row(self, row) -> list[Promotion]:
        """Parse all promotions from a single game row.

        A game can have multiple promotions (e.g., a bobblehead giveaway
        AND a theme night on the same day). Each promo is an accordion item.
        We only extract items where the category is "Promotion" — we skip
        "Game Highlight" (fireworks, run the bases) and "Ticket Offer" (meal deals).
        """
        # --- Parse game info from the row's event-info text ---
        game_date, game_time, opponent = await self._parse_event_info(row)

        if not game_date:
            return []

        # --- Find all "Promotion:" accordion items in this row ---
        accordion_titles = await row.query_selector_all("span.p-accordion__title")
        promotions = []

        for title_el in accordion_titles:
            # Check if this is a "Promotion:" item (not a Game Highlight or Ticket Offer)
            category_el = await title_el.query_selector("strong")
            if not category_el:
                continue
            category = (await category_el.inner_text()).strip()
            if not category.startswith("Promotion"):
                continue

            # Get the promo name (text after the <strong> tag)
            full_text = (await title_el.inner_text()).strip()
            # Remove the category prefix: "Promotion: Star Trek Jersey" -> "Star Trek Jersey"
            promo_name = re.sub(r"^Promotion\s*(\(\d+\))?:\s*", "", full_text).strip()

            if not promo_name:
                continue

            # Get the expanded description if available
            # The accordion has a sibling div.p-wysiwyg with the description
            accordion_item = await title_el.evaluate_handle(
                "el => el.closest('.p-accordion__item') || el.closest('.p-accordion')"
            )
            description = ""
            if accordion_item:
                desc_el = await accordion_item.query_selector(".p-wysiwyg")
                if desc_el:
                    description = (await desc_el.inner_text()).strip()

            promotions.append(
                Promotion(
                    team_slug=self.team_slug,
                    team_name=self.team_name,
                    game_date=game_date,
                    game_time=game_time,
                    opponent=opponent,
                    promo_name=promo_name,
                    promo_description=description,
                    promo_image_url=None,  # Cyclones page has no per-promo images
                    source_url=self.url,
                )
            )

        return promotions
