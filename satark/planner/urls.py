from django.urls import path
from . import views

urlpatterns = [
    path('generate-plan/', views.generate_audit_plan, name='generate_audit_plan'),
]
