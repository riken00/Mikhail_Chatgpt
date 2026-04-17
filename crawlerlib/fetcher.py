"""
Fetcher — Robust HTTP page fetching with retries, rotating user-agents,
rate-limiting, and robots.txt compliance.
"""

import random
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from crawlerlib.utils import setup_logger, normalize_url, get_domain

logger = setup_logger("crawlerlib.fetcher")

# ── User-Agent rotation pool ────────────────────────────────────────────────

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


@dataclass
class FetchResult:
    """Container for the result of a single page fetch."""
    url: str
    status_code: int
    html: str
    headers: dict
    elapsed_ms: float
    success: bool
    error: Optional[str] = None


@dataclass
class FetcherConfig:
    """Tunable knobs for the Fetcher."""
    timeout: int = 30
    max_retries: int = 3
    backoff_factor: float = 0.5
    delay: float = 1.0          # seconds between requests (rate limit)
    respect_robots: bool = True
    proxy: Optional[str] = None
    custom_headers: dict = field(default_factory=dict)


class Fetcher:
    """
    Production-grade HTTP fetcher.

    Features
    --------
    - Automatic retries with exponential back-off
    - Rotating User-Agent strings
    - Configurable rate-limiting
    - robots.txt compliance
    - Optional proxy support
    """

    def __init__(self, config: Optional[FetcherConfig] = None):
        self.config = config or FetcherConfig()
        self._session = self._build_session()
        self._robots_cache: dict[str, RobotFileParser] = {}
        self._last_request_time: float = 0.0

    # ── public API ───────────────────────────────────────────────────────

    def fetch(self, url: str) -> FetchResult:
        """Fetch a single page and return a *FetchResult*."""
        url = normalize_url(url)

        # robots.txt check
        if self.config.respect_robots and not self._is_allowed(url):
            logger.warning("Blocked by robots.txt: %s", url)
            return FetchResult(
                url=url, status_code=0, html="", headers={},
                elapsed_ms=0, success=False,
                error="Blocked by robots.txt",
            )

        # Rate-limit
        self._throttle()

        # Perform request
        headers = {**self.config.custom_headers, "User-Agent": self._random_ua()}
        try:
            logger.info("Fetching: %s", url)
            resp = self._session.get(
                url, headers=headers, timeout=self.config.timeout,
                proxies={"http": self.config.proxy, "https": self.config.proxy} if self.config.proxy else None,
            )
            resp.raise_for_status()
            return FetchResult(
                url=url,
                status_code=resp.status_code,
                html=resp.text,
                headers=dict(resp.headers),
                elapsed_ms=resp.elapsed.total_seconds() * 1000,
                success=True,
            )
        except requests.RequestException as exc:
            logger.error("Failed to fetch %s — %s", url, exc)
            return FetchResult(
                url=url, status_code=getattr(exc.response, "status_code", 0) if exc.response else 0,
                html="", headers={}, elapsed_ms=0, success=False,
                error=str(exc),
            )

    def close(self):
        """Close the underlying session."""
        self._session.close()

    # ── internals ────────────────────────────────────────────────────────

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retries = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _random_ua(self) -> str:
        return random.choice(_USER_AGENTS)

    def _throttle(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.config.delay:
            time.sleep(self.config.delay - elapsed)
        self._last_request_time = time.time()

    def _is_allowed(self, url: str) -> bool:
        domain = get_domain(url)
        if domain not in self._robots_cache:
            rp = RobotFileParser()
            rp.set_url(f"https://{domain}/robots.txt")
            try:
                rp.read()
            except Exception:
                return True  # allow if robots.txt is unreachable
            self._robots_cache[domain] = rp
        return self._robots_cache[domain].can_fetch("*", url)
