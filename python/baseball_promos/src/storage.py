"""
BigQuery storage layer for baseball promotions.

WHY BIGQUERY?
We use BigQuery as the "source of truth" for all scraped promotions. This serves
three purposes:
1. IDEMPOTENCY: Before creating calendar events, we check if a promo already exists
   in BQ (by promo_id). This prevents duplicate calendar events on re-runs.
2. HISTORY: We can track when promos were last scraped and detect changes.
3. CALENDAR LINKING: After creating a calendar event, we store the event ID in BQ
   so we can update (not duplicate) the event on future runs.

DATA FLOW:
    Scraper → list[Promotion] → upsert_promotions() → BigQuery table
    Calendar sync → updates calendar_event_id column for each promo

UPSERT STRATEGY:
BigQuery doesn't have a native UPSERT command like PostgreSQL. Instead, we use
the MERGE statement, which is BigQuery's way of doing "INSERT or UPDATE":
    - If a row with the same promo_id exists, update it
    - If it doesn't exist, insert a new row
The promo_id is a deterministic hash (sha256 of team_slug + date + promo_name),
so the same promotion always gets the same ID regardless of when you scrape it.
"""

import logging
from datetime import datetime

import pandas as pd
from google.cloud import bigquery

from .config import BQ_DATASET, BQ_FULL_TABLE, BQ_PROJECT_ID
from .models import Promotion
from .utils import get_bigquery_client

logger = logging.getLogger(__name__)

# BigQuery table schema — defines the columns and their types.
# This is used when creating the table for the first time.
TABLE_SCHEMA = [
    bigquery.SchemaField("promo_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("team_name", "STRING"),
    bigquery.SchemaField("team_slug", "STRING"),
    bigquery.SchemaField("game_date", "DATE"),
    bigquery.SchemaField("game_time", "STRING"),
    bigquery.SchemaField("opponent", "STRING"),
    bigquery.SchemaField("promo_name", "STRING"),
    bigquery.SchemaField("promo_description", "STRING"),
    bigquery.SchemaField("promo_image_url", "STRING"),
    bigquery.SchemaField("promo_category", "STRING"),
    bigquery.SchemaField("calendar_event_id", "STRING"),
    bigquery.SchemaField("scraped_at", "TIMESTAMP"),
    bigquery.SchemaField("source_url", "STRING"),
]


def ensure_dataset_and_table() -> None:
    """Create the BigQuery dataset and table if they don't exist.

    This is safe to call on every run — it's a no-op if everything
    already exists. Think of it like 'CREATE TABLE IF NOT EXISTS' in SQL.
    """
    client = get_bigquery_client()

    # Create dataset if it doesn't exist
    dataset_ref = bigquery.DatasetReference(BQ_PROJECT_ID, BQ_DATASET)
    dataset = bigquery.Dataset(dataset_ref)
    dataset.location = "us-central1"
    client.create_dataset(dataset, exists_ok=True)
    logger.info(f"Dataset {BQ_DATASET} ready")

    # Create table if it doesn't exist
    table_ref = dataset_ref.table("promotions")
    table = bigquery.Table(table_ref, schema=TABLE_SCHEMA)
    client.create_table(table, exists_ok=True)
    logger.info(f"Table {BQ_FULL_TABLE} ready")


def upsert_promotions(promotions: list[Promotion]) -> int:
    """Upsert promotions into BigQuery using MERGE.

    HOW MERGE WORKS:
    The MERGE statement compares a "source" (our new data) against a "target"
    (the existing table) on a join key (promo_id). For each row:
    - WHEN MATCHED: Update the existing row with new values
    - WHEN NOT MATCHED: Insert a new row

    We use a temporary table as the source because BigQuery's MERGE requires
    a table reference (not inline values) for large datasets.

    Returns the number of promotions upserted.
    """
    if not promotions:
        logger.info("No promotions to upsert")
        return 0

    client = get_bigquery_client()

    # Convert promotions to a DataFrame for easy loading
    rows = []
    for promo in promotions:
        rows.append(
            {
                "promo_id": promo.promo_id,
                "team_name": promo.team_name,
                "team_slug": promo.team_slug,
                "game_date": promo.game_date,  # Keep as date object for PyArrow
                "game_time": promo.game_time,
                "opponent": promo.opponent,
                "promo_name": promo.promo_name,
                "promo_description": promo.promo_description,
                "promo_image_url": promo.promo_image_url,
                "promo_category": promo.promo_category,
                "calendar_event_id": None,  # Will be set by calendar sync
                "scraped_at": datetime.now(),  # Keep as datetime object for PyArrow
                "source_url": promo.source_url,
            }
        )

    df = pd.DataFrame(rows)

    # Load into a temporary staging table, then MERGE into the main table.
    # WHY A STAGING TABLE? BigQuery MERGE needs a source table to join against.
    # We load our new data into a temp table, merge it, then delete the temp table.
    staging_table = f"{BQ_FULL_TABLE}_staging"

    # Upload DataFrame to staging table (overwrite if exists from a failed run)
    job_config = bigquery.LoadJobConfig(
        schema=TABLE_SCHEMA,
        write_disposition="WRITE_TRUNCATE",  # Overwrite staging table each time
    )
    load_job = client.load_table_from_dataframe(
        df, staging_table, job_config=job_config
    )
    load_job.result()  # Wait for completion
    logger.info(f"Loaded {len(rows)} rows into staging table")

    # MERGE: upsert from staging into the main table
    # This is the core idempotency mechanism — same promo_id = update, new = insert.
    # Note: we DON'T update calendar_event_id in the MERGE — that column is managed
    # separately by the calendar sync step.
    merge_query = f"""
    MERGE `{BQ_FULL_TABLE}` AS target
    USING `{staging_table}` AS source
    ON target.promo_id = source.promo_id
    WHEN MATCHED THEN UPDATE SET
        team_name = source.team_name,
        team_slug = source.team_slug,
        game_date = source.game_date,
        game_time = source.game_time,
        opponent = source.opponent,
        promo_name = source.promo_name,
        promo_description = source.promo_description,
        promo_image_url = source.promo_image_url,
        promo_category = source.promo_category,
        scraped_at = source.scraped_at,
        source_url = source.source_url
    WHEN NOT MATCHED THEN INSERT (
        promo_id, team_name, team_slug, game_date, game_time, opponent,
        promo_name, promo_description, promo_image_url, promo_category,
        calendar_event_id, scraped_at, source_url
    ) VALUES (
        source.promo_id, source.team_name, source.team_slug, source.game_date,
        source.game_time, source.opponent, source.promo_name,
        source.promo_description, source.promo_image_url, source.promo_category,
        source.calendar_event_id, source.scraped_at, source.source_url
    )
    """
    merge_job = client.query(merge_query)
    merge_job.result()  # Wait for completion
    logger.info(f"Merged {len(rows)} promotions into {BQ_FULL_TABLE}")

    # Clean up staging table
    client.delete_table(staging_table, not_found_ok=True)

    return len(rows)


def update_calendar_event_id(promo_id: str, calendar_event_id: str) -> None:
    """Update the calendar_event_id for a specific promotion.

    Called after successfully creating/updating a Google Calendar event.
    This links the BQ record to its calendar event so future runs can
    update the existing event instead of creating a duplicate.
    """
    client = get_bigquery_client()
    query = f"""
    UPDATE `{BQ_FULL_TABLE}`
    SET calendar_event_id = @calendar_event_id
    WHERE promo_id = @promo_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "calendar_event_id", "STRING", calendar_event_id
            ),
            bigquery.ScalarQueryParameter("promo_id", "STRING", promo_id),
        ]
    )
    job = client.query(query, job_config=job_config)
    job.result()


def get_existing_calendar_event_ids() -> dict[str, str]:
    """Fetch all promo_id -> calendar_event_id mappings from BigQuery.

    Used by the calendar sync to check which promos already have events.
    Returns a dict where keys are promo_ids and values are calendar_event_ids.
    Only includes promos that already have a calendar event.
    """
    client = get_bigquery_client()
    query = f"""
    SELECT promo_id, calendar_event_id
    FROM `{BQ_FULL_TABLE}`
    WHERE calendar_event_id IS NOT NULL
    """
    df = client.query(query).to_dataframe()
    return dict(zip(df["promo_id"], df["calendar_event_id"]))
