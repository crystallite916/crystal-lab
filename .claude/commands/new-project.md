Guide the user through creating a new project in the crystal-lab monorepo.

## Step 1 — Gather inputs

Ask the user for:
1. **Project name** (must be snake_case)
2. **One-line description** of the project's purpose

## Step 2 — Present a scaffolding plan

Show the full directory structure and file contents before creating anything. Include:

**Directory structure:**
```
python/{project_name}/
├── src/
│   ├── __init__.py
│   ├── config.py
│   └── utils.py
├── tests/
│   └── __init__.py
└── README.md
```

**File content previews:**

`src/config.py` — facade over shared, plus project-specific constants:
```python
from shared.config import (
    GOOGLE_SERVICE_ACCOUNT_FILE,
    BQ_PROJECT_ID,
    BQ_LOCATION,
)

# Project-specific configuration
SPREADSHEET_ID = ""  # TODO: add spreadsheet ID if needed
```

`src/utils.py` — facade over shared, plus project-specific utilities:
```python
from shared.utils import (
    get_gspread_client,
    get_bigquery_client,
    write_to_worksheet,
    execute_bigquery_query,
)

# Project-specific utilities below
```

`README.md` — filled with the project name, description, and placeholder sections for Setup, Usage, and How It Works.

## Step 3 — Wait for approval

Do not create any files until the user confirms the plan. If they request changes, revise the plan and show it again.

## Step 4 — Execute

Copy from `python/_template/` and customize with the project name and description.

After creating, update the Project Map table in `CLAUDE.md` with the new project.
