"""
Abstract base scraper with shared Playwright lifecycle.

WHY A BASE CLASS?
All 3 sites need the same Playwright setup: launch browser -> navigate -> wait
for React to render -> parse -> close. The base class handles this "ceremony"
so each team scraper only needs to implement the site-specific parsing logic.

This is the Template Method pattern: the base class defines the algorithm skeleton
(scrape), and subclasses fill in the varying steps (_wait_for_content, _parse_promotions).
"""

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime

from playwright.async_api import Page, async_playwright

from ..models import Promotion

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Base class for all team promotion scrapers."""

    def __init__(self, team_slug: str, team_name: str, url: str) -> None:
        self.team_slug = team_slug
        self.team_name = team_name
        self.url = url

    async def scrape(self) -> list[Promotion]:
        """Launch browser, navigate to URL, wait for content, and parse promotions.

        We use 'load' instead of 'networkidle' because ad trackers and analytics
        scripts keep making requests indefinitely, which causes 'networkidle' to
        time out. After the page loads, we give React a few seconds to render
        the promotion content into the DOM.
        """
        max_retries = 2
        logger.info(f"Scraping {self.team_name} promotions from {self.url}")

        for attempt in range(1, max_retries + 1):
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                try:
                    # 90s timeout — MiLB pages can be slow
                    await page.goto(self.url, wait_until="load", timeout=90000)
                    # Give React time to hydrate and render dynamic content.
                    # The initial HTML is mostly empty — the promo data gets
                    # injected by JavaScript after the page loads.
                    await asyncio.sleep(8)
                    await self._wait_for_content(page)
                    promotions = await self._parse_promotions(page)
                    for promo in promotions:
                        promo.scraped_at = datetime.now()
                    logger.info(
                        f"Found {len(promotions)} promotions for {self.team_name}"
                    )
                    return promotions
                except Exception:
                    if attempt < max_retries:
                        logger.warning(
                            f"Attempt {attempt} failed for {self.team_name}, retrying..."
                        )
                    else:
                        logger.exception(f"Failed to scrape {self.team_name}")
                        raise
                finally:
                    await browser.close()

    @abstractmethod
    async def _wait_for_content(self, page: Page) -> None:
        """Wait for promotion content to be rendered on the page."""
        ...

    @abstractmethod
    async def _parse_promotions(self, page: Page) -> list[Promotion]:
        """Parse promotion data from the rendered page."""
        ...

    async def _extract_json_ld(self, page: Page) -> list[dict]:
        """Extract JSON-LD structured data blocks from the page.

        WHY JSON-LD?
        All 3 sites embed machine-readable game data in <script type="application/ld+json">
        tags. This is structured data meant for Google Search — it contains the opponent
        name, game date, start time, and venue in a reliable, standardized format.

        This is far more reliable than parsing DOM text for opponent info, because:
        1. It follows the schema.org standard (won't change with CSS redesigns)
        2. It's the same data Google uses for search results
        3. It includes the game ID we can use to match promos to games
        """
        scripts = await page.query_selector_all('script[type="application/ld+json"]')
        events = []
        for script in scripts:
            text = await script.inner_text()
            try:
                data = json.loads(text)
                # Some pages embed a single object, others embed an array
                if isinstance(data, list):
                    events.extend(data)
                elif isinstance(data, dict):
                    events.append(data)
            except json.JSONDecodeError:
                logger.warning("Failed to parse JSON-LD block")
        return events

    def _extract_image_url(self, srcset: str | None) -> str | None:
        """Extract the best (largest) image URL from a srcset attribute.

        WHY SRCSET?
        MLB uses responsive images — the <img> tag has a srcset attribute with
        multiple URLs at different resolutions (372w, 640w, 1024w, etc.).
        We pick the 1024w version: big enough to look good in a calendar event,
        but not unnecessarily huge.
        """
        if not srcset:
            return None
        # srcset format: "//url1 2208w, //url2 1536w, //url3 1024w, ..."
        # Parse into (url, width) pairs
        parts = [p.strip() for p in srcset.split(",")]
        url_width_pairs = []
        for part in parts:
            match = re.match(r"(.*?)\s+(\d+)w", part.strip())
            if match:
                url = match.group(1).strip()
                width = int(match.group(2))
                url_width_pairs.append((url, width))

        if not url_width_pairs:
            return None

        # Prefer 1024w, fall back to the largest available
        for url, width in url_width_pairs:
            if width == 1024:
                return f"https:{url}" if url.startswith("//") else url

        # Fallback: use largest
        url_width_pairs.sort(key=lambda x: x[1], reverse=True)
        url = url_width_pairs[0][0]
        return f"https:{url}" if url.startswith("//") else url

    async def _save_debug_html(self, page: Page, filename: str) -> None:
        """Save rendered HTML for debugging when parsing fails.

        When a scraper breaks (MLB redesigns their page), this lets you
        dump the actual HTML to a file so you can inspect it and update
        the CSS selectors.
        """
        html = await page.content()
        with open(filename, "w") as f:
            f.write(html)
        logger.info(f"Debug HTML saved to {filename}")
