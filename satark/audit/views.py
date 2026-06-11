import json
import decimal
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import connection
from authentication.views import send_encrypted_response, validate_token_user, is_user_admin
from authentication.utils import decrypt_data, log_info, log_error

# Custom JSON encoder to handle decimals in JSON serialization
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

@csrf_exempt
def get_checklist_points(request):
    """
    POST API endpoint to retrieve checklist points.
    Encrypted JSON body:
    {
        "report_type": "Branch Audit", # Optional filter
        "section_code": "SEC_01"       # Optional filter
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        outer_data = json.loads(request.body)
        encrypted_payload = outer_data.get('data', '')
        decrypted_str = decrypt_data(encrypted_payload)
        data = json.loads(decrypted_str) if decrypted_str else {}
        token = data.get('token', '')
    except Exception as e:
        log_error(f"get_checklist_points: parsing/decryption failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Invalid request body or decryption failure'}, status_code=400)

    user = validate_token_user(token)
    if not user:
        return send_encrypted_response({'success': False, 'message': 'Invalid token'}, status_code=401)

    report_type_filter = data.get('report_type')
    section_code_filter = data.get('section_code')

    try:
        query = """
            SELECT 
                checklist_id, report_type, section_code, section_name, 
                section_weight_pct, section_display_order, serial_no, 
                intent_code, intent_title, intent_description, category, 
                max_score, accepted_deviation_pct, sample_method, is_active,
                created_at, updated_at
            FROM [dbo].[audit_branch_checklist_master]
            WHERE 1=1
        """
        params = []
        if report_type_filter:
            query += " AND report_type = %s"
            params.append(report_type_filter)
        if section_code_filter:
            query += " AND section_code = %s"
            params.append(section_code_filter)

        query += " ORDER BY report_type, section_display_order, serial_no"

        with connection.cursor() as cursor:
            cursor.execute(query, params)
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

        return send_encrypted_response({
            'success': True,
            'checklist_points': items
        })
    except Exception as e:
        log_error(f"get_checklist_points: DB error: {str(e)}")
        return send_encrypted_response({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status_code=500)


@csrf_exempt
def create_checklist_point(request):
    """
    POST API endpoint to create a new checklist point.
    Calls the stored procedure `usp_add_audit_checklist_item`.
    Encrypted JSON body:
    {
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
        outer_data = json.loads(request.body)
        encrypted_payload = outer_data.get('data', '')
        decrypted_str = decrypt_data(encrypted_payload)
        data = json.loads(decrypted_str)
        token = data.get('token', '')
    except Exception as e:
        log_error(f"create_checklist_point: parsing/decryption failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Invalid request body or decryption failure'}, status_code=400)

    user = validate_token_user(token)
    if not user:
        return send_encrypted_response({'success': False, 'message': 'Invalid token'}, status_code=401)

    if not is_user_admin(user):
        return send_encrypted_response({'success': False, 'message': 'Access denied: Admin role required'}, status_code=403)

    # Required fields
    required_fields = [
        'report_type', 'section_code', 'section_name', 
        'section_weight_pct', 'section_display_order', 
        'intent_title', 'category', 'max_score', 'accepted_deviation_pct'
    ]
    missing = [field for field in required_fields if field not in data]
    if missing:
        return send_encrypted_response({
            'success': False, 
            'message': f"Missing required fields: {', '.join(missing)}"
        }, status_code=400)

    try:
        with connection.cursor() as cursor:
            # Call stored procedure
            # In python pyodbc / django, calling stored procedure can be done by EXEC
            sp_query = """
                EXEC [dbo].[usp_add_audit_checklist_item]
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
            return send_encrypted_response({'success': False, 'message': 'Stored procedure did not return any records'}, status_code=500)

        created_item = dict(zip(columns, row))
        for key, val in created_item.items():
            if isinstance(val, decimal.Decimal):
                created_item[key] = float(val)
            elif hasattr(val, 'isoformat'):
                created_item[key] = val.isoformat()

        log_info(f"Successfully created checklist point: {created_item.get('intent_code')} by {user.UserCode}")
        return send_encrypted_response({
            'success': True,
            'message': 'Checklist item created successfully',
            'checklist_point': created_item
        })

    except Exception as e:
        log_error(f"create_checklist_point: stored procedure execution failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': f'Stored procedure error: {str(e)}'}, status_code=500)


@csrf_exempt
def get_report_types(request):
    """
    POST API endpoint to retrieve all unique report types.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        outer_data = json.loads(request.body)
        encrypted_payload = outer_data.get('data', '')
        decrypted_str = decrypt_data(encrypted_payload)
        data = json.loads(decrypted_str) if decrypted_str else {}
        token = data.get('token', '')
    except Exception as e:
        log_error(f"get_report_types: parsing/decryption failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Invalid request body or decryption failure'}, status_code=400)

    user = validate_token_user(token)
    if not user:
        return send_encrypted_response({'success': False, 'message': 'Invalid token'}, status_code=401)

    try:
        # We fetch distinct report types from audit_branch_checklist_master to ensure backward compatibility,
        # but merge with default fallback report types.
        with connection.cursor() as cursor:
            cursor.execute("SELECT DISTINCT report_type FROM [dbo].[audit_branch_checklist_master] WHERE report_type IS NOT NULL")
            db_types = [row[0] for row in cursor.fetchall() if row[0]]

        default_types = ["Branch Audit", "Gold Loan Audit", "Concurrent Audit"]
        all_types = list(set(default_types + db_types))

        return send_encrypted_response({
            'success': True,
            'report_types': all_types
        })
    except Exception as e:
        log_error(f"get_report_types: DB error: {str(e)}")
        return send_encrypted_response({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status_code=500)


@csrf_exempt
def get_assigned_audits(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        outer_data = json.loads(request.body)
        encrypted_payload = outer_data.get('data', '')
        decrypted_str = decrypt_data(encrypted_payload)
        data = json.loads(decrypted_str) if decrypted_str else {}
        token = data.get('token', '')
    except Exception as e:
        log_error(f"get_assigned_audits: parsing/decryption failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Invalid request body or decryption failure'}, status_code=400)

    user = validate_token_user(token)
    if not user:
        return send_encrypted_response({'success': False, 'message': 'Invalid token'}, status_code=401)

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
        return send_encrypted_response({
            'success': True,
            'audits': audits,
            'stats': stats
        })
    except Exception as e:
        log_error(f"get_assigned_audits: DB or processing error: {str(e)}")
        return send_encrypted_response({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status_code=500)


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
    Encrypted JSON body:
    {
        "token": "...",
        "branch_id": "BR-001"
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        outer_data = json.loads(request.body)
        encrypted_payload = outer_data.get('data', '')
        decrypted_str = decrypt_data(encrypted_payload)
        data = json.loads(decrypted_str) if decrypted_str else {}
        token = data.get('token', '')
        branch_id = data.get('branch_id', '')
        audit_id = data.get('audit_id')
    except Exception as e:
        log_error(f"get_audit_feedback: parsing/decryption failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Invalid request body or decryption failure'}, status_code=400)

    user = validate_token_user(token)
    if not user:
        return send_encrypted_response({'success': False, 'message': 'Invalid token'}, status_code=401)

    if not branch_id:
        return send_encrypted_response({'success': False, 'message': 'branch_id is required'}, status_code=400)

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

        return send_encrypted_response({
            'success': True,
            'feedback': feedback_list,
            'auditId': feedback_audit_id
        })
    except Exception as e:
        log_error(f"get_audit_feedback: DB error: {str(e)}")
        return send_encrypted_response({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status_code=500)


@csrf_exempt
def save_audit_feedback(request):
    """
    POST API endpoint to save or submit checklist feedback for a branch.
    Encrypted JSON body:
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
        outer_data = json.loads(request.body)
        encrypted_payload = outer_data.get('data', '')
        decrypted_str = decrypt_data(encrypted_payload)
        data = json.loads(decrypted_str) if decrypted_str else {}
        token = data.get('token', '')
        branch_id = data.get('branch_id', '')
        audit_id = data.get('audit_id')
        action = data.get('action', 'DRAFT_SAVED')
        general_remarks = data.get('general_remarks', '')
        feedback_items = data.get('feedback_items', [])
    except Exception as e:
        log_error(f"save_audit_feedback: parsing/decryption failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Invalid request body or decryption failure'}, status_code=400)

    user = validate_token_user(token)
    if not user:
        return send_encrypted_response({'success': False, 'message': 'Invalid token'}, status_code=401)

    if not branch_id:
        return send_encrypted_response({'success': False, 'message': 'branch_id is required'}, status_code=400)

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

        return send_encrypted_response({
            'success': True,
            'message': 'Audit checklist feedback saved successfully'
        })
    except Exception as e:
        log_error(f"save_audit_feedback: failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status_code=500)


