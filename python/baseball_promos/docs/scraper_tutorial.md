# Scraper Development Tutorial

How to reverse-engineer a JavaScript-rendered webpage and build a scraper for it. This documents the exact process used to build the Yankees, Mets, and Brooklyn Cyclones scrapers — and the process you'd follow to fix them when they break or add a new team.

## Table of Contents

1. [The Problem: Empty HTML](#1-the-problem-empty-html)
2. [Step 1: Capture the Rendered Page](#2-step-1-capture-the-rendered-page)
3. [Step 2: Find the Promotion Cards](#3-step-2-find-the-promotion-cards)
4. [Step 3: Map the Card Structure](#4-step-3-map-the-card-structure)
5. [Step 4: Find the Opponent and Time Data](#5-step-4-find-the-opponent-and-time-data)
6. [Step 5: Handle Site Differences](#6-step-5-handle-site-differences)
7. [Step 6: Debug and Fix Issues](#7-step-6-debug-and-fix-issues)
8. [Quick Reference: Common Patterns](#8-quick-reference-common-patterns)

---

## 1. The Problem: Empty HTML

All three team websites (mlb.com, milb.com) are React single-page applications. If you do a simple HTTP request:

```python
import requests
html = requests.get("https://www.mlb.com/yankees/tickets/promotions/schedule").text
```

You get back a page full of `<script>` tags, CSS imports, and tracking pixels — but **zero promotion data**. The actual content is loaded by JavaScript *after* the page renders in a browser.

This is why we need Playwright: it launches a real Chromium browser, executes all the JavaScript, waits for React to render, and *then* lets us read the final DOM.

## 2. Step 1: Capture the Rendered Page

The first step is always the same: use Playwright to load the page and dump the complete rendered HTML to a file for inspection.

```python
import asyncio
from playwright.async_api import async_playwright

async def dump_page(url, filename):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # 'load' not 'networkidle' — ad trackers keep making requests
        # forever, so networkidle often times out
        await page.goto(url, wait_until='load', timeout=60000)

        # Give React time to hydrate and render the promotion content.
        # 8 seconds is generous — most pages render in 2-3 seconds,
        # but we want to be safe.
        await asyncio.sleep(8)

        html = await page.content()
        with open(filename, 'w') as f:
            f.write(html)
        print(f'{filename}: {len(html)} chars')
        await browser.close()

asyncio.run(dump_page(
    'https://www.mlb.com/yankees/tickets/promotions/schedule',
    '/tmp/yankees.html'
))
```

**Why `wait_until='load'` instead of `'networkidle'`?**

Playwright's `networkidle` waits until there are no network requests for 500ms. But MLB pages have ad trackers (Adobe Analytics, Google Tag Manager, Twitter pixels) that make requests continuously. The page content is ready in 2-3 seconds, but `networkidle` hangs for 60+ seconds waiting for tracking scripts to settle — and often times out entirely.

Using `load` (fires when the page's main resources are loaded) plus an explicit sleep is more reliable.

**Tip:** Save these HTML dumps — they're useful as test fixtures and for debugging when selectors break.

## 3. Step 2: Find the Promotion Cards

Now you have a giant HTML file (the Yankees page was ~1MB). The challenge is finding the repeating DOM element that represents each promotion. Here's the investigative process:

### Search for known content

Start by searching for text you can see on the page — promotion names, dates, etc.

```python
import re

with open('/tmp/yankees.html') as f:
    html = f.read()

# Search for date patterns — these should exist if the page rendered
dates = re.findall(
    r'(January|February|March|April|May|June|July|August|September|'
    r'October|November|December)\s+\d{1,2}',
    html
)
print(f"Dates found: {dates[:15]}")
# Output: ['April 4', 'April 4', 'April 17', 'April 17', ...]
```

Dates appearing in pairs (duplicated) is a clue — each date likely appears once in the promo card text *and* once in the ticket grid.

### Search for heading text

```python
# CSS class patterns for headings — MLB uses 'p-heading__text'
headings = re.findall(r'p-heading__text[^"]*"[^>]*>([^<]+)<', html)
print(f"Headings: {headings[:20]}")
```

This gave us:
```
['Yankees Promotional Schedule', 'Calendar Night', 'Yankees Hockey Jersey Night',
 'Hersheypark Kids Ticket Giveaway Day', 'Star Wars Day - Max Fried Mandalorian
 Bobblehead', 'Cap Night', ...]
```

Those are promotion names. Now we know they're in elements with class `p-heading__text`.

### Find the card container

The key technique: **search for a known element and look at its surrounding HTML context.** Since the HTML is minified (one long line), we need to add line breaks before tags to make it readable.

```python
# Find first promo name and show 2000 chars of surrounding context
idx = html.find('Calendar Night')
snippet = html[max(0, idx-300):idx+2500]

# Pretty-print by adding newlines before block-level tags
readable = re.sub(
    r'(<[/]?(?:div|section|article|h[1-6]|img|a|span|p))',
    r'\n\1',
    snippet
)
print(readable[:3000])
```

This revealed the card structure (see next section).

## 4. Step 3: Map the Card Structure

After inspecting the context around "Calendar Night", the Yankees page structure became clear:

```
Yankees Card Structure:
━━━━━━━━━━━━━━━━━━━━━━

h1.p-heading__text → "Calendar Night"          ← PROMO NAME

div.p-featured-content                         ← CARD CONTAINER
  ├── div.p-featured-content__media
  │     └── img[srcset]                        ← PROMO IMAGE (multiple resolutions)
  │         alt="New York Yankees 2026 Calendar"
  │         srcset="//img.mlbstatic.com/...2208w, .../1536w, .../1024w, ..."
  │
  └── div.p-featured-content__body
        └── div.p-wysiwyg
              ├── h4 → "Saturday, April 4"     ← GAME DATE
              ├── p  → "1st 40,000 Guests"     ← ELIGIBILITY
              └── p  → "Presented by Mastercard" ← SPONSOR

div[data-testid="TicketGridWrapper"]           ← TICKET GRID (contains JSON-LD)
  └── script[type="application/ld+json"]       ← STRUCTURED DATA (opponent, time)
```

**Key observations:**
- The promo name is in a heading *before* the card, not inside it
- The image uses `srcset` with multiple resolutions (we pick 1024w)
- The date is in the card body, but *opponent and time* are in a separate JSON-LD block

### Parsing srcset for images

MLB uses responsive images. The `srcset` attribute looks like:

```html
srcset="//img.mlbstatic.com/.../t_w2208/mlb/abc.png 2208w,
        //img.mlbstatic.com/.../t_w1536/mlb/abc.png 1536w,
        //img.mlbstatic.com/.../t_w1024/mlb/abc.png 1024w,
        //img.mlbstatic.com/.../t_w640/mlb/abc.png 640w,
        //img.mlbstatic.com/.../t_w372/mlb/abc.png 372w"
```

We parse this into `(url, width)` pairs and pick the 1024w version — big enough to look good in a calendar event without being wastefully large.

## 5. Step 4: Find the Opponent and Time Data

This was the trickiest part. Initially we searched for team names near the dates:

```python
# Search for opponent names near "April 4"
april4_idx = html.find('April 4')
nearby = html[april4_idx:april4_idx+3000]
for team in ['Marlins', 'Red Sox', 'Blue Jays', 'vs']:
    if team in nearby:
        print(f"Found '{team}' near April 4")
```

Nothing was found! The opponent info isn't in the promo card — it's in a completely different part of the DOM (the ticket grid below the card).

### The JSON-LD discovery

Looking at the ticket grid HTML, we found `<script type="application/ld+json">` tags containing structured data:

```json
{
  "@context": "http://schema.org/",
  "@type": "SportsEvent",
  "name": "Marlins at Yankees",
  "startDate": "2026-04-04",
  "description": "Miami Marlins at New York Yankees on April 4, 2026 at 7:05PM EDT"
}
```

**Why is this significant?**

JSON-LD (JavaScript Object Notation for Linked Data) is structured data that websites embed for Google Search. It follows the [schema.org](https://schema.org/) standard and contains machine-readable event information. This is *far* more reliable than scraping CSS-styled text because:

1. It follows a standard format (won't change with CSS redesigns)
2. It's the same data Google uses for rich search results
3. It includes everything we need: opponent, date, time, venue, game ID

All 3 of our team sites embed JSON-LD, making it the best source for game metadata. We extract it in `base.py`:

```python
async def _extract_json_ld(self, page):
    scripts = await page.query_selector_all('script[type="application/ld+json"]')
    events = []
    for script in scripts:
        text = await script.inner_text()
        data = json.loads(text)
        if isinstance(data, list):
            events.extend(data)
        else:
            events.append(data)
    return events
```

## 6. Step 5: Handle Site Differences

Each site required a different approach. Here's how they compare:

### Yankees (mlb.com/yankees)

| Element | Selector | Notes |
|---------|----------|-------|
| Promo name | `h1.p-heading__text` (preceding heading) | Navigate to parent `.l-grid__content` |
| Image | `div.p-featured-content__media img` | Extract from `srcset` |
| Date | `div.p-featured-content__body h4` | Format: "Saturday, April 4" |
| Eligibility | `div.p-featured-content__body p` | Multiple `<p>` tags |
| Opponent/time | JSON-LD in ticket grid | Key: `startDate` matches card date |

### Mets (mlb.com/mets)

| Element | Selector | Notes |
|---------|----------|-------|
| Promo name | `div.l-grid__content-title` | ALL CAPS text |
| Image | `div.p-image img` | Same srcset approach |
| Date | Element `id` attribute | Format: `id="3-29-26"` (M-DD-YY) |
| Eligibility | `h1.p-heading__text` | Under the image |
| Opponent/time | JSON-LD | Same approach as Yankees |

The Mets date discovery was a nice shortcut: each promo item's `id` attribute is the date in `M-DD-YY` format (e.g., `id="3-29-26"` for March 29, 2026). This is more reliable than parsing natural language dates.

### Cyclones (milb.com/brooklyn)

This was the most different and required the most debugging:

| Element | Selector | Notes |
|---------|----------|-------|
| Promo name | `span.p-accordion__title` after `<strong>Promotion:</strong>` | Filter out "Game Highlight" and "Ticket Offer" |
| Image | None | No per-promo images on this page |
| Date | `.sgt__event-info` text | Format: "Friday\nApr 3\n6:40 PM" |
| Opponent | `.sgt__event-info` text | After time, before "Buy Tickets" |
| Time | `.sgt__event-info` text | Parsed from the same text block |

**Key difference:** The Cyclones page uses a single-game-tickets (SGT) schedule view where promos are accordion items *inside* game rows, not standalone cards. One game can have multiple promotions.

## 7. Step 6: Debug and Fix Issues

### The Cyclones JSON-LD problem

The initial Cyclones scraper used JSON-LD for game info (same as Yankees/Mets), but it failed for most promos:

```
WARNING: No date for Cyclones promo: Star Trek Jersey Giveaway
WARNING: No date for Cyclones promo: Frank Sinatra Bobblehead
...
Found 8 promotions (expected ~31)
```

**Debugging approach:**

```python
# Step 1: Count how many game rows have promos
sgt_rows = await page.query_selector_all('div.sgt-event')
promo_rows = 0
for row in sgt_rows:
    accordions = await row.query_selector_all('span.p-accordion__title')
    for acc in accordions:
        cat_el = await acc.query_selector('strong')
        if cat_el and 'Promotion' in (await cat_el.inner_text()):
            promo_rows += 1

print(f"Rows with promos: {promo_rows}")    # 31

# Step 2: Count JSON-LD game IDs
json_ld_game_ids = set()
for script in await page.query_selector_all('script[type="application/ld+json"]'):
    data = json.loads(await script.inner_text())
    for event in (data if isinstance(data, list) else [data]):
        match = re.search(r'#game=(\d+)', event.get('url', ''))
        if match:
            json_ld_game_ids.add(match.group(1))

print(f"JSON-LD game IDs: {len(json_ld_game_ids)}")  # 10 !!!
```

**Root cause:** The Cyclones page only generates JSON-LD for ~10 games that have ticket grid widgets. The other 51 games exist in the SGT schedule but don't get JSON-LD blocks.

**Fix:** Instead of relying on JSON-LD, parse the date, time, and opponent directly from each game row's visible text:

```python
info_el = await row.query_selector('.sgt__event-info')
text = await info_el.inner_text()
# Returns: 'Friday\nApr 3\n6:40 PM\n \nHudson Valley\nRenegades\nBuy Tickets'
```

Then parse each line:
- Date: look for `"Apr 3"` pattern (abbreviated month — note: **not** "April 3")
- Time: look for `"6:40 PM"` pattern
- Opponent: lines between the time and "Buy Tickets"

### The abbreviated month gotcha

The original `_parse_date_from_row` looked for full month names ("April", "May", etc.) but the Cyclones page uses abbreviated months ("Apr", "May"). This was a simple regex fix from `%B` to `%b`:

```python
# Before (broken): datetime.strptime("April 3 2026", "%B %d %Y")
# After (fixed):   datetime.strptime("Apr 3 2026", "%b %d %Y")
```

After this fix: **31 promotions found** (up from 8).

## 8. Quick Reference: Common Patterns

### Useful search patterns for HTML inspection

```python
# Find all CSS classes in an area
classes = set(re.findall(r'class="([^"]{3,60})"', html_chunk))

# Find all data attributes
data_attrs = re.findall(r'data-(\w+)="([^"]*)"', html_chunk)

# Find all image sources
images = re.findall(r'//img\.mlbstatic\.com/[^"\'>\s]+', html)

# Pretty-print minified HTML
readable = re.sub(r'(<[/]?(?:div|h[1-6]|img|a|span|p))', r'\n\1', html)

# Extract text content (strip tags)
text = re.sub(r'<[^>]+>', ' ', html_chunk)
text = re.sub(r'\s+', ' ', text).strip()
```

### Playwright selectors cheat sheet

```python
# Find by CSS class
elements = await page.query_selector_all('div.my-class')

# Find by attribute
elements = await page.query_selector_all('[data-testid="eventrow"]')

# Find nested element
img = await card.query_selector('div.media img')

# Get attribute value
srcset = await img.get_attribute('srcset')

# Get visible text
text = await element.inner_text()

# Navigate to parent
parent = await element.evaluate_handle("el => el.closest('.parent-class')")

# Check if element exists
exists = await page.query_selector('.maybe-exists')  # Returns None if not found
```

### When to use which data source

| Data | Best Source | Fallback |
|------|-----------|----------|
| Opponent name | JSON-LD `"name"` field | DOM text in event info/ticket grid |
| Game date | JSON-LD `"startDate"` or element `id` | DOM text date parsing |
| Game time | JSON-LD `"description"` | DOM text time parsing |
| Promo name | DOM heading/title element | — |
| Promo image | DOM `img[srcset]` | — |
| Eligibility | DOM paragraph/heading text | — |

### Adding a new team

1. Dump the rendered HTML using the script in [Step 1](#2-step-1-capture-the-rendered-page)
2. Search for known content (dates, promo keywords) to orient yourself
3. Map the card structure by inspecting context around found elements
4. Check for JSON-LD — it's the easiest source for game metadata
5. Create a new scraper class extending `BaseScraper`
6. Implement `_wait_for_content()` and `_parse_promotions()`
7. Add the team to `SCRAPE_TARGETS` in `config.py` and `SCRAPERS` in `scrapers/__init__.py`
8. Test with `python python/baseball_promos/run.py --team <slug> --scrape-only`
