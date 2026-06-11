import json
import decimal
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import connection
from authentication.views import validate_token_user, is_user_admin
from authentication.utils import log_info, log_error

# Custom JSON encoder to handle decimals in JSON serialization
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

# ============================================================
# BRANCH AUDIT CHECKLIST ENDPOINTS
# ============================================================

@csrf_exempt
def get_checklist_points(request):
    """
    POST API endpoint to retrieve checklist points for branch audit.
    Calls `usp_manage_audit_checklist_master` with `@expected_result = 'MANAGE'`.
    Expects plain JSON body:
    {
        "token": "...",
        "report_type": "Branch Audit", # Optional filter
        "section_code": "SEC_01"       # Optional filter
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        log_error(f"get_checklist_points: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    report_type_filter = data.get('report_type')
    section_code_filter = data.get('section_code')

    # Default filters to None so they match NULL check in SP
    if report_type_filter == 'All':
        report_type_filter = None
    if section_code_filter == 'All':
        section_code_filter = None

    try:
        with connection.cursor() as cursor:
            # Call unified stored procedure with 'MANAGE'
            sp_query = """
                EXEC [dbo].[usp_manage_audit_checklist_master]
                    @expected_result = 'MANAGE',
                    @report_type = %s,
                    @section_code = %s
            """
            cursor.execute(sp_query, [report_type_filter, section_code_filter])
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

        items = []
        for row in rows:
            row_dict = dict(zip(columns, row))
            # Convert decimals and datetimes to serializable formats
            for key, val in row_dict.items():
                if isinstance(val, decimal.Decimal):
                    row_dict[key] = float(val)
                elif hasattr(val, 'isoformat'):
                    row_dict[key] = val.isoformat()
            items.append(row_dict)

        return JsonResponse({
            'success': True,
            'checklist_points': items
        })
    except Exception as e:
        log_error(f"get_checklist_points: SP execution error: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def create_checklist_point(request):
    """
    POST API endpoint to create a new checklist point for branch audit.
    Calls `usp_manage_audit_checklist_master` with `@expected_result = 'ADD'`.
    Expects plain JSON body:
    {
        "token": "...",
        "report_type": "Branch Audit",
        "section_code": "SEC_01",
        "section_name": "Center Discipline & Operations",
        "section_weight_pct": 30.00,
        "section_display_order": 1,
        "intent_title": "Is the center register updated completely?",
        "intent_description": "Verify last 3 center meetings updates...",
        "category": "Critical",
        "max_score": 10,
        "accepted_deviation_pct": 0.00,
        "sample_method": "Random sampling of 5 registers",
        "is_active": true
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
        token = data.get('token', '')
    except Exception as e:
        log_error(f"create_checklist_point: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    if not is_user_admin(user):
        return JsonResponse({'success': False, 'message': 'Access denied: Admin role required'}, status=403)

    # Required fields
    required_fields = [
        'report_type', 'section_code', 'section_name', 
        'section_weight_pct', 'section_display_order', 
        'intent_title', 'category', 'max_score', 'accepted_deviation_pct'
    ]
    missing = [field for field in required_fields if field not in data]
    if missing:
        return JsonResponse({
            'success': False, 
            'message': f"Missing required fields: {', '.join(missing)}"
        }, status=400)

    try:
        with connection.cursor() as cursor:
            # Call unified stored procedure with 'ADD'
            sp_query = """
                EXEC [dbo].[usp_manage_audit_checklist_master]
                    @expected_result = 'ADD',
                    @report_type = %s,
                    @section_code = %s,
                    @section_name = %s,
                    @section_weight_pct = %s,
                    @section_display_order = %s,
                    @intent_title = %s,
                    @intent_description = %s,
                    @category = %s,
                    @max_score = %s,
                    @accepted_deviation_pct = %s,
                    @sample_method = %s,
                    @is_active = %s
            """
            cursor.execute(sp_query, [
                data['report_type'],
                data['section_code'],
                data['section_name'],
                float(data['section_weight_pct']),
                int(data['section_display_order']),
                data['intent_title'],
                data.get('intent_description'),
                data['category'],
                int(data['max_score']),
                float(data['accepted_deviation_pct']),
                data.get('sample_method'),
                1 if data.get('is_active', True) else 0
            ])
            
            # Fetch the returned row
            columns = [col[0] for col in cursor.description] if cursor.description else []
            row = cursor.fetchone()

        if not row:
            return JsonResponse({'success': False, 'message': 'Stored procedure did not return any records'}, status=500)

        created_item = dict(zip(columns, row))
        for key, val in created_item.items():
            if isinstance(val, decimal.Decimal):
                created_item[key] = float(val)
            elif hasattr(val, 'isoformat'):
                created_item[key] = val.isoformat()

        log_info(f"Successfully created checklist point: {created_item.get('intent_code')} by {user.UserCode}")
        return JsonResponse({
            'success': True,
            'message': 'Checklist item created successfully',
            'checklist_point': created_item
        })

    except Exception as e:
        log_error(f"create_checklist_point: stored procedure execution failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Stored procedure error: {str(e)}'}, status=500)


@csrf_exempt
def get_report_types(request):
    """
    POST API endpoint to retrieve all unique report types for branch audit.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        log_error(f"get_report_types: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    try:
        # Fetch distinct report types
        with connection.cursor() as cursor:
            cursor.execute("SELECT DISTINCT report_type FROM [dbo].[audit_branch_checklist_master] WHERE report_type IS NOT NULL")
            db_types = [row[0] for row in cursor.fetchall() if row[0]]

        default_types = ["Branch Audit", "Gold Loan Audit", "Concurrent Audit"]
        all_types = list(set(default_types + db_types))

        return JsonResponse({
            'success': True,
            'report_types': all_types
        })
    except Exception as e:
        log_error(f"get_report_types: DB error: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


# ============================================================
# CENTER AUDIT CHECKLIST ENDPOINTS
# ============================================================

@csrf_exempt
def get_center_checklist_points(request):
    """
    POST API endpoint to retrieve checklist points for center audit.
    Expects plain JSON body:
    {
        "token": "..."
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        log_error(f"get_center_checklist_points: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    center_checklist_id, serial_no, parameter_code, 
                    parameter_name, max_score, is_active, created_at, updated_at
                FROM [dbo].[audit_center_checklist_master]
                ORDER BY serial_no ASC
            """)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

        items = []
        for row in rows:
            row_dict = dict(zip(columns, row))
            # Convert decimals/datetimes
            for key, val in row_dict.items():
                if isinstance(val, decimal.Decimal):
                    row_dict[key] = float(val)
                elif hasattr(val, 'isoformat'):
                    row_dict[key] = val.isoformat()
            items.append(row_dict)

        return JsonResponse({
            'success': True,
            'center_checklist_points': items
        })
    except Exception as e:
        log_error(f"get_center_checklist_points: DB error: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def save_center_checklist_point(request):
    """
    POST API endpoint to insert or update a checklist point for center audit.
    Calls stored procedure `usp_save_center_checklist_item`.
    Expects plain JSON body:
    {
        "token": "...",
        "center_checklist_id": null, -- integer or null (null = INSERT, otherwise UPDATE)
        "parameter_name": "Are customers sitting in center meeting layout?",
        "max_score": 10,
        "is_active": true
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
        token = data.get('token', '')
    except Exception as e:
        log_error(f"save_center_checklist_point: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    if not is_user_admin(user):
        return JsonResponse({'success': False, 'message': 'Access denied: Admin role required'}, status=403)

    # Required fields
    required_fields = ['parameter_name', 'max_score']
    missing = [field for field in required_fields if field not in data]
    if missing:
        return JsonResponse({
            'success': False, 
            'message': f"Missing required fields: {', '.join(missing)}"
        }, status=400)

    try:
        center_checklist_id = data.get('center_checklist_id')
        parameter_name = data['parameter_name']
        max_score = int(data['max_score'])
        is_active = data.get('is_active', True)

        with connection.cursor() as cursor:
            # Call stored procedure and capture output variable in SQL Server
            sp_query = """
                DECLARE @out_id INT;
                EXEC [dbo].[usp_save_center_checklist_item]
                    @center_checklist_id = %s,
                    @parameter_name = %s,
                    @max_score = %s,
                    @is_active = %s,
                    @new_center_checklist_id = @out_id OUTPUT;
                SELECT @out_id;
            """
            cursor.execute(sp_query, [
                center_checklist_id,
                parameter_name,
                max_score,
                1 if is_active else 0
            ])
            new_id = cursor.fetchone()[0]

            # Query the updated/created row to return
            cursor.execute("""
                SELECT 
                    center_checklist_id, serial_no, parameter_code, 
                    parameter_name, max_score, is_active, created_at, updated_at
                FROM [dbo].[audit_center_checklist_master]
                WHERE center_checklist_id = %s
            """, [new_id])
            columns = [col[0] for col in cursor.description]
            row = cursor.fetchone()

        if not row:
            return JsonResponse({'success': False, 'message': 'Failed to fetch the saved record'}, status=500)

        saved_item = dict(zip(columns, row))
        for key, val in saved_item.items():
            if isinstance(val, decimal.Decimal):
                saved_item[key] = float(val)
            elif hasattr(val, 'isoformat'):
                saved_item[key] = val.isoformat()

        log_info(f"Successfully saved center checklist point ID {new_id} by {user.UserCode}")
        return JsonResponse({
            'success': True,
            'message': 'Center checklist item saved successfully',
            'center_checklist_point': saved_item
        })

    except Exception as e:
        log_error(f"save_center_checklist_point: SP execution failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Stored procedure error: {str(e)}'}, status=500)


# ============================================================
# CLIENT AUDIT CHECKLIST ENDPOINTS
# ============================================================

@csrf_exempt
def get_client_checklist_points(request):
    """
    POST API endpoint to retrieve checklist points for client audit.
    Expects plain JSON body:
    {
        "token": "..."
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        log_error(f"get_client_checklist_points: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    client_checklist_id, serial_no, parameter_code, 
                    parameter_name, max_score, is_active, created_at, updated_at
                FROM [dbo].[audit_client_checklist_master]
                ORDER BY serial_no ASC
            """)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

        items = []
        for row in rows:
            row_dict = dict(zip(columns, row))
            # Convert decimals/datetimes
            for key, val in row_dict.items():
                if isinstance(val, decimal.Decimal):
                    row_dict[key] = float(val)
                elif hasattr(val, 'isoformat'):
                    row_dict[key] = val.isoformat()
            items.append(row_dict)

        return JsonResponse({
            'success': True,
            'client_checklist_points': items
        })
    except Exception as e:
        log_error(f"get_client_checklist_points: DB error: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def save_client_checklist_point(request):
    """
    POST API endpoint to insert or update a checklist point for client audit.
    Calls stored procedure `usp_save_client_checklist_item`.
    Expects plain JSON body:
    {
        "token": "...",
        "client_checklist_id": null, -- integer or null (null = INSERT, otherwise UPDATE)
        "parameter_name": "...",
        "max_score": 10,
        "is_active": true
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
        token = data.get('token', '')
    except Exception as e:
        log_error(f"save_client_checklist_point: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    if not is_user_admin(user):
        return JsonResponse({'success': False, 'message': 'Access denied: Admin role required'}, status=403)

    # Required fields
    required_fields = ['parameter_name', 'max_score']
    missing = [field for field in required_fields if field not in data]
    if missing:
        return JsonResponse({
            'success': False, 
            'message': f"Missing required fields: {', '.join(missing)}"
        }, status=400)

    try:
        client_checklist_id = data.get('client_checklist_id')
        parameter_name = data['parameter_name']
        max_score = int(data['max_score'])
        is_active = data.get('is_active', True)

        with connection.cursor() as cursor:
            # Call stored procedure and capture output variable in SQL Server
            sp_query = """
                DECLARE @out_id INT;
                EXEC [dbo].[usp_save_client_checklist_item]
                    @client_checklist_id = %s,
                    @parameter_name = %s,
                    @max_score = %s,
                    @is_active = %s,
                    @new_client_checklist_id = @out_id OUTPUT;
                SELECT @out_id;
            """
            cursor.execute(sp_query, [
                client_checklist_id,
                parameter_name,
                max_score,
                1 if is_active else 0
            ])
            new_id = cursor.fetchone()[0]

            # Query the updated/created row to return
            cursor.execute("""
                SELECT 
                    client_checklist_id, serial_no, parameter_code, 
                    parameter_name, max_score, is_active, created_at, updated_at
                FROM [dbo].[audit_client_checklist_master]
                WHERE client_checklist_id = %s
            """, [new_id])
            columns = [col[0] for col in cursor.description]
            row = cursor.fetchone()

        if not row:
            return JsonResponse({'success': False, 'message': 'Failed to fetch the saved record'}, status=500)

        saved_item = dict(zip(columns, row))
        for key, val in saved_item.items():
            if isinstance(val, decimal.Decimal):
                saved_item[key] = float(val)
            elif hasattr(val, 'isoformat'):
                saved_item[key] = val.isoformat()

        log_info(f"Successfully saved client checklist point ID {new_id} by {user.UserCode}")
        return JsonResponse({
            'success': True,
            'message': 'Client checklist item saved successfully',
            'client_checklist_point': saved_item
        })

    except Exception as e:
        log_error(f"save_client_checklist_point: SP execution failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Stored procedure error: {str(e)}'}, status=500)


@csrf_exempt
def get_assigned_audits(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        log_error(f"get_assigned_audits: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    try:
        from planner.models import AuditPlanCurrent
        import datetime
        from django.db.models import Q

        # Retrieve current plans assigned to the user
        user_id_str = str(user.UserID) if user.UserID is not None else ""
        user_code = user.UserCode or ""
        
        queryset = AuditPlanCurrent.objects.filter(
            Q(assigned_auditor=user_id_str) | Q(assigned_auditor=user_code)
        ).order_by('start_date', '-priority_score')

        audits = []
        today = datetime.date.today()

        for item in queryset:
            start_date_str = item.start_date.strftime("%Y-%m-%d") if item.start_date else None
            end_date_str = item.end_date.strftime("%Y-%m-%d") if item.end_date else None
            
            # Compute audit status dynamically based on current date
            status = 'upcoming'
            if item.start_date and item.end_date:
                if today < item.start_date:
                    status = 'upcoming'
                elif item.start_date <= today <= item.end_date:
                    status = 'today'
                else:
                    status = 'completed'

            # Dynamic branch metrics simulation
            p_score = item.priority_score or 0
                    
            audits.append({
                "auditId": item.id,
                "branchName": item.branch,
                "division": item.division,
                "region": item.division,
                "grade": item.grade,
                "size": item.size,
                "auditMode": item.audit_mode,
                "duration": item.duration,
                "startDate": start_date_str,
                "endDate": end_date_str,
                "priorityScore": p_score,
                "planMonth": item.plan_month,
                "status": status,
            })

        # Calculate statistics
        total_assigned = len(audits)
        completed_count = sum(1 for a in audits if a['status'] == 'completed')
        completion_pct = int(completed_count / total_assigned * 100) if total_assigned > 0 else 0        
        stats = {
            "branchesThisMonth": total_assigned,
            "branchesTarget": total_assigned,
            "completionPct": completion_pct
        }
        return JsonResponse({
            'success': True,
            'audits': audits,
            'stats': stats
        })
    except Exception as e:
        log_error(f"get_assigned_audits: DB or processing error: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


import base64
import uuid
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

def save_base64_file(filename, base64_str):
    try:
        if not base64_str:
            return None
        if ';base64,' in base64_str:
            format, imgstr = base64_str.split(';base64,')
        else:
            imgstr = base64_str
        
        data = ContentFile(base64.b64decode(imgstr))
        ext = filename.split('.')[-1] if '.' in filename else 'bin'
        unique_name = f"audit_files/{uuid.uuid4()}.{ext}"
        path = default_storage.save(unique_name, data)
        return path
    except Exception as e:
        log_error(f"save_base64_file: failed: {str(e)}")
        return None

@csrf_exempt
def get_audit_feedback(request):
    """
    POST API endpoint to retrieve checklist feedback for a branch.
    Expects plain JSON body:
    {
        "token": "...",
        "branch_id": "BR-001",
        "audit_id": 123
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        branch_id = data.get('branch_id', '')
        audit_id = data.get('audit_id')
    except Exception as e:
        log_error(f"get_audit_feedback: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    if not branch_id:
        return JsonResponse({'success': False, 'message': 'branch_id is required'}, status=400)

    try:
        # Resolve audit_id if not explicitly provided
        if not audit_id:
            from django.db.models import Q
            from planner.models import AuditPlanCurrent
            user_id_str = str(user.UserID) if user.UserID is not None else ""
            user_code = user.UserCode or ""
            plan = AuditPlanCurrent.objects.filter(
                Q(branch=branch_id) & (Q(assigned_auditor=user_id_str) | Q(assigned_auditor=user_code))
            ).first()
            if plan:
                audit_id = plan.id

        query = """
            SELECT 
                f.audit_id, f.checklist_id, f.answer, f.normal_remark, f.normal_file_path, f.status,
                r.confidential_remark,
                fl.confidential_file_path, fl.file_name as confidential_file_name
            FROM dbo.audit_checklist_feedback f
            LEFT JOIN dbo.audit_confidential_remarks r ON f.branch_id = r.branch_id AND f.checklist_id = r.checklist_id
            LEFT JOIN dbo.audit_confidential_files fl ON f.branch_id = fl.branch_id AND f.checklist_id = fl.checklist_id
            WHERE f.branch_id = %s
        """
        params = [branch_id]
        if audit_id:
            query += " AND f.audit_id = %s"
            params.append(audit_id)

        with connection.cursor() as cursor:
            cursor.execute(query, params)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

        feedback_list = []
        feedback_audit_id = audit_id
        for row in rows:
            row_dict = dict(zip(columns, row))
            if row_dict.get("audit_id") and not feedback_audit_id:
                feedback_audit_id = row_dict.get("audit_id")
            feedback_list.append({
                "checklistId": row_dict.get("checklist_id"),
                "answer": row_dict.get("answer"),
                "normalRemark": row_dict.get("normal_remark"),
                "normalFilePath": row_dict.get("normal_file_path"),
                "status": row_dict.get("status"),
                "confidentialRemark": row_dict.get("confidential_remark"),
                "confidentialFilePath": row_dict.get("confidential_file_path"),
                "confidentialFileName": row_dict.get("confidential_file_name"),
            })

        return JsonResponse({
            'success': True,
            'feedback': feedback_list,
            'auditId': feedback_audit_id
        })
    except Exception as e:
        log_error(f"get_audit_feedback: DB error: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def save_audit_feedback(request):
    """
    POST API endpoint to save or submit checklist feedback for a branch.
    Expects plain JSON body:
    {
        "token": "...",
        "branch_id": "BR-001",
        "action": "DRAFT_SAVED", -- DRAFT_SAVED, SUBMITTED, REJECTED, IN_REVIEW
        "general_remarks": "Some comment",
        "feedback_items": [
            {
                "checklist_id": 1,
                "section_code": "A",
                "section_name": "Office Infrastructure",
                "intent_code": "A1",
                "intent_title": "Is the signboard present?",
                "answer": "Yes",
                "normal_remark": "Signboard is clean.",
                "normal_file": {"filename": "sign.png", "base64": "..."}, # optional
                "confidential_remark": "Secret note...",
                "confidential_file": {"filename": "conf_sign.png", "base64": "..."} # optional
            },
            ...
        ]
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        branch_id = data.get('branch_id', '')
        audit_id = data.get('audit_id')
        action = data.get('action', 'DRAFT_SAVED')
        general_remarks = data.get('general_remarks', '')
        feedback_items = data.get('feedback_items', [])
    except Exception as e:
        log_error(f"save_audit_feedback: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    if not branch_id:
        return JsonResponse({'success': False, 'message': 'branch_id is required'}, status=400)

    # Resolve audit_id if not explicitly provided
    if not audit_id:
        from django.db.models import Q
        from planner.models import AuditPlanCurrent
        user_id_str = str(user.UserID) if user.UserID is not None else ""
        user_code = user.UserCode or ""
        plan = AuditPlanCurrent.objects.filter(
            Q(branch=branch_id) & (Q(assigned_auditor=user_id_str) | Q(assigned_auditor=user_code))
        ).first()
        if plan:
            audit_id = plan.id
        else:
            audit_id = 0 # Default fallback to satisfy NOT NULL column

    # Determine status to set
    status_to = 'pending'
    if action == 'SUBMITTED':
        status_to = 'submitted'
    elif action == 'REJECTED':
        status_to = 'rejected'
    elif action == 'IN_REVIEW':
        status_to = 'inreview'
    elif action == 'DRAFT_SAVED':
        status_to = 'pending'

    from django.db import transaction
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                for item in feedback_items:
                    checklist_id = item.get('checklist_id')
                    section_code = item.get('section_code')
                    section_name = item.get('section_name')
                    intent_code = item.get('intent_code')
                    intent_title = item.get('intent_title')
                    answer = item.get('answer', 'N/A')
                    normal_remark = item.get('normal_remark')
                    confidential_remark = item.get('confidential_remark')
                    
                    # 1. Process normal file upload if provided
                    normal_file = item.get('normal_file')
                    normal_file_path = None
                    if normal_file and isinstance(normal_file, dict) and normal_file.get('base64'):
                        normal_file_path = save_base64_file(normal_file.get('filename', 'upload.png'), normal_file.get('base64'))

                    # 2. Check if record exists in main feedback table for this specific audit and checklist item
                    cursor.execute("""
                        SELECT id, normal_file_path FROM dbo.audit_checklist_feedback 
                        WHERE branch_id = %s AND checklist_id = %s AND audit_id = %s
                    """, [branch_id, checklist_id, audit_id])
                    fb_row = cursor.fetchone()

                    is_confidential_remark_present = 1 if confidential_remark else 0
                    
                    confidential_file = item.get('confidential_file')
                    is_confidential_file_present = 1 if confidential_file and isinstance(confidential_file, dict) and confidential_file.get('base64') else 0

                    if fb_row:
                        fb_id = fb_row[0]
                        # Keep existing file if new one is not uploaded
                        final_normal_file_path = normal_file_path if normal_file_path else fb_row[1]
                        
                        # Update main feedback table
                        cursor.execute("""
                            UPDATE dbo.audit_checklist_feedback
                            SET answer = %s,
                                normal_remark = %s,
                                normal_file_path = %s,
                                is_confidential_remark_present = %s,
                                is_confidential_file_present = %s,
                                status = %s,
                                last_modified_by = %s,
                                audit_id = %s,
                                updated_at = GETDATE()
                            WHERE id = %s
                        """, [answer, normal_remark, final_normal_file_path, is_confidential_remark_present, is_confidential_file_present, status_to, user.UserID, audit_id, fb_id])
                    else:
                        # Insert main feedback table
                        cursor.execute("""
                            INSERT INTO dbo.audit_checklist_feedback (
                                audit_id, branch_id, auditor_id, checklist_id, section_code, section_name,
                                intent_code, intent_title, answer, normal_remark, normal_file_path,
                                is_confidential_remark_present, is_confidential_file_present, status, last_modified_by,
                                created_at, updated_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, GETDATE(), GETDATE())
                        """, [
                            audit_id, branch_id, user.UserID, checklist_id, section_code, section_name,
                            intent_code, intent_title, answer, normal_remark, normal_file_path,
                            is_confidential_remark_present, is_confidential_file_present, status_to, user.UserID
                        ])
                        cursor.execute("SELECT @@IDENTITY")
                        fb_id = int(cursor.fetchone()[0])

                    # 3. Process confidential remark
                    if confidential_remark is not None:
                        cursor.execute("""
                            SELECT id FROM dbo.audit_confidential_remarks
                            WHERE branch_id = %s AND checklist_id = %s
                        """, [branch_id, checklist_id])
                        cr_row = cursor.fetchone()
                        if cr_row:
                            cursor.execute("""
                                UPDATE dbo.audit_confidential_remarks
                                SET confidential_remark = %s,
                                    user_id = %s,
                                    updated_at = GETDATE()
                                WHERE id = %s
                            """, [confidential_remark, user.UserID, cr_row[0]])
                        else:
                            cursor.execute("""
                                INSERT INTO dbo.audit_confidential_remarks (
                                    feedback_id, branch_id, checklist_id, confidential_remark, user_id, created_at, updated_at
                                ) VALUES (%s, %s, %s, %s, %s, GETDATE(), GETDATE())
                            """, [fb_id, branch_id, checklist_id, confidential_remark, user.UserID])

                    # 4. Process confidential file upload
                    if is_confidential_file_present:
                        conf_file_path = save_base64_file(confidential_file.get('filename', 'upload_conf.png'), confidential_file.get('base64'))
                        if conf_file_path:
                            cursor.execute("""
                                SELECT id FROM dbo.audit_confidential_files
                                WHERE branch_id = %s AND checklist_id = %s
                            """, [branch_id, checklist_id])
                            cf_row = cursor.fetchone()
                            if cf_row:
                                cursor.execute("""
                                    UPDATE dbo.audit_confidential_files
                                    SET confidential_file_path = %s,
                                        file_name = %s,
                                        user_id = %s
                                    WHERE id = %s
                                """, [conf_file_path, confidential_file.get('filename'), user.UserID, cf_row[0]])
                            else:
                                cursor.execute("""
                                    INSERT INTO dbo.audit_confidential_files (
                                        feedback_id, branch_id, checklist_id, confidential_file_path, file_name, user_id, created_at
                                    ) VALUES (%s, %s, %s, %s, %s, %s, GETDATE())
                                """, [fb_id, branch_id, checklist_id, conf_file_path, confidential_file.get('filename'), user.UserID])

                # 5. Insert activity log entry (corrected to match created_by column in dbo.audit_activity_log)
                cursor.execute("""
                    INSERT INTO dbo.audit_activity_log (
                        branch_id, action, status_to, created_by, created_at, remarks
                    ) VALUES (%s, %s, %s, %s, GETDATE(), %s)
                """, [branch_id, action, status_to, user.UserID, general_remarks])

        return JsonResponse({
            'success': True,
            'message': 'Audit checklist feedback saved successfully'
        })
    except Exception as e:
        log_error(f"save_audit_feedback: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_center_risk_details(request):
    """
    POST API endpoint to retrieve center-level risk details by branch name.
    Expects plain JSON body:
    {
        "token": "...",
        "branch_name": "Arwal_B",
        "as_on_date": "2026-06-10"  # Optional
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        branch_name = data.get('branch_name', '')
        as_on_date = data.get('as_on_date')
    except Exception as e:
        log_error(f"get_center_risk_details: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    if not branch_name:
        return JsonResponse({'success': False, 'message': 'branch_name parameter is required'}, status=400)

    try:
        branch_id = None
        with connection.cursor() as cursor:
            # 1. Look up in CenterRiskScore directly
            cursor.execute("""
                SELECT TOP 1 BRANCHID 
                FROM CenterRiskScore 
                WHERE BranchName = %s
            """, [branch_name])
            row = cursor.fetchone()
            if row:
                branch_id = row[0]
            else:
                # 2. Look up in VW_Branch_To_GeographicalHierarchy by exact name
                cursor.execute("""
                    SELECT TOP 1 BranchID 
                    FROM [dbo].[VW_Branch_To_GeographicalHierarchy] 
                    WHERE Branch = %s
                """, [branch_name])
                row = cursor.fetchone()
                if row:
                    branch_id = row[0]
                else:
                    # 3. Strip B/_B suffix and look up in hierarchy view
                    stripped = branch_name.replace('_B', '').replace(' B', '').strip()
                    cursor.execute("""
                        SELECT TOP 1 BranchID 
                        FROM [dbo].[VW_Branch_To_GeographicalHierarchy] 
                        WHERE Branch = %s
                    """, [stripped])
                    row = cursor.fetchone()
                    if row:
                        branch_id = row[0]

        if not branch_id:
            log_info(f"get_center_risk_details: Could not resolve branch_id for name: {branch_name}")
            return JsonResponse({
                'success': True,
                'center_risks': [],
                'message': f"Branch '{branch_name}' not resolved to an ID."
            })

        # Call the stored procedure
        with connection.cursor() as cursor:
            cursor.execute("""
                EXEC SP_GetCenterRiskDetails @BranchID = %s, @AsOnDate = %s
            """, [branch_id, as_on_date if as_on_date else None])
            columns = [col[0] for col in cursor.description] if cursor.description else []
            rows = cursor.fetchall()

        items = []
        for row in rows:
            row_dict = dict(zip(columns, row))
            for key, val in row_dict.items():
                if isinstance(val, decimal.Decimal):
                    row_dict[key] = float(val)
                elif hasattr(val, 'isoformat'):
                    row_dict[key] = val.isoformat()
            items.append(row_dict)

        return JsonResponse({
            'success': True,
            'center_risks': items
        })

    except Exception as e:
        log_error(f"get_center_risk_details: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_branch_overview(request):
    """
    POST API endpoint to retrieve branch overview details.
    Expects plain JSON body:
    {
        "token": "...",
        "branch_name": "Arwal_B",
        "as_on_date": "2026-06-10"  # Optional
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        branch_name = data.get('branch_name', '')
        as_on_date = data.get('as_on_date')
    except Exception as e:
        log_error(f"get_branch_overview: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    if not branch_name:
        return JsonResponse({'success': False, 'message': 'branch_name parameter is required'}, status=400)

    try:
        overview_data = {}
        with connection.cursor() as cursor:
            # Call stored procedure
            # If as_on_date is not provided, we omit it so SP uses default, or we can pass None
            if as_on_date:
                cursor.execute("""
                    EXEC SP_GetBranchOverview @BranchName = %s, @AsOnDate = %s
                """, [branch_name, as_on_date])
            else:
                cursor.execute("""
                    EXEC SP_GetBranchOverview @BranchName = %s
                """, [branch_name])
            
            # Loop through multiple result sets returned by SP
            has_more = True
            while has_more:
                columns = [col[0] for col in cursor.description] if cursor.description else []
                rows = cursor.fetchall()
                
                items = []
                for row in rows:
                    row_dict = dict(zip(columns, row))
                    for key, val in row_dict.items():
                        if isinstance(val, decimal.Decimal):
                            row_dict[key] = float(val)
                        elif hasattr(val, 'isoformat'):
                            row_dict[key] = val.isoformat()
                    items.append(row_dict)
                
                if items:
                    section = items[0].get('Section')
                    if section == 'OVERVIEW':
                        overview_data['overview'] = items[0]
                    elif section == 'HIERARCHY':
                        overview_data['hierarchy'] = items
                    elif section == 'PORTFOLIO_HEALTH':
                        overview_data['portfolio_health'] = items
                    elif section == 'DISBURSEMENTS':
                        overview_data['disbursements'] = items
                    elif section == 'STAFF':
                        overview_data['staff'] = items
                        
                has_more = cursor.nextset()

        return JsonResponse({
            'success': True,
            'branch_overview': overview_data
        })

    except Exception as e:
        log_error(f"get_branch_overview: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)
