"""
Storage engines for persisting crawled data.

Currently ships with JSONStorage.  Designed to be swappable — implement
the same save / load interface to plug in SQLite, MongoDB, etc. later.
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from crawlerlib.utils import setup_logger, get_domain

logger = setup_logger("crawlerlib.storage")


class JSONStorage:
    """
    Save crawled page data as pretty-printed JSON files.

    Each crawl run produces a single JSON file named after the domain
    and timestamp, stored in *output_dir*.
    """

    def __init__(self, output_dir: str = "output"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    # ── public API ───────────────────────────────────────────────────────

    def save(self, data: dict[str, Any] | list[dict[str, Any]], *, filename: str | None = None) -> str:
        """
        Save *data* to a JSON file and return the file path.

        Parameters
        ----------
        data : dict or list[dict]
            The scraped data to persist.
        filename : str, optional
            Custom filename.  When omitted a name is auto-generated from
            the domain + timestamp.
        """
        if filename is None:
            # Derive from data
            url = ""
            if isinstance(data, dict):
                url = data.get("url", "") or data.get("start_url", "")
            elif isinstance(data, list) and data:
                url = data[0].get("url", "")
            domain = get_domain(url) if url else "unknown"
            domain_clean = re.sub(r"[^\w.-]", "_", domain)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"{domain_clean}_{ts}.json"

        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        size_kb = os.path.getsize(filepath) / 1024
        logger.info("💾 Saved: %s (%.1f KB)", filepath, size_kb)
        return filepath

    def load(self, filename: str) -> Any:
        """Load and return data from a previously saved JSON file."""
        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_files(self) -> list[str]:
        """Return all JSON files in the output directory."""
        return sorted(
            f for f in os.listdir(self.output_dir)
            if f.endswith(".json")
        )
