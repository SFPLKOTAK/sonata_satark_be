import json
import logging
import decimal
import io
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from satark.cqrs import dispatcher
from authentication.views import validate_token_user, is_user_admin
from .utils import DecimalEncoder
from .excel_utils import generate_branch_audit_excel
from .commands import (
    CreateChecklistPointCommand, CreateChecklistPointCommandHandler,
    SaveCenterChecklistPointCommand, SaveCenterChecklistPointCommandHandler,
    SaveClientChecklistPointCommand, SaveClientChecklistPointCommandHandler,
    StartBranchAuditCommand, StartBranchAuditCommandHandler,
    EndBranchAuditCommand, EndBranchAuditCommandHandler,
    SaveAuditFeedbackCommand, SaveAuditFeedbackCommandHandler,
    ArchiveFeedbackFileCommand, ArchiveFeedbackFileCommandHandler,
    SaveCenterAuditFeedbackCommand, SaveCenterAuditFeedbackCommandHandler,
    ArchiveCenterFeedbackFileCommand, ArchiveCenterFeedbackFileCommandHandler,
    SaveClientAuditFeedbackCommand, SaveClientAuditFeedbackCommandHandler,
    SaveSelectedCentersCommand, SaveSelectedCentersCommandHandler,
    SubmitForReviewCommand, SubmitForReviewCommandHandler,
    RecordPointDecisionCommand, RecordPointDecisionCommandHandler,
    FinalizeReviewCommand, FinalizeReviewCommandHandler
)
from .queries import (
    GetChecklistPointsQuery, GetChecklistPointsQueryHandler,
    GetReportTypesQuery, GetReportTypesQueryHandler,
    GetCenterChecklistPointsQuery, GetCenterChecklistPointsQueryHandler,
    GetClientChecklistPointsQuery, GetClientChecklistPointsQueryHandler,
    GetAssignedAuditsQuery, GetAssignedAuditsQueryHandler,
    GetAuditFeedbackQuery, GetAuditFeedbackQueryHandler,
    ViewFeedbackFileQuery, ViewFeedbackFileQueryHandler,
    GetCenterRiskDetailsQuery, GetCenterRiskDetailsQueryHandler,
    GetBranchOverviewQuery, GetBranchOverviewQueryHandler,
    GetCustomerRiskDetailsQuery, GetCustomerRiskDetailsQueryHandler,
    GetCenterDisbursementsQuery, GetCenterDisbursementsQueryHandler,
    GetCenterAuditFeedbackQuery, GetCenterAuditFeedbackQueryHandler,
    ViewCenterFeedbackFileQuery, ViewCenterFeedbackFileQueryHandler,
    GetClientAuditFeedbackQuery, GetClientAuditFeedbackQueryHandler,
    GetAuditorCapsQuery, GetAuditorCapsQueryHandler,
    GetCompletedAuditsQuery, GetCompletedAuditsQueryHandler,
    GetBranchReportDetailsQuery, GetBranchReportDetailsQueryHandler,
    GetAuditorDashboardQuery, GetAuditorDashboardQueryHandler,
    GetSelectedCentersQuery, GetSelectedCentersQueryHandler,
    GetAuditorPlansQuery, GetAuditorPlansQueryHandler,
    GetReviewQueueQuery, GetReviewQueueQueryHandler,
    GetReviewPointsQuery, GetReviewPointsQueryHandler,
    GetAuditReviewStatusQuery, GetAuditReviewStatusQueryHandler,
    GetBranchReportExcelQuery, GetBranchReportExcelQueryHandler,
    GetAuditeeDashboardQuery, GetAuditeeDashboardQueryHandler,
    GetAuditeeAuditsQuery, GetAuditeeAuditsQueryHandler,
    GetAuditeeCapsQuery, GetAuditeeCapsQueryHandler
)

logger = logging.getLogger("audit.views")

# Register commands with dispatcher
dispatcher.register_command(CreateChecklistPointCommand, CreateChecklistPointCommandHandler())
dispatcher.register_command(SaveCenterChecklistPointCommand, SaveCenterChecklistPointCommandHandler())
dispatcher.register_command(SaveClientChecklistPointCommand, SaveClientChecklistPointCommandHandler())
dispatcher.register_command(StartBranchAuditCommand, StartBranchAuditCommandHandler())
dispatcher.register_command(EndBranchAuditCommand, EndBranchAuditCommandHandler())
dispatcher.register_command(SaveAuditFeedbackCommand, SaveAuditFeedbackCommandHandler())
dispatcher.register_command(ArchiveFeedbackFileCommand, ArchiveFeedbackFileCommandHandler())
dispatcher.register_command(SaveCenterAuditFeedbackCommand, SaveCenterAuditFeedbackCommandHandler())
dispatcher.register_command(ArchiveCenterFeedbackFileCommand, ArchiveCenterFeedbackFileCommandHandler())
dispatcher.register_command(SaveClientAuditFeedbackCommand, SaveClientAuditFeedbackCommandHandler())
dispatcher.register_command(SaveSelectedCentersCommand, SaveSelectedCentersCommandHandler())
dispatcher.register_command(SubmitForReviewCommand, SubmitForReviewCommandHandler())
dispatcher.register_command(RecordPointDecisionCommand, RecordPointDecisionCommandHandler())
dispatcher.register_command(FinalizeReviewCommand, FinalizeReviewCommandHandler())

# Register queries with dispatcher
dispatcher.register_query(GetChecklistPointsQuery, GetChecklistPointsQueryHandler())
dispatcher.register_query(GetReportTypesQuery, GetReportTypesQueryHandler())
dispatcher.register_query(GetCenterChecklistPointsQuery, GetCenterChecklistPointsQueryHandler())
dispatcher.register_query(GetClientChecklistPointsQuery, GetClientChecklistPointsQueryHandler())
dispatcher.register_query(GetAssignedAuditsQuery, GetAssignedAuditsQueryHandler())
dispatcher.register_query(GetAuditFeedbackQuery, GetAuditFeedbackQueryHandler())
dispatcher.register_query(ViewFeedbackFileQuery, ViewFeedbackFileQueryHandler())
dispatcher.register_query(GetCenterRiskDetailsQuery, GetCenterRiskDetailsQueryHandler())
dispatcher.register_query(GetBranchOverviewQuery, GetBranchOverviewQueryHandler())
dispatcher.register_query(GetCustomerRiskDetailsQuery, GetCustomerRiskDetailsQueryHandler())
dispatcher.register_query(GetCenterDisbursementsQuery, GetCenterDisbursementsQueryHandler())
dispatcher.register_query(GetCenterAuditFeedbackQuery, GetCenterAuditFeedbackQueryHandler())
dispatcher.register_query(ViewCenterFeedbackFileQuery, ViewCenterFeedbackFileQueryHandler())
dispatcher.register_query(GetClientAuditFeedbackQuery, GetClientAuditFeedbackQueryHandler())
dispatcher.register_query(GetAuditorCapsQuery, GetAuditorCapsQueryHandler())
dispatcher.register_query(GetCompletedAuditsQuery, GetCompletedAuditsQueryHandler())
dispatcher.register_query(GetBranchReportDetailsQuery, GetBranchReportDetailsQueryHandler())
dispatcher.register_query(GetAuditorDashboardQuery, GetAuditorDashboardQueryHandler())
dispatcher.register_query(GetSelectedCentersQuery, GetSelectedCentersQueryHandler())
dispatcher.register_query(GetAuditorPlansQuery, GetAuditorPlansQueryHandler())
dispatcher.register_query(GetReviewQueueQuery, GetReviewQueueQueryHandler())
dispatcher.register_query(GetReviewPointsQuery, GetReviewPointsQueryHandler())
dispatcher.register_query(GetAuditReviewStatusQuery, GetAuditReviewStatusQueryHandler())
dispatcher.register_query(GetBranchReportExcelQuery, GetBranchReportExcelQueryHandler())
dispatcher.register_query(GetAuditeeDashboardQuery, GetAuditeeDashboardQueryHandler())
dispatcher.register_query(GetAuditeeAuditsQuery, GetAuditeeAuditsQueryHandler())
dispatcher.register_query(GetAuditeeCapsQuery, GetAuditeeCapsQueryHandler())


# --- Reusable View Helper ---
def parse_post_payload(request, action_name):
    if request.method != 'POST':
        return None, JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)
    try:
        data = json.loads(request.body) if request.body else {}
        return data, None
    except Exception as e:
        logger.error(f"{action_name}: parsing failed: {str(e)}")
        return None, JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)


def validate_user_view(token):
    user = validate_token_user(token)
    if not user:
        return None, JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)
    return user, None


# --- Checklist Points Endpoints ---

@csrf_exempt
def get_checklist_points(request):
    data, error_resp = parse_post_payload(request, "get_checklist_points")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    try:
        query = GetChecklistPointsQuery(report_type=data.get('report_type'), section_code=data.get('section_code'))
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def create_checklist_point(request):
    data, error_resp = parse_post_payload(request, "create_checklist_point")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    if not is_user_admin(user):
        return JsonResponse({'success': False, 'message': 'Access denied: Admin role required'}, status=403)

    required_fields = [
        'report_type', 'section_code', 'section_name', 
        'section_weight_pct', 'section_display_order', 
        'intent_title', 'category', 'max_score', 'accepted_deviation_pct'
    ]
    missing = [field for field in required_fields if field not in data]
    if missing:
        return JsonResponse({'success': False, 'message': f"Missing required fields: {', '.join(missing)}"}, status=400)

    try:
        command = CreateChecklistPointCommand(
            report_type=data['report_type'],
            section_code=data['section_code'],
            section_name=data['section_name'],
            section_weight_pct=data['section_weight_pct'],
            section_display_order=data['section_display_order'],
            intent_title=data['intent_title'],
            intent_description=data.get('intent_description'),
            category=data['category'],
            max_score=data['max_score'],
            accepted_deviation_pct=data['accepted_deviation_pct'],
            sample_method=data.get('sample_method'),
            is_active=data.get('is_active', True)
        )
        result = dispatcher.send(command)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Stored procedure error: {str(e)}'}, status=500)


@csrf_exempt
def get_report_types(request):
    data, error_resp = parse_post_payload(request, "get_report_types")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    try:
        result = dispatcher.query(GetReportTypesQuery())
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_center_checklist_points(request):
    data, error_resp = parse_post_payload(request, "get_center_checklist_points")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    try:
        result = dispatcher.query(GetCenterChecklistPointsQuery())
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def save_center_checklist_point(request):
    data, error_resp = parse_post_payload(request, "save_center_checklist_point")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    if not is_user_admin(user):
        return JsonResponse({'success': False, 'message': 'Access denied: Admin role required'}, status=403)

    if 'parameter_name' not in data or 'max_score' not in data:
        return JsonResponse({'success': False, 'message': "Missing required fields"}, status=400)

    try:
        command = SaveCenterChecklistPointCommand(
            parameter_name=data['parameter_name'],
            max_score=data['max_score'],
            center_checklist_id=data.get('center_checklist_id'),
            is_active=data.get('is_active', True)
        )
        result = dispatcher.send(command)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Stored procedure error: {str(e)}'}, status=500)


@csrf_exempt
def get_client_checklist_points(request):
    data, error_resp = parse_post_payload(request, "get_client_checklist_points")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    try:
        result = dispatcher.query(GetClientChecklistPointsQuery())
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def save_client_checklist_point(request):
    data, error_resp = parse_post_payload(request, "save_client_checklist_point")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    if not is_user_admin(user):
        return JsonResponse({'success': False, 'message': 'Access denied: Admin role required'}, status=403)

    if 'parameter_name' not in data or 'max_score' not in data:
        return JsonResponse({'success': False, 'message': "Missing required fields"}, status=400)

    try:
        command = SaveClientChecklistPointCommand(
            parameter_name=data['parameter_name'],
            max_score=data['max_score'],
            client_checklist_id=data.get('client_checklist_id'),
            is_active=data.get('is_active', True)
        )
        result = dispatcher.send(command)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Stored procedure error: {str(e)}'}, status=500)


# --- Audit Lifecycle Endpoints ---

@csrf_exempt
def get_assigned_audits(request):
    data, error_resp = parse_post_payload(request, "get_assigned_audits")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    try:
        result = dispatcher.query(GetAssignedAuditsQuery(user=user))
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def start_branch_audit(request):
    data, error_resp = parse_post_payload(request, "start_branch_audit")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    branch_id = data.get('branch_id')
    if not branch_id:
        return JsonResponse({'success': False, 'message': 'branch_id is required'}, status=400)

    try:
        command = StartBranchAuditCommand(branch_id=branch_id, user=user)
        result = dispatcher.send(command)
        status = result.pop('status_code', 200)
        return JsonResponse(result, status=status)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def end_branch_audit(request):
    data, error_resp = parse_post_payload(request, "end_branch_audit")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    audit_id = data.get('audit_id')
    if not audit_id:
        return JsonResponse({'success': False, 'message': 'audit_id is required'}, status=400)

    try:
        command = EndBranchAuditCommand(audit_id=audit_id, user=user)
        result = dispatcher.send(command)
        status = result.pop('status_code', 200)
        return JsonResponse(result, status=status)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


# --- Audit Feedback & Files Endpoints ---

@csrf_exempt
def get_audit_feedback(request):
    data, error_resp = parse_post_payload(request, "get_audit_feedback")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    branch_id = data.get('branch_id')
    if not branch_id:
        return JsonResponse({'success': False, 'message': 'branch_id is required'}, status=400)

    try:
        query = GetAuditFeedbackQuery(branch_id=branch_id, user=user, audit_id=data.get('audit_id'))
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def save_audit_feedback(request):
    data, error_resp = parse_post_payload(request, "save_audit_feedback")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    branch_id = data.get('branch_id')
    if not branch_id:
        return JsonResponse({'success': False, 'message': 'branch_id is required'}, status=400)

    try:
        command = SaveAuditFeedbackCommand(
            branch_id=branch_id,
            audit_id=data.get('audit_id'),
            action=data.get('action', 'DRAFT_SAVED'),
            general_remarks=data.get('general_remarks', ''),
            feedback_items=data.get('feedback_items', []),
            user=user
        )
        result = dispatcher.send(command)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def view_feedback_file(request):
    data, error_resp = parse_post_payload(request, "view_feedback_file")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    file_id = data.get('file_id')
    if not file_id:
        return JsonResponse({'success': False, 'message': 'file_id is required'}, status=400)

    try:
        query = ViewFeedbackFileQuery(file_id=file_id, is_confidential=bool(data.get('is_confidential', False)))
        result = dispatcher.query(query)
        status = result.pop('status_code', 200)
        return JsonResponse(result, status=status)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def archive_feedback_file(request):
    data, error_resp = parse_post_payload(request, "archive_feedback_file")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    file_id = data.get('file_id')
    if not file_id:
        return JsonResponse({'success': False, 'message': 'file_id is required'}, status=400)

    try:
        command = ArchiveFeedbackFileCommand(file_id=file_id, is_confidential=bool(data.get('is_confidential', False)))
        result = dispatcher.send(command)
        status = result.pop('status_code', 200)
        return JsonResponse(result, status=status)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


# --- Risk Details & Overview ---

@csrf_exempt
def get_center_risk_details(request):
    data, error_resp = parse_post_payload(request, "get_center_risk_details")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    branch_name = data.get('branch_name')
    as_on_date = data.get('as_on_date')
    if not branch_name:
        return JsonResponse({'success': False, 'message': 'branch_name parameter is required'}, status=400)

    try:
        query = GetCenterRiskDetailsQuery(branch_name=branch_name, as_on_date=as_on_date)
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_branch_overview(request):
    data, error_resp = parse_post_payload(request, "get_branch_overview")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    branch_name = data.get('branch_name')
    as_on_date = data.get('as_on_date')
    if not branch_name:
        return JsonResponse({'success': False, 'message': 'branch_name parameter is required'}, status=400)

    try:
        query = GetBranchOverviewQuery(branch_name=branch_name, as_on_date=as_on_date)
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_customer_risk_details(request):
    data, error_resp = parse_post_payload(request, "get_customer_risk_details")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    center_id = data.get('center_id')
    if not center_id:
        return JsonResponse({'success': False, 'message': 'center_id is required'}, status=400)

    try:
        query = GetCustomerRiskDetailsQuery(center_id=center_id, as_on_date=data.get('as_on_date'))
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_center_disbursements(request):
    data, error_resp = parse_post_payload(request, "get_center_disbursements")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    center_id = data.get('center_id')
    if not center_id:
        return JsonResponse({'success': False, 'message': 'center_id is required'}, status=400)

    try:
        query = GetCenterDisbursementsQuery(center_id=center_id, as_on_date=data.get('as_on_date'))
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


# --- Center Feedback & Files ---

@csrf_exempt
def get_center_audit_feedback(request):
    data, error_resp = parse_post_payload(request, "get_center_audit_feedback")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    center_id = data.get('center_id')
    if not center_id:
        return JsonResponse({'success': False, 'message': 'center_id is required'}, status=400)

    try:
        query = GetCenterAuditFeedbackQuery(center_id=center_id, audit_id=data.get('audit_id'), user=user)
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def save_center_audit_feedback(request):
    data, error_resp = parse_post_payload(request, "save_center_audit_feedback")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    audit_id = data.get('audit_id')
    center_id = data.get('center_id')
    branch_id = data.get('branch_id')
    if not audit_id or not center_id or not branch_id:
        return JsonResponse({'success': False, 'message': 'Missing required fields'}, status=400)

    try:
        command = SaveCenterAuditFeedbackCommand(
            audit_id=audit_id,
            center_id=center_id,
            branch_id=branch_id,
            feedback_items=data.get('feedback_items', [])
        )
        result = dispatcher.send(command)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def view_center_feedback_file(request):
    data, error_resp = parse_post_payload(request, "view_center_feedback_file")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    file_id = data.get('file_id')
    if not file_id:
        return JsonResponse({'success': False, 'message': 'file_id is required'}, status=400)

    try:
        query = ViewCenterFeedbackFileQuery(file_id=file_id)
        result = dispatcher.query(query)
        status = result.pop('status_code', 200)
        return JsonResponse(result, status=status)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def archive_center_feedback_file(request):
    data, error_resp = parse_post_payload(request, "archive_center_feedback_file")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    file_id = data.get('file_id')
    if not file_id:
        return JsonResponse({'success': False, 'message': 'file_id is required'}, status=400)

    try:
        command = ArchiveCenterFeedbackFileCommand(file_id=file_id)
        result = dispatcher.send(command)
        status = result.pop('status_code', 200)
        return JsonResponse(result, status=status)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


# --- Client Feedback Endpoints ---

@csrf_exempt
def get_client_audit_feedback(request):
    data, error_resp = parse_post_payload(request, "get_client_audit_feedback")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    audit_id = data.get('audit_id')
    center_id = data.get('center_id')
    client_id = data.get('client_id')
    if not audit_id or not center_id or not client_id:
        return JsonResponse({'success': False, 'message': 'Missing required fields'}, status=400)

    try:
        query = GetClientAuditFeedbackQuery(audit_id=audit_id, center_id=center_id, client_id=client_id)
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def save_client_audit_feedback(request):
    data, error_resp = parse_post_payload(request, "save_client_audit_feedback")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    audit_id = data.get('audit_id')
    center_id = data.get('center_id')
    branch_id = data.get('branch_id')
    client_id = data.get('client_id')
    client_name = data.get('client_name')
    if not audit_id or not center_id or not branch_id or not client_id or not client_name:
        return JsonResponse({'success': False, 'message': 'Missing required fields'}, status=400)

    try:
        command = SaveClientAuditFeedbackCommand(
            audit_id=audit_id,
            center_id=center_id,
            branch_id=branch_id,
            client_id=client_id,
            client_name=client_name,
            feedback_items=data.get('feedback_items', [])
        )
        result = dispatcher.send(command)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


# --- Completed Audits & Reports ---

@csrf_exempt
def get_completed_audits(request):
    data, error_resp = parse_post_payload(request, "get_completed_audits")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    try:
        result = dispatcher.query(GetCompletedAuditsQuery(user=user))
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_branch_report_details(request):
    data, error_resp = parse_post_payload(request, "get_branch_report_details")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    audit_id = data.get('audit_id')
    if not audit_id:
        return JsonResponse({'success': False, 'message': 'audit_id is required'}, status=400)

    try:
        query = GetBranchReportDetailsQuery(audit_id=audit_id)
        result = dispatcher.query(query)
        status = result.pop('status_code', 200)
        return JsonResponse(result, status=status)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


# --- Caps & Plans ---

@csrf_exempt
def get_auditor_caps(request):
    data, error_resp = parse_post_payload(request, "get_auditor_caps")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    try:
        query = GetAuditorCapsQuery(
            user=user,
            month_start_date=data.get('month_start_date'),
            report_type=data.get('report_type', 'CAP')
        )
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def save_selected_centers(request):
    data, error_resp = parse_post_payload(request, "save_selected_centers")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    audit_id = data.get('audit_id')
    branch_id = data.get('branch_id')
    if not audit_id or not branch_id:
        return JsonResponse({'success': False, 'message': 'audit_id and branch_id are required'}, status=400)

    try:
        command = SaveSelectedCentersCommand(audit_id=audit_id, branch_id=branch_id, centers=data.get('centers', []))
        result = dispatcher.send(command)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_selected_centers(request):
    data, error_resp = parse_post_payload(request, "get_selected_centers")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    audit_id = data.get('audit_id')
    if not audit_id:
        return JsonResponse({'success': False, 'message': 'audit_id is required'}, status=400)

    try:
        query = GetSelectedCentersQuery(audit_id=audit_id)
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_auditor_plans(request):
    data, error_resp = parse_post_payload(request, "get_auditor_plans")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    try:
        result = dispatcher.query(GetAuditorPlansQuery(user=user))
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


# --- Review Workflow Endpoints ---

@csrf_exempt
def submit_for_review(request):
    data, error_resp = parse_post_payload(request, "submit_for_review")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    audit_id = data.get('audit_id')
    if not audit_id:
        return JsonResponse({'success': False, 'message': 'audit_id is required'}, status=400)

    try:
        command = SubmitForReviewCommand(audit_id=audit_id, user=user)
        result = dispatcher.send(command)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_review_queue(request):
    data, error_resp = parse_post_payload(request, "get_review_queue")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    try:
        result = dispatcher.query(GetReviewQueueQuery(user=user))
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_review_points(request):
    data, error_resp = parse_post_payload(request, "get_review_points")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    audit_id = data.get('audit_id')
    if not audit_id:
        return JsonResponse({'success': False, 'message': 'audit_id is required'}, status=400)

    try:
        query = GetReviewPointsQuery(audit_id=audit_id)
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def record_point_decision(request):
    data, error_resp = parse_post_payload(request, "record_point_decision")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    required = ['audit_id', 'feedback_id', 'point_type', 'decision', 'remark']
    missing = [r for r in required if r not in data]
    if missing:
        return JsonResponse({'success': False, 'message': f"Missing fields: {', '.join(missing)}"}, status=400)

    try:
        command = RecordPointDecisionCommand(
            audit_id=data['audit_id'],
            feedback_id=data['feedback_id'],
            point_type=data['point_type'],
            decision=data['decision'],
            remark=data['remark'],
            user=user
        )
        result = dispatcher.send(command)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def finalize_review(request):
    data, error_resp = parse_post_payload(request, "finalize_review")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    audit_id = data.get('audit_id')
    action = data.get('action')
    if not audit_id or not action:
        return JsonResponse({'success': False, 'message': 'Missing audit_id or action'}, status=400)

    try:
        command = FinalizeReviewCommand(audit_id=audit_id, action=action, user=user)
        result = dispatcher.send(command)
        status = result.pop('status_code', 200)
        return JsonResponse(result, status=status)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_audit_review_status(request):
    data, error_resp = parse_post_payload(request, "get_audit_review_status")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    audit_id = data.get('audit_id')
    branch_id = data.get('branch_id')
    if not audit_id or not branch_id:
        return JsonResponse({'success': False, 'message': 'audit_id and branch_id are required'}, status=400)

    try:
        query = GetAuditReviewStatusQuery(audit_id=audit_id, branch_id=branch_id)
        result = dispatcher.query(query)
        status = result.pop('status_code', 200) if 'status_code' in result else 200
        return JsonResponse(result, status=status)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_auditor_dashboard(request):
    data, error_resp = parse_post_payload(request, "get_auditor_dashboard")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    try:
        query = GetAuditorDashboardQuery(user=user)
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


# --- Excel Export Endpoint ---

@csrf_exempt
def get_branch_report_excel(request):
    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        audit_id = data.get('audit_id')
        if not token or not audit_id:
            return JsonResponse({'success': False, 'message': 'Missing required fields'})

        user, error_resp = validate_user_view(token)
        if error_resp: return error_resp

        query = GetBranchReportExcelQuery(audit_id=audit_id)
        result = dispatcher.query(query)
        if not result.get('success'):
            status = result.get('status_code', 500)
            return JsonResponse(result, status=status)

        wb = generate_branch_audit_excel(
            result['metadata'],
            result['branch_points'],
            result['center_points'],
            result['client_points']
        )
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        
        response = HttpResponse(buffer.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="Branch_Report_{audit_id}.xlsx"'
        return response

    except Exception as e:
        logger.error(f"get_branch_report_excel: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


# --- Auditee (Branch Manager) Endpoints ---

@csrf_exempt
def get_auditee_dashboard(request):
    data, error_resp = parse_post_payload(request, "get_auditee_dashboard")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    try:
        query = GetAuditeeDashboardQuery(user=user)
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_auditee_audits(request):
    data, error_resp = parse_post_payload(request, "get_auditee_audits")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    try:
        query = GetAuditeeAuditsQuery(user=user)
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_auditee_caps(request):
    data, error_resp = parse_post_payload(request, "get_auditee_caps")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    try:
        query = GetAuditeeCapsQuery(user=user)
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)

from .commands import SendTicketAlertCommand, SendTicketAlertCommandHandler, ResolveTicketCommand, ResolveTicketCommandHandler
from .queries import GetComplianceTicketsQuery, GetComplianceTicketsQueryHandler


# --- Compliance Ticketing Endpoints ----------------------------------------

@csrf_exempt
@require_http_methods(["GET"])
def get_compliance_tickets(request):
    try:
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        user, error_resp = validate_user_view(token)
        if error_resp: return error_resp
        
        user_id = user.UserID
        handler = GetComplianceTicketsQueryHandler()
        result = handler.execute(GetComplianceTicketsQuery(user_id=user_id))
        return JsonResponse(result, status=result.get('status_code', 200))
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def send_ticket_alert(request, ticket_id):
    try:
        data, error_resp = parse_post_payload(request, "send_ticket_alert")
        if error_resp: return error_resp
        
        token = request.headers.get('Authorization', '').replace('Bearer ', '') or data.get('token', '')
        user, error_resp = validate_user_view(token)
        if error_resp: return error_resp
        
        message = data.get('message', '')
        handler = SendTicketAlertCommandHandler()
        result = handler.execute(SendTicketAlertCommand(ticket_id=ticket_id, sender_id=user.UserID, message=message))
        return JsonResponse(result, status=result.get('status_code', 201))
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def resolve_ticket(request, ticket_id):
    try:
        data, error_resp = parse_post_payload(request, "resolve_ticket")
        if error_resp: return error_resp
        
        token = request.headers.get('Authorization', '').replace('Bearer ', '') or data.get('token', '')
        user, error_resp = validate_user_view(token)
        if error_resp: return error_resp

        status = data.get('status', 'RESOLVED')
        handler = ResolveTicketCommandHandler()
        result = handler.execute(ResolveTicketCommand(ticket_id=ticket_id, resolver_id=user.UserID, status=status))
        return JsonResponse(result, status=result.get('status_code', 200))
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def initiate_ticket_call(request, ticket_id):
    try:
        from .commands import InitiateCallCommand, InitiateCallCommandHandler
        
        data, error_resp = parse_post_payload(request, "initiate_ticket_call")
        if error_resp: return error_resp
        
        token = request.headers.get('Authorization', '').replace('Bearer ', '') or data.get('token', '')
        user, error_resp = validate_user_view(token)
        if error_resp: return error_resp
        
        sender_number = data.get('sender_number', '')
        receiver_number = data.get('receiver_number', '')
        
        if not sender_number or not receiver_number:
            return JsonResponse({'success': False, 'message': 'Sender and receiver numbers are required'}, status=400)
            
        handler = InitiateCallCommandHandler()
        result = handler.execute(InitiateCallCommand(
            ticket_id=ticket_id, 
            sender_number=sender_number, 
            receiver_number=receiver_number,
            sender_id=user.UserID
        ))
        return JsonResponse(result, status=result.get('status_code', 201))
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def submit_ticket_response(request, ticket_id):
    try:
        from .commands import SubmitTicketResponseCommand, SubmitTicketResponseCommandHandler
        
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            token = request.POST.get('token', '')
        user, error_resp = validate_user_view(token)
        if error_resp: return error_resp
        
        message = request.POST.get('message', '')
        file_obj = request.FILES.get('file')
        
        file_name = None
        file_data = None
        if file_obj:
            file_name = file_obj.name
            file_data = file_obj.read()
            
        handler = SubmitTicketResponseCommandHandler()
        result = handler.execute(SubmitTicketResponseCommand(
            ticket_id=ticket_id,
            sender_id=user.UserID,
            message=message,
            file_name=file_name,
            file_data=file_data
        ))
        return JsonResponse(result, status=result.get('status_code', 201))
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def view_ticket_response_file(request, response_id):
    try:
        from .queries import ViewTicketResponseFileQuery, ViewTicketResponseFileQueryHandler
        token = request.GET.get('token', '')
        user, error_resp = validate_user_view(token)
        if error_resp: return error_resp
        
        handler = ViewTicketResponseFileQueryHandler()
        result = handler.execute(ViewTicketResponseFileQuery(response_id=response_id))
        
        if not result.get('success'):
            return JsonResponse(result, status=result.get('status_code', 404))
            
        file_name = result.get('file_name', 'response_file')
        file_bytes = result.get('file_bytes')
        
        from django.http import HttpResponse
        import mimetypes
        content_type, _ = mimetypes.guess_type(file_name)
        if not content_type:
            content_type = 'application/octet-stream'
            
        response = HttpResponse(file_bytes, content_type=content_type)
        response['Content-Disposition'] = f'inline; filename="{file_name}"'
        return response
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)