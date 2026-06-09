from django.urls import path
from . import views

urlpatterns = [
    path('generate-plan/', views.generate_audit_plan, name='generate_audit_plan'),
    path('current-plan/', views.get_current_plan, name='get_current_plan'),
    path('overview-data/', views.get_planner_overview, name='get_planner_overview'),
    path('capacity-data/', views.get_capacity_data, name='get_capacity_data'),
]
