# project_name

One-line description of the project.

## Setup

```bash
# From crystal-lab root (shared .venv should already be active)
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Usage

```bash
python -m python.project_name.src.main
```

## Project Structure

```
project_name/
├── src/
│   ├── __init__.py
│   ├── config.py      # Project-specific config (imports from shared)
│   └── utils.py       # Project-specific utilities (imports from shared)
├── tests/
│   ├── __init__.py
│   └── test_example.py
└── README.md
```

## How It Works

TODO: describe the project workflow.

## Testing

```bash
pytest python/project_name/ -v
```
