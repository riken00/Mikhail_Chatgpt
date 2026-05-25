from django.core.management.base import BaseCommand, CommandError
from pandas import options
from LLM.desc import CallLLM
from crawlerlib.crawler import CrawlConfig, Crawler
from logger import CustomLogger
from urllib.parse import urlparse
from pymongo import MongoClient
from django.utils import timezone
from app.utils.stats import StatsCollector
import os, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

logger = CustomLogger(log_folder="logs/crawler2")

MISSING_DESCRIPTION_FILTER = {
    "$and": [
        {
            "$or": [
                {"summary.details.description": {"$exists": False}},
                {"summary.details.description": ""},
                {
                    "$expr": {
                        "$lt": [
                            {
                                "$strLenCP": {
                                    "$ifNull": ["$summary.details.description", ""]
                                }
                            },
                            200,
                        ]
                    }
                },
                {
                    "$and": [
                        {"runner_info.description_script": "done"},
                        {
                            "$expr": {
                                "$lt": [
                                    {
                                        "$strLenCP": {
                                            "$ifNull": [
                                                "$summary.details.description",
                                                "",
                                            ]
                                        }
                                    },
                                    500,
                                ]
                            }
                        },
                    ]
                },
            ]
        },
        {"summary.about.website": {"$exists": True, "$ne": ""}},
        {
            "$or": [
                {
                    "financial.funding_round.number_of_funding_rounds": {
                        "$exists": True,
                        "$ne": "",
                    }
                },
                {
                    "financial.funding_round.total_funding_amount": {
                        "$exists": True,
                        "$ne": "",
                    }
                },
                {
                    "financial.investors.number_of_investors": {
                        "$exists": True,
                        "$ne": "",
                    }
                },
                {"financial.funding_round.table": {"$exists": True, "$ne": {}}},
            ]
        },
        {"runner_info.description_script": {"$exists": False}},
    ]
}


def _normalize_website(raw: str) -> str:
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


class Command(BaseCommand):
    help = """
        Auto-fetch companies missing descriptions from MongoDB, crawl their websites, generate descriptions via LLM, and save back to MongoDB.
        
        # Default — Big LLM (120B), batch 10, depth 1, pages 3
        python manage.py crawler2

        # Custom batch size
        python manage.py crawler2 --batch-size 50

        # Custom crawl depth and pages
        python manage.py crawler2 --max-depth 2 --max-pages 5

        # Use small LLM (8B)
        python manage.py crawler2 --small-llm

        # Full custom run with big LLM
        python manage.py crawler2 --batch-size 20 --max-depth 2 --max-pages 5

        # Full custom run with small LLM
        python manage.py crawler2 --small-llm --batch-size 20 --max-depth 2 --max-pages 5
    """

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=10,
            help="Number of companies to process per run (default: 10).",
        )
        parser.add_argument(
            "--max-depth",
            type=int,
            default=1,
            help="Crawl depth (0=homepage only, 1=follow links).",
        )
        parser.add_argument(
            "--max-pages", type=int, default=3, help="Max pages to crawl per company."
        )
        parser.add_argument(
            "--small-llm",
            action="store_true",
            default=False,
            help="Use small LLM (8B). Default is 120B.",
        )
        parser.add_argument("--no-small-llm", dest="small_llm", action="store_false")
        parser.add_argument(
            "--threads",
            type=int,
            default=30,
            help="Number of parallel threads (default: 10).",
        )

    def _claim_next(self) -> dict | None:
        """Atomically claim one unclaimed document."""

        filters = [
            {
                "$and": [
                    {
                        "$or": [
                            {"summary.details.description": {"$exists": False}},
                            {"summary.details.description": ""},
                            {
                                "$expr": {
                                    "$lt": [
                                        {
                                            "$strLenCP": {
                                                "$ifNull": [
                                                    "$summary.details.description",
                                                    "",
                                                ]
                                            }
                                        },
                                        200,
                                    ]
                                }
                            },
                            # NEW: re-process if done but description < 100 words (approx 500 chars)
                            {
                                "$and": [
                                    {"runner_info.description_script": "done"},
                                    {
                                        "$expr": {
                                            "$lt": [
                                                {
                                                    "$strLenCP": {
                                                        "$ifNull": [
                                                            "$summary.details.description",
                                                            "",
                                                        ]
                                                    }
                                                },
                                                500,
                                            ]
                                        }
                                    },
                                ]
                            },
                        ]
                    },
                    {"summary.about.website": {"$exists": True, "$ne": ""}},
                    {
                        "$or": [
                            {
                                "financial.funding_round.number_of_funding_rounds": {
                                    "$exists": True,
                                    "$ne": "",
                                }
                            },
                            {
                                "financial.funding_round.total_funding_amount": {
                                    "$exists": True,
                                    "$ne": "",
                                }
                            },
                            {
                                "financial.investors.number_of_investors": {
                                    "$exists": True,
                                    "$ne": "",
                                }
                            },
                            {
                                "financial.funding_round.table": {
                                    "$exists": True,
                                    "$ne": {},
                                }
                            },
                        ]
                    },
                    # {"runner_info.description_script": {"$exists": False}}
                ]
            },
        
        {
            "$and": [
                # Has funding
                {
                    "$or": [
                        {"financial.funding_round.number_of_funding_rounds": {"$exists": True, "$ne": ""}},
                        {"financial.funding_round.total_funding_amount": {"$exists": True, "$ne": ""}},
                        {"financial.investors.number_of_investors": {"$exists": True, "$ne": ""}},
                        {"financial.funding_round.table": {"$exists": True, "$ne": {}}},
                    ]
                },
                # Founded after 2005
                {
                    "$or": [
                        {"summary.about.founded_at": {"$regex": "200[6-9]|20[1-9][0-9]", "$options": "i"}},
                        {"summary.about.founded_at": {"$exists": False}},
                        {"summary.about.founded_at": ""},
                    ]
                },
                # Description missing or short (< 100 words ~ 500 chars)
                {
                    "$or": [
                        {"summary.details.description": {"$exists": False}},
                        {"summary.details.description": ""},
                        {"$expr": {"$lt": [{"$strLenCP": {"$ifNull": ["$summary.details.description", ""]}}, 500]}},
                    ]
                },
                {"summary.about.website": {"$exists": True, "$ne": ""}},
                {"runner_info.description_script": {"$ne": "in_progress"}},
            ]
        },
        
        {
            "$and": [
                # crawl_failed or similar
                {
                    "runner_info.description_script": {
                        "$in": ["crawl_failed", "crawl_empty", "crawl_insufficient", "llm_failed", "llm_short"]
                    }
                },
                # Description still missing or short
                {
                    "$or": [
                        {"summary.details.description": {"$exists": False}},
                        {"summary.details.description": ""},
                        {"$expr": {"$lt": [{"$strLenCP": {"$ifNull": ["$summary.details.description", ""]}}, 500]}},
                    ]
                },
                {"summary.about.website": {"$exists": True, "$ne": ""}},
                {"runner_info.description_script": {"$ne": "in_progress"}},
            ]
        },
        
        {
            "$and": [
                # Founded after 2005 (or no date), no funding requirement
                {
                    "$or": [
                        {"summary.about.founded_at": {"$regex": "200[6-9]|20[1-9][0-9]", "$options": "i"}},
                        {"summary.about.founded_at": {"$exists": False}},
                        {"summary.about.founded_at": ""},
                    ]
                },
                # Description missing or short
                {
                    "$or": [
                        {"summary.details.description": {"$exists": False}},
                        {"summary.details.description": ""},
                        {"$expr": {"$lt": [{"$strLenCP": {"$ifNull": ["$summary.details.description", ""]}}, 500]}},
                    ]
                },
                {"summary.about.website": {"$exists": True, "$ne": ""}},
                {"runner_info.description_script": {"$ne": "in_progress"}},
            ]
        },
        
        {
            "$and": [
                # description_script done but description < 100 words (~500 chars)
                {"runner_info.description_script": "done"},
                {
                    "$expr": {
                        "$lt": [{"$strLenCP": {"$ifNull": ["$summary.details.description", ""]}}, 500]
                    }
                },
                {"summary.about.website": {"$exists": True, "$ne": ""}},
            ]
        }
        ]
        data = None
        for filter in filters:
            final_filter = {
                "$and": [
                    filter,
                    {
                        "$or": [
                            {"runner_info.description_script_run_count": {"$exists": False}},
                            {"runner_info.description_script_run_count": {"$lt": 3}}
                        ]
                    }
                ]
            }
            data = self.collection.find_one_and_update(final_filter, {"$set": {"runner_info.description_script": "in_progress"}},return_document=True)
            if data:
                break
            
        return data

        return self.collection.find_one_and_update(
            MISSING_DESCRIPTION_FILTER,
            {"$set": {"runner_info.description_script": "in_progress"}},
            return_document=True,
        )

    def _worker(self, idx, max_depth, max_pages):
        while True:
            doc = self._claim_next()
            if doc is None:
                return

            start_time = time.time()
            success = False
            company_name = doc.get("organization_name", "Unknown")
            raw_website = doc.get("summary", {}).get("about", {}).get("website", "")
            company_url = _normalize_website(raw_website)

            with self.print_lock:
                self.stdout.write(f"\n[thread-{idx}] {company_name} — {company_url}")

            if not company_url:
                with self.print_lock:
                    self.stdout.write(
                        self.style.WARNING(
                            f"[thread-{idx}] No valid website — skipping."
                        )
                    )
                self.collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"runner_info.description_script": "no_website"}},
                )
                self.stats.log(success=False, processing_time=time.time() - start_time)
                continue

            try:
                description = self._run_pipeline(doc, company_url, max_depth, max_pages)
                success = bool(description)
            except Exception as exc:
                logger.error(f"[thread-{idx}] Failed for {company_url}: {exc}")
                with self.print_lock:
                    self.stdout.write(self.style.ERROR(f"[thread-{idx}] Error: {exc}"))
                self.collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"runner_info.description_script": "error"}},
                )
            finally:
                self.stats.log(
                    success=success, processing_time=time.time() - start_time
                )

    def handle(self, *args, **options):
        self.stats = StatsCollector("crawler2")
        self.llm = CallLLM(small_llm=options["small_llm"])
        self.collection = self._get_collection()
        self.print_lock = Lock()

        max_depth = options["max_depth"]
        max_pages = options["max_pages"]
        num_threads = options["threads"]

        self.stdout.write(
            self.style.MIGRATE_HEADING(f"Starting with {num_threads} threads\n")
        )

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(self._worker, idx, max_depth, max_pages)
                for idx in range(1, num_threads + 1)
            ]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    self.stdout.write(self.style.ERROR(f"Thread crashed: {exc}"))

        self.stats.flush()
        self.stdout.write(self.style.SUCCESS("All threads done."))

    def _run_pipeline( self, doc: dict, company_url: str, max_depth: int, max_pages: int ) -> str | None:
        company_name = doc.get("organization_name", "Unknown")
        company_id = doc.get("_id")
        crawled_text = self._crawl_website(
            company_url, max_depth=max_depth, max_pages=max_pages
        )
        company_context = self._build_company_context(doc)

        # If crawl failed and no DB context either — mark as crawl_failed and skip
        if not crawled_text.strip() and not company_context.strip():
            self.stdout.write(
                self.style.WARNING(f"  ⚠️  Nothing extracted {company_name} | {company_id} — marking crawl_failed.")
            )
            self.collection.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {
                        "runner_info.description_script": "crawl_failed",
                        "runner_info.description_script_url": company_url,
                        "runner_info.description_script_reason": "no_content_crawled",
                        "runner_info.description_script_at": timezone.now().isoformat(),
                    },
                    "$inc": {
                        "runner_info.description_script_run_count": 1
                    }
                },
            )
            return None

        # Crawl returned nothing but DB context exists — mark partial and still skip LLM
        if not crawled_text.strip():
            self.stdout.write(
                self.style.WARNING(
                    f"  ⚠️  Crawl returned no data | {company_name} | {company_id} — marking crawl_empty, skipping LLM."
                )
            )
            self.collection.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {
                        "runner_info.description_script": "crawl_empty",
                        "runner_info.description_script_url": company_url,
                        "runner_info.description_script_reason": "crawler_returned_no_pages",
                        "runner_info.description_script_at": timezone.now().isoformat(),
                    },
                    "$inc": {
                        "runner_info.description_script_run_count": 1
                    }
                },
            )
            return None
        
        if len(crawled_text.strip()) < 2000:
            logger.warning(f"Pipeline | '{company_name}' | {company_id}  | crawl returned very little text ({len(crawled_text.strip())} chars) — marking crawl_insufficient.")
            self.collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {
                    "runner_info.description_script":        "crawl_insufficient",
                    "runner_info.description_script_url":    company_url,
                    "runner_info.description_script_reason": "crawler_returned_insufficient_text",
                    "runner_info.description_script_at":     timezone.now().isoformat(),
                },
                 "$inc": {
                        "runner_info.description_script_run_count": 1
                }
                }
            )
            return None

        self.stdout.write(f"  📄 Crawled {len(crawled_text)} chars.")
        full_context = self._merge_context(company_context, crawled_text)
        description = self.llm.get_description(full_context)

        if not description or not description.strip() or len(description.strip()) < 200:
            failed_status = "llm_failed"
            if len(description.strip()) < 200 and len(description.strip()) > 0:
                failed_status = "llm_short"
                logger.warning(f"Pipeline | '{company_name}' | {company_id} | LLM returned short description ({len(description.strip())} chars).")
                
            self.stdout.write(
                self.style.WARNING(
                    f"  ⚠️  LLM returned empty description | {company_name} | {company_id} — marking {failed_status}."
                )
            )
            self.collection.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {
                        "runner_info.description_script": failed_status,
                        "runner_info.description_script_url": company_url,
                        "runner_info.description_script_reason": "llm_returned_empty",
                        "runner_info.description_script_at": timezone.now().isoformat(),
                    },
                    "$inc": {
                        "runner_info.description_script_run_count": 1
                    }
                },
            )
            return None

        self.stdout.write(f"  📝 {description[:160]}…")

        self.collection.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "summary.details.description": description,
                    "runner_info.description_script": "done",
                    "runner_info.description_script_url": company_url,
                    "runner_info.description_script_at": timezone.now().isoformat(),
                },
                "$inc": {
                        "runner_info.description_script_run_count": 1
                    }
            },
        )
        self.stdout.write(self.style.SUCCESS(f"  ✅ Saved (id={doc['_id']})"))
        return description

    def _get_collection(self):
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            raise CommandError("MONGO_URI is not set in .env")
        db_name = os.getenv("STARTUPSCRAPERDATA_DB", "STARTUPSCRAPERDATA")
        col_name = os.getenv("STARTUPSCRAPERDATA_DB_COLLECTION", "CorrectData")
        self._mongo_client = MongoClient(mongo_uri)
        return self._mongo_client[db_name][col_name]

    def _crawl_website(self, url: str, max_depth: int = 1, max_pages: int = 3) -> str:
        config = CrawlConfig(
            max_depth=max_depth,
            max_pages=max_pages,
            delay=0.5,
            same_domain_only=True,
            respect_robots=True,
            max_retries=1,
            timeout=5,
            page_intents=["about", "product", "services"],
        )
        try:
            logger.info(f"Crawling {url} (depth={max_depth})")
            with Crawler(url, config=config) as crawler:
                pages = crawler.crawl()
        except Exception as exc:
            logger.error(f"crawlerlib failed for {url}: {exc}")
            return ""

        if not pages:
            return ""

        chunks = []
        for page in pages:
            if isinstance(page, str):
                # crawlerlib returned raw strings
                if page.strip():
                    chunks.append(page.strip()[:2000])
            elif isinstance(page, dict):
                structured = page.get("structured_content", {})
                if structured:
                    chunk = self._structured_to_text(structured)
                    if chunk.strip():
                        chunks.append(chunk)
                else:
                    flat = page.get("text_content", "").strip()
                    if flat:
                        chunks.append(flat[:2000])

        return "\n\n".join(chunks)

    def _build_company_context(self, doc: dict) -> str:
        lines = []
        name = doc.get("organization_name", "")
        if name:
            lines.append(f"Company: {name}")

        details = doc.get("summary", {}).get("details", {})
        about = doc.get("summary", {}).get("about", {})

        if details.get("industries"):
            lines.append(f"Industries: {details['industries']}")
        if details.get("founded_date") or details.get("founded_year"):
            lines.append(
                f"Founded: {details.get('founded_date') or details.get('founded_year')}"
            )
        location = about.get("location", {})
        if isinstance(location, dict) and location.get("country"):
            location_str = ", ".join(
                filter(
                    None,
                    [
                        location.get("city"),
                        location.get("state"),
                        location.get("country"),
                    ],
                )
            )
            lines.append(f"Headquarters: {location_str}")
        elif isinstance(location, str) and location.strip():
            lines.append(f"Headquarters: {location.strip()}")

        if about.get("no_of_employees"):
            lines.append(f"Employees: {about['no_of_employees']}")
        if details.get("company_type"):
            lines.append(f"Type: {details['company_type']}")
        if details.get("founders"):
            lines.append(f"Founders: {details['founders']}")
        if about.get("last_funding_type"):
            lines.append(f"Last funding type: {about['last_funding_type']}")

        funding = doc.get("financial", {}).get("funding_round", {})
        if funding.get("total_funding_amount"):
            lines.append(f"Total funding: {funding['total_funding_amount']}")
        if funding.get("number_of_funding_rounds"):
            lines.append(f"Funding rounds: {funding['number_of_funding_rounds']}")

        parent_industries = doc.get("parentIndustry", [])
        if parent_industries:
            lines.append(f"Parent industries: {', '.join(parent_industries)}")

        return "\n".join(lines)

    def _merge_context(self, company_context: str, crawled_text: str) -> str:
        combined = ""
        if company_context.strip():
            combined += (
                "=== Company Information (from database) ===\n"
                + company_context.strip()
            )
        if crawled_text.strip():
            if combined:
                combined += "\n\n"
            combined += "=== Website Content (crawled) ===\n" + crawled_text.strip()
        return combined[:5000]

    def _structured_to_text(self, structured: dict) -> str:
        parts = []

        def _flatten(value, indent=0):
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
