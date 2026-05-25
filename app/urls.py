from django.urls import path
from django.conf.urls import include
from .views import WeeklyStatsView,VerifyEmail


urlpatterns = [
    path('check',VerifyEmail.as_view(),name='prt10'),
    path("api/stats/weekly/", WeeklyStatsView.as_view(), name="weekly-stats"),
]


    