"""
PageNavigator — Intelligent page discovery via navigation detection
and fuzzy intent matching.

When a user says "get the about page", this module finds the best
matching URL even if the site calls it "Our Story", "Who We Are", etc.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from crawlerlib.utils import setup_logger, resolve_url, is_valid_url, same_domain

logger = setup_logger("crawlerlib.navigator")


# ── Intent synonym map ──────────────────────────────────────────────────────

INTENT_SYNONYMS: dict[str, list[str]] = {
    "about": [
        "about", "about-us", "about_us", "our-story", "our_story",
        "who-we-are", "who_we_are", "company", "team", "our-team",
        "our_team", "overview", "mission", "vision", "history",
        "leadership", "founders", "the-team", "meet-the-team",
        "what-we-do", "who-are-we", "our-mission", "our-vision",
    ],
    "contact": [
        "contact", "contact-us", "contact_us", "get-in-touch",
        "get_in_touch", "reach-us", "reach_us", "support",
        "help", "connect", "enquiry", "inquiry", "write-to-us",
        "talk-to-us", "feedback",
    ],
    "pricing": [
        "pricing", "plans", "packages", "cost", "subscription",
        "subscriptions", "buy", "purchase", "billing", "price",
        "rates", "pricing-plans", "compare-plans", "upgrade",
    ],
    "blog": [
        "blog", "articles", "news", "insights", "resources",
        "posts", "stories", "updates", "press", "media",
        "announcements", "newsletter", "publications", "journal",
        "thought-leadership", "whitepapers", "case-studies",
    ],
    "services": [
        "services", "solutions", "what-we-do", "offerings",
        "products", "features", "capabilities", "platform",
        "tools", "integrations", "modules", "our-services",
        "our-products", "what-we-offer",
    ],
    "careers": [
        "careers", "jobs", "join-us", "join_us", "hiring",
        "work-with-us", "work_with_us", "openings", "positions",
        "opportunities", "culture", "life-at", "join-our-team",
        "we-are-hiring", "vacancies", "employment",
    ],
    "faq": [
        "faq", "faqs", "help", "questions", "support",
        "knowledge-base", "knowledge_base", "help-center",
        "help_center", "documentation", "docs", "guide",
        "how-it-works", "getting-started", "learn",
    ],
    "privacy": [
        "privacy", "privacy-policy", "privacy_policy",
        "data-policy", "data_policy", "gdpr", "cookie-policy",
        "cookies", "data-protection",
    ],
    "terms": [
        "terms", "terms-of-service", "terms_of_service",
        "tos", "legal", "terms-and-conditions", "disclaimer",
        "agreement", "eula",
    ],
}

# Flattened display-text synonyms (cleaned for fuzzy matching against link text)
_TEXT_SYNONYMS: dict[str, list[str]] = {}
for _intent, _slugs in INTENT_SYNONYMS.items():
    _TEXT_SYNONYMS[_intent] = [
        s.replace("-", " ").replace("_", " ") for s in _slugs
    ]


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class NavLink:
    """A single navigable link discovered on the page."""
    text: str
    href: str
    location: str           # "header", "sidebar", "footer", "body"
    score: float = 0.0      # match score when intent-matching

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "href": self.href,
            "location": self.location,
            "score": round(self.score, 2),
        }


@dataclass
class NavigationMap:
    """All navigation links grouped by location."""
    header: list[NavLink] = field(default_factory=list)
    sidebar: list[NavLink] = field(default_factory=list)
    footer: list[NavLink] = field(default_factory=list)
    body: list[NavLink] = field(default_factory=list)

    @property
    def all_links(self) -> list[NavLink]:
        return self.header + self.sidebar + self.footer + self.body

    def to_dict(self) -> dict:
        return {
            "header": [l.to_dict() for l in self.header],
            "sidebar": [l.to_dict() for l in self.sidebar],
            "footer": [l.to_dict() for l in self.footer],
            "body": [l.to_dict() for l in self.body],
        }


# ── Navigator ───────────────────────────────────────────────────────────────

class PageNavigator:
    """
    Discover navigation structure and intelligently find pages by intent.

    Usage
    -----
    >>> nav = PageNavigator()
    >>> nav_map = nav.discover_navigation(html, base_url)
    >>> about_links = nav.find_pages(html, base_url, "about")
    >>> random_pages = nav.get_random_menu_pages(html, base_url, 3)
    """

    def __init__(self, parser_engine: str = "lxml"):
        self._engine = parser_engine

    # ── Public API ───────────────────────────────────────────────────────

    def discover_navigation(self, html: str, base_url: str) -> NavigationMap:
        """
        Scan the page for navigation elements and return all discovered
        links grouped by location (header, sidebar, footer, body).
        """
        soup = BeautifulSoup(html, self._engine)
        nav_map = NavigationMap()

        # 1. Header navigation
        for container in self._find_header_navs(soup):
            nav_map.header.extend(
                self._extract_nav_links(container, base_url, "header")
            )

        # 2. Sidebar navigation
        for container in self._find_sidebars(soup):
            nav_map.sidebar.extend(
                self._extract_nav_links(container, base_url, "sidebar")
            )

        # 3. Footer navigation
        for container in self._find_footers(soup):
            nav_map.footer.extend(
                self._extract_nav_links(container, base_url, "footer")
            )

        # 4. Body-level links (fallback — links not in above)
        seen_hrefs = {l.href for l in nav_map.all_links}
        for a in soup.find_all("a", href=True):
            href = resolve_url(base_url, a["href"])
            if href not in seen_hrefs and is_valid_url(href) and same_domain(base_url, href):
                text = a.get_text(strip=True)
                if text and len(text) < 100:  # skip massive link text
                    nav_map.body.append(NavLink(text=text, href=href, location="body"))
                    seen_hrefs.add(href)

        # Deduplicate within each group
        nav_map.header = self._dedupe(nav_map.header)
        nav_map.sidebar = self._dedupe(nav_map.sidebar)
        nav_map.footer = self._dedupe(nav_map.footer)
        nav_map.body = self._dedupe(nav_map.body)

        total = len(nav_map.all_links)
        logger.info(
            "🧭 Navigation discovered: %d links (header=%d, sidebar=%d, footer=%d, body=%d)",
            total, len(nav_map.header), len(nav_map.sidebar),
            len(nav_map.footer), len(nav_map.body),
        )
        return nav_map

    def find_pages(
        self,
        html: str,
        base_url: str,
        intent: str,
        *,
        top_n: int = 3,
    ) -> list[NavLink]:
        """
        Find the best-matching pages for a given *intent* (e.g. "about").

        Returns up to *top_n* results sorted by match score (highest first).
        """
        intent = intent.lower().strip()
        synonyms_path = INTENT_SYNONYMS.get(intent, [intent])
        synonyms_text = _TEXT_SYNONYMS.get(intent, [intent.replace("-", " ")])

        nav_map = self.discover_navigation(html, base_url)
        candidates = nav_map.all_links

        scored: list[NavLink] = []
        for link in candidates:
            score = self._score_link(link, intent, synonyms_path, synonyms_text)
            if score > 0:
                link.score = score
                scored.append(link)

        # Sort by score descending
        scored.sort(key=lambda l: l.score, reverse=True)

        if scored:
            logger.info(
                "🔍 Intent '%s' — top match: %s (score=%.1f)",
                intent, scored[0].href, scored[0].score,
            )
        else:
            logger.warning("⚠️ No pages found for intent '%s'", intent)

        return scored[:top_n]

    def get_random_menu_pages(
        self,
        html: str,
        base_url: str,
        count: int = 3,
    ) -> list[NavLink]:
        """
        Return *count* random pages from the site navigation.
        Prioritizes header/sidebar links over footer/body.
        """
        nav_map = self.discover_navigation(html, base_url)

        # Prefer header + sidebar
        priority_links = nav_map.header + nav_map.sidebar
        fallback_links = nav_map.footer + nav_map.body

        pool = priority_links if priority_links else fallback_links
        if not pool:
            pool = fallback_links

        # Filter out the start page itself
        pool = [l for l in pool if l.href.rstrip("/") != base_url.rstrip("/")]

        count = min(count, len(pool))
        selected = random.sample(pool, count) if pool else []

        logger.info(
            "🎲 Random menu pages: selected %d from %d candidates",
            len(selected), len(pool),
        )
        return selected

    # ── Scoring ──────────────────────────────────────────────────────────

    def _score_link(
        self,
        link: NavLink,
        intent: str,
        synonyms_path: list[str],
        synonyms_text: list[str],
    ) -> float:
        """Score a link against an intent. Higher = better match."""
        score = 0.0
        path = urlparse(link.href).path.lower().strip("/")
        text = link.text.lower().strip()

        # ── URL path matching ────────────────────────────────────────────
        path_segments = [s for s in path.split("/") if s]
        last_segment = path_segments[-1] if path_segments else ""

        for synonym in synonyms_path:
            # Exact path match
            if last_segment == synonym:
                score = max(score, 100)
            # Path contains synonym
            elif synonym in last_segment:
                score = max(score, 80)
            # Any segment matches
            elif synonym in path_segments:
                score = max(score, 70)

        # ── Link text matching ───────────────────────────────────────────
        for synonym in synonyms_text:
            # Exact text match
            if text == synonym:
                score = max(score, 95)
            # Text starts with synonym
            elif text.startswith(synonym):
                score = max(score, 85)
            # Synonym contained in text
            elif synonym in text:
                score = max(score, 70)
            # Fuzzy match (for "Our Story" matching "about")
            else:
                ratio = SequenceMatcher(None, text, synonym).ratio()
                if ratio > 0.6:
                    score = max(score, ratio * 60)

        # ── Location boost ───────────────────────────────────────────────
        location_boost = {
            "header": 1.15,
            "sidebar": 1.10,
            "footer": 0.90,
            "body": 0.80,
        }
        score *= location_boost.get(link.location, 1.0)

        return score

    # ── Navigation element detection ─────────────────────────────────────

    @staticmethod
    def _find_header_navs(soup: BeautifulSoup) -> list[Tag]:
        """Find header/primary navigation containers."""
        containers = []

        # <nav> elements, especially in <header>
        for nav in soup.find_all("nav"):
            containers.append(nav)

        # <header> elements (if nav wasn't inside)
        for header in soup.find_all("header"):
            if not header.find("nav"):
                containers.append(header)

        # role="navigation"
        for el in soup.find_all(attrs={"role": "navigation"}):
            if el not in containers:
                containers.append(el)

        # Common class/id patterns for navbars
        nav_patterns = re.compile(
            r"(navbar|nav-bar|main-nav|primary-nav|top-nav|site-nav|"
            r"header-nav|navigation|menu-bar|main-menu|primary-menu)",
            re.I,
        )
        for el in soup.find_all(["div", "ul"], class_=nav_patterns):
            if el not in containers:
                containers.append(el)
        for el in soup.find_all(["div", "ul"], id=nav_patterns):
            if el not in containers:
                containers.append(el)

        return containers

    @staticmethod
    def _find_sidebars(soup: BeautifulSoup) -> list[Tag]:
        """Find sidebar navigation containers."""
        containers = []

        # <aside> elements
        for aside in soup.find_all("aside"):
            containers.append(aside)

        # role="complementary"
        for el in soup.find_all(attrs={"role": "complementary"}):
            if el not in containers:
                containers.append(el)

        # Common sidebar class/id patterns
        sidebar_patterns = re.compile(
            r"(sidebar|side-bar|side-nav|side-menu|left-nav|right-nav|"
            r"left-panel|right-panel|drawer|off-canvas)",
            re.I,
        )
        for el in soup.find_all(["div", "aside", "nav"], class_=sidebar_patterns):
            if el not in containers:
                containers.append(el)
        for el in soup.find_all(["div", "aside", "nav"], id=sidebar_patterns):
            if el not in containers:
                containers.append(el)

        return containers

    @staticmethod
    def _find_footers(soup: BeautifulSoup) -> list[Tag]:
        """Find footer navigation containers."""
        containers = []

        for footer in soup.find_all("footer"):
            containers.append(footer)

        for el in soup.find_all(attrs={"role": "contentinfo"}):
            if el not in containers:
                containers.append(el)

        footer_patterns = re.compile(
            r"(footer|bottom-nav|foot-nav|footer-nav|site-footer|footer-menu)",
            re.I,
        )
        for el in soup.find_all("div", class_=footer_patterns):
            if el not in containers:
                containers.append(el)
        for el in soup.find_all("div", id=footer_patterns):
            if el not in containers:
                containers.append(el)

        return containers

    @staticmethod
    def _extract_nav_links(container: Tag, base_url: str, location: str) -> list[NavLink]:
        """Extract all <a> links from a navigation container."""
        links = []
        for a in container.find_all("a", href=True):
            href = resolve_url(base_url, a["href"])
            if not is_valid_url(href):
                continue
            text = a.get_text(strip=True)
            if not text or len(text) > 100:
                continue
            # Skip anchors, javascript, mailto
            raw_href = a["href"].strip()
            if raw_href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            links.append(NavLink(text=text, href=href, location=location))
        return links

    @staticmethod
    def _dedupe(links: list[NavLink]) -> list[NavLink]:
        """Deduplicate links by href, keeping the first occurrence."""
        seen: set[str] = set()
        result = []
        for link in links:
            normalized = link.href.rstrip("/")
            if normalized not in seen:
                seen.add(normalized)
                result.append(link)
        return result
