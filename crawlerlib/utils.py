"""
Utility helpers — URL normalization, domain extraction, logging setup.
"""

import logging
import re
from urllib.parse import urlparse, urljoin, urldefrag


# ── Logging ──────────────────────────────────────────────────────────────────

def setup_logger(name: str = "crawlerlib", level: int = logging.INFO) -> logging.Logger:
    """Create a nicely-formatted logger instance."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "\033[36m%(asctime)s\033[0m │ \033[1m%(name)s\033[0m │ %(levelname)s │ %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


# ── URL helpers ──────────────────────────────────────────────────────────────

def normalize_url(url: str) -> str:
    """Ensure the URL has a scheme and strip fragments."""
    url = url.strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    url, _ = urldefrag(url)  # strip #fragment
    # Remove trailing slash for consistency (except root)
    parsed = urlparse(url)
    if parsed.path and parsed.path != "/":
        url = url.rstrip("/")
    return url


def is_valid_url(url: str) -> bool:
    """Return True if *url* looks like a valid HTTP(S) URL."""
    try:
        result = urlparse(url)
        return all([result.scheme in ("http", "https"), result.netloc])
    except Exception:
        return False


def get_domain(url: str) -> str:
    """Extract the domain (netloc) from a URL."""
    return urlparse(url).netloc


def resolve_url(base: str, href: str) -> str:
    """Resolve a potentially relative *href* against a *base* URL."""
    resolved = urljoin(base, href)
    return normalize_url(resolved)


def same_domain(url1: str, url2: str) -> bool:
    """Return True when both URLs share the same domain."""
    return get_domain(url1) == get_domain(url2)
