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
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("""
                EXEC [dbo].[usp_ManageBranchAudit]
                    @ReportType = 'assigned-audits',
                    @UserID = %s
            """, [user.UserID])
            
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

        audits = []
        for row in rows:
            audits.append(dict(zip(columns, row)))

        # Fetch selected centers for these audits
        audit_ids = [a['auditId'] for a in audits if a.get('auditId')]
        selected_centers_map = {}
        if audit_ids:
            with connection.cursor() as cursor_centers:
                placeholders = ', '.join(['%s'] * len(audit_ids))
                cursor_centers.execute(f"""
                    SELECT audit_id, center_id, center_name 
                    FROM dbo.audit_branch_selected_centers
                    WHERE audit_id IN ({placeholders})
                """, audit_ids)
                for center_row in cursor_centers.fetchall():
                    aid, cid, cname = center_row
                    if aid not in selected_centers_map:
                        selected_centers_map[aid] = []
                    selected_centers_map[aid].append({
                        'centerId': cid,
                        'centerName': cname
                    })

        for a in audits:
            a['selectedCenters'] = selected_centers_map.get(a['auditId'], [])

        # Calculate statistics
        total_assigned = len(audits)
        completed_count = sum(1 for a in audits if a['status'] == 'completed')
        in_progress_count = sum(1 for a in audits if a.get('isStarted') and a['status'] != 'completed')
        completion_pct = int(completed_count / total_assigned * 100) if total_assigned > 0 else 0
        stats = {
            "branchesThisMonth": completed_count,
            "branchesTarget": total_assigned,
            "completionPct": completion_pct,
            "inProgressCount": in_progress_count
        }
        return JsonResponse({
            'success': True,
            'audits': audits,
            'stats': stats
        })
    except Exception as e:
        log_error(f"get_assigned_audits: DB or processing error: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def start_branch_audit(request):
    """
    POST API endpoint to record audit progress starting in database.
    Expects JSON body:
    {
        "token": "...",
        "branch_id": 6944
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        branch_id = data.get('branch_id')
    except Exception as e:
        log_error(f"start_branch_audit: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    if not branch_id:
        return JsonResponse({'success': False, 'message': 'branch_id is required'}, status=400)

    try:
        with connection.cursor() as cursor:
            # 1. Look up plan details from audit_plan_current
            cursor.execute("""
                SELECT id, branch_id, start_date, end_date
                FROM dbo.audit_plan_current
                WHERE branch_id = %s OR id = %s
            """, [branch_id, branch_id])
            plan_row = cursor.fetchone()

            if not plan_row:
                return JsonResponse({'success': False, 'message': 'Matching audit plan not found for this branch'}, status=404)

            audit_id, plan_branch_id, start_date, end_date = plan_row

            # 2. Upsert into audit_branch_progress
            cursor.execute("SELECT 1 FROM dbo.audit_branch_progress WHERE audit_id = %s", [audit_id])
            exists = cursor.fetchone()

            if exists:
                cursor.execute("""
                    UPDATE dbo.audit_branch_progress
                    SET audit_status = 'in-progress',
                        audit_assigned_to = %s
                    WHERE audit_id = %s
                """, [user.UserID, audit_id])
            else:
                cursor.execute("""
                    INSERT INTO dbo.audit_branch_progress (
                        audit_id, audit_branch_id, audit_start_date, audit_end_date, audit_status, audit_assigned_to
                    ) VALUES (%s, %s, %s, NULL, 'in-progress', %s)
                """, [audit_id, plan_branch_id, start_date, user.UserID])

        return JsonResponse({
            'success': True,
            'message': 'Audit progress started successfully',
            'audit_id': audit_id
        })
    except Exception as e:
        log_error(f"start_branch_audit: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def end_branch_audit(request):
    """
    POST API to mark an audit as completed.
    Sets audit_end_date = today, audit_status = 'submitted' in audit_branch_progress,
    then calls usp_PopulateAuditChecklistScores to calculate all scores.
    Expects JSON body: { "token": "...", "audit_id": 71 }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        audit_id = data.get('audit_id')
    except Exception as e:
        log_error(f"end_branch_audit: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    if not audit_id:
        return JsonResponse({'success': False, 'message': 'audit_id is required'}, status=400)

    try:
        with connection.cursor() as cursor:
            # 1. Verify the audit belongs to this user
            cursor.execute("""
                SELECT audit_id FROM dbo.audit_branch_progress
                WHERE audit_id = %s AND audit_assigned_to = %s
            """, [audit_id, user.UserID])
            progress_row = cursor.fetchone()

            if not progress_row:
                return JsonResponse({'success': False, 'message': 'Audit progress record not found for this user'}, status=404)

            # 2. Set audit_end_date to today and mark status as submitted
            cursor.execute("""
                UPDATE dbo.audit_branch_progress
                SET audit_end_date = CAST(GETDATE() AS DATE),
                    audit_status = 'submitted'
                WHERE audit_id = %s AND audit_assigned_to = %s
            """, [audit_id, user.UserID])

            # 3. Run score population stored procedure
            score_error = None
            try:
                cursor.execute("""
                    SELECT MAX(audit_end_date) FROM dbo.audit_branch_progress 
                    WHERE audit_id = %s
                """, [audit_id])
                row = cursor.fetchone()
                as_on_date = row[0] if row and row[0] else None

                cursor.execute("EXEC dbo.usp_PopulateAuditChecklistScores @AsOnDate = %s", [as_on_date])
            except Exception as sp_err:
                log_error(f"end_branch_audit: usp_PopulateAuditChecklistScores failed: {str(sp_err)}")
                score_error = str(sp_err)

        if score_error:
            return JsonResponse({
                'success': True,
                'message': 'Audit ended successfully but score calculation had an error.',
                'audit_id': audit_id,
                'score_error': score_error
            })

        return JsonResponse({
            'success': True,
            'message': 'Audit ended successfully. Scores have been calculated.',
            'audit_id': audit_id
        })
    except Exception as e:
        log_error(f"end_branch_audit: failed: {str(e)}")
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
        branch_id = str(data.get('branch_id', '')).strip()
        audit_id = data.get('audit_id')
    except Exception as e:
        log_error(f"get_audit_feedback: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    if not branch_id:
        return JsonResponse({'success': False, 'message': 'branch_id is required'}, status=400)

    # Ensure branch_id is numeric if name was passed
    if branch_id:
        from planner.models import AuditPlanCurrent
        try:
            int(branch_id)
        except ValueError:
            plan_obj = AuditPlanCurrent.objects.filter(branch=branch_id).first()
            if plan_obj and plan_obj.branch_id:
                branch_id = str(plan_obj.branch_id)

    try:
        # Resolve audit_id if not explicitly provided
        if not audit_id:
            from django.db.models import Q
            from planner.models import AuditPlanCurrent
            user_id_str = str(user.UserID) if user.UserID is not None else ""
            user_code = user.UserCode or ""
            
            plan = None
            try:
                val_int = int(branch_id)
                plan = AuditPlanCurrent.objects.filter(
                    Q(branch_id=val_int) & (Q(assigned_auditor=user_id_str) | Q(assigned_auditor=user_code))
                ).first()
            except ValueError:
                pass
                
            if not plan:
                plan = AuditPlanCurrent.objects.filter(
                    Q(branch=branch_id) & (Q(assigned_auditor=user_id_str) | Q(assigned_auditor=user_code))
                ).first()
                
            if plan:
                audit_id = plan.id

        with connection.cursor() as cursor:
            cursor.execute("""
                EXEC [dbo].[usp_ManageBranchAudit]
                    @ReportType = 'feedback',
                    @BranchID = %s,
                    @AuditID = %s
            """, [branch_id, audit_id])
            
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
    # pyrefly: ignore [missing-import]
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
        # pyrefly: ignore [missing-import]
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
    # pyrefly: ignore [missing-import]
    from PIL import Image
    try:
        # pyrefly: ignore [missing-import]
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
        branch_id = str(data.get('branch_id', '')).strip()
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

    # Ensure branch_id is numeric if name was passed
    if branch_id:
        from planner.models import AuditPlanCurrent
        try:
            int(branch_id)
        except ValueError:
            plan_obj = None
            if audit_id and audit_id != 0:
                plan_obj = AuditPlanCurrent.objects.filter(id=audit_id).first()
            if not plan_obj:
                plan_obj = AuditPlanCurrent.objects.filter(branch=branch_id).first()
            if plan_obj and plan_obj.branch_id:
                branch_id = str(plan_obj.branch_id)

    # Resolve audit_id if not explicitly provided
    if not audit_id:
        from django.db.models import Q
        from planner.models import AuditPlanCurrent
        user_id_str = str(user.UserID) if user.UserID is not None else ""
        user_code = user.UserCode or ""
        
        plan = None
        try:
            val_int = int(branch_id)
            plan = AuditPlanCurrent.objects.filter(
                Q(branch_id=val_int) & (Q(assigned_auditor=user_id_str) | Q(assigned_auditor=user_code))
            ).first()
        except ValueError:
            pass
            
        if not plan:
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
                        FROM dbo.audit_branch_checklist_feedback 
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
                            UPDATE dbo.audit_branch_checklist_feedback
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
                            INSERT INTO dbo.audit_branch_checklist_feedback (
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
                            UPDATE dbo.audit_branch_normal_files
                            SET is_archived = 1, updated_at = GETDATE()
                            WHERE branch_id = %s AND checklist_id = %s AND is_archived = 0
                        """, [branch_id, checklist_id])
                        
                        # Insert new normal file
                        cursor.execute("""
                            INSERT INTO dbo.audit_branch_normal_files (
                                feedback_id, branch_id, checklist_id, file_name, file_content, is_archived, uploaded_by, created_at, updated_at
                            ) VALUES (%s, %s, %s, %s, %s, 0, %s, GETDATE(), GETDATE())
                        """, [fb_id, branch_id, checklist_id, normal_file_name, normal_file_bytes, user.UserID])
                        cursor.execute("SELECT @@IDENTITY")
                        new_normal_file_id = int(cursor.fetchone()[0])

                    # Process confidential remark
                    if confidential_remark is not None:
                        cursor.execute("""
                            SELECT id FROM dbo.audit_branch_confidential_remarks
                            WHERE branch_id = %s AND checklist_id = %s
                        """, [branch_id, checklist_id])
                        cr_row = cursor.fetchone()
                        if cr_row:
                            cursor.execute("""
                                UPDATE dbo.audit_branch_confidential_remarks
                                SET confidential_remark = %s,
                                    user_id = %s,
                                    updated_at = GETDATE()
                                WHERE id = %s
                            """, [confidential_remark, user.UserID, cr_row[0]])
                        else:
                            cursor.execute("""
                                INSERT INTO dbo.audit_branch_confidential_remarks (
                                    feedback_id, branch_id, checklist_id, confidential_remark, user_id, created_at, updated_at
                                ) VALUES (%s, %s, %s, %s, %s, GETDATE(), GETDATE())
                            """, [fb_id, branch_id, checklist_id, confidential_remark, user.UserID])

                    # Store confidential file as binary in database
                    new_confidential_file_id = None
                    if has_new_confidential_file:
                        # Archive previous confidential file
                        cursor.execute("""
                            UPDATE dbo.audit_branch_confidential_files
                            SET is_archived = 1, updated_at = GETDATE()
                            WHERE branch_id = %s AND checklist_id = %s AND is_archived = 0
                        """, [branch_id, checklist_id])
                        
                        # Insert new confidential file
                        cursor.execute("""
                            INSERT INTO dbo.audit_branch_confidential_files (
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
            cursor.execute("""
                EXEC [dbo].[usp_ManageBranchAudit]
                    @ReportType = 'view-file',
                    @FileType = %s,
                    @FileID = %s
            """, [file_type, file_id])
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
        branch_id = str(data.get('branch_id', '')).strip()
    except Exception as e:
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    if not checklist_id or not branch_id:
        return JsonResponse({'success': False, 'message': 'checklist_id and branch_id are required'}, status=400)

    # Ensure branch_id is numeric if name was passed
    if branch_id:
        from planner.models import AuditPlanCurrent
        try:
            int(branch_id)
        except ValueError:
            plan_obj = AuditPlanCurrent.objects.filter(branch=branch_id).first()
            if plan_obj and plan_obj.branch_id:
                branch_id = str(plan_obj.branch_id)

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                EXEC [dbo].[usp_ManageBranchAudit]
                    @ReportType = 'archive-file',
                    @FileType = %s,
                    @BranchID = %s,
                    @ChecklistID = %s
            """, [file_type, branch_id, checklist_id])
            
            # Fetch output from execution to complete execution correctly
            if cursor.description:
                cursor.fetchall()

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
                ev.image_text as evidence_text,
                f.branchid
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
                "branchId": row_dict.get("branchid"),
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
        branch_id = data.get('branch_id') or data.get('branchid')
        if branch_id is not None:
            branch_id = str(branch_id).strip()
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

    # Resolve branch_id if not explicitly provided
    if not branch_id:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT TOP 1 BRANCHID 
                FROM CenterRiskScore 
                WHERE CenterID = %s OR CenterID = %s
            """, [str(center_id), center_id])
            row = cursor.fetchone()
            if row:
                branch_id = row[0]

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
                                branchid = %s,
                                updated_at = GETDATE()
                            WHERE id = %s
                        """, [answer, normal_remark, final_normal_file_path, is_confidential_remark_present, is_confidential_file_present, status_to, user.UserID, audit_id, branch_id, fb_id])
                    else:
                        # Insert main feedback table
                        cursor.execute("""
                            INSERT INTO dbo.audit_center_checklist_feedback (
                                audit_id, center_id, auditor_id, center_checklist_id, parameter_code, parameter_name,
                                answer, normal_remark, normal_file_path,
                                is_confidential_remark_present, is_confidential_file_present, status, last_modified_by,
                                branchid, created_at, updated_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, GETDATE(), GETDATE())
                        """, [
                            audit_id, center_id, user.UserID, checklist_id, parameter_code, parameter_name,
                            answer, normal_remark, normal_file_name,
                            is_confidential_remark_present, is_confidential_file_present, status_to, user.UserID,
                            branch_id
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


# ============================================================
# CLIENT AUDIT FEEDBACK ENDPOINTS
# ============================================================

@csrf_exempt
def get_client_audit_feedback(request):
    """
    POST API endpoint to retrieve saved checklist feedback for a client (customer).
    Expects plain JSON body:
    {
        "token": "...",
        "client_id": "CUST001",
        "center_id": 456,
        "audit_id": 123   -- optional
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        client_id = data.get('client_id', '')
        center_id_raw = data.get('center_id')
        audit_id = data.get('audit_id')
    except Exception as e:
        log_error(f"get_client_audit_feedback: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    if not client_id:
        return JsonResponse({'success': False, 'message': 'client_id is required'}, status=400)

    try:
        center_id = int(center_id_raw) if center_id_raw is not None else None
    except (ValueError, TypeError):
        center_id = None

    try:
        query = """
            SELECT
                id, audit_id, branch_id, center_id,
                client_id, client_name, auditor_id,
                client_checklist_id, parameter_code, parameter_name,
                answer, remarks, status,
                created_at, updated_at
            FROM dbo.audit_client_checklist_feedback
            WHERE client_id = %s
        """
        params = [client_id]

        if audit_id:
            query += " AND audit_id = %s"
            params.append(audit_id)
        elif center_id is not None:
            query += " AND center_id = %s"
            params.append(center_id)

        query += " ORDER BY client_checklist_id ASC"

        with connection.cursor() as cursor:
            cursor.execute(query, params)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

        feedback_list = []
        feedback_audit_id = audit_id
        for row in rows:
            row_dict = dict(zip(columns, row))
            if row_dict.get('audit_id') and not feedback_audit_id:
                feedback_audit_id = row_dict.get('audit_id')
            for key, val in row_dict.items():
                if isinstance(val, decimal.Decimal):
                    row_dict[key] = float(val)
                elif hasattr(val, 'isoformat'):
                    row_dict[key] = val.isoformat()

            feedback_list.append({
                'checklistId': row_dict.get('client_checklist_id'),
                'answer': row_dict.get('answer'),
                'remarks': row_dict.get('remarks'),
                'status': row_dict.get('status'),
            })

        return JsonResponse({
            'success': True,
            'feedback': feedback_list,
            'auditId': feedback_audit_id
        })
    except Exception as e:
        log_error(f"get_client_audit_feedback: DB error: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def save_client_audit_feedback(request):
    """
    POST API endpoint to save or submit checklist feedback for a client (customer).
    Expects plain JSON body:
    {
        "token": "...",
        "audit_id": 123,
        "branch_id": "BRANCH_NAME",
        "center_id": 456,
        "client_id": "CUST001",
        "client_name": "Ramabai Sharma",
        "action": "SUBMITTED",   -- or "DRAFT_SAVED"
        "feedback_items": [
            {
                "client_checklist_id": 1,
                "parameter_code": "CLT_001",
                "parameter_name": "House Verification...",
                "answer": "Yes",
                "remarks": "Verified at address"
            }
        ]
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        audit_id = data.get('audit_id')
        branch_id = data.get('branch_id', '')
        center_id_raw = data.get('center_id')
        client_id = data.get('client_id', '')
        client_name = data.get('client_name', '')
        action = data.get('action', 'DRAFT_SAVED')
        feedback_items = data.get('feedback_items', [])

        print(branch_id, "this is the branch id")
    except Exception as e:
        log_error(f"save_client_audit_feedback: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    if not client_id:
        return JsonResponse({'success': False, 'message': 'client_id is required'}, status=400)

    try:
        center_id = int(center_id_raw) if center_id_raw is not None else None
    except (ValueError, TypeError):
        center_id = None

    # Determine status
    status_to = 'pending'
    if action == 'SUBMITTED':
        status_to = 'submitted'
    elif action == 'DRAFT_SAVED':
        status_to = 'pending'

    from django.db import transaction
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                for item in feedback_items:
                    checklist_id = item.get('client_checklist_id')
                    parameter_code = item.get('parameter_code', '')
                    parameter_name = item.get('parameter_name', '')
                    answer = item.get('answer', 'N/A')
                    remarks = item.get('remarks', '')

                    # Check if record already exists
                    if audit_id is not None:
                        cursor.execute("""
                            SELECT id
                            FROM dbo.audit_client_checklist_feedback
                            WHERE client_id = %s AND client_checklist_id = %s AND audit_id = %s
                        """, [client_id, checklist_id, audit_id])
                    else:
                        cursor.execute("""
                            SELECT id
                            FROM dbo.audit_client_checklist_feedback
                            WHERE client_id = %s AND client_checklist_id = %s AND audit_id IS NULL
                        """, [client_id, checklist_id])
                    existing = cursor.fetchone()

                    if existing:
                        cursor.execute("""
                            UPDATE dbo.audit_client_checklist_feedback
                            SET answer = %s,
                                remarks = %s,
                                status = %s,
                                audit_id = %s,
                                branch_id = %s,
                                center_id = %s,
                                client_name = %s,
                                last_modified_by = %s,
                                updated_at = GETDATE()
                            WHERE id = %s
                        """, [
                            answer, remarks, status_to,
                            audit_id, branch_id, center_id,
                            client_name, user.UserID, existing[0]
                        ])
                    else:
                        cursor.execute("""
                            INSERT INTO dbo.audit_client_checklist_feedback (
                                audit_id, branch_id, center_id,
                                client_id, client_name, auditor_id,
                                client_checklist_id, parameter_code, parameter_name,
                                answer, remarks, status, last_modified_by,
                                created_at, updated_at
                            ) VALUES (
                                %s, %s, %s,
                                %s, %s, %s,
                                %s, %s, %s,
                                %s, %s, %s, %s,
                                GETDATE(), GETDATE()
                            )
                        """, [
                            audit_id, branch_id, center_id,
                            client_id, client_name, user.UserID,
                            checklist_id, parameter_code, parameter_name,
                            answer, remarks, status_to, user.UserID
                        ])

        log_info(f"save_client_audit_feedback: saved {len(feedback_items)} items for client {client_id} by {user.UserCode}")
        return JsonResponse({
            'success': True,
            'message': f'Client checklist feedback {action.lower()} successfully'
        })
    except Exception as e:
        log_error(f"save_client_audit_feedback: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_auditor_caps(request):
    """
    POST API to fetch all Corrective Action Points (CAPs) for the logged-in auditor.
    CAPs = all 'Yes' answers from branch, center, and client checklist feedback for a given month.
    Expects JSON body:
    {
        "token": "...",
        "month_start_date": "2026-06-01"   (optional, defaults to current month)
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        month_start_date = data.get('month_start_date', None)
        report_type = data.get('report_type', 'CAP')
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Invalid request: {str(e)}'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    try:
        with connection.cursor() as cursor:
            if month_start_date:
                cursor.execute("""
                    EXEC dbo.usp_ManageAuditCAPs
                        @ReportType = %s,
                        @UserID = %s,
                        @MonthStartDate = %s
                """, [report_type, user.UserID, month_start_date])
            else:
                cursor.execute("""
                    EXEC dbo.usp_ManageAuditCAPs
                        @ReportType = %s,
                        @UserID = %s
                """, [report_type, user.UserID])

            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

        caps = []
        import decimal
        for row in rows:
            cap = dict(zip(columns, row))
            for k, v in cap.items():
                if isinstance(v, decimal.Decimal):
                    cap[k] = float(v)
                elif hasattr(v, 'isoformat'):
                    cap[k] = v.isoformat()
            caps.append(cap)

        return JsonResponse({
            'success': True,
            'caps': caps,
            'total_caps': len(caps)
        })
    except Exception as e:
        log_error(f"get_auditor_caps failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_completed_audits(request):
    """
    POST API to fetch all completed audits for the logged-in auditor.
    An audit is completed if audit_end_date is not null.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Invalid request: {str(e)}'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    try:
        with connection.cursor() as cursor:
            # Query completed audits assigned to user, including subordinates if division/zonal head
            query = """
                SET NOCOUNT ON;
                DROP TABLE IF EXISTS #UserList;
                CREATE TABLE #UserList
                (
                    UserID   VARCHAR(255),
                    UserName NVARCHAR(255)
                );

                INSERT INTO #UserList (UserID, UserName)
                SELECT DISTINCT CAST(fa_userid AS VARCHAR(255)), fa_username
                FROM dbo.VW_Branch_To_GeographicalHierarchy_head_audit
                WHERE (division_head_userid = %s OR zonal_userid = %s)
                  AND fa_userid IS NOT NULL;
         
                INSERT INTO #UserList (UserID, UserName)
                SELECT CAST(%s AS VARCHAR(255)), amt.UserName
                FROM dbo.accounts_mst_usertbl amt
                WHERE amt.UserID = %s
                  AND NOT EXISTS (SELECT 1 FROM #UserList WHERE UserID = CAST(%s AS VARCHAR(255)));

                SELECT 
                    p.audit_id, 
                    p.audit_branch_id, 
                    p.audit_start_date, 
                    p.audit_end_date, 
                    p.audit_status, 
                    b.Branch,
                    b.Zone,
                    b.Division,
                    b.Region,
                    b.Hub
                FROM dbo.audit_branch_progress p
                LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON p.audit_branch_id = b.BranchID
                WHERE p.audit_assigned_to IN (SELECT UserID FROM #UserList)
                  AND p.audit_end_date IS NOT NULL
                ORDER BY p.audit_end_date DESC;
            """
            cursor.execute(query, [user.UserID, user.UserID, user.UserID, user.UserID, user.UserID])
            rows = cursor.fetchall()

            completed_list = []
            for row in rows:
                audit_id = row[0]
                branch_id = row[1]
                start_date = row[2]
                end_date = row[3]
                status = row[4]
                branch_name = row[5] or f"Branch {branch_id}"
                zone = row[6]
                division = row[7]
                region = row[8]
                hub = row[9]

                # Fetch final summary for scores
                cursor.execute("""
                    SELECT total_max_score, total_score_obtained, final_score_pct
                    FROM dbo.audit_branch_final_summary
                    WHERE audit_id = %s
                """, [audit_id])
                sum_row = cursor.fetchone()

                total_max = 0
                total_obtained = 0
                score_pct = 0.0

                if sum_row:
                    total_max = float(sum_row[0]) if sum_row[0] is not None else 0.0
                    total_obtained = float(sum_row[1]) if sum_row[1] is not None else 0.0
                    score_pct = float(sum_row[2]) if sum_row[2] is not None else 0.0

                # Compute Grade
                if score_pct > 80.0:
                    grade = 'A'
                elif score_pct >= 60.0:
                    grade = 'B'
                elif score_pct >= 40.0:
                    grade = 'C'
                else:
                    grade = 'D'

                completed_list.append({
                    'audit_id': audit_id,
                    'branch_id': branch_id,
                    'branch_name': branch_name,
                    'start_date': start_date.strftime('%Y-%m-%d') if start_date else None,
                    'end_date': end_date.strftime('%Y-%m-%d') if end_date else None,
                    'status': status,
                    'zone': zone,
                    'division': division,
                    'region': region,
                    'hub': hub,
                    'total_max_score': total_max,
                    'total_score_obtained': total_obtained,
                    'score_pct': round(score_pct, 2),
                    'grade': grade
                })

        return JsonResponse({'success': True, 'audits': completed_list})
    except Exception as e:
        log_error(f"get_completed_audits failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_branch_report_details(request):
    """
    POST API to fetch detailed report data for a completed branch audit.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        audit_id = data.get('audit_id')
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Invalid request: {str(e)}'}, status=400)

    if not audit_id:
        return JsonResponse({'success': False, 'message': 'audit_id is required'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    try:
        with connection.cursor() as cursor:
            # 1. Fetch audit metadata & branch geo
            cursor.execute("""
                SELECT 
                    p.audit_id, 
                    p.audit_branch_id, 
                    p.audit_start_date, 
                    p.audit_end_date, 
                    p.audit_status, 
                    b.Branch, b.Zone, b.Division, b.Region, b.Hub,
                    u.UserName
                FROM dbo.audit_branch_progress p
                LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON p.audit_branch_id = b.BranchID
                LEFT JOIN dbo.accounts_mst_usertbl u ON p.audit_assigned_to = u.UserID
                WHERE p.audit_id = %s
            """, [audit_id])
            meta_row = cursor.fetchone()

            if not meta_row:
                return JsonResponse({'success': False, 'message': 'Audit progress record not found'}, status=404)

            audit_meta = {
                'audit_id': meta_row[0],
                'branch_id': meta_row[1],
                'start_date': meta_row[2].strftime('%Y-%m-%d') if meta_row[2] else None,
                'end_date': meta_row[3].strftime('%Y-%m-%d') if meta_row[3] else None,
                'status': meta_row[4],
                'branch_name': meta_row[5],
                'zone': meta_row[6],
                'division': meta_row[7],
                'region': meta_row[8],
                'hub': meta_row[9],
                'auditor_name': meta_row[10]
            }

            # 2. Fetch final summary scores
            cursor.execute("""
                SELECT 
                    branch_max_score_final, branch_score_obtained,
                    center_count, center_max_score_final, center_score_obtained,
                    client_count, client_max_score_final, client_score_obtained,
                    total_max_score, total_score_obtained, final_score_pct
                FROM dbo.audit_branch_final_summary
                WHERE audit_id = %s
            """, [audit_id])
            summary_row = cursor.fetchone()

            scores = {}
            if summary_row:
                scores = {
                    'branch_max_score_final': float(summary_row[0]) if summary_row[0] is not None else 0.0,
                    'branch_score_obtained': float(summary_row[1]) if summary_row[1] is not None else 0.0,
                    'center_count': int(summary_row[2]) if summary_row[2] is not None else 0,
                    'center_max_score_final': float(summary_row[3]) if summary_row[3] is not None else 0.0,
                    'center_score_obtained': float(summary_row[4]) if summary_row[4] is not None else 0.0,
                    'client_count': int(summary_row[5]) if summary_row[5] is not None else 0,
                    'client_max_score_final': float(summary_row[6]) if summary_row[6] is not None else 0.0,
                    'client_score_obtained': float(summary_row[7]) if summary_row[7] is not None else 0.0,
                    'total_max_score': float(summary_row[8]) if summary_row[8] is not None else 0.0,
                    'total_score_obtained': float(summary_row[9]) if summary_row[9] is not None else 0.0,
                    'final_score_pct': float(summary_row[10]) if summary_row[10] is not None else 0.0,
                }
                pct = scores['final_score_pct']
                if pct > 80.0:
                    scores['grade'] = 'A'
                elif pct >= 60.0:
                    scores['grade'] = 'B'
                elif pct >= 40.0:
                    scores['grade'] = 'C'
                else:
                    scores['grade'] = 'D'
            else:
                scores = {
                    'branch_max_score_final': 0.0, 'branch_score_obtained': 0.0,
                    'center_count': 0, 'center_max_score_final': 0.0, 'center_score_obtained': 0.0,
                    'client_count': 0, 'client_max_score_final': 0.0, 'client_score_obtained': 0.0,
                    'total_max_score': 0.0, 'total_score_obtained': 0.0, 'final_score_pct': 0.0,
                    'grade': 'N/A'
                }

            # 3. Fetch branch checklist scores (with auditor remark)
            cursor.execute("""
                SELECT
                    s.section_code, s.section_name, s.intent_code, s.intent_title,
                    s.answer, s.max_score, s.score_obtained, s.feedback_id,
                    f.normal_remark AS auditor_remark
                FROM dbo.audit_branch_checklist_score s
                LEFT JOIN dbo.audit_branch_checklist_feedback f
                    ON f.audit_id = s.audit_id AND f.checklist_id = s.checklist_id
                WHERE s.audit_id = %s
                ORDER BY s.section_code, s.intent_code
            """, [audit_id])
            branch_cols = [d[0] for d in cursor.description]
            branch_scores = [dict(zip(branch_cols, r)) for r in cursor.fetchall()]

            # Fetch ALL reviewer remarks for branch from review log (one feedback_id can have many entries)
            cursor.execute("""
                SELECT feedback_id, cycle_id, decision, review_remark, decided_at
                FROM dbo.audit_branch_checklist_review_log
                WHERE audit_id = %s AND review_remark IS NOT NULL AND LTRIM(RTRIM(review_remark)) <> ''
                ORDER BY feedback_id, log_id
            """, [audit_id])
            branch_review_log_rows = cursor.fetchall()
            branch_review_map = {}
            for row in branch_review_log_rows:
                fid = row[0]
                if fid not in branch_review_map:
                    branch_review_map[fid] = []
                branch_review_map[fid].append({
                    'cycle_id': row[1],
                    'decision': row[2],
                    'remark': row[3],
                    'decided_at': row[4].isoformat() if hasattr(row[4], 'isoformat') else str(row[4]) if row[4] else None
                })

            # Attach reviewer_remarks list to each branch score item
            for item in branch_scores:
                fid = item.pop('feedback_id', None)
                item['reviewer_remarks'] = branch_review_map.get(fid, [])

            # 4. Fetch center checklist scores (with auditor remark)
            cursor.execute("""
                SELECT
                    s.center_id, s.parameter_code, s.parameter_name,
                    s.answer, s.max_score, s.score_obtained, s.feedback_id,
                    f.normal_remark AS auditor_remark
                FROM dbo.audit_center_checklist_score s
                LEFT JOIN dbo.audit_center_checklist_feedback f
                    ON f.audit_id = s.audit_id AND f.center_checklist_id = s.center_checklist_id AND f.center_id = s.center_id
                WHERE s.audit_id = %s
                ORDER BY s.center_id, s.parameter_code
            """, [audit_id])
            center_cols = [d[0] for d in cursor.description]
            center_scores = [dict(zip(center_cols, r)) for r in cursor.fetchall()]

            # Fetch ALL reviewer remarks for center from review log
            try:
                cursor.execute("""
                    SELECT feedback_id, cycle_id, decision, review_remark, decided_at
                    FROM dbo.audit_center_checklist_review_log
                    WHERE audit_id = %s AND review_remark IS NOT NULL AND LTRIM(RTRIM(review_remark)) <> ''
                    ORDER BY feedback_id, log_id
                """, [audit_id])
                center_review_log_rows = cursor.fetchall()
                center_review_map = {}
                for row in center_review_log_rows:
                    fid = row[0]
                    if fid not in center_review_map:
                        center_review_map[fid] = []
                    center_review_map[fid].append({
                        'cycle_id': row[1], 'decision': row[2], 'remark': row[3],
                        'decided_at': row[4].isoformat() if hasattr(row[4], 'isoformat') else str(row[4]) if row[4] else None
                    })
            except Exception:
                center_review_map = {}

            for item in center_scores:
                fid = item.pop('feedback_id', None)
                item['reviewer_remarks'] = center_review_map.get(fid, [])

            # 5. Fetch client checklist scores (with auditor remark)
            cursor.execute("""
                SELECT
                    s.center_id, s.client_id, s.client_name,
                    s.parameter_code, s.parameter_name,
                    s.answer, s.max_score, s.score_obtained, s.feedback_id,
                    f.remarks AS auditor_remark
                FROM dbo.audit_client_checklist_score s
                LEFT JOIN dbo.audit_client_checklist_feedback f
                    ON f.audit_id = s.audit_id AND f.client_checklist_id = s.client_checklist_id AND f.client_id = s.client_id
                WHERE s.audit_id = %s
                ORDER BY s.center_id, s.client_id, s.parameter_code
            """, [audit_id])
            client_cols = [d[0] for d in cursor.description]
            client_scores = [dict(zip(client_cols, r)) for r in cursor.fetchall()]

            # Fetch ALL reviewer remarks for client from review log
            try:
                cursor.execute("""
                    SELECT feedback_id, cycle_id, decision, review_remark, decided_at
                    FROM dbo.audit_client_checklist_review_log
                    WHERE audit_id = %s AND review_remark IS NOT NULL AND LTRIM(RTRIM(review_remark)) <> ''
                    ORDER BY feedback_id, log_id
                """, [audit_id])
                client_review_log_rows = cursor.fetchall()
                client_review_map = {}
                for row in client_review_log_rows:
                    fid = row[0]
                    if fid not in client_review_map:
                        client_review_map[fid] = []
                    client_review_map[fid].append({
                        'cycle_id': row[1], 'decision': row[2], 'remark': row[3],
                        'decided_at': row[4].isoformat() if hasattr(row[4], 'isoformat') else str(row[4]) if row[4] else None
                    })
            except Exception:
                client_review_map = {}

            for item in client_scores:
                fid = item.pop('feedback_id', None)
                item['reviewer_remarks'] = client_review_map.get(fid, [])

        return JsonResponse({
            'success': True,
            'metadata': audit_meta,
            'scores': scores,
            'branch_details': branch_scores,
            'center_details': center_scores,
            'client_details': client_scores
        })
    except Exception as e:
        log_error(f"get_branch_report_details failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)

@csrf_exempt
def get_auditor_dashboard(request):
    """
    POST API endpoint to retrieve the auditor dashboard data.
    Calls `Sp_auditor_dashboard` with `@UserID`.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        log_error(f"get_auditor_dashboard: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)
    
    user_id = str(user.UserID)

    try:
        with connection.cursor() as cursor:
            # 1. My Audits
            cursor.execute("EXEC [dbo].[Sp_auditor_dashboard] @UserID = %s", [user_id])
            
            audits_columns = [col[0] for col in cursor.description]
            audits_rows = cursor.fetchall()
            audits = [dict(zip(audits_columns, row)) for row in audits_rows]

            # 2. Today's Plan
            cursor.nextset()
            todays_plan_columns = [col[0] for col in cursor.description]
            todays_plan_rows = cursor.fetchall()
            todays_plan = [dict(zip(todays_plan_columns, row)) for row in todays_plan_rows]

            # 3. CAPs
            cursor.nextset()
            caps_columns = [col[0] for col in cursor.description]
            caps_rows = cursor.fetchall()
            caps = [dict(zip(caps_columns, row)) for row in caps_rows]

        return JsonResponse({
            'success': True,
            'audits': audits,
            'todaysPlan': todays_plan,
            'caps': caps
        })
    except Exception as e:
        log_error(f"get_auditor_dashboard: SP execution error: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def save_selected_centers(request):
    """
    POST API to save selected centers for a specific audit.
    Expects JSON body:
    {
        "token": "...",
        "audit_id": 71,
        "branch_id": 248,
        "centers": [
            { "center_id": "C01", "center_name": "Center A" },
            ...
        ]
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        audit_id = data.get('audit_id')
        branch_id = data.get('branch_id')
        centers = data.get('centers', [])
    except Exception as e:
        log_error(f"save_selected_centers: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    if not audit_id or not branch_id:
        return JsonResponse({'success': False, 'message': 'audit_id and branch_id are required'}, status=400)

    try:
        # Convert centers list to JSON string
        centers_json = json.dumps(centers)

        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("""
                EXEC dbo.usp_ManageAuditorPlans
                    @Action = 'SAVE',
                    @AuditID = %s,
                    @BranchID = %s,
                    @CenterIDsJson = %s
            """, [audit_id, branch_id, centers_json])
            
            row = cursor.fetchone()
            success = row[0] if row else 0
            message = row[1] if row and len(row) > 1 else 'Centers saved'

        return JsonResponse({'success': bool(success), 'message': message})
    except Exception as e:
        log_error(f"save_selected_centers failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_selected_centers(request):
    """
    POST API to fetch selected centers for a specific audit.
    Expects JSON body:
    {
        "token": "...",
        "audit_id": 71
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        audit_id = data.get('audit_id')
    except Exception as e:
        log_error(f"get_selected_centers: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    if not audit_id:
        return JsonResponse({'success': False, 'message': 'audit_id is required'}, status=400)

    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("""
                EXEC dbo.usp_ManageAuditorPlans
                    @Action = 'GET',
                    @AuditID = %s
            """, [audit_id])
            
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

        selected_centers = []
        for row in rows:
            selected_centers.append(dict(zip(columns, row)))

        return JsonResponse({'success': True, 'centers': selected_centers})
    except Exception as e:
        log_error(f"get_selected_centers failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_auditor_plans(request):
    """
    POST API to retrieve all branches and their selected centers for the logged-in auditor.
    Expects JSON body:
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
        log_error(f"get_auditor_plans: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)

    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("""
                EXEC dbo.usp_ManageAuditorPlans
                    @Action = 'GET_ALL',
                    @UserID = %s
            """, [user.UserID])
            
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

        # Build list of centers and group by branch/audit in Python
        plans_map = {}
        for row in rows:
            row_dict = dict(zip(columns, row))
            audit_id = row_dict.get('auditId')
            
            if audit_id not in plans_map:
                plans_map[audit_id] = {
                    'auditId': audit_id,
                    'branchId': row_dict.get('branchId'),
                    'branchName': row_dict.get('branchName'),
                    'division': row_dict.get('division'),
                    'startDate': row_dict.get('startDate'),
                    'endDate': row_dict.get('endDate'),
                    'auditStatus': row_dict.get('auditStatus'),
                    'selectedCenters': []
                }
            
            center_id = row_dict.get('centerId')
            if center_id:
                plans_map[audit_id]['selectedCenters'].append({
                    'centerId': center_id,
                    'centerName': row_dict.get('centerName'),
                    'selectedAt': row_dict.get('selectedAt').isoformat() if hasattr(row_dict.get('selectedAt'), 'isoformat') else row_dict.get('selectedAt')
                })

        plans_list = list(plans_map.values())

        return JsonResponse({'success': True, 'plans': plans_list})
    except Exception as e:
        log_error(f"get_auditor_plans failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


# ============================================================
# AUDIT REVIEW WORKFLOW ENDPOINTS
# ============================================================

@csrf_exempt
def submit_for_review(request):
    """
    POST /audit/workflow/submit-for-review/
    Auditor submits the completed audit for division head review.
    Also calculates scores (like end_branch_audit) before calling the review SP.

    Expects JSON body:
    {
        "token": "...",
        "audit_id": 71,
        "branch_id": 248
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        audit_id = data.get('audit_id')
        branch_id = data.get('branch_id')
    except Exception as e:
        log_error(f"submit_for_review: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    if not audit_id or not branch_id:
        return JsonResponse({'success': False, 'message': 'audit_id and branch_id are required'}, status=400)

    try:
        with connection.cursor() as cursor:
            # Step 1: Set audit_end_date if not set, update status to in-progress momentarily
            # (scores calculation requires audit_end_date to be set)
            cursor.execute("""
                UPDATE dbo.audit_branch_progress
                SET audit_end_date = ISNULL(audit_end_date, CAST(GETDATE() AS DATE))
                WHERE audit_id = %s AND audit_branch_id = %s AND audit_assigned_to = %s
            """, [audit_id, branch_id, user.UserID])

            # Step 2: Run score population stored procedure
            try:
                cursor.execute("""
                    SELECT MAX(audit_end_date) FROM dbo.audit_branch_progress 
                    WHERE audit_id = %s AND audit_branch_id = %s
                """, [audit_id, branch_id])
                row = cursor.fetchone()
                as_on_date = row[0] if row and row[0] else None

                cursor.execute("EXEC dbo.usp_PopulateAuditChecklistScores @AsOnDate = %s", [as_on_date])
            except Exception as sp_err:
                log_error(f"submit_for_review: usp_PopulateAuditChecklistScores failed: {str(sp_err)}")
                # Non-fatal — continue with submission

            # Step 3: Call the review workflow SP
            cursor.execute("""
                EXEC dbo.usp_AuditWorkflow_Monolithic
                    @process_name = 'submit_for_review',
                    @audit_id = %s,
                    @branch_id = %s,
                    @submitted_by = %s
            """, [audit_id, branch_id, user.UserID])

        log_info(f"submit_for_review: audit {audit_id} branch {branch_id} submitted by user {user.UserID}")
        return JsonResponse({
            'success': True,
            'message': 'Audit submitted for review successfully.'
        })
    except Exception as e:
        log_error(f"submit_for_review: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_review_queue(request):
    """
    POST /audit/workflow/review-queue/
    Division Head: fetches list of audits pending their review.
    Returns audits in status 'submitted' or 'under-review' assigned to auditors
    under this division head's hierarchy.

    Expects JSON body:
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
        log_error(f"get_review_queue: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    p.audit_id,
                    p.audit_branch_id      AS branch_id,
                    p.audit_status,
                    p.audit_start_date,
                    p.audit_end_date,
                    p.current_cycle_no,
                    p.audit_pending_with,
                    b.Branch               AS branch_name,
                    b.Division,
                    b.Zone,
                    b.Region,
                    b.Hub,
                    u.UserName             AS auditor_name,
                    rc.submitted_at,
                    rc.cycle_no,
                    rc.review_started_at
                FROM dbo.audit_branch_progress p
                INNER JOIN dbo.VW_Branch_To_GeographicalHierarchy_head_audit h
                    ON h.fa_userid = p.audit_assigned_to
                   AND h.division_head_userid = %s
                LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b
                    ON b.BranchID = p.audit_branch_id
                LEFT JOIN dbo.accounts_mst_usertbl u
                    ON u.UserID = p.audit_assigned_to
                LEFT JOIN dbo.audit_branch_review_cycle rc
                    ON rc.audit_id = p.audit_id
                   AND rc.branch_id = p.audit_branch_id
                   AND rc.cycle_no = p.current_cycle_no
                WHERE p.audit_status IN ('submitted', 'under-review')
                ORDER BY rc.submitted_at DESC
            """, [user.UserID])

            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

        audits = []
        for row in rows:
            d = dict(zip(columns, row))
            for k, v in d.items():
                if hasattr(v, 'isoformat'):
                    d[k] = v.isoformat()
            audits.append(d)

        return JsonResponse({
            'success': True,
            'audits': audits,
            'pending_count': len(audits)
        })
    except Exception as e:
        log_error(f"get_review_queue: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_review_points(request):
    """
    POST /audit/workflow/review-points/
    Division Head: fetches all checklist points (branch + center + client)
    for a specific audit with their current review_status.

    Expects JSON body:
    {
        "token": "...",
        "audit_id": 71,
        "branch_id": 248
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        audit_id = data.get('audit_id')
        branch_id = data.get('branch_id')
    except Exception as e:
        log_error(f"get_review_points: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    if not audit_id or not branch_id:
        return JsonResponse({'success': False, 'message': 'audit_id and branch_id are required'}, status=400)

    try:
        with connection.cursor() as cursor:
            # Fetch audit metadata
            cursor.execute("""
                SELECT
                    p.audit_id, p.audit_branch_id, p.audit_status,
                    p.audit_start_date, p.audit_end_date, p.current_cycle_no,
                    b.Branch AS branch_name, b.Division,
                    u.UserName AS auditor_name,
                    rc.cycle_id, rc.submitted_at, rc.reviewer_id
                FROM dbo.audit_branch_progress p
                LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON b.BranchID = p.audit_branch_id
                LEFT JOIN dbo.accounts_mst_usertbl u ON u.UserID = p.audit_assigned_to
                LEFT JOIN dbo.audit_branch_review_cycle rc
                    ON rc.audit_id = p.audit_id
                   AND rc.branch_id = p.audit_branch_id
                   AND rc.cycle_no = p.current_cycle_no
                WHERE p.audit_id = %s AND p.audit_branch_id = %s
            """, [audit_id, branch_id])
            meta_row = cursor.fetchone()
            if not meta_row:
                return JsonResponse({'success': False, 'message': 'Audit not found'}, status=404)

            meta_cols = [d[0] for d in cursor.description]
            audit_meta = dict(zip(meta_cols, meta_row))
            for k, v in audit_meta.items():
                if hasattr(v, 'isoformat'):
                    audit_meta[k] = v.isoformat()

            # Fetch branch points
            cursor.execute("""
                SELECT
                    f.id AS feedback_id,
                    f.checklist_id,
                    f.section_code,
                    f.section_name,
                    f.intent_code,
                    f.intent_title,
                    f.answer,
                    f.normal_remark AS auditor_remark,
                    f.review_status,
                    f.review_remark,
                    f.reviewed_by,
                    f.reviewed_at,
                    nf.id AS normal_file_id,
                    nf.file_name AS normal_file_name
                FROM dbo.audit_branch_checklist_feedback f
                LEFT JOIN dbo.audit_branch_normal_files nf
                    ON nf.feedback_id = f.id AND nf.is_archived = 0
                WHERE f.audit_id = %s AND TRY_CAST(f.branch_id AS INT) = %s
                ORDER BY f.section_code, f.intent_code
            """, [audit_id, branch_id])
            branch_cols = [d[0] for d in cursor.description]
            branch_points = []
            for row in cursor.fetchall():
                d = dict(zip(branch_cols, row))
                for k, v in d.items():
                    if hasattr(v, 'isoformat'):
                        d[k] = v.isoformat()
                branch_points.append(d)

            # Fetch center points
            cursor.execute("""
                SELECT
                    f.id AS feedback_id,
                    f.center_checklist_id AS checklist_id,
                    f.center_id,
                    f.parameter_code,
                    f.parameter_name,
                    f.answer,
                    f.normal_remark AS auditor_remark,
                    f.review_status,
                    f.review_remark,
                    f.reviewed_by,
                    f.reviewed_at,
                    nf.id AS normal_file_id,
                    nf.file_name AS normal_file_name
                FROM dbo.audit_center_checklist_feedback f
                LEFT JOIN dbo.audit_center_normal_files nf
                    ON nf.feedback_id = f.id AND nf.is_archived = 0
                WHERE f.audit_id = %s AND TRY_CAST(f.branchid AS INT) = %s
                ORDER BY f.center_id, f.parameter_code
            """, [audit_id, branch_id])
            center_cols = [d[0] for d in cursor.description]
            center_points = []
            for row in cursor.fetchall():
                d = dict(zip(center_cols, row))
                for k, v in d.items():
                    if hasattr(v, 'isoformat'):
                        d[k] = v.isoformat()
                center_points.append(d)

            # Fetch client points
            cursor.execute("""
                SELECT
                    f.id AS feedback_id,
                    f.client_checklist_id AS checklist_id,
                    f.center_id,
                    TRY_CAST(f.client_id AS INT) AS client_id,
                    f.client_name,
                    f.parameter_code,
                    f.parameter_name,
                    f.answer,
                    f.remarks AS auditor_remark,
                    CAST(f.review_status AS VARCHAR(20)) AS review_status,
                    f.review_remark,
                    f.reviewed_by,
                    f.reviewed_at
                FROM dbo.audit_client_checklist_feedback f
                WHERE f.audit_id = %s AND TRY_CAST(f.branch_id AS INT) = %s
                ORDER BY f.center_id, f.client_id, f.parameter_code
            """, [audit_id, branch_id])
            client_cols = [d[0] for d in cursor.description]
            client_points = []
            for row in cursor.fetchall():
                d = dict(zip(client_cols, row))
                for k, v in d.items():
                    if hasattr(v, 'isoformat'):
                        d[k] = v.isoformat()
                client_points.append(d)

        return JsonResponse({
            'success': True,
            'audit_meta': audit_meta,
            'branch_points': branch_points,
            'center_points': center_points,
            'client_points': client_points
        })
    except Exception as e:
        log_error(f"get_review_points: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def record_point_decision(request):
    """
    POST /audit/workflow/record-decision/
    Division Head: validates or reverts a single checklist point.

    Expects JSON body:
    {
        "token": "...",
        "feedback_id": 94,
        "entity_type": "branch",   -- 'branch' | 'center' | 'client'
        "decision": "validated",   -- 'validated' | 'reverted'
        "review_remark": "..."     -- optional, required if reverted
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        feedback_id = data.get('feedback_id')
        entity_type = data.get('entity_type')
        decision = data.get('decision')
        review_remark = data.get('review_remark', '')
    except Exception as e:
        log_error(f"record_point_decision: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    if not feedback_id or not entity_type or not decision:
        return JsonResponse({'success': False, 'message': 'feedback_id, entity_type, and decision are required'}, status=400)

    if decision not in ('validated', 'reverted'):
        return JsonResponse({'success': False, 'message': 'decision must be validated or reverted'}, status=400)

    if entity_type not in ('branch', 'center', 'client'):
        return JsonResponse({'success': False, 'message': 'entity_type must be branch, center, or client'}, status=400)

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                EXEC dbo.usp_AuditWorkflow_Monolithic
                    @process_name   = 'record_point_decision',
                    @feedback_id    = %s,
                    @entity_type    = %s,
                    @reviewer_id    = %s,
                    @decision       = %s,
                    @review_remark  = %s
            """, [feedback_id, entity_type, user.UserID, decision, review_remark or None])

        log_info(f"record_point_decision: feedback_id={feedback_id} entity={entity_type} decision={decision} by user {user.UserID}")
        return JsonResponse({
            'success': True,
            'message': f'Point {decision} successfully.'
        })
    except Exception as e:
        log_error(f"record_point_decision: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def finalize_review(request):
    """
    POST /audit/workflow/finalize-review/
    Division Head: finalizes the review cycle for a branch audit.
    - If all points validated → audit_status = 'completed'
    - If any points reverted → audit_status = 'reverted', pending back to auditor

    Expects JSON body:
    {
        "token": "...",
        "audit_id": 71,
        "branch_id": 248
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        audit_id = data.get('audit_id')
        branch_id = data.get('branch_id')
    except Exception as e:
        log_error(f"finalize_review: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    if not audit_id or not branch_id:
        return JsonResponse({'success': False, 'message': 'audit_id and branch_id are required'}, status=400)

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                EXEC dbo.usp_AuditWorkflow_Monolithic
                    @process_name = 'finalize_review',
                    @audit_id     = %s,
                    @branch_id    = %s,
                    @reviewer_id  = %s
            """, [audit_id, branch_id, user.UserID])

            # Fetch the resulting status
            cursor.execute("""
                SELECT audit_status FROM dbo.audit_branch_progress
                WHERE audit_id = %s AND audit_branch_id = %s
            """, [audit_id, branch_id])
            status_row = cursor.fetchone()
            final_status = status_row[0] if status_row else 'unknown'

        log_info(f"finalize_review: audit {audit_id} branch {branch_id} finalized by user {user.UserID} -> {final_status}")

        message_map = {
            'completed': 'Review finalized. Audit is now completed — all points validated.',
            'reverted': 'Review finalized. Audit reverted to auditor — some points need correction.',
        }
        return JsonResponse({
            'success': True,
            'final_status': final_status,
            'message': message_map.get(final_status, f'Review finalized. Status: {final_status}')
        })
    except Exception as e:
        log_error(f"finalize_review: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_audit_review_status(request):
    """
    POST /audit/workflow/review-status/
    Auditor: fetches current review status + any review remarks for their audit.
    Used to show the auditor what was reverted and what needs fixing.

    Expects JSON body:
    {
        "token": "...",
        "audit_id": 71,
        "branch_id": 248
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        audit_id = data.get('audit_id')
        branch_id = data.get('branch_id')
    except Exception as e:
        log_error(f"get_audit_review_status: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    if not audit_id or not branch_id:
        return JsonResponse({'success': False, 'message': 'audit_id and branch_id are required'}, status=400)

    try:
        with connection.cursor() as cursor:
            # Fetch audit status + cycle info
            cursor.execute("""
                SELECT
                    p.audit_status,
                    p.current_cycle_no,
                    p.audit_pending_with,
                    rc.submitted_at,
                    rc.review_started_at,
                    rc.review_completed_at,
                    rc.outcome,
                    u_rev.UserName AS reviewer_name
                FROM dbo.audit_branch_progress p
                LEFT JOIN dbo.audit_branch_review_cycle rc
                    ON rc.audit_id = p.audit_id
                   AND rc.branch_id = p.audit_branch_id
                   AND rc.cycle_no = p.current_cycle_no
                LEFT JOIN dbo.accounts_mst_usertbl u_rev
                    ON u_rev.UserID = p.audit_pending_with
                WHERE p.audit_id = %s AND p.audit_branch_id = %s
            """, [audit_id, branch_id])
            row = cursor.fetchone()
            if not row:
                return JsonResponse({'success': False, 'message': 'Audit not found'}, status=404)

            cols = [d[0] for d in cursor.description]
            status_info = dict(zip(cols, row))
            for k, v in status_info.items():
                if hasattr(v, 'isoformat'):
                    status_info[k] = v.isoformat()

            # Fetch branch feedback with review remarks
            cursor.execute("""
                SELECT
                    f.id AS feedback_id, f.checklist_id,
                    f.intent_code, f.intent_title,
                    f.answer, f.review_status, f.review_remark
                FROM dbo.audit_branch_checklist_feedback f
                WHERE f.audit_id = %s AND TRY_CAST(f.branch_id AS INT) = %s
                ORDER BY f.section_code, f.intent_code
            """, [audit_id, branch_id])
            branch_review = [dict(zip([d[0] for d in cursor.description], r)) for r in cursor.fetchall()]

            # Fetch center feedback with review remarks
            cursor.execute("""
                SELECT
                    f.id AS feedback_id, f.center_checklist_id AS checklist_id,
                    f.center_id, f.parameter_code, f.parameter_name,
                    f.answer, f.review_status, f.review_remark
                FROM dbo.audit_center_checklist_feedback f
                WHERE f.audit_id = %s AND TRY_CAST(f.branchid AS INT) = %s
                ORDER BY f.center_id, f.parameter_code
            """, [audit_id, branch_id])
            center_review = [dict(zip([d[0] for d in cursor.description], r)) for r in cursor.fetchall()]

            # Fetch client feedback with review remarks
            cursor.execute("""
                SELECT
                    f.id AS feedback_id, f.client_checklist_id AS checklist_id,
                    f.center_id, TRY_CAST(f.client_id AS INT) AS client_id,
                    f.client_name, f.parameter_code, f.parameter_name,
                    f.answer, CAST(f.review_status AS VARCHAR(20)) AS review_status, f.review_remark
                FROM dbo.audit_client_checklist_feedback f
                WHERE f.audit_id = %s AND TRY_CAST(f.branch_id AS INT) = %s
                ORDER BY f.center_id, f.client_id, f.parameter_code
            """, [audit_id, branch_id])
            client_review = [dict(zip([d[0] for d in cursor.description], r)) for r in cursor.fetchall()]

        return JsonResponse({
            'success': True,
            'status_info': status_info,
            'branch_review': branch_review,
            'center_review': center_review,
            'client_review': client_review
        })
    except Exception as e:
        log_error(f"get_audit_review_status: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)





@csrf_exempt
def get_branch_report_excel(request):
    try:
        import json
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        audit_id = data.get('audit_id')
        if not token or not audit_id:
            return JsonResponse({'success': False, 'message': 'Missing required fields'})

        user = validate_token_user(token)
        if not user:
            return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

        with connection.cursor() as cursor:
            # 1. Fetch metadata
            cursor.execute("""
                SELECT 
                    p.audit_branch_id, 
                    b.Branch, 
                    p.audit_start_date, 
                    p.audit_end_date, 
                    u.UserName AS auditor_name,
                    p.audit_status
                FROM dbo.audit_branch_progress p
                LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON p.audit_branch_id = b.BranchID
                LEFT JOIN dbo.accounts_mst_usertbl u ON p.audit_assigned_to = u.UserID
                WHERE p.audit_id = %s
            """, [audit_id])
            meta_row = cursor.fetchone()
            if not meta_row:
                return JsonResponse({'success': False, 'message': 'Audit not found'}, status=404)
            
            branch_id = meta_row[0]
            
            # Fetch summary
            cursor.execute("""
                SELECT 
                    total_max_score, total_score, score_pct
                FROM dbo.audit_branch_score_summary
                WHERE audit_id = %s
            """, [audit_id])
            summary_row = cursor.fetchone()
            
            total_max = 0
            total_obtained = 0
            pct = 0
            if summary_row:
                total_max = float(summary_row[0] or 0)
                total_obtained = float(summary_row[1] or 0)
                pct = float(summary_row[2] or 0)
                
            grade = 'D'
            if pct > 80.0: grade = 'A'
            elif pct >= 60.0: grade = 'B'
            elif pct >= 40.0: grade = 'C'

            metadata = {
                'branch_name': meta_row[1] or 'Unknown',
                'audit_period': f"{meta_row[2].strftime('%Y-%m-%d') if meta_row[2] else ''} to {meta_row[3].strftime('%Y-%m-%d') if meta_row[3] else ''}",
                'auditor_name': meta_row[4] or 'Unknown',
                'status': meta_row[5],
                'total_score': total_obtained,
                'total_max_score': total_max,
                'percentage': pct,
                'grade': grade
            }

            # 2. Fetch Branch Points
            cursor.execute("""
                SELECT
                    f.id AS feedback_id,
                    f.section_code,
                    f.intent_title AS intent,
                    m.intent_description AS risk_issue,
                    m.category,
                    f.answer AS yes_no_na,
                    '' AS sample_verification,
                    '' AS correct_finding,
                    '' AS wrong_finding,
                    '' AS total_sample,
                    '' AS process_deviation,
                    s.max_score,
                    s.score_obtained AS obtained_score,
                    CASE WHEN s.score_obtained < s.max_score THEN 'Yes' ELSE 'No' END AS is_issue,
                    f.normal_remark AS auditor_remark
                FROM dbo.audit_branch_checklist_feedback f
                LEFT JOIN dbo.audit_branch_checklist_master m ON f.checklist_id = m.checklist_id
                LEFT JOIN dbo.audit_branch_checklist_score s ON f.checklist_id = s.checklist_id AND f.audit_id = s.audit_id
                WHERE f.audit_id = %s AND TRY_CAST(f.branch_id AS INT) = %s
                ORDER BY f.section_code, f.intent_code
            """, [audit_id, branch_id])
            branch_cols = [d[0] for d in cursor.description]
            branch_points = [dict(zip(branch_cols, row)) for row in cursor.fetchall()]

            # Fetch ALL reviewer remarks for branch from review log (multiple per feedback_id)
            cursor.execute("""
                SELECT feedback_id, cycle_id, decision, review_remark
                FROM dbo.audit_branch_checklist_review_log
                WHERE audit_id = %s AND review_remark IS NOT NULL AND LTRIM(RTRIM(review_remark)) <> ''
                ORDER BY feedback_id, log_id
            """, [audit_id])
            branch_excel_review_map = {}
            for rrow in cursor.fetchall():
                fid = rrow[0]
                if fid not in branch_excel_review_map:
                    branch_excel_review_map[fid] = []
                branch_excel_review_map[fid].append(f"Cycle {rrow[1]} ({rrow[2]}): {rrow[3]}")

            for pt in branch_points:
                fid = pt.pop('feedback_id', None)
                pt['reviewer_remark'] = '\n'.join(branch_excel_review_map.get(fid, []))

            # 3. Fetch Center Points
            cursor.execute("""
                SELECT
                    f.id AS feedback_id,
                    f.center_id,
                    f.parameter_code,
                    f.parameter_name,
                    f.answer,
                    f.normal_remark AS auditor_remark
                FROM dbo.audit_center_checklist_feedback f
                WHERE f.audit_id = %s AND TRY_CAST(f.branchid AS INT) = %s
                ORDER BY f.center_id, f.parameter_code
            """, [audit_id, branch_id])
            center_cols = [d[0] for d in cursor.description]
            center_points = [dict(zip(center_cols, row)) for row in cursor.fetchall()]

            try:
                cursor.execute("""
                    SELECT feedback_id, cycle_id, decision, review_remark
                    FROM dbo.audit_center_checklist_review_log
                    WHERE audit_id = %s AND review_remark IS NOT NULL AND LTRIM(RTRIM(review_remark)) <> ''
                    ORDER BY feedback_id, log_id
                """, [audit_id])
                center_excel_review_map = {}
                for rrow in cursor.fetchall():
                    fid = rrow[0]
                    if fid not in center_excel_review_map:
                        center_excel_review_map[fid] = []
                    center_excel_review_map[fid].append(f"Cycle {rrow[1]} ({rrow[2]}): {rrow[3]}")
            except Exception:
                center_excel_review_map = {}

            for pt in center_points:
                fid = pt.pop('feedback_id', None)
                pt['reviewer_remark'] = '\n'.join(center_excel_review_map.get(fid, []))

            # 4. Fetch Client Points
            cursor.execute("""
                SELECT
                    f.id AS feedback_id,
                    f.center_id,
                    TRY_CAST(f.client_id AS INT) AS client_id,
                    f.client_name,
                    f.parameter_code,
                    f.parameter_name,
                    f.answer,
                    f.remarks AS auditor_remark
                FROM dbo.audit_client_checklist_feedback f
                WHERE f.audit_id = %s AND TRY_CAST(f.branch_id AS INT) = %s
                ORDER BY f.center_id, f.client_id, f.parameter_code
            """, [audit_id, branch_id])
            client_cols = [d[0] for d in cursor.description]
            client_points = [dict(zip(client_cols, row)) for row in cursor.fetchall()]

            try:
                cursor.execute("""
                    SELECT feedback_id, cycle_id, decision, review_remark
                    FROM dbo.audit_client_checklist_review_log
                    WHERE audit_id = %s AND review_remark IS NOT NULL AND LTRIM(RTRIM(review_remark)) <> ''
                    ORDER BY feedback_id, log_id
                """, [audit_id])
                client_excel_review_map = {}
                for rrow in cursor.fetchall():
                    fid = rrow[0]
                    if fid not in client_excel_review_map:
                        client_excel_review_map[fid] = []
                    client_excel_review_map[fid].append(f"Cycle {rrow[1]} ({rrow[2]}): {rrow[3]}")
            except Exception:
                client_excel_review_map = {}

            for pt in client_points:
                fid = pt.pop('feedback_id', None)
                pt['reviewer_remark'] = '\n'.join(client_excel_review_map.get(fid, []))

        from .excel_utils import generate_branch_audit_excel
        import io
        from django.http import HttpResponse

        wb = generate_branch_audit_excel(metadata, branch_points, center_points, client_points)
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        
        response = HttpResponse(buffer.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="Branch_Report_{audit_id}.xlsx"'
        return response

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


# ============================================================
# AUDITEE (BRANCH MANAGER) ENDPOINTS
# ============================================================

def get_user_branch_ids(cursor, user):
    branch_id = int(user.BranchID) if user.BranchID else 0
    buid = int(user.Buid) if user.Buid else 0
    butype = int(user.BUType) if user.BUType else 0

    branch_ids = []
    if butype == 2 and buid:
        cursor.execute("""
            SELECT DISTINCT branchid FROM VW_Branch_To_GeographicalHierarchy
            WHERE divisionid = %s
        """, [buid])
        branch_ids = [str(row[0]) for row in cursor.fetchall()]
    elif butype == 3 and buid:
        cursor.execute("""
            SELECT DISTINCT branchid FROM VW_Branch_To_GeographicalHierarchy
            WHERE regionid = %s
        """, [buid])
        branch_ids = [str(row[0]) for row in cursor.fetchall()]
    elif butype == 4 and buid:
        cursor.execute("""
            SELECT DISTINCT branchid FROM VW_Branch_To_GeographicalHierarchy
            WHERE hubid = %s
        """, [buid])
        branch_ids = [str(row[0]) for row in cursor.fetchall()]
    elif butype == 5 and buid:
        cursor.execute("""
            SELECT DISTINCT branchid FROM VW_Branch_To_GeographicalHierarchy
            WHERE branchid = %s
        """, [buid])
        branch_ids = [str(row[0]) for row in cursor.fetchall()]
    elif branch_id:
        branch_ids = [str(branch_id)]
    
    if not branch_ids:
        branch_ids = ['0']
    return branch_ids


@csrf_exempt
def get_auditee_dashboard(request):
    """
    POST /audit/auditee/dashboard/
    Fetches dashboard KPIs for the logged in Auditee (Branch Manager or higher).
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        log_error(f"get_auditee_dashboard: parsing failed: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid request body or JSON parse error'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    branch_id = int(user.BranchID) if user.BranchID else 0
    buid = int(user.Buid) if user.Buid else 0
    butype = int(user.BUType) if user.BUType else 0
    print("butype", butype)
    print("buid", buid)
    print("branch_id", branch_id)
    if not branch_id and not buid:
        return JsonResponse({'success': False, 'message': 'User is not assigned to a branch or hierarchy unit'}, status=400)

    try:
        with connection.cursor() as cursor:
            # 0. get all branchid below the specific user
            branch_ids = get_user_branch_ids(cursor, user)
            print("branch_ids", branch_ids)

            placeholders = ', '.join(['%s'] * len(branch_ids))

            # 1. Get total completed audits
            cursor.execute(f"""
                SELECT COUNT(*) FROM dbo.audit_branch_progress
                WHERE audit_branch_id in ({placeholders}) AND (audit_status = 'completed' or audit_status = 'submitted' or audit_status='reverted')
            """, branch_ids)
            completed_audits = cursor.fetchone()[0]

            # 2. Get latest audit score
            cursor.execute(f"""
                SELECT TOP 1 s.score_pct, c.grade, p.audit_end_date, p.audit_id
                FROM dbo.audit_branch_score_summary s
                JOIN dbo.audit_branch_progress p ON s.audit_id = p.audit_id
                LEFT JOIN dbo.audit_plan_current c ON s.audit_id = c.id
                WHERE p.audit_branch_id in ({placeholders}) AND (p.audit_status = 'completed' or p.audit_status = 'submitted' or audit_status='reverted')
                ORDER BY p.audit_end_date DESC
            """, branch_ids)
            latest_audit = cursor.fetchone()
            latest_score = latest_audit[0] if latest_audit else 0
            latest_grade = latest_audit[1] if latest_audit else '-'
            latest_date = latest_audit[2].isoformat() if latest_audit and latest_audit[2] else None
            latest_audit_id = latest_audit[3] if latest_audit else None
            
            # 3. Get open CAPs count
            total_open_caps = 0
            if latest_audit_id:
                params = branch_ids + [latest_audit_id]
                cursor.execute(f"""
                    SELECT COUNT(*) FROM dbo.audit_branch_checklist_feedback
                    WHERE TRY_CAST(branch_id AS INT) in ({placeholders}) AND answer = 'Yes' and audit_id = %s
                """, params)
                branch_caps = cursor.fetchone()[0]

                cursor.execute(f"""
                    SELECT COUNT(*) FROM dbo.audit_center_checklist_feedback
                    WHERE TRY_CAST(branchid AS INT) in ({placeholders}) AND answer = 'Yes' and audit_id = %s
                """, params)
                center_caps = cursor.fetchone()[0]

                cursor.execute(f"""
                    SELECT COUNT(*) FROM dbo.audit_client_checklist_feedback
                    WHERE TRY_CAST(branch_id AS INT) in ({placeholders}) AND answer = 'Yes' and audit_id = %s
                """, params)
                client_caps = cursor.fetchone()[0]

                total_open_caps = branch_caps + center_caps + client_caps

        return JsonResponse({
            'success': True,
            'completed_audits': completed_audits,
            'latest_score': float(latest_score) if latest_score else 0,
            'latest_grade': latest_grade,
            'latest_date': latest_date,
            'total_open_caps': total_open_caps,
            'branch_name': f"Branch {branch_id or buid}"
        })
    except Exception as e:
        log_error(f"get_auditee_dashboard: failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_auditee_audits(request):
    """
    POST /audit/auditee/audits/
    Fetches all completed audits for the logged in Auditee (Branch Manager or higher).
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Invalid request: {str(e)}'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    branch_id = int(user.BranchID) if user.BranchID else 0
    buid = int(user.Buid) if user.Buid else 0
    if not branch_id and not buid:
        return JsonResponse({'success': False, 'message': 'User is not assigned to a branch or hierarchy unit'}, status=400)

    try:
        with connection.cursor() as cursor:
            branch_ids = get_user_branch_ids(cursor, user)
            placeholders = ', '.join(['%s'] * len(branch_ids))
            # Query completed audits for branch
            query = f"""
                SELECT 
                    p.audit_id, 
                    p.audit_branch_id, 
                    p.audit_start_date, 
                    p.audit_end_date, 
                    p.audit_status,
                    b.Branch as branch_name, 
                    b.Division, 
                    b.Zone,
                    b.Region,
                    u.UserName as auditor_name,
                    c.grade,
                    s.score_pct,
                    s.total_max_score,
                    s.total_score,
                    c.audit_mode
                FROM dbo.audit_branch_progress p
                LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON p.audit_branch_id = b.BranchID
                LEFT JOIN dbo.accounts_mst_usertbl u ON p.audit_assigned_to = u.UserID
                LEFT JOIN dbo.audit_plan_current c ON p.audit_id = c.id
                LEFT JOIN dbo.audit_branch_score_summary s ON p.audit_id = s.audit_id
                WHERE p.audit_status = 'completed' or audit_status='reverted' or audit_status='submitted' AND p.audit_branch_id in ({placeholders})
                ORDER BY p.audit_end_date DESC
            """
            cursor.execute(query, branch_ids)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
            
        audits = []
        for row in rows:
            audit = dict(zip(columns, row))
            # formatting dates and numbers
            if audit['audit_start_date']:
                audit['audit_start_date'] = audit['audit_start_date'].isoformat()
            if audit['audit_end_date']:
                audit['audit_end_date'] = audit['audit_end_date'].isoformat()
            if audit['score_pct'] is not None:
                audit['score_pct'] = float(audit['score_pct'])
                
            audits.append(audit)

        return JsonResponse({
            'success': True,
            'audits': audits
        })
    except Exception as e:
        log_error(f"get_auditee_audits failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)


@csrf_exempt
def get_auditee_caps(request):
    """
    POST /audit/auditee/caps/
    Fetches all Corrective Action Points for the Auditee's branch.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Invalid request: {str(e)}'}, status=400)

    user = validate_token_user(token)
    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid or expired token'}, status=401)

    branch_id = int(user.BranchID) if user.BranchID else 0
    buid = int(user.Buid) if user.Buid else 0
    if not branch_id and not buid:
        return JsonResponse({'success': False, 'message': 'User is not assigned to a branch or hierarchy unit'}, status=400)

    try:
        with connection.cursor() as cursor:
            branch_ids = get_user_branch_ids(cursor, user)
            placeholders = ', '.join(['%s'] * len(branch_ids))

            # Branch-level CAPs
            cursor.execute(f"""
                SELECT
                    'BRANCH'            AS cap_type,
                    bf.id               AS feedback_id,
                    bf.audit_id,
                    bf.branch_id,
                    NULL                AS center_id,
                    NULL                AS client_id,
                    NULL                AS client_name,
                    bf.intent_code      AS parameter_code,
                    bf.intent_title     AS parameter_name,
                    bf.section_code,
                    bf.section_name,
                    bf.answer,
                    bf.normal_remark    AS remark,
                    ISNULL(b.Branch, CONCAT('Branch ', bf.branch_id)) AS branch_name,
                    bf.created_at
                FROM dbo.audit_branch_checklist_feedback bf
                LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON TRY_CAST(bf.branch_id AS INT) = b.BranchID
                WHERE bf.answer = 'Yes' AND TRY_CAST(bf.branch_id AS INT) in ({placeholders})
            """, branch_ids)
            branch_cols = [col[0] for col in cursor.description]
            branch_rows = cursor.fetchall()

            # Center-level CAPs
            cursor.execute(f"""
                SELECT
                    'CENTER'            AS cap_type,
                    cf.id               AS feedback_id,
                    cf.audit_id,
                    cf.branchid         AS branch_id,
                    cf.center_id,
                    NULL                AS client_id,
                    NULL                AS client_name,
                    cf.parameter_code,
                    cf.parameter_name,
                    NULL                AS section_code,
                    NULL                AS section_name,
                    cf.answer,
                    cf.normal_remark    AS remark,
                    ISNULL(b.Branch, CONCAT('Branch ', cf.branchid)) AS branch_name,
                    cf.created_at
                FROM dbo.audit_center_checklist_feedback cf
                LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON TRY_CAST(cf.branchid AS INT) = b.BranchID
                WHERE cf.answer = 'Yes' AND TRY_CAST(cf.branchid AS INT) in ({placeholders})
            """, branch_ids)
            center_rows = cursor.fetchall()

            # Client-level CAPs
            cursor.execute(f"""
                SELECT
                    'CLIENT'            AS cap_type,
                    clf.id              AS feedback_id,
                    clf.audit_id,
                    clf.branch_id,
                    clf.center_id,
                    clf.client_id,
                    clf.client_name,
                    clf.parameter_code,
                    clf.parameter_name,
                    NULL                AS section_code,
                    NULL                AS section_name,
                    clf.answer,
                    clf.remarks         AS remark,
                    ISNULL(b.Branch, CONCAT('Branch ', clf.branch_id)) AS branch_name,
                    clf.created_at
                FROM dbo.audit_client_checklist_feedback clf
                LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON TRY_CAST(clf.branch_id AS INT) = b.BranchID
                WHERE clf.answer = 'Yes' AND TRY_CAST(clf.branch_id AS INT) in ({placeholders})
            """, branch_ids)
            client_rows = cursor.fetchall()

        caps = []
        for row in branch_rows + center_rows + client_rows:
            cap = dict(zip(branch_cols, row))
            for k, v in cap.items():
                if hasattr(v, 'isoformat'):
                    cap[k] = v.isoformat()
            caps.append(cap)
            
        caps.sort(key=lambda x: x['created_at'], reverse=True)

        return JsonResponse({
            'success': True,
            'caps': caps
        })
    except Exception as e:
        log_error(f"get_auditee_caps failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status=500)
