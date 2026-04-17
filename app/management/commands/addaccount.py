"""
addaccount -- Management command to register a new ChatGPT account.

Creates the Chrome profile directory, saves the credentials to user_details,
and verifies the login by launching a real browser session. If login fails,
the account record is removed so no stale credentials remain in the database.

Usage:
    python manage.py addaccount --email user@example.com --password secret123
    python manage.py addaccount --email user@example.com --password secret123 --profile "Profile 5"
    python manage.py addaccount --email user@example.com --password secret123 --profile-dir /path/to/profiles
"""

import logging
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from app.bot import Bot
from app.models import user_details

logger = logging.getLogger("addaccount_command")


class Command(BaseCommand):
    help = (
        "Register a new ChatGPT account: create a Chrome profile, save credentials "
        "to the database, and verify the login works."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            required=True,
            help="Email address for the ChatGPT account.",
        )
        parser.add_argument(
            "--password",
            required=True,
            help="Password for the ChatGPT account.",
        )
        parser.add_argument(
            "--profile",
            default="",
            help=(
                "Chrome profile directory name (e.g. 'Profile 3'). "
                "If omitted, auto-generates based on the next available number."
            ),
        )
        parser.add_argument(
            "--profile-dir",
            default="Profiles",
            help="Root folder that holds all Chrome profiles (default: 'Profiles').",
        )
        parser.add_argument(
            "--skip-login",
            action="store_true",
            default=False,
            help="Skip the login verification step (just save the account).",
        )

    def handle(self, *args, **options):
        email = options["email"].strip()
        password = options["password"]
        profile_dir = options["profile_dir"]
        profile_name = options["profile"].strip() or self._auto_profile_name(profile_dir)
        skip_login = options["skip_login"]

        # Validate email format (basic check)
        if "@" not in email or "." not in email.split("@")[-1]:
            raise CommandError(f"Invalid email address: {email}")

        # Check if account already exists
        if user_details.objects.filter(email=email).exists():
            raise CommandError(
                f"Account with email '{email}' already exists in the database."
            )

        # Step 1: Create the Chrome profile directory
        profile_path = os.path.join(profile_dir, profile_name)
        if not os.path.exists(profile_path):
            os.makedirs(profile_path, exist_ok=True)
            self.stdout.write(f"Created profile directory: {profile_path}")
        else:
            self.stdout.write(f"Profile directory already exists: {profile_path}")

        # Step 2: Save to database
        try:
            account = user_details.objects.create(
                email=email,
                password=password,
                profile=profile_name,
                ProfileDict=profile_dir,
            )
        except IntegrityError as exc:
            raise CommandError(f"Failed to create account record: {exc}")

        self.stdout.write(
            self.style.SUCCESS(f"Account saved: {email} (profile: {profile_name})")
        )

        if skip_login:
            self.stdout.write(
                "Login verification skipped. Account saved but not verified."
            )
            return

        # Step 3: Verify login
        self.stdout.write(f"Verifying login for {email} ...")

        bot = Bot(account=account)
        login_ok = False
        try:
            login_ok = bot.login_chat(close_driver=True)
        except Exception as exc:
            logger.error("Login verification error for %s: %s", email, exc)
            self.stdout.write(self.style.ERROR(f"Login error: {exc}"))
        finally:
            bot.CloseDriver()

        if login_ok:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Login verified successfully for {email}. Account is ready to use."
                )
            )
        else:
            # Clean up the DB record since the account is not usable
            account.delete()
            self.stdout.write(
                self.style.ERROR(
                    f"Login failed for {email}. "
                    f"The account record has been removed from the database.\n"
                    f"Please check the credentials and try again."
                )
            )
            raise CommandError(f"Login verification failed for {email}.")

    def _auto_profile_name(self, profile_dir: str) -> str:
        """
        Generate the next available profile name based on existing
        directories in the profile root folder (e.g. 'Profile_4').
        """
        existing_count = user_details.objects.count()
        candidate = f"Profile_{existing_count + 1}"

        # Make sure the name does not collide with an existing directory
        full_path = os.path.join(profile_dir, candidate)
        suffix = existing_count + 1
        while os.path.exists(full_path):
            suffix += 1
            candidate = f"Profile_{suffix}"
            full_path = os.path.join(profile_dir, candidate)

        return candidate
