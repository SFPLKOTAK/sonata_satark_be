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
                f.audit_id, f.checklist_id, f.answer, f.normal_remark, f.status,
                r.confidential_remark,
                fl.id as confidential_file_id, fl.file_name as confidential_file_name,
                nf.id as normal_file_id, nf.file_name as normal_file_name
            FROM dbo.audit_checklist_feedback f
            LEFT JOIN dbo.audit_confidential_remarks r ON f.branch_id = r.branch_id AND f.checklist_id = r.checklist_id
            LEFT JOIN dbo.audit_confidential_files fl ON f.branch_id = fl.branch_id AND f.checklist_id = fl.checklist_id AND fl.is_archived = 0
            LEFT JOIN dbo.audit_normal_files nf ON f.branch_id = nf.branch_id AND f.checklist_id = nf.checklist_id AND nf.is_archived = 0
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
            
            normal_file_id = row_dict.get("normal_file_id")
            confidential_file_id = row_dict.get("confidential_file_id")

            feedback_list.append({
                "checklistId": row_dict.get("checklist_id"),
                "answer": row_dict.get("answer"),
                "normalRemark": row_dict.get("normal_remark"),
                "status": row_dict.get("status"),
                "confidentialRemark": row_dict.get("confidential_remark"),
                "normalFile": {
                    "id": normal_file_id,
                    "filename": row_dict.get("normal_file_name")
                } if normal_file_id else None,
                "confidentialFile": {
                    "id": confidential_file_id,
                    "filename": row_dict.get("confidential_file_name")
                } if confidential_file_id else None,
            })

        return JsonResponse({
            'success': True,
            'feedback': feedback_list,
            'auditId': feedback_audit_id
        })
    except Exception as e:
        log_error(f"get_audit_feedback: DB error: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


# def compress_file_backend(file_bytes, filename):
#     """
#     Given file bytes and a filename, checks if the file is an image.
#     If it is an image, compresses it to JPEG at 50% quality with optimization.
#     If it is not an image (or if compression fails/is larger), uses lossless lzma.
#     Returns (compressed_bytes, final_filename).
#     """
#     import io
#     import lzma
#     from PIL import Image

#     ext = filename.split('.')[-1].lower()
#     is_image = ext in ['jpg', 'jpeg', 'png', 'bmp', 'webp']
    
#     compressed_payload = None
#     final_filename = filename

#     if is_image:
#         try:
#             img = Image.open(io.BytesIO(file_bytes))
#             if img.mode in ('RGBA', 'LA', 'P'):
#                 img = img.convert('RGB')
            
#             out_buf = io.BytesIO()
#             # Compress to JPEG with 50% quality and optimization
#             img.save(out_buf, format='JPEG', quality=50, optimize=True)
#             img_bytes = out_buf.getvalue()
            
#             if len(img_bytes) < len(file_bytes):
#                 compressed_payload = img_bytes
#                 # Update extension to .jpg if it was PNG or BMP to avoid MIME type confusion
#                 if ext not in ['jpg', 'jpeg']:
#                     base_name = '.'.join(filename.split('.')[:-1])
#                     final_filename = f"{base_name}.jpg"
#         except Exception as e:
#             log_error(f"compress_file_backend: image compression failed for {filename}: {str(e)}")

#     # If it was not an image, or image compression did not yield size savings
#     if not compressed_payload:
#         compressed_payload = file_bytes

#     # Lossless compress the resulting bytes using lzma (preset 9)
#     try:
#         lzma_bytes = lzma.compress(compressed_payload, preset=9)
#         return lzma_bytes, final_filename
#     except Exception as e:
#         log_error(f"compress_file_backend: lzma compression failed for {filename}: {str(e)}")
#         return compressed_payload, final_filename


import io
import lzma
import base64
import struct

# Magic header to identify our compression format version
COMPRESS_MAGIC = b'\x43\x4D\x50\x56\x31'  # "CMPV1"


import subprocess
import tempfile
import os

def compress_pdf(file_bytes):
    """Uses Ghostscript to re-compress PDF embedded images. Requires: apt install ghostscript"""
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as inp:
        inp.write(file_bytes)
        inp_path = inp.name

    out_path = inp_path + '_compressed.pdf'

    try:
        result = subprocess.run([
            'gs',
            '-sDEVICE=pdfwrite',
            '-dCompatibilityLevel=1.4',
            '-dPDFSETTINGS=/screen',   # /screen=72dpi, /ebook=150dpi, /printer=300dpi
            '-dNOPAUSE',
            '-dQUIET',
            '-dBATCH',
            f'-sOutputFile={out_path}',
            inp_path
        ], capture_output=True, timeout=30)

        if result.returncode == 0 and os.path.exists(out_path):
            with open(out_path, 'rb') as f:
                compressed = f.read()
            if len(compressed) < len(file_bytes):
                return compressed
    except Exception as e:
        log_error(f"ghostscript compression failed: {e}")
    finally:
        os.unlink(inp_path)
        if os.path.exists(out_path):
            os.unlink(out_path)

    return file_bytes  # fallback to original


import io
import lzma
import os
import subprocess
import tempfile

COMPRESS_MAGIC = b'\x43\x4D\x50\x56\x31'  # "CMPV1"
IMAGE_EXTS = {'jpg', 'jpeg', 'png', 'bmp', 'webp', 'tiff', 'gif'}
MAX_IMAGE_DIM = 2400   # max pixels per side — raised for audit evidence clarity
JPEG_QUALITY  = 88    # 88 is near-lossless for audit photos; was 20 (too blurry)


def _compress_image(file_bytes, filename):
    """Resize + JPEG re-encode. Returns (bytes, new_filename) or (None, filename) if no gain."""
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(file_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')

        w, h = img.size
        if w > MAX_IMAGE_DIM or h > MAX_IMAGE_DIM:
            ratio = min(MAX_IMAGE_DIM / w, MAX_IMAGE_DIM / h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=JPEG_QUALITY, optimize=True, progressive=True)
        jpeg_bytes = buf.getvalue()

        if len(jpeg_bytes) < len(file_bytes):
            base = filename.rsplit('.', 1)[0]
            return jpeg_bytes, f"{base}.jpg"

    except Exception as e:
        log_error(f"_compress_image failed for {filename}: {e}")

    return None, filename


def _compress_pdf_ghostscript(file_bytes):
    print(f"[gs] attempting ghostscript...")
    """Re-compress PDF using Ghostscript /ebook preset (~150dpi). Returns bytes or None."""
    inp = out = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(file_bytes)
            inp = f.name
        out = inp + '_gs_out.pdf'

        result = subprocess.run(
            [
                'gs', '-sDEVICE=pdfwrite', '-dCompatibilityLevel=1.4',
                '-dPDFSETTINGS=/ebook',   # 150dpi — readable + compressed
                '-dNOPAUSE', '-dQUIET', '-dBATCH',
                f'-sOutputFile={out}', inp,
            ],
            capture_output=True, timeout=30
        )

        if result.returncode == 0 and os.path.exists(out):
            with open(out, 'rb') as f:
                compressed = f.read()
            return compressed if len(compressed) < len(file_bytes) else None

    except FileNotFoundError:
        pass  # Ghostscript not installed — will fall through to pikepdf
    except Exception as e:
        log_error(f"_compress_pdf_ghostscript failed: {e}")
    finally:
        for path in (inp, out):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except Exception:
                    pass

    return None


def _compress_pdf_pikepdf(file_bytes):
    """Re-compress PDF using pikepdf (pure Python fallback). Returns bytes or None."""
    
    print("[pk]pikepdf")
    inp = out = None
    
    try:
        import pikepdf

        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(file_bytes)
            inp = f.name
        out = inp + '_pk_out.pdf'

        with pikepdf.open(inp) as pdf:
            pdf.save(out, compress_streams=True, recompress_flate=True)

        with open(out, 'rb') as f:
            compressed = f.read()
        return compressed if len(compressed) < len(file_bytes) else None

    except ImportError:
        pass  # pikepdf not installed
    except Exception as e:
        log_error(f"_compress_pdf_pikepdf failed: {e}")
    finally:
        for path in (inp, out):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except Exception:
                    pass

    return None


def _compress_pdf_pypdf(file_bytes):
    """Re-compress PDF using pypdf. Returns bytes or None."""
    import io
    from PIL import Image
    try:
        from pypdf import PdfReader, PdfWriter
        
        reader = PdfReader(io.BytesIO(file_bytes))
        writer = PdfWriter()
        
        # 1. Add all pages to the writer first
        for page in reader.pages:
            writer.add_page(page)
            
        # 2. Iterate through the writer's pages and compress embedded images
        for page in writer.pages:
            for img in page.images:
                try:
                    original_img_size = len(img.data)
                    # Only compress images that are large (e.g. over 50KB)
                    if original_img_size > 50 * 1024:
                        pil_img = img.image
                        w, h = pil_img.size
                        
                        # Resize if dimensions are larger than 1200px
                        if w > 1200 or h > 1200:
                            ratio = min(1200 / w, 1200 / h)
                            new_w, new_h = int(w * ratio), int(h * ratio)
                            pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                            
                        # Convert to RGB if transparent/palette (JPEG doesn't support transparency)
                        if pil_img.mode in ("RGBA", "LA", "P"):
                            pil_img = pil_img.convert("RGB")
                        
                        # Replace image in-place
                        img.replace(pil_img, quality=40)
                except Exception as e:
                    log_error(f"_compress_pdf_pypdf: failed to replace image: {e}")
        
        # 3. Apply standard structural compressions
        for page in writer.pages:
            try:
                page.compress_content_streams()
            except Exception:
                pass
        try:
            writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
        except Exception:
            try:
                writer.compress_identical_objects()
            except Exception:
                pass
            
        # 4. Save directly to a binary stream in memory
        out_buf = io.BytesIO()
        writer.write(out_buf)
        compressed = out_buf.getvalue()
        out_buf.close()
        
        if len(compressed) < len(file_bytes):
            return compressed
    except Exception as e:
        log_error(f"_compress_pdf_pypdf failed: {e}")
    return None


def _compress_pdf(file_bytes):
    # Try pypdf first
    compressed = _compress_pdf_pypdf(file_bytes)
    if compressed:
        return compressed

    # Try pikepdf fallback
    compressed = _compress_pdf_pikepdf(file_bytes)
    if compressed:
        return compressed

    return file_bytes


def _apply_lzma(data):
    """Apply LZMA preset 9. Returns (bytes, flag) — flag indicates if LZMA was applied."""
    try:
        lzma_bytes = lzma.compress(data, preset=9)
        if len(lzma_bytes) < len(data):
            return lzma_bytes, b'\x01'
    except Exception as e:
        log_error(f"_apply_lzma failed: {e}")

    return data, b'\x00'


def compress_file_backend(file_bytes, filename):
    """
    Compress a file for DB storage.

    Pipeline per type:
      Images → resize to 2400px max + JPEG q88 → LZMA
      PDFs   → Ghostscript /ebook (→ pikepdf fallback) → LZMA
      Other  → LZMA only

    Output format: CMPV1 magic (5B) + lzma_flag (1B) + payload

    Returns (compressed_bytes, final_filename)
    """
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    original_size = len(file_bytes)
    payload = file_bytes
    print("ext",ext)
    if ext in IMAGE_EXTS:
        compressed, filename = _compress_image(file_bytes, filename)
        if compressed:
            payload = compressed

    elif ext == 'pdf':
        payload = _compress_pdf(file_bytes)

    # Always attempt LZMA on the result
    print("payload",payload)
    payload, lzma_flag = _apply_lzma(payload)

    result = COMPRESS_MAGIC + lzma_flag + payload

    ratio = (1 - len(result) / original_size) * 100 if original_size else 0
    print(f"[compress] {filename}: {original_size:,}B -> {len(result):,}B ({ratio:.1f}% reduction)")

    return result, filename


def decompress_file_backend(stored_bytes, filename):
    """
    Decompresses bytes stored by compress_file_backend.
    Handles:
    1. New format: CMPV1 magic header
    2. Legacy LZMA (no header, compressed by old code)
    3. Legacy zlib
    4. Uncompressed (raw bytes)
    
    Returns decompressed bytes.
    """
    if not stored_bytes:
        return stored_bytes

    # Check for our magic header (new format)
    if stored_bytes[:5] == COMPRESS_MAGIC:
        compression_flag = stored_bytes[5:6]
        data = stored_bytes[6:]
        if compression_flag == b'\x01':
            return lzma.decompress(data)
        else:
            return data  # Raw, no LZMA applied

    # Legacy fallback: try LZMA, then zlib, then raw
    try:
        return lzma.decompress(stored_bytes)
    except Exception:
        pass

    try:
        import zlib
        return zlib.decompress(stored_bytes)
    except Exception:
        pass

    # Last resort: return as-is (legacy uncompressed files)
    return stored_bytes

@csrf_exempt
def save_audit_feedback(request):
    """
    POST API endpoint to save or submit checklist feedback for a branch.
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
                saved_files = {}
                for item in feedback_items:
                    checklist_id = item.get('checklist_id')
                    section_code = item.get('section_code')
                    section_name = item.get('section_name')
                    intent_code = item.get('intent_code')
                    intent_title = item.get('intent_title')
                    answer = item.get('answer', 'N/A')
                    normal_remark = item.get('normal_remark')
                    confidential_remark = item.get('confidential_remark')
                    
                    # Process normal file data
                    normal_file = item.get('normal_file')
                    has_new_normal_file = False
                    normal_file_bytes = None
                    normal_file_name = None
                    if normal_file and isinstance(normal_file, dict) and normal_file.get('base64'):
                        has_new_normal_file = True
                        normal_file_name = normal_file.get('filename', 'upload.png')
                        base64_str = normal_file.get('base64')
                        if ';base64,' in base64_str:
                            _, base64_data = base64_str.split(';base64,')
                        else:
                            base64_data = base64_str
                        decoded_bytes = base64.b64decode(base64_data)
                        normal_file_bytes, normal_file_name = compress_file_backend(decoded_bytes, normal_file_name)

                    # Process confidential file data
                    confidential_file = item.get('confidential_file')
                    has_new_confidential_file = False
                    confidential_file_bytes = None
                    confidential_file_name = None
                    if confidential_file and isinstance(confidential_file, dict) and confidential_file.get('base64'):
                        has_new_confidential_file = True
                        confidential_file_name = confidential_file.get('filename', 'upload_conf.png')
                        base64_str = confidential_file.get('base64')
                        if ';base64,' in base64_str:
                            _, base64_data = base64_str.split(';base64,')
                        else:
                            base64_data = base64_str
                        decoded_bytes = base64.b64decode(base64_data)
                        confidential_file_bytes, confidential_file_name = compress_file_backend(decoded_bytes, confidential_file_name)

                    # Check if record exists in main feedback table
                    cursor.execute("""
                        SELECT id, normal_file_path, is_confidential_file_present 
                        FROM dbo.audit_checklist_feedback 
                        WHERE branch_id = %s AND checklist_id = %s AND audit_id = %s
                    """, [branch_id, checklist_id, audit_id])
                    fb_row = cursor.fetchone()

                    is_confidential_remark_present = 1 if confidential_remark else 0
                    
                    if has_new_confidential_file:
                        is_confidential_file_present = 1
                    else:
                        is_confidential_file_present = fb_row[2] if fb_row else 0

                    if fb_row:
                        fb_id = fb_row[0]
                        final_normal_file_path = normal_file_name if has_new_normal_file else fb_row[1]
                        
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
                            intent_code, intent_title, answer, normal_remark, normal_file_name,
                            is_confidential_remark_present, is_confidential_file_present, status_to, user.UserID
                        ])
                        cursor.execute("SELECT @@IDENTITY")
                        fb_id = int(cursor.fetchone()[0])

                    # Store normal file as binary in separate table
                    new_normal_file_id = None
                    if has_new_normal_file:
                        # Archive previous normal file
                        cursor.execute("""
                            UPDATE dbo.audit_normal_files
                            SET is_archived = 1, updated_at = GETDATE()
                            WHERE branch_id = %s AND checklist_id = %s AND is_archived = 0
                        """, [branch_id, checklist_id])
                        
                        # Insert new normal file
                        cursor.execute("""
                            INSERT INTO dbo.audit_normal_files (
                                feedback_id, branch_id, checklist_id, file_name, file_content, is_archived, uploaded_by, created_at, updated_at
                            ) VALUES (%s, %s, %s, %s, %s, 0, %s, GETDATE(), GETDATE())
                        """, [fb_id, branch_id, checklist_id, normal_file_name, normal_file_bytes, user.UserID])
                        cursor.execute("SELECT @@IDENTITY")
                        new_normal_file_id = int(cursor.fetchone()[0])

                    # Process confidential remark
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

                    # Store confidential file as binary in database
                    new_confidential_file_id = None
                    if has_new_confidential_file:
                        # Archive previous confidential file
                        cursor.execute("""
                            UPDATE dbo.audit_confidential_files
                            SET is_archived = 1, updated_at = GETDATE()
                            WHERE branch_id = %s AND checklist_id = %s AND is_archived = 0
                        """, [branch_id, checklist_id])
                        
                        # Insert new confidential file
                        cursor.execute("""
                            INSERT INTO dbo.audit_confidential_files (
                                feedback_id, branch_id, checklist_id, confidential_file_path, file_name, file_content, is_archived, user_id, created_at, updated_at
                            ) VALUES (%s, %s, %s, NULL, %s, %s, 0, %s, GETDATE(), GETDATE())
                        """, [fb_id, branch_id, checklist_id, confidential_file_name, confidential_file_bytes, user.UserID])
                        cursor.execute("SELECT @@IDENTITY")
                        new_confidential_file_id = int(cursor.fetchone()[0])

                    if new_normal_file_id or new_confidential_file_id:
                        saved_files[checklist_id] = {}
                        if new_normal_file_id:
                            saved_files[checklist_id]['normalFile'] = {
                                'id': new_normal_file_id,
                                'filename': normal_file_name
                            }
                        if new_confidential_file_id:
                            saved_files[checklist_id]['confidentialFile'] = {
                                'id': new_confidential_file_id,
                                'filename': confidential_file_name
                            }

                # Insert activity log entry
                cursor.execute("""
                    INSERT INTO dbo.audit_activity_log (
                        branch_id, action, status_to, created_by, created_at, remarks
                    ) VALUES (%s, %s, %s, %s, GETDATE(), %s)
                """, [branch_id, action, status_to, user.UserID, general_remarks])

        return JsonResponse({
            'success': True,
            'message': 'Audit checklist feedback saved successfully',
            'saved_files': saved_files
        })
    except Exception as e:
        log_error(f"save_audit_feedback: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def view_feedback_file(request):
    """
    POST endpoint to retrieve file details and binary content (encoded in base64 data URL) from DB.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
        token = data.get('token', '')
        file_type = data.get('file_type', 'normal')
        file_id = data.get('file_id')
    except Exception as e:
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    if not file_id:
        return JsonResponse({'success': False, 'message': 'file_id is required'}, status=400)

    try:
        import base64
        import mimetypes

        with connection.cursor() as cursor:
            if file_type == 'normal':
                cursor.execute("SELECT file_name, file_content FROM dbo.audit_normal_files WHERE id = %s", [file_id])
            else:
                cursor.execute("SELECT file_name, file_content FROM dbo.audit_confidential_files WHERE id = %s", [file_id])
            row = cursor.fetchone()

        if not row:
            return JsonResponse({'success': False, 'message': 'File not found'}, status=404)

        file_name, file_content = row
        if not file_content:
            return JsonResponse({'success': False, 'message': 'File content is empty'}, status=404)

        # Decompress with lzma, with fallbacks for zlib and uncompressed legacy files
        import lzma
        import zlib
        try:
            decompressed_bytes = decompress_file_backend(file_content, file_name)
        except Exception:
            try:
                decompressed_bytes = zlib.decompress(file_content)
            except Exception:
                decompressed_bytes = file_content

        # Convert VARBINARY bytes to base64
        base64_str = base64.b64encode(decompressed_bytes).decode('utf-8')
        mime_type, _ = mimetypes.guess_type(file_name)
        if not mime_type:
            mime_type = 'application/octet-stream'

        data_url = f"data:{mime_type};base64,{base64_str}"

        return JsonResponse({
            'success': True,
            'filename': file_name,
            'dataUrl': data_url
        })
    except Exception as e:
        log_error(f"view_feedback_file: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def archive_feedback_file(request):
    """
    POST endpoint to archive a file (setting is_archived = 1) and sync check state.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
        token = data.get('token', '')
        file_type = data.get('file_type', 'normal')
        checklist_id = data.get('checklist_id')
        branch_id = data.get('branch_id', '')
    except Exception as e:
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    if not checklist_id or not branch_id:
        return JsonResponse({'success': False, 'message': 'checklist_id and branch_id are required'}, status=400)

    try:
        with connection.cursor() as cursor:
            if file_type == 'normal':
                cursor.execute("""
                    UPDATE dbo.audit_normal_files
                    SET is_archived = 1, updated_at = GETDATE()
                    WHERE branch_id = %s AND checklist_id = %s AND is_archived = 0
                """, [branch_id, checklist_id])

                cursor.execute("""
                    UPDATE dbo.audit_checklist_feedback
                    SET normal_file_path = NULL, updated_at = GETDATE()
                    WHERE branch_id = %s AND checklist_id = %s
                """, [branch_id, checklist_id])
            else:
                cursor.execute("""
                    UPDATE dbo.audit_confidential_files
                    SET is_archived = 1, updated_at = GETDATE()
                    WHERE branch_id = %s AND checklist_id = %s AND is_archived = 0
                """, [branch_id, checklist_id])

                cursor.execute("""
                    UPDATE dbo.audit_checklist_feedback
                    SET is_confidential_file_present = 0, updated_at = GETDATE()
                    WHERE branch_id = %s AND checklist_id = %s
                """, [branch_id, checklist_id])

        return JsonResponse({
            'success': True,
            'message': 'File archived successfully'
        })
    except Exception as e:
        log_error(f"archive_feedback_file: failed: {str(e)}")
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


@csrf_exempt
def get_customer_risk_details(request):
    """
    POST API endpoint to retrieve customer-level risk details by Center ID.
    Expects plain JSON body:
    {
        "token": "...",
        "center_id": 138245,
        "as_on_date": "2026-06-08"  # Optional
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        center_id_raw = data.get('center_id')
        as_on_date = data.get('as_on_date')
        print("data :",data)
        print("token :",token)
        print("center_id_raw :",center_id_raw)
        print("as_on_date :",as_on_date)
    except Exception as e:
        log_error(f"get_customer_risk_details: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    if center_id_raw is None:
        return JsonResponse({'success': False, 'message': 'center_id parameter is required'}, status=400)

    try:
        center_id = int(center_id_raw)
    except ValueError:
        return JsonResponse({'success': False, 'message': 'center_id must be a valid integer'}, status=400)

    try:
        with connection.cursor() as cursor:
            db_date = as_on_date if as_on_date else None
            cursor.execute("""
                EXEC SP_GetCustomerRiskDetails @CenterID = %s, @AsOnDate = %s
            """, [center_id, db_date])
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
            'customer_risks': items
        })

    except Exception as e:
        log_error(f"get_customer_risk_details: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_center_disbursements(request):
    """
    POST API endpoint to retrieve center-level disbursements using SP_GetCenterOverview.
    Expects plain JSON body:
    {
        "token": "...",
        "center_id": 138245,
        "as_on_date": "2026-06-08"  # Optional, defaults to '2026-06-08'
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        center_id_raw = data.get('center_id')
        as_on_date = data.get('as_on_date', '2026-06-08')
    except Exception as e:
        log_error(f"get_center_disbursements: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    if center_id_raw is None:
        return JsonResponse({'success': False, 'message': 'center_id parameter is required'}, status=400)

    try:
        center_id = int(center_id_raw)
    except ValueError:
        return JsonResponse({'success': False, 'message': 'center_id must be a valid integer'}, status=400)

    try:
        with connection.cursor() as cursor:
            db_date = as_on_date if as_on_date else '2026-06-08'
            cursor.execute("""
                EXEC SP_GetCenterOverview @CenterID = %s, @AsOnDate = %s, @ReportType = 'LAST_TO_CURRENT_DISBURSEMENTS'
            """, [center_id, db_date])
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
            'disbursements': items
        })

    except Exception as e:
        log_error(f"get_center_disbursements: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_center_audit_feedback(request):
    """
    POST API endpoint to retrieve checklist feedback for a center.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        center_id_raw = data.get('center_id')
        audit_id = data.get('audit_id')
    except Exception as e:
        log_error(f"get_center_audit_feedback: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    if center_id_raw is None:
        return JsonResponse({'success': False, 'message': 'center_id is required'}, status=400)

    try:
        center_id = int(center_id_raw)
    except ValueError:
        return JsonResponse({'success': False, 'message': 'center_id must be a valid integer'}, status=400)

    try:
        # Resolve audit_id if not explicitly provided
        if not audit_id:
            from django.db.models import Q
            from planner.models import AuditPlanCurrent
            user_id_str = str(user.UserID) if user.UserID is not None else ""
            user_code = user.UserCode or ""
            branch_name = None
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT TOP 1 BranchName 
                    FROM CenterRiskScore 
                    WHERE CenterID = %s OR CenterID = %s
                """, [str(center_id), center_id])
                row = cursor.fetchone()
                if row:
                    branch_name = row[0]
            if branch_name:
                plan = AuditPlanCurrent.objects.filter(
                    Q(branch=branch_name) & (Q(assigned_auditor=user_id_str) | Q(assigned_auditor=user_code))
                ).first()
                if plan:
                    audit_id = plan.id
                else:
                    audit_id = 0
            else:
                audit_id = 0

        query = """
            SELECT 
                f.audit_id, f.center_checklist_id, f.answer, f.normal_remark, f.status,
                r.confidential_remark,
                fl.id as confidential_file_id, fl.file_name as confidential_file_name,
                nf.id as normal_file_id, nf.file_name as normal_file_name,
                ev.id as evidence_file_id, ev.file_name as evidence_file_name,
                ev.latitude as evidence_latitude, ev.longitude as evidence_longitude,
                ev.image_text as evidence_text
            FROM dbo.audit_center_checklist_feedback f
            LEFT JOIN dbo.audit_center_confidential_remarks r ON f.center_id = r.center_id AND f.center_checklist_id = r.center_checklist_id
            LEFT JOIN dbo.audit_center_confidential_files fl ON f.center_id = fl.center_id AND f.center_checklist_id = fl.center_checklist_id AND fl.is_archived = 0
            LEFT JOIN dbo.audit_center_normal_files nf ON f.center_id = nf.center_id AND f.center_checklist_id = nf.center_checklist_id AND nf.is_archived = 0
            LEFT JOIN dbo.audit_center_evidence ev ON f.center_id = ev.center_id AND f.center_checklist_id = ev.center_checklist_id AND ev.is_archived = 0
            WHERE f.center_id = %s
        """
        params = [center_id]
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
            
            normal_file_id = row_dict.get("normal_file_id")
            confidential_file_id = row_dict.get("confidential_file_id")
            evidence_file_id = row_dict.get("evidence_file_id")

            # Convert decimals to float safely
            evidence_latitude = row_dict.get("evidence_latitude")
            if isinstance(evidence_latitude, decimal.Decimal):
                evidence_latitude = float(evidence_latitude)
            evidence_longitude = row_dict.get("evidence_longitude")
            if isinstance(evidence_longitude, decimal.Decimal):
                evidence_longitude = float(evidence_longitude)

            feedback_list.append({
                "checklistId": row_dict.get("center_checklist_id"),
                "answer": row_dict.get("answer"),
                "normalRemark": row_dict.get("normal_remark"),
                "status": row_dict.get("status"),
                "confidentialRemark": row_dict.get("confidential_remark"),
                "normalFile": {
                    "id": normal_file_id,
                    "filename": row_dict.get("normal_file_name")
                } if normal_file_id else None,
                "confidentialFile": {
                    "id": confidential_file_id,
                    "filename": row_dict.get("confidential_file_name")
                } if confidential_file_id else None,
                "evidenceImage": {
                    "id": evidence_file_id,
                    "filename": row_dict.get("evidence_file_name"),
                    "latitude": evidence_latitude,
                    "longitude": evidence_longitude,
                    "imageText": row_dict.get("evidence_text")
                } if evidence_file_id else None,
            })

        return JsonResponse({
            'success': True,
            'feedback': feedback_list,
            'auditId': feedback_audit_id
        })
    except Exception as e:
        log_error(f"get_center_audit_feedback: DB error: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def save_center_audit_feedback(request):
    """
    POST API endpoint to save or submit checklist feedback for a center.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        center_id_raw = data.get('center_id')
        audit_id = data.get('audit_id')
        action = data.get('action', 'DRAFT_SAVED')
        general_remarks = data.get('general_remarks', '')
        feedback_items = data.get('feedback_items', [])
    except Exception as e:
        log_error(f"save_center_audit_feedback: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    if center_id_raw is None:
        return JsonResponse({'success': False, 'message': 'center_id is required'}, status=400)

    try:
        center_id = int(center_id_raw)
    except ValueError:
        return JsonResponse({'success': False, 'message': 'center_id must be a valid integer'}, status=400)

    # Resolve audit_id if not explicitly provided
    if not audit_id:
        from django.db.models import Q
        from planner.models import AuditPlanCurrent
        user_id_str = str(user.UserID) if user.UserID is not None else ""
        user_code = user.UserCode or ""
        branch_name = None
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT TOP 1 BranchName 
                FROM CenterRiskScore 
                WHERE CenterID = %s OR CenterID = %s
            """, [str(center_id), center_id])
            row = cursor.fetchone()
            if row:
                branch_name = row[0]
        if branch_name:
            plan = AuditPlanCurrent.objects.filter(
                Q(branch=branch_name) & (Q(assigned_auditor=user_id_str) | Q(assigned_auditor=user_code))
            ).first()
            if plan:
                audit_id = plan.id
            else:
                audit_id = 0
        else:
            audit_id = 0

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

    import base64
    from django.db import transaction
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                saved_files = {}
                for item in feedback_items:
                    checklist_id = item.get('checklist_id')
                    parameter_code = item.get('parameter_code', '')
                    parameter_name = item.get('parameter_name', '')
                    answer = item.get('answer', 'N/A')
                    normal_remark = item.get('normal_remark')
                    confidential_remark = item.get('confidential_remark')
                    
                    # Process normal file data
                    normal_file = item.get('normal_file')
                    has_new_normal_file = False
                    normal_file_bytes = None
                    normal_file_name = None
                    if normal_file and isinstance(normal_file, dict) and normal_file.get('base64'):
                        has_new_normal_file = True
                        normal_file_name = normal_file.get('filename', 'upload.png')
                        base64_str = normal_file.get('base64')
                        if ';base64,' in base64_str:
                            _, base64_data = base64_str.split(';base64,')
                        else:
                            base64_data = base64_str
                        decoded_bytes = base64.b64decode(base64_data)
                        normal_file_bytes, normal_file_name = compress_file_backend(decoded_bytes, normal_file_name)

                    # Process confidential file data
                    confidential_file = item.get('confidential_file')
                    has_new_confidential_file = False
                    confidential_file_bytes = None
                    confidential_file_name = None
                    if confidential_file and isinstance(confidential_file, dict) and confidential_file.get('base64'):
                        has_new_confidential_file = True
                        confidential_file_name = confidential_file.get('filename', 'upload_conf.png')
                        base64_str = confidential_file.get('base64')
                        if ';base64,' in base64_str:
                            _, base64_data = base64_str.split(';base64,')
                        else:
                            base64_data = base64_str
                        decoded_bytes = base64.b64decode(base64_data)
                        confidential_file_bytes, confidential_file_name = compress_file_backend(decoded_bytes, confidential_file_name)

                    # Process evidence image data
                    evidence_image = item.get('evidence_image')
                    has_new_evidence_image = False
                    evidence_image_bytes = None
                    evidence_image_name = None
                    evidence_latitude = None
                    evidence_longitude = None
                    evidence_text = None
                    if evidence_image and isinstance(evidence_image, dict) and evidence_image.get('base64'):
                        has_new_evidence_image = True
                        evidence_image_name = evidence_image.get('filename', 'captured.jpg')
                        evidence_latitude = evidence_image.get('latitude')
                        evidence_longitude = evidence_image.get('longitude')
                        evidence_text = evidence_image.get('image_text')
                        
                        base64_str = evidence_image.get('base64')
                        if ';base64,' in base64_str:
                            _, base64_data = base64_str.split(';base64,')
                        else:
                            base64_data = base64_str
                        decoded_bytes = base64.b64decode(base64_data)
                        evidence_image_bytes, evidence_image_name = compress_file_backend(decoded_bytes, evidence_image_name)

                    # Check if record exists in main feedback table
                    cursor.execute("""
                        SELECT id, normal_file_path, is_confidential_file_present 
                        FROM dbo.audit_center_checklist_feedback 
                        WHERE center_id = %s AND center_checklist_id = %s AND audit_id = %s
                    """, [center_id, checklist_id, audit_id])
                    fb_row = cursor.fetchone()

                    is_confidential_remark_present = 1 if confidential_remark else 0
                    
                    if has_new_confidential_file:
                        is_confidential_file_present = 1
                    else:
                        is_confidential_file_present = fb_row[2] if fb_row else 0

                    if fb_row:
                        fb_id = fb_row[0]
                        final_normal_file_path = normal_file_name if has_new_normal_file else fb_row[1]
                        
                        # Update main feedback table
                        cursor.execute("""
                            UPDATE dbo.audit_center_checklist_feedback
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
                            INSERT INTO dbo.audit_center_checklist_feedback (
                                audit_id, center_id, auditor_id, center_checklist_id, parameter_code, parameter_name,
                                answer, normal_remark, normal_file_path,
                                is_confidential_remark_present, is_confidential_file_present, status, last_modified_by,
                                created_at, updated_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, GETDATE(), GETDATE())
                        """, [
                            audit_id, center_id, user.UserID, checklist_id, parameter_code, parameter_name,
                            answer, normal_remark, normal_file_name,
                            is_confidential_remark_present, is_confidential_file_present, status_to, user.UserID
                        ])
                        cursor.execute("SELECT @@IDENTITY")
                        fb_id = int(cursor.fetchone()[0])

                    # Store normal file as binary in separate table
                    new_normal_file_id = None
                    if has_new_normal_file:
                        # Archive previous normal file
                        cursor.execute("""
                            UPDATE dbo.audit_center_normal_files
                            SET is_archived = 1, updated_at = GETDATE()
                            WHERE center_id = %s AND center_checklist_id = %s AND is_archived = 0
                        """, [center_id, checklist_id])
                        
                        # Insert new normal file
                        cursor.execute("""
                            INSERT INTO dbo.audit_center_normal_files (
                                feedback_id, center_id, center_checklist_id, file_name, file_content, is_archived, uploaded_by, created_at, updated_at
                            ) VALUES (%s, %s, %s, %s, %s, 0, %s, GETDATE(), GETDATE())
                        """, [fb_id, center_id, checklist_id, normal_file_name, normal_file_bytes, user.UserID])
                        cursor.execute("SELECT @@IDENTITY")
                        new_normal_file_id = int(cursor.fetchone()[0])

                    # Process confidential remark
                    if confidential_remark is not None:
                        cursor.execute("""
                            SELECT id FROM dbo.audit_center_confidential_remarks
                            WHERE center_id = %s AND center_checklist_id = %s
                        """, [center_id, checklist_id])
                        cr_row = cursor.fetchone()
                        if cr_row:
                            cursor.execute("""
                                UPDATE dbo.audit_center_confidential_remarks
                                SET confidential_remark = %s,
                                    user_id = %s,
                                    updated_at = GETDATE()
                                WHERE id = %s
                            """, [confidential_remark, user.UserID, cr_row[0]])
                        else:
                            cursor.execute("""
                                INSERT INTO dbo.audit_center_confidential_remarks (
                                    feedback_id, center_id, center_checklist_id, confidential_remark, user_id, created_at, updated_at
                                ) VALUES (%s, %s, %s, %s, %s, GETDATE(), GETDATE())
                            """, [fb_id, center_id, checklist_id, confidential_remark, user.UserID])

                    # Store confidential file as binary in database
                    new_confidential_file_id = None
                    if has_new_confidential_file:
                        # Archive previous confidential file
                        cursor.execute("""
                            UPDATE dbo.audit_center_confidential_files
                            SET is_archived = 1, updated_at = GETDATE()
                            WHERE center_id = %s AND center_checklist_id = %s AND is_archived = 0
                        """, [center_id, checklist_id])
                        
                        # Insert new confidential file
                        cursor.execute("""
                            INSERT INTO dbo.audit_center_confidential_files (
                                feedback_id, center_id, center_checklist_id, confidential_file_path, file_name, file_content, is_archived, user_id, created_at, updated_at
                            ) VALUES (%s, %s, %s, NULL, %s, %s, 0, %s, GETDATE(), GETDATE())
                        """, [fb_id, center_id, checklist_id, confidential_file_name, confidential_file_bytes, user.UserID])
                        cursor.execute("SELECT @@IDENTITY")
                        new_confidential_file_id = int(cursor.fetchone()[0])

                    # Store evidence captured image in database
                    new_evidence_file_id = None
                    if has_new_evidence_image:
                        # Archive previous evidence file
                        cursor.execute("""
                            UPDATE dbo.audit_center_evidence
                            SET is_archived = 1, updated_at = GETDATE()
                            WHERE center_id = %s AND center_checklist_id = %s AND is_archived = 0
                        """, [center_id, checklist_id])
                        
                        # Insert new evidence file
                        cursor.execute("""
                            INSERT INTO dbo.audit_center_evidence (
                                feedback_id, center_id, center_checklist_id, file_name, file_content,
                                latitude, longitude, image_text, is_archived, uploaded_by, created_at, updated_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s, GETDATE(), GETDATE())
                        """, [fb_id, center_id, checklist_id, evidence_image_name, evidence_image_bytes,
                              evidence_latitude, evidence_longitude, evidence_text, user.UserID])
                        cursor.execute("SELECT @@IDENTITY")
                        new_evidence_file_id = int(cursor.fetchone()[0])

                    if new_normal_file_id or new_confidential_file_id or new_evidence_file_id:
                        saved_files[checklist_id] = {}
                        if new_normal_file_id:
                            saved_files[checklist_id]['normalFile'] = {
                                'id': new_normal_file_id,
                                'filename': normal_file_name
                            }
                        if new_confidential_file_id:
                            saved_files[checklist_id]['confidentialFile'] = {
                                'id': new_confidential_file_id,
                                'filename': confidential_file_name
                            }
                        if new_evidence_file_id:
                            saved_files[checklist_id]['evidenceImage'] = {
                                'id': new_evidence_file_id,
                                'filename': evidence_image_name,
                                'latitude': evidence_latitude,
                                'longitude': evidence_longitude,
                                'imageText': evidence_text
                            }

                # Insert activity log entry
                cursor.execute("""
                    INSERT INTO dbo.audit_center_activity_log (
                        center_id, action, status_to, created_by, created_at, remarks
                    ) VALUES (%s, %s, %s, %s, GETDATE(), %s)
                """, [center_id, action, status_to, user.UserID, general_remarks])

        return JsonResponse({
            'success': True,
            'message': 'Center checklist feedback saved successfully',
            'saved_files': saved_files
        })
    except Exception as e:
        log_error(f"save_center_audit_feedback: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def view_center_feedback_file(request):
    """
    POST endpoint to retrieve file details and binary content (encoded in base64 data URL) for center from DB.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
        token = data.get('token', '')
        file_type = data.get('file_type', 'normal')
        file_id = data.get('file_id')
    except Exception as e:
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    if not file_id:
        return JsonResponse({'success': False, 'message': 'file_id is required'}, status=400)

    try:
        import base64
        import mimetypes

        with connection.cursor() as cursor:
            if file_type == 'normal':
                cursor.execute("SELECT file_name, file_content FROM dbo.audit_center_normal_files WHERE id = %s", [file_id])
            elif file_type == 'confidential':
                cursor.execute("SELECT file_name, file_content FROM dbo.audit_center_confidential_files WHERE id = %s", [file_id])
            else:
                cursor.execute("SELECT file_name, file_content FROM dbo.audit_center_evidence WHERE id = %s", [file_id])
            row = cursor.fetchone()

        if not row:
            return JsonResponse({'success': False, 'message': 'File not found'}, status=404)

        file_name, file_content = row
        if not file_content:
            return JsonResponse({'success': False, 'message': 'File content is empty'}, status=404)

        decompressed_bytes = decompress_file_backend(file_content, file_name)

        # Convert VARBINARY bytes to base64
        base64_str = base64.b64encode(decompressed_bytes).decode('utf-8')
        mime_type, _ = mimetypes.guess_type(file_name)
        if not mime_type:
            mime_type = 'application/octet-stream'

        data_url = f"data:{mime_type};base64,{base64_str}"

        return JsonResponse({
            'success': True,
            'filename': file_name,
            'dataUrl': data_url
        })
    except Exception as e:
        log_error(f"view_center_feedback_file: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def archive_center_feedback_file(request):
    """
    POST endpoint to archive a center feedback file (setting is_archived = 1) and sync check state.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
        token = data.get('token', '')
        file_type = data.get('file_type', 'normal')
        checklist_id = data.get('checklist_id')
        center_id_raw = data.get('center_id')
    except Exception as e:
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    if not checklist_id or center_id_raw is None:
        return JsonResponse({'success': False, 'message': 'checklist_id and center_id are required'}, status=400)

    try:
        center_id = int(center_id_raw)
    except ValueError:
        return JsonResponse({'success': False, 'message': 'center_id must be a valid integer'}, status=400)

    try:
        with connection.cursor() as cursor:
            if file_type == 'normal':
                cursor.execute("""
                    UPDATE dbo.audit_center_normal_files
                    SET is_archived = 1, updated_at = GETDATE()
                    WHERE center_id = %s AND center_checklist_id = %s AND is_archived = 0
                """, [center_id, checklist_id])

                cursor.execute("""
                    UPDATE dbo.audit_center_checklist_feedback
                    SET normal_file_path = NULL, updated_at = GETDATE()
                    WHERE center_id = %s AND center_checklist_id = %s
                """, [center_id, checklist_id])
            elif file_type == 'confidential':
                cursor.execute("""
                    UPDATE dbo.audit_center_confidential_files
                    SET is_archived = 1, updated_at = GETDATE()
                    WHERE center_id = %s AND center_checklist_id = %s AND is_archived = 0
                """, [center_id, checklist_id])

                cursor.execute("""
                    UPDATE dbo.audit_center_checklist_feedback
                    SET is_confidential_file_present = 0, updated_at = GETDATE()
                    WHERE center_id = %s AND center_checklist_id = %s
                """, [center_id, checklist_id])
            else: # file_type == 'evidence'
                cursor.execute("""
                    UPDATE dbo.audit_center_evidence
                    SET is_archived = 1, updated_at = GETDATE()
                    WHERE center_id = %s AND center_checklist_id = %s AND is_archived = 0
                """, [center_id, checklist_id])

        return JsonResponse({
            'success': True,
            'message': 'File archived successfully'
        })
    except Exception as e:
        log_error(f"archive_center_feedback_file: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


