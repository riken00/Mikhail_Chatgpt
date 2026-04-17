"""
scrape -- Management command for the legacy paraphrase/entity-extraction workflow.

Picks up to --n accounts from user_details and runs the Bot.work() loop
concurrently, one browser process per account.

Usage:
    python manage.py scrape --n 2
"""

import concurrent.futures
import logging
import time

from django.core.management.base import BaseCommand

from app.bot import Bot
from app.models import user_details

logger = logging.getLogger("scrape_command")


class Command(BaseCommand):
    help = "Run the ChatGPT scraping bot across N user accounts concurrently."

    def add_arguments(self, parser):
        parser.add_argument(
            "--n",
            type=int,
            default=1,
            help="Number of accounts to run simultaneously (capped by total accounts in DB).",
        )

    def handle(self, *args, **options):
        n = self._resolve_account_count(options["n"])
        accounts = list(user_details.objects.all()[:n])

        if not accounts:
            self.stdout.write(
                self.style.WARNING("No user_details records found. Add accounts first.")
            )
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING(f"\nStarting scrape across {len(accounts)} account(s).\n")
        )

        if len(accounts) == 1:
            # Single account -- run in the main thread (simpler, easier to debug)
            self._run_account(accounts[0])
        else:
            # Multiple accounts -- run each in its own thread
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(accounts)) as executor:
                futures = {executor.submit(self._run_account, acc): acc for acc in accounts}
                for future in concurrent.futures.as_completed(futures):
                    acc = futures[future]
                    try:
                        future.result()
                    except Exception as exc:
                        logger.error("Account %s raised an error: %s", acc.email, exc)

    # -- Worker --

    def _run_account(self, account: user_details) -> None:
        """Run the main Bot.work() loop for a single account in a retry wrapper."""
        while True:
            bot = Bot(account=account)
            try:
                bot.work()
            except Exception as exc:
                logger.error("Bot error for %s: %s", account.email, exc)
            finally:
                bot.CloseDriver()
            # Brief pause before retrying (avoids hammering on repeated failures)
            time.sleep(5)

    # -- Helpers --

    def _resolve_account_count(self, requested: int) -> int:
        """Cap requested n to the number of accounts actually in the database."""
        total = user_details.objects.count()
        resolved = min(requested, total) if total else 0
        if resolved < requested:
            logger.warning(
                "Requested %d accounts but only %d exist in DB -- using %d.",
                requested, total, resolved,
            )
        return resolved