# crystal-lab

Welcome to my personal GitHub portfolio!
This repo is a collection of Python projects, technical docs, and case studies that showcase my work across automation, data analysis, and tooling.

---

## Getting Started

```bash
# Clone and set up
git clone https://github.com/crystallite916/crystal-lab.git
cd crystal-lab

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # macOS/Linux

# Install dependencies and shared package
pip install -r requirements.txt
pip install -e .

# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Verify setup
python -c "from shared.config import PROJECT_ROOT; print(f'Setup complete: {PROJECT_ROOT}')"
```

---

## Tech Stack

- **Languages:** Python, SQL, JavaScript (basic)
- **Python Tools:** pandas, NumPy, FastAPI, Airflow, Jupyter, pytest
- **Cloud & DevOps:** Google Cloud, Docker, GitHub Actions
- **Other:** Google Sheets / Apps Script automations

---

## Repository Structure

```
crystal-lab/
├── python/                # Python projects
│   └── _template/         # Scaffolding template for new projects
├── shared/                # Shared utilities package (config, GCP clients)
├── docs/                  # Resume, case studies, reference notes
├── assets/                # Images for README + documentation
├── credentials/           # Service account keys (gitignored)
├── .vscode/               # VSCode workspace settings
├── .claude/commands/      # Custom Claude Code commands
├── pyproject.toml         # Python package & tool configuration
├── requirements.txt       # Shared dependencies
├── .pre-commit-config.yaml # Code quality hooks (Black, Flake8)
├── .env.example           # Environment variable template
├── CLAUDE.md              # Claude Code project context
└── README.md
```

---

## Projects

| Project | Description | Status |
|---|---|---|
| — | *No projects yet — use `/new-project` to scaffold one* | — |

---

## Testing

```bash
# Run all tests
pytest python/ -v

# Run tests for a specific project
pytest python/project_name/ -v

# Run with markers
pytest python/ -v -m "not slow"
```
