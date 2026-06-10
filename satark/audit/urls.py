from django.urls import path
from .views import get_checklist_points, create_checklist_point, get_report_types

urlpatterns = [
    path('checklists/', get_checklist_points, name='get_checklist_points'),
    path('checklists/create/', create_checklist_point, name='create_checklist_point'),
    path('report-types/', get_report_types, name='get_report_types'),
]
