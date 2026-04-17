"""
entities -- Management command that tags news documents in MongoDB with
entities, channels, and sectors using ChatGPT browser automation.

Connects to NEWSSCRAPERDATA.MAIN_NEWS_ALL and processes documents in three
priority passes:
  P1: completely untouched (need channels + sectors + entities)
  P2: channels/sectors done, entities missing
  P3: re-pass docs with old entity rules (llm_tagged_entities == 1)

For each document, a single combined prompt is sent to ChatGPT asking for
all needed classifications in one JSON response. Results are bulk-written
back to MongoDB every BATCH_WRITE documents.

Usage:
    python manage.py entities
    python manage.py entities --batch-size 200
    python manage.py entities --n 2
"""

import json
import logging
import os
import re
import signal
import time
import random

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne
from pymongo.errors import (
    ConnectionFailure,
    OperationFailure,
    ServerSelectionTimeoutError,
)

from app.account_manager import AccountManager
from app.bot import Bot
from app.llm_apis import LLMService, CHANNELS_MAP, SECTORS_LIST
from app.models import user_details

load_dotenv()

logger = logging.getLogger("entities_command")

BATCH_WRITE = 20
FETCH_BATCH = 50

# Constants removed, using app.llm_apis instead.

# MongoDB query passes in priority order
QUERIES = [
    # P1: completely untouched
    {
        "llm_tagged":          {"$ne": True},
        "llm_tagged_entities": {"$nin": [1, 2]},
    },
    # P2: channels/sectors done, entities missing
    {
        "llm_tagged":          True,
        "llm_tagged_entities": {"$nin": [1, 2]},
    },
    # P3: re-pass old rules
    {
        "llm_tagged_entities": 1,
    },
]

PROJECTION = {
    "_id": 1, "title": 1, "description": 1,
    "llm_tagged": 1, "llm_tagged_entities": 1,
    "channel": 1, "sectors": 1,
}


class Command(BaseCommand):
    help = (
        "Tag news documents in MongoDB with entities, channels, and sectors "
        "using ChatGPT browser automation."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mongo_client = None
        self._shutdown_requested = False

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size", type=int, default=500,
            help="Max documents to process per run (default: 500).",
        )
        parser.add_argument(
            "--n", type=int, default=1,
            help="Max ChatGPT accounts to use.",
        )
        parser.add_argument(
            "--llm", type=bool, default=False,
            help="Use LLM for entity tagging.",
        )
        parser.add_argument(
            "--prompt-sleep-min", type=int, default=5, metavar="SECS",
            help="Min seconds to sleep between prompts.",
        )
        parser.add_argument(
            "--prompt-sleep-max", type=int, default=15, metavar="SECS",
            help="Max seconds to sleep between prompts.",
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
            "--engine", choices=["openai", "selenium"], default="selenium",
            help="LLM engine to use (default: selenium).",
        )
        parser.add_argument(
            "--openai-api-key", default=os.getenv("OPENAI_API_KEY", ""),
            help="OpenAI API Key (if using openai engine).",
        )
        parser.add_argument(
            "--openai-base-url", default=os.getenv("OPENAI_BASE_URL", ""),
            help="OpenAI Base URL (optional).",
        )
        parser.add_argument(
            "--openai-model", default=os.getenv("OPENAI_MODEL", "gpt-4"),
            help="OpenAI Model name.",
        )

    # -- Main handler --

    def handle(self, *args, **options):
        total_accounts = user_details.objects.count()
        if total_accounts == 0:
            raise CommandError(
                "No ChatGPT accounts found. Add accounts first with: "
                "python manage.py addaccount"
            )
        requested_n = options["n"]
        if requested_n > total_accounts:
            logger.warning(
                "Requested %d accounts but only %d exist -- using %d.",
                requested_n, total_accounts, total_accounts,
            )
            options["n"] = total_accounts

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        manager = AccountManager(
            max_accounts=options["n"],
            prompt_sleep_min=options["prompt_sleep_min"],
            prompt_sleep_max=options["prompt_sleep_max"],
            max_session_hours=options["max_session_hours"],
            rest_hours=options["rest_hours"],
        )

        self.engine = options["engine"]
        self.llm_config = {
            "api_key": options["openai_api_key"],
            "base_url": options["openai_base_url"],
            "model": options["openai_model"],
        }

        collection = self._get_collection()

        account = manager.acquire()
        bot = Bot(account=account)
        ok_count = 0
        fail_count = 0

        try:
            self._login_bot(bot, account)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Logged in as {account.email} (Engine: {self.engine}) -- starting entity tagging.\n"
                )
            )

            llm_service = LLMService(
                engine=self.engine,
                bot_instance=bot,
                **self.llm_config
            )

            remaining_budget = options["batch_size"]

            for p_index, query in enumerate(QUERIES, start=1):
                if self._shutdown_requested or remaining_budget <= 0:
                    break

                total = collection.count_documents(query)
                if total == 0:
                    self.stdout.write(f"P{p_index}: nothing to process, skipping.")
                    continue

                self.stdout.write(
                    self.style.MIGRATE_HEADING(
                        f"\nP{p_index}: {total} documents to process.\n"
                    )
                )

                skip = 0
                bulk_ops: list[UpdateOne] = []
                pass_ok = 0
                pass_fail = 0

                while not self._shutdown_requested and remaining_budget > 0:
                    batch = list(
                        collection.find(query, PROJECTION)
                        .sort("time", -1)
                        .skip(skip)
                        .limit(FETCH_BATCH)
                    )
                    if not batch:
                        self.stdout.write(f"P{p_index}: all batches done.")
                        break

                    self.stdout.write(
                        f"P{p_index} | Fetched batch: {skip} -> {skip + len(batch)}"
                    )

                    for doc in batch:
                        if self._shutdown_requested or remaining_budget <= 0:
                            break

                        # Rotate account if needed
                        if account.is_resting():
                            self.stdout.write(
                                self.style.WARNING(
                                    f"Account {account.email} is resting -- switching..."
                                )
                            )
                            bot.CloseDriver()
                            manager.release(account, apply_prompt_sleep=False)
                            account = manager.acquire()
                            bot = Bot(account=account)
                            self._login_bot(bot, account)
                            llm_service = LLMService(
                                engine=self.engine,
                                bot_instance=bot,
                                **self.llm_config
                            )
                            self.stdout.write(
                                self.style.SUCCESS(f"Switched to {account.email}")
                            )

                        op = self._process_doc(doc, llm_service)
                        if op is not None:
                            bulk_ops.append(op)
                            pass_ok += 1
                            ok_count += 1
                        else:
                            pass_fail += 1
                            fail_count += 1

                        remaining_budget -= 1

                        # Bulk write when buffer is full
                        if len(bulk_ops) >= BATCH_WRITE:
                            self._flush_bulk(collection, bulk_ops, p_index, pass_ok, total)

                        # Inter-prompt sleep
                        sleep_sec = random.randint(options["prompt_sleep_min"], options["prompt_sleep_max"])
                        time.sleep(sleep_sec)

                    # Flush remaining ops for this fetch batch
                    if bulk_ops:
                        self._flush_bulk(collection, bulk_ops, p_index, pass_ok, total)

                    skip += FETCH_BATCH

                self.stdout.write(
                    f"P{p_index} complete: {pass_ok} ok, {pass_fail} failed."
                )

        finally:
            bot.CloseDriver()
            manager.release(account, apply_prompt_sleep=False)
            self._close_mongo()

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone -- {ok_count} succeeded, {fail_count} failed."
            )
        )

    # -- Signal handler --

    def _handle_signal(self, signum, frame):
        sig_name = signal.Signals(signum).name
        self.stderr.write(
            f"\n{sig_name} received -- finishing current document and shutting down.\n"
        )
        self._shutdown_requested = True

    # -- Login helper --

    def _login_bot(self, bot: Bot, account) -> None:
        self.stdout.write(f"Logging in as {account.email} ...")
        if not bot.login_chat(close_driver=False):
            raise CommandError(f"Login failed for account: {account.email}")

    # -- Per-document processing --

    def _process_doc(self, doc: dict, llm_service: LLMService) -> UpdateOne | None:
        """
        Determine what the document needs (entities, channels, sectors),
        delegate to LLMService, and return an UpdateOne op.
        """
        doc_id = doc.get("_id")
        title = doc.get("title", "")
        raw_desc = doc.get("description", "")
        if isinstance(raw_desc, dict):
            description = raw_desc.get("details", "") or raw_desc.get("summary", "")
        else:
            description = raw_desc or ""

        if not title and not description:
            logger.warning("Skipping doc %s -- no title or description.", doc_id)
            return None

        needs_tagging = not (doc.get("channel") and doc.get("sectors"))
        entity_status = doc.get("llm_tagged_entities", 0)
        needs_entities = entity_status != 2

        if not needs_tagging and not needs_entities:
            return None

        t0 = time.time()

        try:
            result = llm_service.extract_metadata(
                title, description, needs_tagging, needs_entities,
            )
        except Exception as exc:
            logger.error("Failed for doc %s: %s", doc_id, exc)
            self.stdout.write(self.style.ERROR(f"  Error on {doc_id}: {exc}"))
            return None

        elapsed = round(time.time() - t0, 2)
        self.stdout.write(f"  Doc {doc_id} | {elapsed}s")

        update_fields = {}
        if needs_tagging and needs_entities:
            update_fields.update({
                "channel":             result.get("channel", {}),
                "sectors":             result.get("sectors", []),
                "llm_tagged":          True,
                "entities":            result.get("entities", []),
                "llm_tagged_entities": 2,
            })
        elif needs_tagging:
            update_fields.update({
                "channel":    result.get("channel", {}),
                "sectors":    result.get("sectors", []),
                "llm_tagged": True,
            })
        elif needs_entities:
            update_fields.update({
                "entities":            result.get("entities", []),
                "llm_tagged_entities": 2,
            })

        if not update_fields:
            return None

        return UpdateOne({"_id": doc_id}, {"$set": update_fields})

    # -- Bulk write --

    def _flush_bulk(
        self, collection, bulk_ops: list, p_index: int, pass_ok: int, total: int,
    ) -> None:
        """Write pending bulk operations to MongoDB and clear the buffer."""
        if not bulk_ops:
            return
        try:
            collection.bulk_write(bulk_ops, ordered=False)
            self.stdout.write(
                f"  Written {len(bulk_ops)} ops | P{p_index} | {pass_ok}/{total}"
            )
        except (ConnectionFailure, OperationFailure) as exc:
            logger.error("Bulk write failed: %s", exc)
            self.stdout.write(self.style.ERROR(f"  Bulk write error: {exc}"))
        bulk_ops.clear()

    # -- MongoDB helpers --

    def _get_collection(self):
        """Return the news collection handle (connection is cached)."""
        if self._mongo_client is None:
            mongo_uri = os.getenv("MONGO_URI")
            if not mongo_uri:
                raise CommandError("MONGO_URI is not set in .env")
            try:
                client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
                client.admin.command("ping")
            except (ConnectionFailure, ServerSelectionTimeoutError) as exc:
                raise CommandError(f"Cannot connect to MongoDB: {exc}")
            self._mongo_client = client

        db_name = os.getenv("NEWSSCRAPERDATA_DB", "NEWSSCRAPERDATA")
        col_name = os.getenv("NEWSSCRAPERDATA_COLLECTION", "MAIN_NEWS_ALL")
        return self._mongo_client[db_name][col_name]

    def _close_mongo(self):
        if self._mongo_client is not None:
            try:
                self._mongo_client.close()
            except Exception:
                pass
            self._mongo_client = None


# Prompt helpers removed, moved to app.llm_apis.LLMService.
