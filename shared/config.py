"""
Shared configuration for crystal-lab projects.
Contains common paths and settings used across multiple projects.
"""

from pathlib import Path

# Project paths
# This file is in shared/, so go up one level to get to crystal-lab root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Shared credential paths
GOOGLE_SERVICE_ACCOUNT_FILE = PROJECT_ROOT / "credentials/google-drive-key.json"
BIG_QUERY_SERVICE_ACCOUNT_FILE = PROJECT_ROOT / "credentials/big-query-key.json"

# Google API Scopes
SCOPES_SHEETS = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SCOPES_BIGQUERY = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/drive",
]

# BigQuery Configuration
BQ_PROJECT_ID = "instant-bonfire-481001-c0"
BQ_LOCATION = "us-central1"
