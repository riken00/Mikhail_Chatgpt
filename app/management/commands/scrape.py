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
        ThreadNumber = int(options.get('n'))
        print(ThreadNumber)
        ThreadNumber = self.get_lowest_number(ThreadNumber)
        print(ThreadNumber)
        if ThreadNumber > 51: 
            print('Please run threading system under number of 51')
            return
        random_profile_dic = random.sample(range(1, ThreadNumber+1), ThreadNumber)
        for i in random_profile_dic:
            x = threading.Thread(target= self.start_bot, args=(i,))
            x.start()
    
    def start_bot(self,i):
        while True:
            try:
                user_ = user_details.objects.filter(ProfileDict=i).order_by('?')[0]
                bot = Bot()
                try: 
                    bot.get_driver(user_.profile,user_.ProfileDict)
                    bot.work(user_.email,user_.password)
                    
                except Exception as e: print(e)
                finally:
                    bot.CloseDriver()
            except : ...
    def get_lowest_number(self,num1):
        """
        Returns the lowest of two numbers
        """
        return min(num1, user_details.objects.count())
    