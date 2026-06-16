from django.urls import path
from .views import (
    get_checklist_points, create_checklist_point, get_report_types, get_assigned_audits, start_branch_audit, get_audit_feedback, save_audit_feedback,
    get_center_checklist_points, save_center_checklist_point,
    get_client_checklist_points, save_client_checklist_point,
    view_feedback_file, archive_feedback_file,
    get_center_risk_details, get_branch_overview, get_customer_risk_details, get_center_disbursements,
    get_center_audit_feedback, save_center_audit_feedback,
    view_center_feedback_file, archive_center_feedback_file,
    get_client_audit_feedback, save_client_audit_feedback,
    get_completed_audits, get_branch_report_details,
    get_auditor_dashboard
)

urlpatterns = [
    path('auditor-dashboard/', get_auditor_dashboard, name='get_auditor_dashboard'),
    # Branch Audit Checklist routes
    path('checklists/', get_checklist_points, name='get_checklist_points'),
    path('checklists/create/', create_checklist_point, name='create_checklist_point'),
    path('report-types/', get_report_types, name='get_report_types'),
    path('assigned-audits/', get_assigned_audits, name='get_assigned_audits'),
    path('start-audit/', start_branch_audit, name='start_branch_audit'),
    path('feedback/', get_audit_feedback, name='get_audit_feedback'),
    path('feedback/save/', save_audit_feedback, name='save_audit_feedback'),
    path('feedback/file/view/', view_feedback_file, name='view_feedback_file'),
    path('feedback/file/archive/', archive_feedback_file, name='archive_feedback_file'),

    # Center Audit Checklist routes
    path('center-checklists/', get_center_checklist_points, name='get_center_checklist_points'),
    path('center-checklists/save/', save_center_checklist_point, name='save_center_checklist_point'),
    path('center-feedback/', get_center_audit_feedback, name='get_center_audit_feedback'),
    path('center-feedback/save/', save_center_audit_feedback, name='save_center_audit_feedback'),
    path('center-feedback/file/view/', view_center_feedback_file, name='view_center_feedback_file'),
    path('center-feedback/file/archive/', archive_center_feedback_file, name='archive_center_feedback_file'),

    # Client Audit Checklist routes
    path('client-checklists/', get_client_checklist_points, name='get_client_checklist_points'),
    path('client-checklists/save/', save_client_checklist_point, name='save_client_checklist_point'),

    # Client Audit Feedback routes
    path('client-feedback/', get_client_audit_feedback, name='get_client_audit_feedback'),
    path('client-feedback/save/', save_client_audit_feedback, name='save_client_audit_feedback'),

    # Center Risk Details route
    path('centers/risk-details/', get_center_risk_details, name='get_center_risk_details'),

    # Customer Risk Details route
    path('customers/risk-details/', get_customer_risk_details, name='get_customer_risk_details'),

    # Center Disbursements route
    path('centers/disbursements/', get_center_disbursements, name='get_center_disbursements'),

    # Branch Overview route
    path('branch/overview/', get_branch_overview, name='get_branch_overview'),

    # Combined Reports routes
    path('completed-audits/', get_completed_audits, name='get_completed_audits'),
    path('branch-report/details/', get_branch_report_details, name='get_branch_report_details'),
]



