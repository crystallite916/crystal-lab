"""
Data models for baseball promotions.
"""

import hashlib
from datetime import date, datetime

from pydantic import BaseModel, computed_field


class Promotion(BaseModel):
    """A single baseball game promotion/giveaway."""

    team_slug: str
    team_name: str
    game_date: date
    game_time: str | None = None
    opponent: str
    promo_name: str
    promo_description: str = ""
    promo_image_url: str | None = None
    promo_category: str = "giveaway"
    source_url: str
    scraped_at: datetime | None = None

    @computed_field
    @property
    def promo_id(self) -> str:
        """Deterministic ID from team + date + promo name."""
        raw = f"{self.team_slug}:{self.game_date}:{self.promo_name}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
