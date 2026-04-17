"""
crawler — Management command that:
  1. Fetches a batch of companies from MongoDB that have a website but no description.
  2. Crawls each company's website using crawlerlib.
  3. Sends the extracted site content to ChatGPT and asks for a JSON-compatible
     ~250-word company description.
  4. Updates the same MongoDB document at summary.details.description.
  5. Also persists a record in Django's ParaphrasedText model.

Usage:
    python manage.py crawler                          # auto-batch from MongoDB
    python manage.py crawler --url https://stripe.com # single URL (manual mode)
    python manage.py crawler --batch-size 20 --n 2
"""

import json
import logging
import os
import textwrap
from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId

from app.account_manager import AccountManager
from app.bot import Bot
from app.models import ParaphrasedText, Text
from crawlerlib import Crawler
from crawlerlib.crawler import CrawlConfig

load_dotenv()

logger = logging.getLogger("crawler_command")


# ── MongoDB filter — companies with website but no description, and funding data ──

MISSING_DESCRIPTION_FILTER = {
    "$and": [
        {
            "$or": [
                {"summary.details.description": {"$exists": False}},
                {"summary.details.description": ""},
            ]
        },
        {
            "summary.about.website": {"$exists": True, "$ne": ""}
        },
        {
            "$or": [
                {"financial.funding_round.number_of_funding_rounds": {"$exists": True, "$ne": ""}},
                {"financial.funding_round.total_funding_amount": {"$exists": True, "$ne": ""}},
                {"financial.investors.number_of_investors": {"$exists": True, "$ne": ""}},
                {"financial.funding_round.table": {"$exists": True, "$ne": {}}},
            ]
        },
    ]
}


class Command(BaseCommand):
    help = (
        "Auto-fetch companies missing descriptions from MongoDB, crawl their websites, "
        "generate descriptions via ChatGPT, and save back to MongoDB + Django."
    )

    # ── Arguments ──────────────────────────────────────────────────────────

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            default="",
            help="(Optional) Single company website URL — skips MongoDB batch mode.",
        )
        parser.add_argument(
            "--batch-size", type=int, default=10,
            help="Number of companies to process per run (default: 10).",
        )
        parser.add_argument(
            "--n", type=int, default=1,
            help="Max ChatGPT accounts to use (rotated per company).",
        )
        parser.add_argument(
            "--prompt-sleep-min", type=int, default=10, metavar="SECS",
            help="Min seconds to sleep between prompts on the same account.",
        )
        parser.add_argument(
            "--prompt-sleep-max", type=int, default=30, metavar="SECS",
            help="Max seconds to sleep between prompts on the same account.",
        )
        parser.add_argument(
            "--max-session-hours", type=float, default=5.0,
            help="Continuous-use limit (hours) before an account is rested.",
        )
        parser.add_argument(
            "--rest-hours", type=float, default=3.0,
            help="Rest duration (hours) after hitting the session limit.",
        )
        parser.add_argument(
            "--max-depth", type=int, default=1,
            help="crawlerlib BFS depth (0=homepage only, 1=also follow links).",
        )

    # ── Main handler ────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        # Set up the shared account manager (rotates accounts across all companies)
        manager = AccountManager(
            max_accounts=options["n"],
            prompt_sleep_min=options["prompt_sleep_min"],
            prompt_sleep_max=options["prompt_sleep_max"],
            max_session_hours=options["max_session_hours"],
            rest_hours=options["rest_hours"],
        )

        if options["url"]:
            # Manual single-URL mode
            self._process_single_url(options["url"], options["max_depth"], manager)
        else:
            # Auto-batch mode — pull companies from MongoDB
            self._process_batch(options["batch_size"], options["max_depth"], manager)

    # ── Single URL mode ─────────────────────────────────────────────────────

    def _process_single_url(self, url: str, max_depth: int, manager: AccountManager):
        """Process one URL manually — no MongoDB lookup, just crawl + generate + save."""
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n🌐 Manual mode — crawling: {url}\n"))
        self._run_pipeline(
            company_url=url,
            mongo_doc_id=None,      # not tied to a specific MongoDB document
            max_depth=max_depth,
            manager=manager,
        )

    # ── Batch mode ───────────────────────────────────────────────────────────

    def _process_batch(self, batch_size: int, max_depth: int, manager: AccountManager):
        """Fetch a batch of companies from MongoDB and process each one."""
        collection = self._get_collection()
        companies = list(
            collection.find(MISSING_DESCRIPTION_FILTER).limit(batch_size)
        )

        if not companies:
            self.stdout.write(
                self.style.WARNING("⚠️  No companies found matching the filter.")
            )
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\n📋 Found {len(companies)} companies without descriptions — processing…\n"
            )
        )

        ok_count = 0
        fail_count = 0

        for idx, doc in enumerate(companies, start=1):
            company_name = doc.get("organization_name", "Unknown")
            raw_website = doc.get("summary", {}).get("about", {}).get("website", "")
            company_url = _normalize_website(raw_website)

            self.stdout.write(
                f"\n[{idx}/{len(companies)}] {company_name} — {company_url}"
            )

            if not company_url:
                self.stdout.write(self.style.WARNING("  ⚠️  No valid website — skipping."))
                fail_count += 1
                continue

            try:
                description = self._run_pipeline(
                    company_url=company_url,
                    mongo_doc_id=doc["_id"],
                    max_depth=max_depth,
                    manager=manager,
                    extra_context=_build_company_context(doc),
                )
                if description:
                    ok_count += 1
                else:
                    fail_count += 1
            except Exception as exc:
                logger.error("❌ Failed for %s: %s", company_url, exc)
                self.stdout.write(self.style.ERROR(f"  ❌ Error: {exc}"))
                fail_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✅ Done — {ok_count} succeeded, {fail_count} failed out of {len(companies)}."
            )
        )

    # ── Core pipeline — crawl → generate → save ────────────────────────────

    def _run_pipeline(
        self,
        company_url: str,
        mongo_doc_id,            # ObjectId or None
        max_depth: int,
        manager: AccountManager,
        extra_context: str = "",
    ) -> str | None:
        """
        Full pipeline for one company:
          crawl website → build prompt context → ChatGPT → save to Mongo + Django.
        Returns the generated description, or None on failure.
        """
        # Step 1 — Crawl the website
        crawled_text = self._crawl_website(company_url, max_depth=max_depth)
        if not crawled_text.strip() and not extra_context.strip():
            self.stdout.write(
                self.style.WARNING(f"  ⚠️  Nothing useful extracted from {company_url} — skipping.")
            )
            return None

        self.stdout.write(f"  📄 Crawled {len(crawled_text)} chars.")

        # Combine crawled website content with any structured MongoDB context
        full_context = _merge_context(extra_context, crawled_text)

        # Step 2 — Acquire a ChatGPT account and generate description
        account = manager.acquire()
        self.stdout.write(f"  👤 Account: {account.email}")

        bot = Bot(account=account)
        description = None
        try:
            if not bot.login_chat(close_driver=False):
                raise RuntimeError(f"Login failed for {account.email}")

            description = bot.generate_company_description(full_context)

            if not description or not description.strip():
                raise RuntimeError("ChatGPT returned an empty response.")

            self.stdout.write(
                f"  📝 {textwrap.shorten(description, 160)}"
            )

            # Step 3 — Update the MongoDB document (or insert if manual mode)
            mongo_object_id = self._update_mongo(
                mongo_doc_id=mongo_doc_id,
                company_url=company_url,
                description=description,
            )

            # Step 4 — Save to Django
            self._save_to_django(
                company_url=company_url,
                description=description,
                mongo_id=str(mongo_object_id),
            )

            self.stdout.write(self.style.SUCCESS(f"  ✅ Saved (mongo_id={mongo_object_id})"))

        finally:
            bot.CloseDriver()
            manager.release(account)

        return description

    # ── Crawl helper ────────────────────────────────────────────────────────

    def _crawl_website(self, url: str, max_depth: int = 1) -> str:
        """
        Crawl the company website using crawlerlib and return a flat
        plain-text blob from the structured page extractions.
        """
        config = CrawlConfig(
            max_depth=max_depth,
            max_pages=10,
            delay=1.5,
            same_domain_only=True,
            respect_robots=True,
            page_intents=["about", "product", "services", "mission"],
        )

        try:
            logger.info("🕷️  Crawling %s (depth=%d)", url, max_depth)
            with Crawler(url, config=config) as crawler:
                pages = crawler.crawl()
        except Exception as exc:
            logger.error("❌ crawlerlib failed for %s: %s", url, exc)
            return ""

        if not pages:
            return ""

        # ParsedPage.to_dict() already includes structured_content — no re-parse needed
        chunks: list[str] = []
        for page in pages:
            structured = page.get("structured_content", {})
            if structured:
                chunk = _structured_to_text(structured)
                if chunk.strip():
                    chunks.append(chunk)
            else:
                # Fallback: raw text
                flat = page.get("text_content", "").strip()
                if flat:
                    chunks.append(flat[:2000])  # cap flat fallback

        return "\n\n".join(chunks)

    # ── MongoDB helpers ──────────────────────────────────────────────────────

    def _get_collection(self):
        """Return the primary MongoDB collection handle."""
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            raise CommandError("MONGO_URI is not set in .env")
        db_name = os.getenv("STARTUPSCRAPERDATA_DB", "STARTUPSCRAPERDATA")
        col_name = os.getenv("STARTUPSCRAPERDATA_DB_COLLECTION", "CorrectData")
        client = MongoClient(mongo_uri)
        # Store on self so the connection lasts the whole command run
        self._mongo_client = client
        return client[db_name][col_name]

    def _update_mongo(self, mongo_doc_id, company_url: str, description: str):
        """
        If mongo_doc_id is provided (batch mode), patch summary.details.description
        in the existing document. Otherwise insert a new standalone document.
        Returns the MongoDB ObjectId.
        """
        collection = self._get_collection()
        generated_at = timezone.now().isoformat()

        if mongo_doc_id:
            # Update the existing company document in-place
            collection.update_one(
                {"_id": mongo_doc_id},
                {
                    "$set": {
                        "summary.details.description": description,
                        "runner_info.description_script": generated_at,
                    }
                },
            )
            logger.info("🔄 Updated MongoDB doc %s with new description.", mongo_doc_id)
            return mongo_doc_id
        else:
            # Manual mode — insert a standalone record
            result = collection.insert_one(
                {
                    "company_url": company_url,
                    "summary": {"details": {"description": description}},
                    "runner_info": {"description_script": generated_at},
                    "word_count": len(description.split()),
                }
            )
            logger.info("➕ Inserted new MongoDB doc %s.", result.inserted_id)
            return result.inserted_id

    # ── Django helper ────────────────────────────────────────────────────────

    def _save_to_django(self, company_url: str, description: str, mongo_id: str):
        """
        Persist the description in Django — stub Text row + ParaphrasedText row
        with the MongoDB ObjectId cross-reference.
        """
        source_text = Text.objects.create(
            text=f"[Crawled] {company_url}",
            pharaphreased="DONE",
        )
        obj = ParaphrasedText.objects.create(
            sentence=source_text,
            response=description,
            PageTitle=company_url,
            number=1,
            mongo_id=mongo_id,
        )
        logger.info("💾 ParaphrasedText pk=%d (mongo_id=%s)", obj.pk, mongo_id)
        return obj


# ── Module-level helpers ──────────────────────────────────────────────────────

def _normalize_website(raw: str) -> str:
    """Ensure the website string is a valid http/https URL."""
    if not raw:
        return ""
    raw = raw.strip().rstrip("/")
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
        if parsed.netloc:
            return raw
    except Exception:
        pass
    return ""


def _build_company_context(doc: dict) -> str:
    """
    Extract key fields from a MongoDB company document and format them
    as a concise text block to supplement the crawled website content.
    """
    lines: list[str] = []

    name = doc.get("organization_name", "")
    if name:
        lines.append(f"Company: {name}")

    details = doc.get("summary", {}).get("details", {})
    about = doc.get("summary", {}).get("about", {})

    if details.get("industries"):
        lines.append(f"Industries: {details['industries']}")
    if details.get("founded_date") or details.get("founded_year"):
        lines.append(f"Founded: {details.get('founded_date') or details.get('founded_year')}")
    if about.get("location", {}).get("country"):
        loc = about["location"]
        location_str = ", ".join(filter(None, [loc.get("city"), loc.get("state"), loc.get("country")]))
        lines.append(f"Headquarters: {location_str}")
    if about.get("no_of_employees"):
        lines.append(f"Employees: {about['no_of_employees']}")
    if details.get("company_type"):
        lines.append(f"Type: {details['company_type']}")
    if details.get("founders"):
        lines.append(f"Founders: {details['founders']}")
    if about.get("last_funding_type"):
        lines.append(f"Last funding type: {about['last_funding_type']}")

    # Financial summary
    funding = doc.get("financial", {}).get("funding_round", {})
    if funding.get("total_funding_amount"):
        lines.append(f"Total funding: {funding['total_funding_amount']}")
    if funding.get("number_of_funding_rounds"):
        lines.append(f"Funding rounds: {funding['number_of_funding_rounds']}")

    # Parent industries
    parent_industries = doc.get("parentIndustry", [])
    if parent_industries:
        lines.append(f"Parent industries: {', '.join(parent_industries)}")

    return "\n".join(lines)


def _merge_context(company_context: str, crawled_text: str) -> str:
    """
    Merge structured MongoDB context with crawled website text.
    MongoDB context goes first (most structured/reliable data).
    Together they are capped at ~4000 chars to stay within prompt limits.
    """
    combined = ""
    if company_context.strip():
        combined += "=== Company Information (from database) ===\n" + company_context.strip()
    if crawled_text.strip():
        if combined:
            combined += "\n\n"
        combined += "=== Website Content (crawled) ===\n" + crawled_text.strip()
    # Safety cap — ~4000 chars is well within ChatGPT's effective context
    return combined[:4000]


def _structured_to_text(structured: dict) -> str:
    """
    Recursively flatten a StructuredExtractor output dict into plain text
    suitable for inclusion in a ChatGPT prompt.
    """
    parts: list[str] = []

    def _flatten(value, indent: int = 0) -> None:
        pad = "  " * indent
        if isinstance(value, str):
            if value.strip():
                parts.append(f"{pad}{value.strip()}")
        elif isinstance(value, list):
            for item in value:
                _flatten(item, indent)
        elif isinstance(value, dict):
            for k, v in value.items():
                if k in ("images", "cta", "links", "price"):
                    continue
                if isinstance(v, str) and v.strip():
                    parts.append(f"{pad}{k}: {v.strip()}")
                else:
                    parts.append(f"{pad}{k}:")
                    _flatten(v, indent + 1)

    for section_title, section_content in structured.items():
        parts.append(f"\n## {section_title}")
        _flatten(section_content)

    return "\n".join(parts)