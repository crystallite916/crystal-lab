"""
Run the baseball promos pipeline.

Usage (from crystal-lab root):
    python python/baseball_promos/run.py [--scrape-only] [--no-calendar] [--team <slug>]
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add the crystal-lab root to sys.path so 'shared' and project imports work
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from python.baseball_promos.src.main import main  # noqa: E402

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(main())
