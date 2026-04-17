"""
Crawler — The main orchestrator that ties fetching, parsing, storage,
and smart page discovery into a complete crawl pipeline.

Supports single-page scrape, multi-page BFS crawl with depth control,
and intelligent page discovery via intent matching.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from crawlerlib.fetcher import Fetcher, FetcherConfig
from crawlerlib.navigator import PageNavigator
from crawlerlib.parser import PageParser, ParsedPage
from crawlerlib.storage import JSONStorage
from crawlerlib.utils import (
    setup_logger,
    normalize_url,
    is_valid_url,
    same_domain,
)

logger = setup_logger("crawlerlib.crawler")


@dataclass
class CrawlConfig:
    """Configuration for a crawl run."""
    max_depth: int = 1            # 0 = single page, 1 = page + its links, etc.
    max_pages: int = 50           # safety cap
    delay: float = 1.0            # seconds between fetches
    same_domain_only: bool = True # stay on the same domain
    timeout: int = 30
    max_retries: int = 3
    respect_robots: bool = True
    proxy: Optional[str] = None
    custom_selectors: Optional[dict[str, str]] = None
    custom_headers: dict = field(default_factory=dict)

    # ── Smart page discovery ─────────────────────────────────────────────
    # e.g., ["about", "pricing", "menu:3"]
    page_intents: list[str] = field(default_factory=list)


class Crawler:
    """
    Premium web crawler with intelligent page discovery.

    Usage
    -----
    Basic crawl:
    >>> with Crawler("https://example.com") as c:
    ...     results = c.crawl()
    ...     c.save()

    With smart page discovery:
    >>> config = CrawlConfig(page_intents=["about", "pricing", "menu:3"])
    >>> with Crawler("https://example.com", config=config) as c:
    ...     results = c.crawl()
    ...     c.save()
    """

    def __init__(
        self,
        url: str,
        config: Optional[CrawlConfig] = None,
        output_dir: str = "output",
    ):
        self.start_url = normalize_url(url)
        self.config = config or CrawlConfig()
        self._fetcher = Fetcher(
            FetcherConfig(
                timeout=self.config.timeout,
                max_retries=self.config.max_retries,
                backoff_factor=0.5,
                delay=self.config.delay,
                respect_robots=self.config.respect_robots,
                proxy=self.config.proxy,
                custom_headers=self.config.custom_headers,
            )
        )
        self._parser = PageParser()
        self._navigator = PageNavigator()
        self._storage = JSONStorage(output_dir)

        self.pages: list[ParsedPage] = []
        self._visited: set[str] = set()
        self._discovery_results: dict[str, list[dict]] = {}

    # ── context manager ──────────────────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ── public API ───────────────────────────────────────────────────────

    def crawl(self) -> list[dict]:
        """
        Run the crawl starting from *self.start_url*.

        If page_intents are configured, the crawler will:
        1. Crawl the start URL first
        2. Discover navigation links
        3. Auto-crawl pages matching each intent
        """
        logger.info(
            "Starting crawl: %s (depth=%d, max_pages=%d, intents=%s)",
            self.start_url, self.config.max_depth, self.config.max_pages,
            self.config.page_intents or "none",
        )
        start_time = time.time()

        # Phase 1: Crawl start URL (and BFS if depth > 0)
        self._bfs_crawl(self.start_url)

        # Phase 2: Smart page discovery
        if self.config.page_intents and self.pages:
            self._discover_and_crawl_intents()

        elapsed = time.time() - start_time
        logger.info(
            "🏁 Crawl complete — %d pages in %.1fs",
            len(self.pages), elapsed,
        )

        return self.results()

    def results(self) -> list[dict]:
        """Return the crawled data as a list of dicts."""
        return [p.to_dict() for p in self.pages]

    def save(self, filename: str | None = None) -> str:
        """Persist the crawled data to JSON and return the file path."""
        data = {
            "start_url": self.start_url,
            "crawled_at": datetime.now(timezone.utc).isoformat(),
            "total_pages": len(self.pages),
            "config": {
                "max_depth": self.config.max_depth,
                "max_pages": self.config.max_pages,
                "same_domain_only": self.config.same_domain_only,
                "page_intents": self.config.page_intents,
            },
            "discovery_results": self._discovery_results,
            "pages": self.results(),
        }
        return self._storage.save(data, filename=filename)

    def close(self):
        """Release resources."""
        self._fetcher.close()

    # ── BFS crawl ────────────────────────────────────────────────────────

    def _bfs_crawl(self, start_url: str):
        """BFS crawl from start_url with depth control."""
        queue: deque[tuple[str, int]] = deque()
        queue.append((start_url, 0))

        while queue and len(self.pages) < self.config.max_pages:
            url, depth = queue.popleft()
            normalized = url.rstrip("/")

            if normalized in self._visited:
                continue
            self._visited.add(normalized)

            parsed = self._fetch_and_parse(url)
            if not parsed:
                continue

            logger.info(
                "Page %d/%d crawled (depth=%d): %s",
                len(self.pages), self.config.max_pages, depth, url,
            )

            # Enqueue child links if within depth
            if depth < self.config.max_depth:
                for link in parsed.links:
                    href = link.get("href", "")
                    if not href or not is_valid_url(href):
                        continue
                    if self.config.same_domain_only and not same_domain(self.start_url, href):
                        continue
                    if href.rstrip("/") not in self._visited:
                        queue.append((href, depth + 1))

    # ── Smart page discovery ─────────────────────────────────────────────

    def _discover_and_crawl_intents(self):
        """Use PageNavigator to find and crawl pages matching intents."""
        # We use the first page's HTML for navigation discovery
        first_result = self._fetcher.fetch(self.start_url)
        if not first_result.success:
            logger.warning("Could not re-fetch start URL for navigation discovery")
            return

        html = first_result.html

        for intent_str in self.config.page_intents:
            if len(self.pages) >= self.config.max_pages:
                break

            intent_str = intent_str.strip().lower()

            # Handle "menu:N" syntax
            if intent_str.startswith("menu:"):
                count = int(intent_str.split(":")[1]) if ":" in intent_str else 3
                self._crawl_random_menu(html, count)
            else:
                self._crawl_intent(html, intent_str)

    def _crawl_intent(self, html: str, intent: str):
        """Find and crawl pages matching an intent."""
        logger.info("🔎 Discovering pages for intent: '%s'", intent)

        matches = self._navigator.find_pages(html, self.start_url, intent, top_n=3)

        if not matches:
            logger.warning("No pages found for intent '%s'", intent)
            self._discovery_results[intent] = []
            return

        self._discovery_results[intent] = [m.to_dict() for m in matches]

        # Crawl the best match (and second-best if available)
        for match in matches[:2]:
            if len(self.pages) >= self.config.max_pages:
                break
            if match.href.rstrip("/") in self._visited:
                logger.info("  ↳ Already visited: %s", match.href)
                continue

            logger.info(
                "  ↳ Crawling '%s' match: %s (score=%.1f)",
                intent, match.href, match.score,
            )
            self._fetch_and_parse(match.href)

    def _crawl_random_menu(self, html: str, count: int):
        """Crawl N random pages from the site navigation."""
        logger.info("🎲 Discovering %d random menu pages", count)

        pages = self._navigator.get_random_menu_pages(html, self.start_url, count)

        self._discovery_results[f"menu:{count}"] = [p.to_dict() for p in pages]

        for page_link in pages:
            if len(self.pages) >= self.config.max_pages:
                break
            if page_link.href.rstrip("/") in self._visited:
                continue

            logger.info("  ↳ Crawling menu page: %s", page_link.href)
            self._fetch_and_parse(page_link.href)

    # ── Shared fetch + parse ─────────────────────────────────────────────

    def _fetch_and_parse(self, url: str) -> ParsedPage | None:
        """Fetch and parse a single URL, add to self.pages."""
        result = self._fetcher.fetch(url)
        if not result.success:
            return None

        parsed = self._parser.parse(
            result.html, url,
            custom_selectors=self.config.custom_selectors,
        )
        self.pages.append(parsed)
        self._visited.add(url.rstrip("/"))
        return parsed
