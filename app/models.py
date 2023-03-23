from django.db import models
from django.forms import PasswordInput

# Create your models here.
class TimeStemp(models.Model):
    
    created = models.DateTimeField(auto_now_add=True, verbose_name='Created')
    updated = models.DateTimeField(auto_now=True, verbose_name='Last Updated')
    
    class Meta:
        abstract = True

class Text(TimeStemp):
    PROCESS = (
    ('RUNNING','RUNNING'),
    ('NOT_DONE','NOT_DONE'),
    ('DONE','DONE'),
    ) 
    text = models.TextField()
    pharaphreased = models.CharField(choices=PROCESS,default='NOT_DONE',max_length=10)
    
class ParaphrasedText(TimeStemp):
    sentence = models.ForeignKey(Text,on_delete=models.CASCADE)
    response = models.TextField()
    PageTitle = models.TextField()
    number = models.IntegerField()
    
class user_details(TimeStemp):
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)
    profile = models.CharField(max_length=255)
    ProfileDict = models.CharField(max_length=255,default=0)
    
    