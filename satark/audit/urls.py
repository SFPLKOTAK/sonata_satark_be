from django.urls import path
from .views import (
    get_checklist_points, create_checklist_point, get_report_types, get_assigned_audits, get_audit_feedback, save_audit_feedback,
    get_center_checklist_points, save_center_checklist_point,
    get_client_checklist_points, save_client_checklist_point
)

urlpatterns = [
    # Branch Audit Checklist routes
    path('checklists/', get_checklist_points, name='get_checklist_points'),
    path('checklists/create/', create_checklist_point, name='create_checklist_point'),
    path('report-types/', get_report_types, name='get_report_types'),
    path('assigned-audits/', get_assigned_audits, name='get_assigned_audits'),
    path('feedback/', get_audit_feedback, name='get_audit_feedback'),
    path('feedback/save/', save_audit_feedback, name='save_audit_feedback'),

    # Center Audit Checklist routes
    path('center-checklists/', get_center_checklist_points, name='get_center_checklist_points'),
    path('center-checklists/save/', save_center_checklist_point, name='save_center_checklist_point'),

    # Client Audit Checklist routes
    path('client-checklists/', get_client_checklist_points, name='get_client_checklist_points'),
    path('client-checklists/save/', save_client_checklist_point, name='save_client_checklist_point'),
]


