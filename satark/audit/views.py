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
        import traceback
        logger.error(f"save_audit_feedback FULL ERROR:\n{traceback.format_exc()}")
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

    center_id = data.get('center_id')
    if center_id is None:
        return JsonResponse({'success': False, 'message': 'center_id is required'}, status=400)

    try:
        command = SaveCenterAuditFeedbackCommand(
            center_id=center_id,
            audit_id=data.get('audit_id'),
            branch_id=data.get('branch_id') or data.get('branchid'),
            action=data.get('action', 'DRAFT_SAVED'),
            general_remarks=data.get('general_remarks', ''),
            feedback_items=data.get('feedback_items', []),
            user=user
        )
        result = dispatcher.send(command)
        return JsonResponse(result)
    except Exception as e:
        import traceback
        logger.error(f"save_center_audit_feedback FULL ERROR:\n{traceback.format_exc()}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def view_center_feedback_file(request):
    data, error_resp = parse_post_payload(request, "view_center_feedback_file")
    if error_resp: return error_resp
    user, error_resp = validate_user_view(data.get('token', ''))
    if error_resp: return error_resp

    file_id = data.get('file_id')
    file_type = data.get('file_type')
    if not file_id:
        return JsonResponse({'success': False, 'message': 'file_id is required'}, status=400)
    if not file_type:
        return JsonResponse({'success': False, 'message': 'file_type is required'}, status=400)

    try:
        query = ViewCenterFeedbackFileQuery(file_id=file_id, file_type=file_type)
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
    file_type = data.get('file_type')
    if not file_id:
        return JsonResponse({'success': False, 'message': 'file_id is required'}, status=400)
    if not file_type:
        return JsonResponse({'success': False, 'message': 'file_type is required'}, status=400)

    try:
        command = ArchiveCenterFeedbackFileCommand(file_id=file_id, file_type=file_type)
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

    client_id = data.get('client_id')
    if not client_id:
        return JsonResponse({'success': False, 'message': 'client_id is required'}, status=400)

    try:
        command = SaveClientAuditFeedbackCommand(
            audit_id=data.get('audit_id'),
            branch_id=data.get('branch_id', ''),
            center_id=data.get('center_id'),
            client_id=client_id,
            client_name=data.get('client_name', ''),
            action=data.get('action', 'DRAFT_SAVED'),
            feedback_items=data.get('feedback_items', []),
            user=user
        )
        result = dispatcher.send(command)
        return JsonResponse(result)
    except Exception as e:
        import traceback
        logger.error(f"save_client_audit_feedback FULL ERROR:\n{traceback.format_exc()}")
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

    feedback_id = data.get('feedback_id')
    decision = data.get('decision')
    if not feedback_id or not decision:
        return JsonResponse({'success': False, 'message': 'feedback_id and decision are required'}, status=400)

    try:
        command = RecordPointDecisionCommand(
            feedback_id=feedback_id,
            decision=decision,
            entity_type=data.get('entity_type') or data.get('point_type') or 'branch',
            review_remark=data.get('review_remark') or data.get('remark') or '',
            audit_id=data.get('audit_id'),
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
    if not audit_id:
        return JsonResponse({'success': False, 'message': 'audit_id is required'}, status=400)

    try:
        command = FinalizeReviewCommand(
            audit_id=audit_id,
            branch_id=data.get('branch_id'),
            action=data.get('action'),
            user=user
        )
        result = dispatcher.send(command)
        return JsonResponse(result)
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
        
        response = HttpResponse(file_bytes, content_type=content_type)
        response['Content-Disposition'] = f'inline; filename="{file_name}"'
        return response
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@csrf_exempt
def get_branch_ml_risk_predictions(request):
    """
    API Endpoint: Fetches ML Risk Predictions & Key Risk Points for a given branch_id or branch_name
    Source Table: dbo.ML_TBL_Monthly_Branch_Risk_Predictions
    """
    import re
    branch_id = None
    branch_name = None

    if request.method == 'GET':
        branch_id = request.GET.get('branch_id')
        branch_name = request.GET.get('branch_name')
    else:
        try:
            body = json.loads(request.body.decode('utf-8'))
            branch_id = body.get('branch_id')
            branch_name = body.get('branch_name')
        except Exception:
            branch_id = request.POST.get('branch_id')
            branch_name = request.POST.get('branch_name')

    # Extract numeric branch ID or string branch name
    clean_id = None
    clean_name = str(branch_name).strip() if branch_name else None

    if branch_id is not None:
        str_id = str(branch_id).strip()
        match_digits = re.findall(r'\d+', str_id)
        if match_digits:
            clean_id = int(match_digits[-1])
        if not clean_name and '(' in str_id:
            clean_name = str_id.split('(')[0].strip()

    if clean_name and clean_name.lower() in ['none', 'null', 'undefined']:
        clean_name = None

    if clean_id is None and not clean_name:
        return JsonResponse({'success': False, 'message': 'branch_id or branch_name parameter is required'}, status=400)

    try:
        from django.db import connection
        cursor = connection.cursor()

        # Primary Query: Active Monthly Predictions Table
        query_active = """
        SELECT TOP 1
            Branch_ID, BranchName, Zone, Division, Region, AsOnDate,
            Predicted_Score, Predicted_Grade_From_Score, Predicted_Grade_Direct_Classifier,
            Final_Recommended_Grade, Risk_Level, Risk_Warnings, Key_points_impacting_risk,
            Model_Version, ScoredAt
        FROM dbo.ML_TBL_Monthly_Branch_Risk_Predictions
        WHERE (%s IS NOT NULL AND Branch_ID = %s)
           OR (%s IS NOT NULL AND UPPER(BranchName) = UPPER(%s))
           OR (%s IS NOT NULL AND UPPER(BranchName) LIKE UPPER(%s))
        ORDER BY ScoredAt DESC
        """
        like_name = f"%{clean_name}%" if clean_name else None
        cursor.execute(query_active, [clean_id, clean_id, clean_name, clean_name, clean_name, like_name])
        row = cursor.fetchone()

        # Fallback Query: Historical Archive Table
        if not row:
            query_history = """
            SELECT TOP 1
                Branch_ID, BranchName, Zone, Division, Region, AsOnDate,
                Predicted_Score, Predicted_Grade_From_Score, Predicted_Grade_Direct_Classifier,
                Final_Recommended_Grade, Risk_Level, Risk_Warnings, Key_points_impacting_risk,
                Model_Version, ScoredAt
            FROM dbo.ML_TBL_Branch_Risk_Prediction_History
            WHERE (%s IS NOT NULL AND Branch_ID = %s)
               OR (%s IS NOT NULL AND UPPER(BranchName) = UPPER(%s))
               OR (%s IS NOT NULL AND UPPER(BranchName) LIKE UPPER(%s))
            ORDER BY AsOnDate DESC, ScoredAt DESC
            """
            cursor.execute(query_history, [clean_id, clean_id, clean_name, clean_name, clean_name, like_name])
            row = cursor.fetchone()

        if not row:
            return JsonResponse({
                'success': False, 
                'message': f'No ML risk prediction data found for branch_id={clean_id}, branch_name="{clean_name}"'
            }, status=404)

        # Parse fields
        b_id, b_name, zone, division, region, as_on_date, \
        pred_score, grade_from_score, grade_direct_clf, \
        final_grade, risk_level, warnings_raw, key_points_raw, \
        model_version, scored_at = row

        # Parse warnings
        warnings = []
        if warnings_raw:
            try:
                warnings = json.loads(warnings_raw)
            except Exception:
                warnings = [w.strip() for w in str(warnings_raw).split(',') if w.strip()]

        # Parse key risk points list
        key_points_list = []
        if key_points_raw:
            key_points_list = [kp.strip() for kp in str(key_points_raw).split(',') if kp.strip()]

        payload = {
            'branch_id': b_id,
            'branch_name': b_name,
            'zone': zone,
            'division': division,
            'region': region,
            'as_on_date': str(as_on_date) if as_on_date else None,
            'predicted_score': float(pred_score) if pred_score is not None else None,
            'predicted_grade_from_score': grade_from_score,
            'predicted_grade_direct_classifier': grade_direct_clf,
            'final_recommended_grade': final_grade,
            'risk_level': risk_level,
            'risk_warnings': warnings,
            'key_points_impacting_risk': key_points_raw,
            'key_risk_points_list': key_points_list,
            'model_version': model_version,
            'scored_at': scored_at.strftime('%Y-%m-%d %H:%M:%S') if scored_at else None
        }

        return JsonResponse({
            'success': True,
            'data': payload
        })

    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_branch_past_audits_trend(request):
    """
    API Endpoint: Fetches Past 6 Audits History Trend from audit_branch_grade_history_final
    Table: dbo.audit_branch_grade_history_final
    Columns: Zone, Division, Region, Branch_Name, Branch_ID, Month, Grade, Score, isactual
    """
    import re
    from datetime import datetime

    branch_id = None
    branch_name = None

    if request.method == 'GET':
        branch_id = request.GET.get('branch_id')
        branch_name = request.GET.get('branch_name')
    else:
        try:
            body = json.loads(request.body.decode('utf-8'))
            branch_id = body.get('branch_id')
            branch_name = body.get('branch_name')
        except Exception:
            branch_id = request.POST.get('branch_id')
            branch_name = request.POST.get('branch_name')

    clean_id = None
    clean_name = str(branch_name).strip() if branch_name else None

    if branch_id is not None:
        str_id = str(branch_id).strip()
        match_digits = re.findall(r'\d+', str_id)
        if match_digits:
            clean_id = int(match_digits[-1])
        if not clean_name and '(' in str_id:
            clean_name = str_id.split('(')[0].strip()

    if clean_name and clean_name.lower() in ['none', 'null', 'undefined']:
        clean_name = None

    if clean_id is None and not clean_name:
        return JsonResponse({'success': False, 'message': 'branch_id or branch_name parameter is required'}, status=400)

    try:
        from django.db import connection
        cursor = connection.cursor()

        query_history = """
        SELECT TOP 6
            Branch_ID, Branch_Name, Month, Grade, Score, isactual, Zone, Division, Region
        FROM dbo.audit_branch_grade_history_final
        WHERE (%s IS NOT NULL AND Branch_ID = %s)
           OR (%s IS NOT NULL AND UPPER(Branch_Name) = UPPER(%s))
           OR (%s IS NOT NULL AND UPPER(Branch_Name) LIKE UPPER(%s))
        ORDER BY Month DESC
        """
        like_name = f"%{clean_name}%" if clean_name else None
        cursor.execute(query_history, [clean_id, clean_id, clean_name, clean_name, clean_name, like_name])
        rows = cursor.fetchall()

        if not rows:
            return JsonResponse({
                'success': False,
                'message': f'No historical audit records found in audit_branch_grade_history_final for branch_id={clean_id}, branch_name="{clean_name}"',
                'trend': [],
                'scores': []
            }, status=404)

        # Reverse to get chronological order (oldest to newest for left-to-right line chart)
        rows_chronological = list(reversed(rows))

        trend_list = []
        scores_list = []

        for row in rows_chronological:
            b_id, b_name, m_date, grade, score, is_act, z, d, r = row
            m_str = str(m_date) if m_date else ''
            
            # Format Month Label (e.g. '2025-12-01' -> 'Dec 25')
            month_label = m_str
            if m_date:
                try:
                    if isinstance(m_date, str):
                        dt = datetime.strptime(m_date[:10], '%Y-%m-%d')
                    else:
                        dt = m_date
                    month_label = dt.strftime('%b %y')
                except Exception:
                    month_label = m_str

            score_val = float(score) if score is not None else 0.0
            scores_list.append(score_val)

            trend_list.append({
                'branch_id': b_id,
                'branch_name': b_name,
                'month': m_str,
                'month_label': month_label,
                'grade': grade or 'N/A',
                'score': score_val,
                'is_actual': bool(is_act) if is_act is not None else True,
                'zone': z,
                'division': d,
                'region': r
            })

        return JsonResponse({
            'success': True,
            'branch_id': rows_chronological[0][0],
            'branch_name': rows_chronological[0][1],
            'trend': trend_list,
            'scores': scores_list
        })

    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)