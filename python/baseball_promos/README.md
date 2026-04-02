# Baseball Promos

Scrape baseball promotion and giveaway schedules from MLB and MiLB team websites, store them in BigQuery, and sync them to Google Calendar with event details and images.

## Why This Exists

MLB and MiLB teams run promotional events throughout the season — bobblehead giveaways, jersey nights, themed events, fireworks shows, etc. But this info is scattered across individual team websites with no unified view. This project scrapes promotion schedules from 3 teams and puts them on your Google Calendar so you can plan which games to attend at a glance.

## Teams Covered

| Team | League | Source URL |
|------|--------|-----------|
| New York Yankees | MLB | [Promotional Schedule](https://www.mlb.com/yankees/tickets/promotions/schedule) |
| New York Mets | MLB | [Gate Giveaways](https://www.mlb.com/mets/tickets/promotions/giveaways) |
| Brooklyn Cyclones | MiLB (High-A) | [Promotions](https://www.milb.com/brooklyn/tickets/promotions) |

## Architecture

```
[3 Team Websites] → Playwright (headless browser) → list[Promotion]
                                                          │
                                                          ├──→ BigQuery (upsert)
                                                          │
                                                          └──→ Google Calendar (sync)
```

### Why Playwright?

All 3 sites are React single-page applications. The initial HTML the server sends is essentially empty — all the promotion data is loaded by JavaScript after the page renders. A simple HTTP request (like `requests.get()`) would only get the empty shell. Playwright launches a real Chromium browser in headless mode, waits for React to finish rendering, and then we can read the fully-populated DOM.

### Why BigQuery?

BigQuery serves as the source of truth between scraping and calendar sync. It enables:
- **Idempotency** — the MERGE (upsert) strategy means re-running the scraper updates existing records instead of creating duplicates
- **Calendar linking** — each promotion's Google Calendar event ID is stored in BQ, so future runs can update existing events instead of creating new ones
- **History** — timestamps track when each promotion was last scraped

### Why OAuth (not a Service Account) for Calendar?

Google Calendar is a personal API. A service account would create events on its own invisible calendar. To create events on *your* calendar, we need OAuth 2.0 which authenticates as your Google account (`crystallite916@gmail.com`).

## Data Model

Each promotion is stored as a `Promotion` object with a deterministic `promo_id` (SHA-256 hash of `team_slug + game_date + promo_name`). This means the same promotion always gets the same ID, enabling reliable upserts.

| Field | Description |
|-------|-------------|
| `promo_id` | Deterministic hash (primary key) |
| `team_slug` | `yankees`, `mets`, or `brooklyn` |
| `game_date` | Date of the game |
| `game_time` | Start time (e.g., `7:05 PM`) |
| `opponent` | Opposing team name |
| `promo_name` | Name of the promotion item |
| `promo_description` | Eligibility details, sponsor info |
| `promo_image_url` | URL to the promotion item image (MLB CDN) |
| `calendar_event_id` | Google Calendar event ID (set after sync) |

## Setup

### Prerequisites

- Python 3.12+ with the crystal-lab virtual environment
- GCP project: `instant-bonfire-481001-c0`
- `gcloud` CLI installed and authenticated (for BigQuery via Application Default Credentials)

### 1. Install Dependencies

```bash
cd crystal-lab
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
playwright install chromium
```

### 2. Set Up BigQuery Auth (one-time per machine)

```bash
gcloud auth application-default login
```

This opens a browser to authenticate with your Google account. The BigQuery client picks up these credentials automatically — no key file needed.

### 3. Set Up Google Calendar OAuth (one-time)

1. Go to [GCP Console > APIs & Services > Credentials](https://console.cloud.google.com/apis/credentials)
2. Click **Create Credentials > OAuth 2.0 Client ID**
3. Application type: **Desktop application**
4. Download the JSON file
5. Save it as `crystal-lab/credentials/calendar_oauth_client.json`
6. Enable the **Google Calendar API**: [APIs & Services > Library](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com)
7. Configure the **OAuth consent screen**: [APIs & Services > OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent)
   - Add `crystallite916@gmail.com` as a test user (required while the app is in "Testing" mode)

The first time you run the full pipeline, a browser window will open asking you to authorize calendar access. After that, a refresh token is saved to `credentials/calendar_token.json` and future runs are fully automated.

## Usage

All commands should be run from the crystal-lab root directory with the venv activated.

```bash
# Scrape all 3 teams and print results (no BigQuery or Calendar)
python python/baseball_promos/run.py --scrape-only

# Scrape a single team
python python/baseball_promos/run.py --team yankees --scrape-only

# Scrape + store in BigQuery (skip Calendar)
python python/baseball_promos/run.py --no-calendar

# Full pipeline: scrape → BigQuery → Google Calendar
python python/baseball_promos/run.py
```

### Command Line Options

| Flag | Description |
|------|-------------|
| `--scrape-only` | Scrape and print results. No BigQuery or Calendar writes. |
| `--no-calendar` | Scrape and store in BigQuery, but skip Calendar sync. |
| `--team <slug>` | Only scrape one team. Choices: `yankees`, `mets`, `brooklyn`. |

## Project Structure

```
python/baseball_promos/
  __init__.py
  run.py                     # Entry point: python python/baseball_promos/run.py
  src/
    __init__.py
    config.py                # GCP settings, scrape target URLs, calendar config
    models.py                # Pydantic Promotion model with computed promo_id
    main.py                  # Orchestrator: scrape → store → sync
    utils.py                 # Facade over shared.utils
    storage.py               # BigQuery MERGE (upsert) + calendar event ID tracking
    calendar_sync.py         # OAuth flow + idempotent event create/update
    scrapers/
      __init__.py            # Exports SCRAPERS registry
      base.py                # Abstract base: Playwright lifecycle, JSON-LD, srcset
      yankees.py             # Yankees: featured-content cards + heading names
      mets.py                # Mets: forge-list items with date-based IDs
      cyclones.py            # Cyclones: SGT event rows + accordion promotions
  tests/
    __init__.py
```

## How the Scrapers Work

Each team website has a different DOM structure, so each has its own scraper class. But they all share a common pattern defined in `base.py`:

1. **Launch Playwright** → open headless Chromium
2. **Navigate** → load the page with `wait_until="load"` (not `networkidle`, which hangs due to ad trackers)
3. **Wait for React** → sleep 8 seconds, then wait for a specific CSS selector that confirms the promos are rendered
4. **Extract JSON-LD** → parse `<script type="application/ld+json">` blocks for opponent/time data (schema.org structured data, more reliable than DOM text)
5. **Parse promo cards** → site-specific CSS selectors to extract names, images, dates, descriptions
6. **Return** → list of `Promotion` objects

For a detailed tutorial on how the DOM selectors were discovered, see [docs/scraper_tutorial.md](docs/scraper_tutorial.md).

## Calendar Event Format

Events appear on your Google Calendar like this:

- **Title:** `[Yankees] Star Wars Bobblehead - vs Orioles`
- **Time:** Game start time with a 3-hour duration (or all-day if time is unknown)
- **Description:** HTML with eligibility details, a link to the team site, and an embedded promo item image (when available)

Events are tagged with a hidden `promo_id` in extended properties, enabling idempotent updates on re-runs.

## Maintenance Notes

- **MLB.com redesigns annually.** When selectors break, use Playwright to dump the rendered HTML and inspect the new structure. See the [scraper tutorial](docs/scraper_tutorial.md) for the debugging workflow.
- **Promotion schedules are usually published before the season** (March) with occasional mid-season additions. Running the scraper weekly during the season is sufficient.
- **OAuth tokens don't expire** unless you revoke them. The refresh token in `calendar_token.json` auto-renews the access token on each run.
