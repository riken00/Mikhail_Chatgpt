from django.core.management.base import BaseCommand
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException,InvalidElementStateException
import time, random, pandas as pd
from app.models import user_details
import threading, random
from django.core.management.base import BaseCommand
from app.bot import Bot
import pandas as pd, random
import concurrent.futures


class Command(BaseCommand):
    
    def add_arguments(self, parser):
        parser.add_argument(
            "--n",
            type=int,
            nargs="?",
            default=1,
        )
        
    def handle(self, *args, **options):
        self.start_bot()
    
    def start_bot(self):
        while True:
            try:
                bot = Bot()
                try: 
                    bot.work()
                    
                except Exception as e: print(e)
                finally:
                    bot.CloseDriver()
            except : ...
    def get_lowest_number(self,num1):
        """
        Returns the lowest of two numbers
        """
        return min(num1, user_details.objects.count())
    