# CLAUDE.md

Personal Python portfolio monorepo. Projects live in `python/` with a shared utilities package.

---

## Project Map

| Project | Location | Description | Status |
|---|---|---|---|
| _template | `python/_template/` | Scaffolding template for new projects | Template |
| baseball_promos | `python/baseball_promos/` | Scrape MLB/MiLB promo schedules → BigQuery → Google Calendar | Active |

---

## Key Rules

### Virtual Environment

- Shared `.venv` at repo root — use for all projects
- Activate: `source .venv/bin/activate`
- Install: `pip install -r requirements.txt && pip install -e .`

### Shared Package — Facade Pattern

Every project's `src/config.py` and `src/utils.py` re-export from `shared/`:

```python
# src/config.py
from shared.config import GOOGLE_SERVICE_ACCOUNT_FILE, BQ_PROJECT_ID
SPREADSHEET_ID = "project-specific-id"  # add project constants here

# src/utils.py
from shared.utils import get_gspread_client, write_to_worksheet
# add project-specific utilities below
```

### Code Style

- PEP 8; snake_case for all file and directory names
- 100-character line length (enforced by Black)
- Docstrings and type hints on all functions

### Security

Never commit credentials. OAuth tokens live in `credentials/` (gitignored). BigQuery uses Application Default Credentials (`gcloud auth application-default login`).

---

## Commands

- `/new-project` — scaffold a new project with the correct structure and facade pattern
- `/run-tests` — run the test suite (`python/` directory)

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'shared'`**
```bash
source .venv/bin/activate && pip install -e .
```
