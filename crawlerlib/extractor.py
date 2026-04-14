"""
StructuredExtractor — Hierarchical DOM-to-data extraction engine.

Instead of dumping flat paragraph lists, this mirrors how a human reads
a page: section by section, preserving the container → content hierarchy.

Output is a clean dict of labeled sections where each section's value is
a string, list, or nested dict depending on the content structure.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from crawlerlib.utils import setup_logger, resolve_url

logger = setup_logger("crawlerlib.extractor")

# ── Constants ───────────────────────────────────────────────────────────────

# Tags that denote major content sections
_SECTION_TAGS = {"section", "article", "main", "aside", "header", "footer"}

# Class/ID patterns that signal a meaningful container
_CONTAINER_PATTERNS = re.compile(
    r"(section|block|container|wrapper|content|feature|hero|card|banner|"
    r"module|panel|widget|area|region|segment|group|grid|row|column|"
    r"testimonial|pricing|team|stats|about|cta|callout|highlight|"
    r"services|benefits|portfolio|gallery|showcase|intro|overview)",
    re.I,
)

# Tags to skip entirely during extraction
_SKIP_TAGS = {"script", "style", "noscript", "svg", "path", "meta", "link", "br", "hr"}

# Inline elements whose text is merged with parent
_INLINE_TAGS = {
    "span", "strong", "em", "b", "i", "u", "a", "small", "sub", "sup",
    "mark", "abbr", "cite", "code", "kbd", "var", "s", "del", "ins",
    "time", "data", "q", "dfn", "ruby", "rt", "rp", "bdi", "bdo", "wbr",
}

# Minimum text length to be considered meaningful
_MIN_TEXT_LENGTH = 10

# Maximum recursion depth for nested container extraction
_MAX_DEPTH = 3


class StructuredExtractor:
    """
    Extract page content as a hierarchical structure that mirrors
    the actual DOM layout.

    Usage
    -----
    >>> extractor = StructuredExtractor()
    >>> soup = BeautifulSoup(html, "lxml")
    >>> structured = extractor.extract(soup, url)
    """

    def __init__(self, parser_engine: str = "lxml"):
        self._engine = parser_engine

    # ── Public API ───────────────────────────────────────────────────────

    def extract(self, html_or_soup: str | BeautifulSoup, url: str = "") -> dict[str, Any]:
        """
        Extract structured content from HTML.

        Returns a dict like:
        {
            "Hero Section": {"heading": "...", "description": "...", "cta": "..."},
            "Features": [{"title": "...", "description": "..."}, ...],
            "About Us": "paragraph text...",
        }
        """
        if isinstance(html_or_soup, str):
            soup = BeautifulSoup(html_or_soup, self._engine)
        else:
            soup = html_or_soup

        # Remove noise
        self._strip_noise(soup)

        # Find the main content area (prefer <main>, fallback to <body>)
        main = soup.find("main") or soup.find("body") or soup
        if not isinstance(main, Tag):
            return {}

        # Discover top-level sections
        sections = self._discover_sections(main)

        if not sections:
            # Fallback: treat the entire main as one section
            content = self._extract_section_content(main, url, depth=0)
            if content:
                return {"Page Content": content}
            return {}

        result: dict[str, Any] = {}
        unnamed_counter = 0

        for section_tag in sections:
            label = self._derive_label(section_tag)
            if not label:
                unnamed_counter += 1
                label = f"Section {unnamed_counter}"

            # Avoid duplicate keys
            if label in result:
                i = 2
                while f"{label} ({i})" in result:
                    i += 1
                label = f"{label} ({i})"

            content = self._extract_section_content(section_tag, url, depth=0)
            if content:
                result[label] = content

        logger.info(
            "📦 Extracted %d structured sections from %s",
            len(result), url or "HTML",
        )
        return result

    # ── Section discovery ────────────────────────────────────────────────

    def _discover_sections(self, root: Tag) -> list[Tag]:
        """
        Find top-level content sections within *root*.
        Uses semantic tags, class/id patterns, and heading-based splitting.
        """
        sections: list[Tag] = []

        # Strategy 1: Semantic section tags
        for child in root.children:
            if not isinstance(child, Tag):
                continue
            if child.name in _SECTION_TAGS:
                sections.append(child)
            elif child.name == "div" and self._is_content_container(child):
                sections.append(child)

        # If we found meaningful sections, return them
        if len(sections) >= 2:
            return sections

        # Strategy 2: Look one level deeper
        sections.clear()
        for child in root.children:
            if not isinstance(child, Tag):
                continue
            if child.name in _SKIP_TAGS:
                continue

            # Check grandchildren
            if child.name == "div":
                grandchildren_sections = []
                for grandchild in child.children:
                    if not isinstance(grandchild, Tag):
                        continue
                    if grandchild.name in _SECTION_TAGS:
                        grandchildren_sections.append(grandchild)
                    elif grandchild.name == "div" and self._is_content_container(grandchild):
                        grandchildren_sections.append(grandchild)

                if grandchildren_sections:
                    sections.extend(grandchildren_sections)
                elif self._is_content_container(child):
                    sections.append(child)

        if len(sections) >= 2:
            return sections

        # Strategy 3: Split by headings
        sections = self._split_by_headings(root)
        if sections:
            return sections

        return []

    def _split_by_headings(self, root: Tag) -> list[Tag]:
        """
        Split content into sections based on heading elements.
        Each heading starts a new logical section.
        """
        # Find all headings at any level
        headings = root.find_all(re.compile(r"^h[1-6]$"))
        if len(headings) < 2:
            return []

        # This is complex — for now, return the parent containers of headings
        seen_parents: list[Tag] = []
        for h in headings:
            parent = h.parent
            if parent and isinstance(parent, Tag) and parent not in seen_parents:
                # Walk up to find a meaningful container
                container = self._find_meaningful_parent(h, root)
                if container and container not in seen_parents:
                    seen_parents.append(container)

        return seen_parents

    @staticmethod
    def _find_meaningful_parent(tag: Tag, root: Tag) -> Tag | None:
        """Walk up from *tag* to find the nearest meaningful container."""
        current = tag.parent
        while current and current != root and isinstance(current, Tag):
            if current.name in _SECTION_TAGS:
                return current
            if current.name == "div":
                class_str = " ".join(current.get("class", []))
                id_str = current.get("id", "")
                if _CONTAINER_PATTERNS.search(class_str) or _CONTAINER_PATTERNS.search(id_str):
                    return current
                # If div has multiple block-level children, it's likely a section
                block_children = [
                    c for c in current.children
                    if isinstance(c, Tag) and c.name not in _INLINE_TAGS and c.name not in _SKIP_TAGS
                ]
                if len(block_children) >= 2:
                    return current
            current = current.parent
        return tag.parent if isinstance(tag.parent, Tag) else None

    # ── Content extraction ───────────────────────────────────────────────

    def _extract_section_content(self, section: Tag, url: str, depth: int = 0) -> Any:
        """
        Extract the content of a section as the most appropriate data type:
        - Simple text → string
        - List of similar items → list of dicts
        - Mixed content → dict with labeled entries
        """
        # Flatten wrapper divs: if section has a single meaningful child,
        # skip the wrapper and extract the child directly
        section = self._unwrap_single_child(section)

        # At max depth, just return the text content
        if depth >= _MAX_DEPTH:
            text = section.get_text(separator=" ", strip=True)
            text = re.sub(r"\s+", " ", text).strip()
            return text if text and len(text) >= _MIN_TEXT_LENGTH else None

        # Check for repeated card/item patterns first
        cards = self._detect_card_pattern(section, url)
        if cards:
            return cards

        # Check for list elements
        lists = self._extract_lists(section)
        if lists and not self._has_significant_other_content(section):
            return lists

        # Check for tables
        tables = self._extract_tables(section)
        if tables:
            return tables

        # Build a content dict from child elements
        content = self._build_content_dict(section, url, depth=depth)

        # Simplify: if dict has only one key with a simple value, unwrap
        if isinstance(content, dict):
            if len(content) == 1:
                val = list(content.values())[0]
                if isinstance(val, str):
                    return val

            # If dict has only text content, merge into a string
            if all(isinstance(v, str) for v in content.values()):
                combined = " ".join(v for v in content.values() if v)
                if len(content) <= 2 and len(combined) < 500:
                    return combined

        return content if content else None

    @staticmethod
    def _unwrap_single_child(tag: Tag) -> Tag:
        """
        If a tag contains only a single meaningful child element (ignoring
        whitespace text nodes), return that child. Recurse until we find
        a container with multiple children or non-div content.
        """
        max_unwraps = 5  # safety limit
        for _ in range(max_unwraps):
            meaningful_children = [
                c for c in tag.children
                if isinstance(c, Tag) and c.name not in _SKIP_TAGS
            ]
            # Also check for significant direct text
            has_direct_text = any(
                isinstance(c, NavigableString) and c.strip() and len(c.strip()) >= _MIN_TEXT_LENGTH
                for c in tag.children
            )
            if len(meaningful_children) == 1 and not has_direct_text:
                child = meaningful_children[0]
                if child.name in ("div", "section", "article", "main"):
                    tag = child
                    continue
            break
        return tag

    def _build_content_dict(self, section: Tag, url: str, depth: int = 0) -> dict[str, Any]:
        """Build a dict representation of a section's content."""
        result: dict[str, Any] = {}
        unnamed_idx = 0

        # Gather the section's direct text and children
        heading = self._find_section_heading(section)
        heading_text = heading.get_text(strip=True) if heading else ""
        if heading_text:
            result["heading"] = heading_text

        for child in section.children:
            if isinstance(child, NavigableString):
                text = child.strip()
                if text and len(text) >= _MIN_TEXT_LENGTH:
                    if "description" not in result:
                        result["description"] = text
                    else:
                        unnamed_idx += 1
                        result[f"text_{unnamed_idx}"] = text
                continue

            if not isinstance(child, Tag):
                continue
            if child.name in _SKIP_TAGS:
                continue
            if child == heading:
                continue

            # Heading tags → become keys for what follows
            if child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                key = child.get_text(strip=True)
                if key and key != heading_text:  # skip if same as section heading
                    result[key] = ""  # will be filled by next text sibling
                continue

            # Paragraphs
            if child.name == "p":
                text = child.get_text(strip=True)
                if text and len(text) >= _MIN_TEXT_LENGTH:
                    # Try to attach to a preceding empty heading key
                    empty_key = self._find_last_empty_key(result)
                    if empty_key:
                        result[empty_key] = text
                    elif "description" not in result:
                        result["description"] = text
                    else:
                        unnamed_idx += 1
                        result[f"text_{unnamed_idx}"] = text
                continue

            # Lists
            if child.name in ("ul", "ol"):
                items = [
                    li.get_text(strip=True)
                    for li in child.find_all("li", recursive=False)
                    if li.get_text(strip=True)
                ]
                if items:
                    label = self._derive_label(child) or "items"
                    result[label] = items
                continue

            # Images
            if child.name == "img":
                src = child.get("src", "")
                if src:
                    resolved = resolve_url(url, src) if url else src
                    alt = child.get("alt", "")
                    result.setdefault("images", []).append(
                        {"src": resolved, "alt": alt}
                    )
                continue

            # Buttons / CTAs
            if child.name in ("button", "a") and child.get_text(strip=True):
                text = child.get_text(strip=True)
                if len(text) < 60:
                    if child.name == "a" and child.get("href"):
                        result.setdefault("cta", []).append({
                            "text": text,
                            "href": resolve_url(url, child["href"]) if url else child["href"],
                        })
                    else:
                        result.setdefault("cta", []).append({"text": text})
                continue

            # Nested containers — recurse with depth limit
            if child.name == "div" or child.name in _SECTION_TAGS:
                sub_content = self._extract_section_content(child, url, depth=depth + 1)
                if sub_content:
                    label = self._derive_label(child)
                    # Skip if label is same as parent heading (prevents nesting same key)
                    if label and label == heading_text:
                        # Merge sub_content directly into result instead of nesting
                        if isinstance(sub_content, dict):
                            for k, v in sub_content.items():
                                if k not in result:
                                    result[k] = v
                        elif isinstance(sub_content, str) and "description" not in result:
                            result["description"] = sub_content
                        continue
                    if not label:
                        unnamed_idx += 1
                        label = f"content_{unnamed_idx}"
                    # Deduplicate label
                    if label in result:
                        i = 2
                        while f"{label} ({i})" in result:
                            i += 1
                        label = f"{label} ({i})"
                    result[label] = sub_content

        # Simplify single CTA
        if "cta" in result and isinstance(result["cta"], list) and len(result["cta"]) == 1:
            result["cta"] = result["cta"][0]

        return result

    # ── Card / repeated pattern detection ────────────────────────────────

    def _detect_card_pattern(self, section: Tag, url: str) -> list[dict] | None:
        """
        Detect if a section contains repeated similar items (cards, features,
        team members, pricing plans, etc.) and extract them as a list of dicts.
        """
        # Find direct child divs/articles with similar classes
        children = [
            c for c in section.children
            if isinstance(c, Tag) and c.name in ("div", "article", "li")
            and c.name not in _SKIP_TAGS
        ]

        if len(children) < 2:
            return None

        # Check if children share similar structure (same tag + similar classes)
        class_groups: dict[str, list[Tag]] = {}
        for child in children:
            class_key = child.name + "|" + ",".join(sorted(child.get("class", [])))
            class_groups.setdefault(class_key, []).append(child)

        # Find the largest group of similar children
        largest = max(class_groups.values(), key=len) if class_groups else []
        if len(largest) < 2:
            return None

        # Verify structural similarity — each child should have similar child tags
        structures = []
        for item in largest:
            child_tags = tuple(
                c.name for c in item.children
                if isinstance(c, Tag) and c.name not in _SKIP_TAGS
            )
            structures.append(child_tags)

        # At least 60% of items should share a common structure
        if not structures:
            return None
        most_common = max(set(structures), key=structures.count)
        similarity = structures.count(most_common) / len(structures)
        if similarity < 0.5:
            return None

        # Extract each card as a dict
        cards = []
        for item in largest:
            card = self._extract_card(item, url)
            if card:
                cards.append(card)

        return cards if len(cards) >= 2 else None

    def _extract_card(self, item: Tag, url: str) -> dict[str, Any]:
        """Extract a single card/item into a flat dict."""
        card: dict[str, Any] = {}

        # Title: first heading
        heading = item.find(re.compile(r"^h[1-6]$"))
        if heading:
            card["title"] = heading.get_text(strip=True)

        # Image
        img = item.find("img", src=True)
        if img:
            src = resolve_url(url, img["src"]) if url else img["src"]
            card["image"] = src
            alt = img.get("alt", "")
            if alt:
                card["image_alt"] = alt

        # Description: first paragraph or longest text block
        paras = item.find_all("p")
        if paras:
            desc = " ".join(p.get_text(strip=True) for p in paras if p.get_text(strip=True))
            if desc:
                card["description"] = desc

        # Links / CTAs
        links = item.find_all("a", href=True)
        for link in links:
            text = link.get_text(strip=True)
            if text and link != heading:  # Don't duplicate heading link
                href = resolve_url(url, link["href"]) if url else link["href"]
                card.setdefault("links", []).append({"text": text, "href": href})

        # Lists inside card
        for ul in item.find_all(["ul", "ol"]):
            items = [li.get_text(strip=True) for li in ul.find_all("li") if li.get_text(strip=True)]
            if items:
                card.setdefault("features", []).extend(items)

        # Pricing / highlighted values
        for span in item.find_all(["span", "strong", "b", "em"]):
            text = span.get_text(strip=True)
            if text and re.match(r"^[\$€£¥₹]?\d+[\d,\.]*", text):
                card["price"] = text

        # If we didn't get structured data, get full text
        if not card or (len(card) == 1 and "image" in card):
            full_text = item.get_text(strip=True)
            if full_text and len(full_text) >= _MIN_TEXT_LENGTH:
                card["text"] = full_text

        return card

    # ── Helper methods ───────────────────────────────────────────────────

    @staticmethod
    def _is_content_container(tag: Tag) -> bool:
        """Check if a div is likely a meaningful content section."""
        class_str = " ".join(tag.get("class", []))
        id_str = tag.get("id", "") or ""
        combined = f"{class_str} {id_str}"

        if _CONTAINER_PATTERNS.search(combined):
            return True

        # Has a heading inside
        if tag.find(re.compile(r"^h[1-6]$")):
            return True

        return False

    @staticmethod
    def _derive_label(tag: Tag) -> str:
        """
        Derive a human-readable label for a section.

        IMPORTANT: Only uses DIRECT child headings, not deep .find(),
        to prevent the same heading from labeling every wrapper div.
        """
        # 1. aria-label
        aria = tag.get("aria-label")
        if aria:
            return str(aria).strip()

        # 2. aria-labelledby → find that element's text
        labelledby = tag.get("aria-labelledby")
        if labelledby:
            # Only look for direct children with that id
            for child in tag.children:
                if isinstance(child, Tag) and child.get("id") == labelledby:
                    return child.get_text(strip=True)

        # 3. First DIRECT child heading only (not deep search)
        for child in tag.children:
            if isinstance(child, Tag) and child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                text = child.get_text(strip=True)
                if text:
                    return text

        # 4. Meaningful id or class
        tag_id = tag.get("id", "")
        if tag_id and not re.match(r"^[a-f0-9-]{20,}$", tag_id):  # skip UUIDs
            return _clean_css_name(tag_id)

        classes = tag.get("class", [])
        for cls in classes:
            if _CONTAINER_PATTERNS.search(cls) and len(cls) > 3:
                return _clean_css_name(cls)

        return ""

    @staticmethod
    def _find_section_heading(section: Tag):
        """Find the primary heading of a section (direct child heading)."""
        for child in section.children:
            if isinstance(child, Tag) and child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                return child
        return None

    @staticmethod
    def _find_last_empty_key(d: dict) -> str | None:
        """Find the last key in dict whose value is empty string."""
        for key in reversed(list(d.keys())):
            if d[key] == "":
                return key
        return None

    @staticmethod
    def _extract_lists(section: Tag) -> list | None:
        """Extract <ul>/<ol> lists from a section."""
        lists = section.find_all(["ul", "ol"], recursive=False)
        if not lists:
            return None
        all_items = []
        for lst in lists:
            items = [li.get_text(strip=True) for li in lst.find_all("li") if li.get_text(strip=True)]
            all_items.extend(items)
        return all_items if all_items else None

    @staticmethod
    def _extract_tables(section: Tag) -> list[dict] | None:
        """Extract tables as list of row dicts."""
        tables = section.find_all("table")
        if not tables:
            return None
        result = []
        for table in tables:
            headers = []
            header_row = table.find("thead")
            if header_row:
                headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]

            rows = []
            tbody = table.find("tbody") or table
            for tr in tbody.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    if headers and len(cells) == len(headers):
                        rows.append(dict(zip(headers, cells)))
                    else:
                        rows.append(cells)
            if rows:
                result.extend(rows)
        return result if result else None

    @staticmethod
    def _has_significant_other_content(section: Tag) -> bool:
        """Check if section has significant content besides lists."""
        for child in section.children:
            if isinstance(child, Tag):
                if child.name in ("p", "div", "article", "section"):
                    text = child.get_text(strip=True)
                    if text and len(text) > 50:
                        return True
        return False

    @staticmethod
    def _strip_noise(soup: BeautifulSoup):
        """Remove non-content elements."""
        for tag in soup(["script", "style", "noscript", "svg", "iframe", "object", "embed"]):
            tag.decompose()
        # Remove hidden elements
        for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
            tag.decompose()
        for tag in soup.find_all(attrs={"hidden": True}):
            tag.decompose()
        for tag in soup.find_all(attrs={"aria-hidden": "true"}):
            tag.decompose()


# ── Module-level helpers ────────────────────────────────────────────────────

def _clean_css_name(name: str) -> str:
    """Convert a CSS class/id name to a human-readable label."""
    # Remove common prefixes/suffixes
    cleaned = re.sub(r"^(js-|wp-|el-|css-)", "", name)
    # Replace separators with spaces
    cleaned = re.sub(r"[-_]+", " ", cleaned)
    # CamelCase → spaces
    cleaned = re.sub(r"([a-z])([A-Z])", r"\1 \2", cleaned)
    # Title case
    cleaned = cleaned.strip().title()
    return cleaned
