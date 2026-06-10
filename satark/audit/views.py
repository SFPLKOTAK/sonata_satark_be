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
