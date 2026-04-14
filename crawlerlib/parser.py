"""
PageParser — Extract structured data from raw HTML.

Combines flat metadata extraction (title, meta, links, images) with
the new hierarchical StructuredExtractor for section-level content.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag

from crawlerlib.extractor import StructuredExtractor
from crawlerlib.utils import setup_logger, resolve_url

logger = setup_logger("crawlerlib.parser")


@dataclass
class ParsedPage:
    """Structured representation of a parsed HTML page."""
    url: str = ""
    title: str = ""
    meta_description: str = ""
    meta_keywords: list[str] = field(default_factory=list)
    canonical_url: str = ""
    language: str = ""

    # Structured content (hierarchical sections)
    structured_content: dict[str, Any] = field(default_factory=dict)

    # Navigation & metadata
    links: list[dict[str, str]] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)

    # Structured data
    opengraph: dict[str, str] = field(default_factory=dict)
    json_ld: list[dict[str, Any]] = field(default_factory=list)

    # Legacy flat fields (kept for backward compatibility)
    headings: dict[str, list[str]] = field(default_factory=dict)
    paragraphs: list[str] = field(default_factory=list)
    text_content: str = ""

    def to_dict(self) -> dict:
        """Serialize to a plain dict (JSON-safe)."""
        return {
            "url": self.url,
            "title": self.title,
            "meta_description": self.meta_description,
            "meta_keywords": self.meta_keywords,
            "canonical_url": self.canonical_url,
            "language": self.language,
            "structured_content": self.structured_content,
            "links": self.links,
            "images": self.images,
            "tables": self.tables,
            "opengraph": self.opengraph,
            "json_ld": self.json_ld,
            "headings": self.headings,
            "paragraphs": self.paragraphs,
            "text_content": self.text_content,
        }


class PageParser:
    """
    Parse raw HTML into a structured *ParsedPage*.

    Uses StructuredExtractor for hierarchical content and also supports
    CSS-selector-based custom field extraction.
    """

    def __init__(self, parser_engine: str = "lxml"):
        self._engine = parser_engine
        self._extractor = StructuredExtractor(parser_engine)

    # ── public API ───────────────────────────────────────────────────────

    def parse(
        self,
        html: str,
        url: str = "",
        *,
        custom_selectors: Optional[dict[str, str]] = None,
    ) -> ParsedPage:
        """Parse *html* and return a *ParsedPage*."""
        soup = BeautifulSoup(html, self._engine)
        page = ParsedPage(url=url)

        # ── Metadata ─────────────────────────────────────────────────────
        page.title = self._extract_title(soup)
        page.meta_description = self._extract_meta(soup, "description")
        page.meta_keywords = [
            k.strip()
            for k in self._extract_meta(soup, "keywords").split(",")
            if k.strip()
        ]
        page.canonical_url = self._extract_canonical(soup)
        page.language = self._extract_language(soup)
        page.opengraph = self._extract_opengraph(soup)
        page.json_ld = self._extract_json_ld(soup)

        # ── Links & media ────────────────────────────────────────────────
        page.links = self._extract_links(soup, url)
        page.images = self._extract_images(soup, url)
        page.tables = self._extract_tables(soup)

        # ── Structured content (NEW — hierarchical extraction) ───────────
        page.structured_content = self._extractor.extract(html, url)

        # ── Legacy flat extraction (backward compat) ─────────────────────
        page.headings = self._extract_headings(soup)
        page.paragraphs = self._extract_paragraphs(soup)
        page.text_content = self._extract_text(soup)

        # ── Custom selectors ─────────────────────────────────────────────
        if custom_selectors:
            for key, selector in custom_selectors.items():
                elements = soup.select(selector)
                setattr(page, key, [el.get_text(strip=True) for el in elements])

        logger.info(
            "📄 Parsed: %s — title=%r, sections=%d, links=%d",
            url, page.title, len(page.structured_content), len(page.links),
        )
        return page

    # ── extraction helpers ───────────────────────────────────────────────

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        tag = soup.find("title")
        return tag.get_text(strip=True) if tag else ""

    @staticmethod
    def _extract_meta(soup: BeautifulSoup, name: str) -> str:
        tag = soup.find("meta", attrs={"name": re.compile(name, re.I)})
        if tag and isinstance(tag, Tag):
            return tag.get("content", "")
        return ""

    @staticmethod
    def _extract_canonical(soup: BeautifulSoup) -> str:
        tag = soup.find("link", attrs={"rel": "canonical"})
        if tag and isinstance(tag, Tag):
            return tag.get("href", "")
        return ""

    @staticmethod
    def _extract_language(soup: BeautifulSoup) -> str:
        html_tag = soup.find("html")
        if html_tag and isinstance(html_tag, Tag):
            return html_tag.get("lang", "")
        return ""

    @staticmethod
    def _extract_headings(soup: BeautifulSoup) -> dict[str, list[str]]:
        headings: dict[str, list[str]] = {}
        for level in range(1, 7):
            tag_name = f"h{level}"
            tags = soup.find_all(tag_name)
            if tags:
                headings[tag_name] = [t.get_text(strip=True) for t in tags]
        return headings

    @staticmethod
    def _extract_paragraphs(soup: BeautifulSoup) -> list[str]:
        return [
            p.get_text(strip=True)
            for p in soup.find_all("p")
            if p.get_text(strip=True)
        ]

    @staticmethod
    def _extract_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            resolved = resolve_url(base_url, href) if base_url else href
            links.append({
                "text": a.get_text(strip=True),
                "href": resolved,
            })
        return links

    @staticmethod
    def _extract_images(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
        images = []
        for img in soup.find_all("img", src=True):
            src = img["src"]
            resolved = resolve_url(base_url, src) if base_url else src
            images.append({
                "src": resolved,
                "alt": img.get("alt", ""),
            })
        return images

    @staticmethod
    def _extract_tables(soup: BeautifulSoup) -> list[list[list[str]]]:
        tables = []
        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [
                    td.get_text(strip=True)
                    for td in tr.find_all(["td", "th"])
                ]
                if cells:
                    rows.append(cells)
            if rows:
                tables.append(rows)
        return tables

    @staticmethod
    def _extract_opengraph(soup: BeautifulSoup) -> dict[str, str]:
        og: dict[str, str] = {}
        for meta in soup.find_all("meta", attrs={"property": re.compile(r"^og:", re.I)}):
            key = meta.get("property", "").replace("og:", "")
            value = meta.get("content", "")
            if key and value:
                og[key] = value
        return og

    @staticmethod
    def _extract_json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
        results = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict):
                    results.append(data)
                elif isinstance(data, list):
                    results.extend(data)
            except (json.JSONDecodeError, TypeError):
                continue
        return results

    @staticmethod
    def _extract_text(soup: BeautifulSoup) -> str:
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        return re.sub(r"\s+", " ", text).strip()
