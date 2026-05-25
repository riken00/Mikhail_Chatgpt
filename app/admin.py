from django.contrib import admin
from .models import Text, ParaphrasedText, user_details, ProcessingStatsHourly, ProcessingStatsDaily, ProcessingStatsOverall

admin.site.register(Text)
admin.site.register(ParaphrasedText)
admin.site.register(user_details)
admin.site.register(ProcessingStatsHourly)
admin.site.register(ProcessingStatsDaily)
admin.site.register(ProcessingStatsOverall)
