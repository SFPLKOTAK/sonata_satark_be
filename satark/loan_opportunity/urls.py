from django.urls import path
from . import views

urlpatterns = [
    path('call-recordings/', views.fetch_call_center_recordings, name='fetch_call_recordings'),
    path('call-center-recordings/', views.fetch_call_center_recordings, name='fetch_call_center_recordings'),
]
