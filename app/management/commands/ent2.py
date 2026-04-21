from django.core.management.base import BaseCommand, CommandError
from LLM.main import CallLLM
from logger import CustomLogger
from pymongo import MongoClient, UpdateOne
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from dotenv import load_dotenv
import os, time, datetime

load_dotenv()
logger = CustomLogger(log_folder="logs/news_tagger")

MONGO_URI   = os.getenv("MONGO_URI")
BATCH_WRITE = 20
MAX_WORKERS = 10
FETCH_BATCH = 50

lock            = Lock()
processed_count = 0
error_count     = 0


class Command(BaseCommand):
    help = "Tag news documents in MongoDB with sectors, channels, and entities using LLM."

    def add_arguments(self, parser):
        parser.add_argument("--small-llm", action="store_true", default=True, help="Use 12B LLM. Default is small llm 8B.")
        parser.add_argument("--max-workers", type=int, default=MAX_WORKERS, help="Parallel workers (default: 20).")
        parser.add_argument("--fetch-batch", type=int, default=FETCH_BATCH, help="Docs fetched per batch (default: 50).")
        parser.add_argument("--batch-write", type=int, default=BATCH_WRITE, help="Bulk write threshold (default: 20).")

    def handle(self, *args, **options):
        global processed_count, error_count
        processed_count = 0
        error_count     = 0

        self.llm         = CallLLM(small_llm=options["small_llm"])
        self.max_workers = options["max_workers"]
        self.fetch_batch = options["fetch_batch"]
        self.batch_write = options["batch_write"]

        llm_label = "8B (small)" if options["small_llm"] else "120B (big)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n🚀 Starting news tagger — LLM: {llm_label}\n"))

        if not MONGO_URI:
            raise CommandError("MONGO_URI is not set in .env")

        mongo_client = MongoClient(MONGO_URI)
        collection   = mongo_client["NEWSSCRAPERDATA"]["MAIN_NEWS_ALL"]
        projection   = {
            "_id": 1, "title": 1, "description": 1,
            "llm_tagged": 1, "llm_tagged_entities": 1,
            "channel": 1, "sectors": 1
        }

        queries = [
            # P1: completely untouched
            {
                "llm_tagged":          {"$ne": True},
                "llm_tagged_entities": {"$nin": [1, 2]}
            },
            # P2: channels/sectors done, entities missing
            {
                "llm_tagged":          True,
                "llm_tagged_entities": {"$nin": [1, 2]}
            },
            # P3: re-pass old rules
            {
                "llm_tagged_entities": 1
            },
        ]

        start = time.time()

        for p_index, query in enumerate(queries, start=1):
            total = collection.count_documents(query)

            if total == 0:
                self.stdout.write(f"⏭️  P{p_index}: nothing to process, skipping.")
                continue

            self.stdout.write(self.style.MIGRATE_HEADING(f"\n📦 P{p_index}: {total} documents to process."))
            logger.info(f"P{p_index}: {total} docs")

            skip     = 0
            bulk_ops = []

            while True:
                batch = list(
                    collection.find(query, projection)
                    .sort("time", -1)
                    .skip(skip)
                    .limit(self.fetch_batch)
                )

                if not batch:
                    self.stdout.write(self.style.SUCCESS(f"✅ P{p_index}: all batches done."))
                    break

                self.stdout.write(f"🔄 P{p_index} | Fetched: {skip} → {skip + len(batch)}")

                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = {executor.submit(self._process_doc, doc): doc for doc in batch}

                    for future in as_completed(futures):
                        op = future.result()
                        if op:
                            bulk_ops.append(op)

                        if len(bulk_ops) >= self.batch_write:
                            collection.bulk_write(bulk_ops, ordered=False)
                            bulk_ops.clear()
                            elapsed = time.time() - start
                            rate    = processed_count / elapsed if elapsed > 0 else 0
                            eta     = (total - processed_count) / rate if rate > 0 else 0
                            msg = (
                                f"💾 Written | P{p_index} | {processed_count}/{total} | "
                                f"Errors: {error_count} | "
                                f"{rate:.1f} docs/sec | "
                                f"ETA: {eta/60:.1f} min"
                            )
                            self.stdout.write(msg)
                            logger.info(msg)

                if bulk_ops:
                    collection.bulk_write(bulk_ops, ordered=False)
                    bulk_ops.clear()

                skip += self.fetch_batch

        elapsed = time.time() - start
        msg = (
            f"🎯 Done | Processed: {processed_count} | "
            f"Errors: {error_count} | "
            f"Time: {elapsed/60:.1f} min"
        )
        self.stdout.write(self.style.SUCCESS(f"\n{msg}"))
        logger.info(msg)
        mongo_client.close()

    def _process_doc(self, doc: dict) -> UpdateOne | None:
        global processed_count, error_count
        try:
            raw_desc = doc.get("description", "")
            if isinstance(raw_desc, dict):
                description = raw_desc.get("details", "") or raw_desc.get("summary", "")
            else:
                description = raw_desc or ""

            title         = doc.get("title", "")
            needs_tagging = not (doc.get("channel") and doc.get("sectors"))
            needs_entities = doc.get("llm_tagged_entities", 0) != 2

            if not needs_tagging and not needs_entities:
                return None

            update_fields = {}
            t0 = time.time()

            if needs_tagging and needs_entities:
                result = self.llm.get_all(title, description)
                channels = {k: self.llm.channels_mapping[k] for k in result.get("channels", []) if k in self.llm.channels_mapping}
                update_fields.update({
                    "channel":             channels,
                    "sectors":             result.get("sectors", []),
                    "llm_tagged":          True,
                    "entities":            result.get("entities", []),
                    "llm_tagged_entities": 2
                })

            elif needs_tagging:
                result = self.llm.get_all(title, description)
                channels = {k: self.llm.channels_mapping[k] for k in result.get("channels", []) if k in self.llm.channels_mapping}
                update_fields.update({
                    "channel":    channels,
                    "sectors":    result.get("sectors", []),
                    "llm_tagged": True
                })

            elif needs_entities:
                result = self.llm.get_entities(title, description)
                update_fields.update({
                    "entities":            result.get("entities", []),
                    "llm_tagged_entities": 2
                })

            total = round(time.time() - t0, 2)
            print(f"{datetime.datetime.now()} | ID: {doc['_id']} | TOTAL: {total}s")
            logger.info(f"ID: {doc['_id']} | total: {total}s")

            with lock:
                processed_count += 1

            if not update_fields:
                return None

            return UpdateOne({"_id": doc["_id"]}, {"$set": update_fields})

        except Exception as e:
            with lock:
                error_count += 1
            logger.error(f"Doc error {doc.get('_id')}: {e}")
            return None