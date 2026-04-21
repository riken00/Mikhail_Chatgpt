"""
AccountManager -- Thread-safe, anti-bot account scheduler.

Responsibilities:
  - Pick available user_details accounts (not currently resting).
  - Track continuous session duration; force a rest after max_session_hours.
  - Enforce a configurable sleep between consecutive prompts on the same account.
  - Manage per-account threading locks so two threads never share one browser.
"""

import logging
import random
import time
import threading
from datetime import timedelta

from django.utils import timezone

from app.models import user_details

logger = logging.getLogger("account_manager")


class AccountManager:
    """
    Manages a pool of ChatGPT accounts from the user_details model.

    Usage
    -----
    >>> manager = AccountManager(max_accounts=2)
    >>> account = manager.acquire()        # blocks until one is free
    >>> try:
    ...     # do work with account
    ... finally:
    ...     manager.release(account)       # marks last_used_at, sleeps, etc.
    """

    def __init__(
        self,
        max_accounts: int = 1,
        prompt_sleep_min: int = 10,
        prompt_sleep_max: int = 30,
        max_session_hours: float = 5.0,
        rest_hours: float = 3.0,
    ):
        self.max_accounts = max_accounts
        self.prompt_sleep_min = prompt_sleep_min
        self.prompt_sleep_max = prompt_sleep_max
        self.max_session_hours = max_session_hours
        self.rest_hours = rest_hours

        self._lock = threading.Lock()
        self._in_use: set[int] = set()

    def acquire(self, timeout: float = 3600.0) -> user_details:
        deadline = time.time() + timeout
        breakpoint()
        while time.time() < deadline:
            account = self._pick_account()
            if account:
                # If the account has an expired rest, clear it
                if account.rest_until and account.rest_until <= timezone.now():
                    account.rest_until = None
                    account.session_started_at = None
                    account.save(update_fields=["rest_until", "session_started_at"])

                # Check if existing session is stale (exceeded max session hours)
                if self._session_duration_hours(account) >= self.max_session_hours:
                    self._force_rest(account)
                    with self._lock:
                        self._in_use.discard(account.pk)
                    continue

                self._mark_session_start(account)
                return account
            logger.info("All accounts busy or resting -- waiting 30 s ...")
            time.sleep(30)
        raise RuntimeError("No ChatGPT account became available within the timeout window.")

    def release(self, account: user_details, apply_prompt_sleep: bool = True):
        now = timezone.now()
        account.last_used_at = now
        account.save(update_fields=["last_used_at"])

        if self._session_duration_hours(account) >= self.max_session_hours:
            self._force_rest(account)

        with self._lock:
            self._in_use.discard(account.pk)

        if apply_prompt_sleep:
            sleep_sec = random.randint(self.prompt_sleep_min, self.prompt_sleep_max)
            logger.info("Inter-prompt sleep for account %s: %d s", account.email, sleep_sec)
            time.sleep(sleep_sec)

    def _pick_account(self) -> user_details | None:
        with self._lock:
            # Deterministic ordering so account selection is predictable
            candidates = user_details.objects.order_by("pk")[: self.max_accounts]
            for account in candidates:
                if account.pk in self._in_use:
                    continue
                if account.is_resting():
                    logger.debug(
                        "Account %s resting until %s", account.email, account.rest_until
                    )
                    continue
                self._in_use.add(account.pk)
                return account
        return None

    def _mark_session_start(self, account: user_details):
        now = timezone.now()
        if not account.session_started_at:
            account.session_started_at = now
        account.last_used_at = now
        account.save(update_fields=["session_started_at", "last_used_at"])

    def _session_duration_hours(self, account: user_details) -> float:
        """How many hours has the current session been running?"""
        if not account.session_started_at:
            return 0.0
        delta = timezone.now() - account.session_started_at
        return delta.total_seconds() / 3600

    def _force_rest(self, account: user_details):
        rest_end = timezone.now() + timedelta(hours=self.rest_hours)
        account.rest_until = rest_end
        account.session_started_at = None
        account.save(update_fields=["rest_until", "session_started_at"])
        logger.warning(
            "Account %s has been active for %.1f h -- forced rest until %s",
            account.email,
            self.max_session_hours,
            rest_end.strftime("%H:%M UTC"),
        )
