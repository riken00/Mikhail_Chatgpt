from django.urls import path
from django.conf.urls import include
from .views import *


urlpatterns = [
    path('check',VerifyEmail.as_view(),name='prt10'),
    
]


    