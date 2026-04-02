"""
Configuration for the baseball_promos project.
Facade over shared.config with project-specific constants.
"""

from shared.config import (
    PROJECT_ROOT,
    BQ_PROJECT_ID,
)

# BigQuery
BQ_DATASET = "baseball_promos"
BQ_TABLE = "promotions"
BQ_FULL_TABLE = f"{BQ_PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE}"

# Google Calendar OAuth
CALENDAR_ID = "primary"
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]
CALENDAR_OAUTH_CLIENT_FILE = PROJECT_ROOT / "credentials/calendar_oauth_client.json"
CALENDAR_TOKEN_FILE = PROJECT_ROOT / "credentials/calendar_token.json"

# Scrape targets
SCRAPE_TARGETS = {
    "yankees": {
        "url": "https://www.mlb.com/yankees/tickets/promotions/schedule",
        "team_name": "Yankees",
    },
    "mets": {
        "url": "https://www.mlb.com/mets/tickets/promotions/giveaways",
        "team_name": "Mets",
    },
    "brooklyn": {
        "url": "https://www.milb.com/brooklyn/tickets/promotions",
        "team_name": "Brooklyn Cyclones",
    },
}
