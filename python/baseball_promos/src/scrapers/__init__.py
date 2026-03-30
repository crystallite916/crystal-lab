from .yankees import YankeesScraper
from .mets import MetsScraper
from .cyclones import CyclonesScraper

SCRAPERS = {
    "yankees": YankeesScraper,
    "mets": MetsScraper,
    "brooklyn": CyclonesScraper,
}
