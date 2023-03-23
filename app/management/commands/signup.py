from django.core.management.base import BaseCommand
from app.bot import Bot
import pandas as pd, random

class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            '--n',
            dest='n',
            default=1,
            type=int,
            help='Number of signups to create',
        )

    def handle(self, *args, **options):
        n = options['n']
        print(n,'------111h kj h hjjhjbj h')
        
        
        for i in range(n):
            try:
                bot = Bot()
                # bot.singup(profile_name=random.randint(10000,99999))
                bot.singup()
            except Exception as e: print(e) 
            finally : 
                bot.CloseDriver()