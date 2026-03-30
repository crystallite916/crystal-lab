"""
Google Calendar sync for baseball promotions.

AUTHENTICATION:
We use OAuth 2.0 (not a service account) because Google Calendar is a personal
API — a service account would create events on its own hidden calendar, not yours.
The flow works like this:
    1st run: Opens your browser → Google login → "Allow access?" → saves token
    Future runs: Uses the saved refresh token automatically (no browser needed)

IDEMPOTENCY:
Each calendar event gets a hidden metadata tag (extendedProperties.private.promo_id)
containing our deterministic promo hash. On re-runs:
    - Search for events with matching promo_id
    - If found → update the existing event (e.g., if the description changed)
    - If not found → create a new event
This ensures you never get duplicate events, even if you run the scraper daily.

EVENT FORMAT:
    Summary:  [Yankees] Star Wars Bobblehead - vs Red Sox
    Description: HTML with promo details, eligibility, and an image tag
    When: Timed event if we know game time, all-day event otherwise
"""

import logging
from datetime import date, datetime, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import CALENDAR_ID, CALENDAR_OAUTH_CLIENT_FILE, CALENDAR_SCOPES, CALENDAR_TOKEN_FILE
from .models import Promotion

logger = logging.getLogger(__name__)


def get_calendar_service():
    """Build an authorized Google Calendar API service.

    HOW OAUTH TOKEN CACHING WORKS:
    - First run: No token file exists → runs the OAuth consent flow
      (opens browser, you log in, grant permission)
    - The resulting credentials (access token + refresh token) are saved
      to calendar_token.json in the credentials/ directory
    - Next run: Loads the saved token. If it's expired, the refresh token
      is used to get a new access token automatically (no browser needed).
    - The refresh token itself doesn't expire unless you revoke it.
    """
    creds = None

    # Try to load existing credentials from the saved token file
    if CALENDAR_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(
            str(CALENDAR_TOKEN_FILE), CALENDAR_SCOPES
        )

    # If no valid credentials, run the OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Token expired but we have a refresh token → auto-refresh
            creds.refresh(Request())
        else:
            # No token at all → need user consent (opens browser)
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CALENDAR_OAUTH_CLIENT_FILE), CALENDAR_SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save credentials for next run
        with open(CALENDAR_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        logger.info(f"Calendar credentials saved to {CALENDAR_TOKEN_FILE}")

    # Build and return the Calendar API service
    # This is a thin wrapper around the REST API that gives us Python methods
    # like service.events().list(), service.events().insert(), etc.
    return build("calendar", "v3", credentials=creds)


def sync_promotions_to_calendar(
    promotions: list[Promotion],
    existing_event_ids: dict[str, str] | None = None,
) -> dict[str, str]:
    """Sync a list of promotions to Google Calendar.

    Args:
        promotions: List of Promotion objects to sync
        existing_event_ids: Optional dict of promo_id -> calendar_event_id
            from BigQuery. If provided, skips the Calendar API lookup for
            promos that already have a known event ID.

    Returns:
        Dict mapping promo_id -> calendar_event_id for all synced events.
        (Used to update BigQuery with the event IDs.)

    The sync is idempotent: running it twice produces the same result.
    """
    service = get_calendar_service()
    if existing_event_ids is None:
        existing_event_ids = {}

    result: dict[str, str] = {}

    for promo in promotions:
        try:
            event_id = _sync_single_promotion(
                service, promo, existing_event_ids.get(promo.promo_id)
            )
            if event_id:
                result[promo.promo_id] = event_id
        except Exception:
            logger.warning(
                f"Failed to sync calendar event for: {promo.promo_name}",
                exc_info=True,
            )

    logger.info(f"Synced {len(result)} events to Google Calendar")
    return result


def _sync_single_promotion(
    service,
    promo: Promotion,
    known_event_id: str | None,
) -> str | None:
    """Create or update a single calendar event for a promotion.

    WHY WE CHECK BOTH BigQuery AND Calendar API:
    1. If BigQuery has a calendar_event_id → try to update that event directly
    2. If not → search Calendar by extendedProperties as a fallback
       (handles the case where BQ was wiped but calendar events still exist)
    3. If neither finds a match → create a new event
    """
    event_body = _build_event_body(promo)

    # Strategy 1: Use the known event ID from BigQuery
    if known_event_id:
        try:
            service.events().update(
                calendarId=CALENDAR_ID,
                eventId=known_event_id,
                body=event_body,
            ).execute()
            logger.debug(f"Updated event {known_event_id} for {promo.promo_name}")
            return known_event_id
        except Exception:
            # Event might have been deleted manually — fall through to search
            logger.debug(f"Event {known_event_id} not found, will search or create")

    # Strategy 2: Search for existing event by promo_id in extendedProperties
    # The Calendar API lets you filter by private extended properties, which
    # is how we tag events with our promo_id.
    existing = _find_event_by_promo_id(service, promo.promo_id)
    if existing:
        event_id = existing["id"]
        service.events().update(
            calendarId=CALENDAR_ID,
            eventId=event_id,
            body=event_body,
        ).execute()
        logger.debug(f"Updated found event {event_id} for {promo.promo_name}")
        return event_id

    # Strategy 3: Create a new event
    created = service.events().insert(
        calendarId=CALENDAR_ID,
        body=event_body,
    ).execute()
    event_id = created["id"]
    logger.info(f"Created event {event_id} for {promo.promo_name}")
    return event_id


def _build_event_body(promo: Promotion) -> dict:
    """Build a Google Calendar event body from a Promotion.

    EVENT STRUCTURE:
    - summary: Short title with team tag and opponent
    - description: HTML with full details and promo image
    - start/end: Timed event if game time is known, all-day otherwise
    - extendedProperties.private: Hidden metadata with promo_id for lookup
    """
    summary = f"[{promo.team_name}] {promo.promo_name} - vs {promo.opponent}"

    # Build HTML description with promo details and image
    # Google Calendar supports basic HTML in the description field
    desc_parts = []
    if promo.promo_description:
        desc_parts.append(f"<b>{promo.promo_description}</b>")
    desc_parts.append(f"vs {promo.opponent}")
    if promo.game_time:
        desc_parts.append(f"Game time: {promo.game_time}")
    if promo.promo_image_url:
        # Embed the image — Google Calendar renders <img> tags in descriptions
        desc_parts.append(f'<br><img src="{promo.promo_image_url}" width="300">')
    desc_parts.append(f'<br><a href="{promo.source_url}">View on team site</a>')

    description = "<br>".join(desc_parts)

    # Build start/end times
    # If we know the game time, create a timed event (assume ~3 hour game).
    # If not, create an all-day event.
    if promo.game_time:
        start, end = _build_timed_event(promo.game_date, promo.game_time)
    else:
        start = {"date": promo.game_date.isoformat()}
        end = {"date": promo.game_date.isoformat()}

    return {
        "summary": summary,
        "description": description,
        "start": start,
        "end": end,
        "extendedProperties": {
            "private": {
                "promo_id": promo.promo_id,
                "team_slug": promo.team_slug,
            }
        },
    }


def _build_timed_event(
    game_date: date, game_time: str
) -> tuple[dict, dict]:
    """Convert a date + time string into Calendar API start/end dicts.

    Game time comes in various formats: '7:05PM', '7:05 PM', '1:35PM'.
    We parse it and create a 3-hour event window (typical baseball game length).
    """
    # Normalize time format: ensure space before AM/PM
    time_str = game_time.strip().upper()
    if "AM" in time_str and " AM" not in time_str:
        time_str = time_str.replace("AM", " AM")
    if "PM" in time_str and " PM" not in time_str:
        time_str = time_str.replace("PM", " PM")

    try:
        game_datetime = datetime.strptime(
            f"{game_date.isoformat()} {time_str}", "%Y-%m-%d %I:%M %p"
        )
        end_datetime = game_datetime + timedelta(hours=3)

        # Use dateTime format with timezone (ET for all our teams)
        return (
            {"dateTime": game_datetime.isoformat(), "timeZone": "America/New_York"},
            {"dateTime": end_datetime.isoformat(), "timeZone": "America/New_York"},
        )
    except ValueError:
        logger.warning(f"Could not parse time '{game_time}', using all-day event")
        return (
            {"date": game_date.isoformat()},
            {"date": game_date.isoformat()},
        )


def _find_event_by_promo_id(service, promo_id: str) -> dict | None:
    """Search for a calendar event by its promo_id extended property.

    The Calendar API supports filtering events by private extended properties,
    which is how we find events we've previously created. This avoids the need
    to list ALL events and filter client-side.
    """
    events_result = (
        service.events()
        .list(
            calendarId=CALENDAR_ID,
            privateExtendedProperty=f"promo_id={promo_id}",
            maxResults=1,
        )
        .execute()
    )
    items = events_result.get("items", [])
    return items[0] if items else None
