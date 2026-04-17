from django.contrib import admin
from .models import Text, ParaphrasedText, user_details

admin.site.register(Text)
admin.site.register(ParaphrasedText)
admin.site.register(user_details)

# Register your models here.
