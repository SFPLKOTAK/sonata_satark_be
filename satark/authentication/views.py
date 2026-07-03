import json
import datetime
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
import jwt
from .models import AccountsMstUsertbl, JWTToken
from .utils import encrypt_data, decrypt_data, log_info, log_error

DESIGNATION_MAPPING = {
    1: 'ADMIN',
    2: 'ZONAL_HEAD',
    3: 'DIVISION_HEAD',
    4: 'AUDITOR',
    5: 'AUDIT_HEAD',
    6: 'AUDITEE',
}

ROLE_LABELS = {
    'ADMIN': 'Administrator',
    'AUDIT_HEAD': 'Audit Head (HO)',
    'ZONAL_HEAD': 'Zonal Audit Head',
    'DIVISION_HEAD': 'Division Audit Head',
    'AUDITOR': 'Field Auditor',
    'AUDITEE': 'Auditee (Branch Mgr)',
}

LEVEL_MAPPING = {
    'ADMIN': 'Admin',
    'AUDIT_HEAD': 'L1',
    'ZONAL_HEAD': 'L2',
    'DIVISION_HEAD': 'L3',
    'AUDITOR': 'L4',
    'AUDITEE': 'BM',
}

def get_current_ist():
    # Returns naive datetime representing local Indian Standard Time
    return datetime.datetime.now(timezone.get_current_timezone()).replace(tzinfo=None)

def generate_access_token(user):
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        'user_id': user.id,
        'usercode': user.UserCode,
        'exp': now_utc + datetime.timedelta(hours=1),
        'iat': now_utc,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

def generate_refresh_token(user):
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        'user_id': user.id,
        'usercode': user.UserCode,
        'exp': now_utc + datetime.timedelta(hours=48),
        'iat': now_utc,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

def send_encrypted_response(data_dict, status_code=200):
    return JsonResponse(data_dict, status=status_code)


from django.contrib.auth.hashers import check_password
@csrf_exempt
def login_view(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body) if request.body else {}
        print("data",data)
        usercode = data.get('username', '').strip()
        password = data.get('password', '')
    except Exception as e:
        log_error(f"Login request parsing failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Invalid request body'}, status_code=400)

    if not usercode or not password:
        log_error("Login failed: usercode or password missing")
        return send_encrypted_response({'success': False, 'message': 'usercode and password are required'}, status_code=400)

    log_info(f"Login attempt for user: {usercode}")

    try:
        user = AccountsMstUsertbl.objects.get(UserCode=usercode)
        print(user.password)


        # TEMPORARY DEBUG PRINTS
        print(f"Type of password: {type(password)}")
        print(f"Exact password being checked: '{password}'")  # Quotes will show hidden spaces
        print(f"DB Hash being checked against: '{user.password}'")

        # You can even test a manual check right here:
        from django.contrib.auth.hashers import make_password
        print(f"Does it match manually?: {check_password('Sonata123@', user.password)}")
    except AccountsMstUsertbl.DoesNotExist:
        log_error(f"Login failed: User {usercode} not found")
        return send_encrypted_response({'success': False, 'message': 'Invalid usercode or password'}, status_code=401)


    if not check_password(password, user.password):
        log_error(f"Login failed: Invalid password for user {usercode}")
        return send_encrypted_response({'success': False, 'message': 'Invalid usercode or password'}, status_code=401)

    if not user.is_active:
        log_error(f"Login failed: User {usercode} account is inactive")
        return send_encrypted_response({'success': False, 'message': 'User account is inactive'}, status_code=403)

    # Generate tokens
    access_token = generate_access_token(user)
    refresh_token = generate_refresh_token(user)

    # Store tokens in database with IST naive timestamps
    now_ist = get_current_ist()
    access_expires_at = now_ist + datetime.timedelta(hours=1)
    refresh_expires_at = now_ist + datetime.timedelta(hours=48)

    try:
        JWTToken.objects.create(
            user=user,
            access_token=access_token,
            refresh_token=refresh_token,
            created_at=now_ist,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at
        )
    except Exception as e:
        log_error(f"Failed to save JWT token for user {usercode}: {str(e)}")

    # Map role & details dynamically from the database
    db_role_id = None
    db_role_name = None
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT r.RoleId, r.RoleName
                FROM [dbo].[map_userRole] mur
                JOIN [dbo].[mst_role] r ON mur.RoleId = r.RoleId
                WHERE mur.UserID = %s AND mur.IsActive = 1
            """, [user.UserID])
            row = cursor.fetchone()
            if row:
                db_role_id = row[0]
                db_role_name = row[1]
    except Exception as e:
        log_error(f"Failed to query database user role: {str(e)}")

    DB_ROLE_MAPPING = {
        1: 'ADMIN',
        2: 'ZONAL_HEAD',
        3: 'DIVISION_HEAD',
        4: 'AUDITOR',
        5: 'AUDIT_HEAD',
        6: 'AUDITEE',
    }

    role = DB_ROLE_MAPPING.get(db_role_id, 'AUDITEE')
    role_label = db_role_name if db_role_name else ROLE_LABELS.get(role, 'Auditee')
    level = LEVEL_MAPPING.get(role, 'BM')
    name = user.UserName

    user_details = {
        'id': user.id,
        'usercode': usercode,
        'name': name,
        'role': role,
        'roleLabel': role_label,
        'level': level,
        'mobile': user.ContactNo,
        'email': user.Email,
        'empId': user.EmpID,
    }

    log_info(f"User login successful: {usercode}")

    return send_encrypted_response({
        'success': True,
        'access_token': access_token,
        'refresh_token': refresh_token,
        'user': user_details
    })

@csrf_exempt
def refresh_view(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        refresh_token = data.get('refresh_token', '')
    except Exception as e:
        log_error(f"Refresh request parsing failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Invalid request body'}, status_code=400)

    if not refresh_token:
        log_error("Refresh failed: Refresh token missing")
        return send_encrypted_response({'success': False, 'message': 'Refresh token is required'}, status_code=400)

    log_info("Token refresh attempt started")

    try:
        # Find token record
        token_record = JWTToken.objects.get(refresh_token=refresh_token)
    except JWTToken.DoesNotExist:
        log_error("Refresh failed: Token record not found in database")
        return send_encrypted_response({'success': False, 'message': 'Invalid refresh token'}, status_code=401)

    now_ist = get_current_ist()

    # Check if refresh token is expired in DB
    if token_record.refresh_expires_at < now_ist:
        log_error(f"Refresh failed: Token expired in database at {token_record.refresh_expires_at}")
        token_record.delete()
        return send_encrypted_response({'success': False, 'message': 'Refresh token expired'}, status_code=401)

    # Verify signature and expiration via PyJWT
    try:
        jwt.decode(refresh_token, settings.SECRET_KEY, algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        log_error("Refresh failed: JWT signature expired")
        token_record.delete()
        return send_encrypted_response({'success': False, 'message': 'Refresh token signature expired'}, status_code=401)
    except jwt.InvalidTokenError:
        log_error("Refresh failed: JWT signature invalid")
        return send_encrypted_response({'success': False, 'message': 'Invalid refresh token signature'}, status_code=401)

    user = token_record.user
    new_access_token = generate_access_token(user)

    try:
        # Update access token in database (overwrites/deletes the old access token)
        token_record.access_token = new_access_token
        token_record.access_expires_at = now_ist + datetime.timedelta(hours=1)
        token_record.save()
    except Exception as e:
        log_error(f"Failed to update database access token during refresh: {str(e)}")

    log_info(f"Token refresh successful for user: {user.UserCode}")

    return send_encrypted_response({
        'success': True,
        'access_token': new_access_token
    })

def validate_token_user(token):
    try:
        jwt_payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        user_id = jwt_payload.get('user_id')
        return AccountsMstUsertbl.objects.get(id=user_id)
    except Exception:
        return None

def is_user_admin(user):
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM [dbo].[map_userRole] WHERE UserID = %s AND RoleId = 1 AND IsActive = 1", [user.UserID])
            return cursor.fetchone()[0] > 0
    except Exception:
        return False

@csrf_exempt
def menu_view(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        log_error(f"Menu request parsing failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Invalid request body'}, status_code=400)

    user = validate_token_user(token)
    if not user:
        return send_encrypted_response({'success': False, 'message': 'Invalid token'}, status_code=401)

    db_role_id = None
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT RoleId
                FROM [dbo].[map_userRole]
                WHERE UserID = %s AND IsActive = 1
            """, [user.UserID])
            row = cursor.fetchone()
            if row:
                db_role_id = row[0]
    except Exception as e:
        log_error(f"Failed to query database user role: {str(e)}")

    if not db_role_id:
        return send_encrypted_response({'success': True, 'items': []})

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT i.id, i.label, i.icon, i.to_path, i.badge_text, i.sort_order
                FROM [dbo].[accounts_menu_item] i
                JOIN [dbo].[accounts_role_menu_mapping] m ON i.id = m.menu_item_id
                WHERE m.role_id = %s AND i.is_active = 1
                ORDER BY i.sort_order ASC
            """, [db_role_id])
            rows = cursor.fetchall()

        items_list = []
        for i_id, i_label, i_icon, i_to_path, i_badge, i_sort in rows:
            items_list.append({
                'label': i_label,
                'icon': i_icon,
                'to': i_to_path,
                'badge': i_badge if i_badge else None
            })
        
        return send_encrypted_response({'success': True, 'items': items_list})
    except Exception as e:
        log_error(f"Failed to load menu list: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Internal Server Error'}, status_code=500)

@csrf_exempt
def admin_menu_view(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        log_error(f"Admin menu request parsing failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Invalid request body'}, status_code=400)

    user = validate_token_user(token)
    if not user:
        return send_encrypted_response({'success': False, 'message': 'Invalid token'}, status_code=401)

    if not is_user_admin(user):
        return send_encrypted_response({'success': False, 'message': 'Access denied'}, status_code=403)

    try:
        from django.db import connection
        with connection.cursor() as cursor:
            # Roles
            cursor.execute("SELECT RoleId, RoleName FROM [dbo].[mst_role] WHERE IsDeleted = 0 OR IsDeleted IS NULL")
            roles = [{'RoleId': r[0], 'RoleName': r[1]} for r in cursor.fetchall()]
            
            # Items
            cursor.execute("SELECT id, label, icon, to_path, badge_text, sort_order, is_active FROM [dbo].[accounts_menu_item] ORDER BY sort_order")
            items = [{
                'id': i[0],
                'label': i[1],
                'icon': i[2],
                'to_path': i[3],
                'badge_text': i[4],
                'sort_order': i[5],
                'is_active': bool(i[6])
            } for i in cursor.fetchall()]
            
            # Mappings
            cursor.execute("SELECT role_id, menu_item_id FROM [dbo].[accounts_role_menu_mapping]")
            mappings = [{'role_id': m[0], 'menu_item_id': m[1]} for m in cursor.fetchall()]

        return send_encrypted_response({
            'success': True,
            'roles': roles,
            'items': items,
            'mappings': mappings
        })
    except Exception as e:
        log_error(f"Failed to fetch admin menu config: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Internal Server Error'}, status_code=500)

@csrf_exempt
def admin_save_menu_view(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        items = data.get('items', [])
        mappings = data.get('mappings', [])
    except Exception as e:
        log_error(f"Admin menu save request parsing failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Invalid request body'}, status_code=400)

    user = validate_token_user(token)
    if not user:
        return send_encrypted_response({'success': False, 'message': 'Invalid token'}, status_code=401)

    if not is_user_admin(user):
        return send_encrypted_response({'success': False, 'message': 'Access denied'}, status_code=403)

    from django.db import transaction, connection
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                # Delete items not in request
                incoming_item_ids = [i['id'] for i in items if i.get('id') is not None and i['id'] >= 0]
                if incoming_item_ids:
                    placeholders = ', '.join(['%s'] * len(incoming_item_ids))
                    cursor.execute(f"DELETE FROM [dbo].[accounts_menu_item] WHERE id NOT IN ({placeholders})", incoming_item_ids)
                else:
                    cursor.execute("DELETE FROM [dbo].[accounts_menu_item]")
                    
                # Process items
                item_id_map = {}
                for i in items:
                    i_id = i.get('id')
                    label = i['label']
                    icon = i['icon']
                    to_path = i['to_path']
                    badge = i.get('badge_text')
                    i_sort = i['sort_order']
                    i_active = 1 if i.get('is_active', True) else 0
                    
                    if i_id is None or i_id < 0:
                        cursor.execute("""
                            INSERT INTO [dbo].[accounts_menu_item] (label, icon, to_path, badge_text, sort_order, is_active)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, [label, icon, to_path, badge, i_sort, i_active])
                        cursor.execute("SELECT @@IDENTITY")
                        new_id = int(cursor.fetchone()[0])
                        if i_id is not None:
                            item_id_map[i_id] = new_id
                    else:
                        cursor.execute("""
                            UPDATE [dbo].[accounts_menu_item]
                            SET label = %s, icon = %s, to_path = %s, badge_text = %s, sort_order = %s, is_active = %s
                            WHERE id = %s
                        """, [label, icon, to_path, badge, i_sort, i_active, i_id])
                        item_id_map[i_id] = i_id
                        
                # Reset mappings
                cursor.execute("DELETE FROM [dbo].[accounts_role_menu_mapping]")
                for m in mappings:
                    role_id = int(m['role_id'])
                    item_id = int(m['menu_item_id'])
                    if item_id in item_id_map:
                        item_id = item_id_map[item_id]
                        
                    cursor.execute("""
                        INSERT INTO [dbo].[accounts_role_menu_mapping] (role_id, menu_item_id)
                        VALUES (%s, %s)
                    """, [role_id, item_id])

        log_info("Admin menu configuration updated successfully.")
        return send_encrypted_response({'success': True, 'message': 'Menu configuration saved successfully'})
    except Exception as ex:
        log_error(f"Failed to save menu configuration: {str(ex)}")
        return send_encrypted_response({'success': False, 'message': f'Failed to save configuration: {str(ex)}'}, status_code=500)


@csrf_exempt
def admin_user_list_view(request):
    """Return full user list with role info, plus roles & geo hierarchy for dropdowns."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        log_error(f"admin_user_list_view: parse failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Invalid request body'}, status_code=400)

    user = validate_token_user(token)
    if not user:
        return send_encrypted_response({'success': False, 'message': 'Invalid token'}, status_code=401)

    if not is_user_admin(user):
        return send_encrypted_response({'success': False, 'message': 'Access denied'}, status_code=403)

    from django.db import connection
    try:
        with connection.cursor() as cursor:
            # All users with current role
            cursor.execute("""
                SELECT
                    mu.UserID, mu.UserCode, mu.UserName, mu.EmpID,
                    mu.ContactNo, mu.Email,
                    mu.Hoid, mu.DivisionID, mu.RegionID, mu.HubID, mu.BranchID,
                    mu.BUType, mu.Buid, mu.IsActive,
                    mr.RoleId, mr.RoleName
                FROM [dbo].[accounts_mst_usertbl] mu
                LEFT JOIN [dbo].[map_userRole] mur ON mu.UserID = mur.UserID AND mur.IsActive = 1
                LEFT JOIN [dbo].[mst_role] mr ON mur.RoleId = mr.RoleId
                ORDER BY mu.UserName
            """)
            cols = [d[0] for d in cursor.description]
            users = [dict(zip(cols, row)) for row in cursor.fetchall()]

            # All roles
            cursor.execute("SELECT RoleId, RoleName FROM [dbo].[mst_role] WHERE IsDeleted = 0 OR IsDeleted IS NULL ORDER BY RoleId")
            roles = [{'RoleId': r[0], 'RoleName': r[1]} for r in cursor.fetchall()]

            # Geographic hierarchy (Zone, DivisionID, Division, RegionID, Region, HubID, Hub, BranchID, Branch)
            cursor.execute("""
                SELECT Zone, DivisionID, Division, RegionID, Region, HubID, Hub, BranchID, Branch
                FROM [dbo].[VW_Branch_To_GeographicalHierarchy]
                ORDER BY Zone, Division, Region, Hub, Branch
            """)
            geo_cols = [d[0] for d in cursor.description]
            geo_rows = [dict(zip(geo_cols, row)) for row in cursor.fetchall()]

        return send_encrypted_response({
            'success': True,
            'users': users,
            'roles': roles,
            'geo_hierarchy': geo_rows
        })
    except Exception as e:
        log_error(f"admin_user_list_view: DB error: {str(e)}")
        return send_encrypted_response({'success': False, 'message': f'Internal Server Error: {str(e)}'}, status_code=500)


@csrf_exempt
def admin_save_user_view(request):
    """Update user details, role, and sync geographic hierarchy fields."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        user_id = data.get('user_id')
        new_role_id = data.get('role_id')         # int
        new_branch_id = data.get('branch_id')     # BranchID from geo view, may be None
        new_contact = data.get('contact_no')
        new_email = data.get('email')
    except Exception as e:
        log_error(f"admin_save_user_view: parse failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Invalid request body'}, status_code=400)

    admin_user = validate_token_user(token)
    if not admin_user:
        return send_encrypted_response({'success': False, 'message': 'Invalid token'}, status_code=401)

    if not is_user_admin(admin_user):
        return send_encrypted_response({'success': False, 'message': 'Access denied'}, status_code=403)

    if not user_id:
        return send_encrypted_response({'success': False, 'message': 'user_id is required'}, status_code=400)

    from django.db import connection, transaction
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                # ------ Read old values ------
                cursor.execute("""
                    SELECT mu.ContactNo, mu.Email, mu.Hoid, mu.DivisionID, mu.RegionID,
                           mu.HubID, mu.BranchID, mu.BUType, mu.Buid,
                           mr.RoleId, mr.RoleName
                    FROM [dbo].[accounts_mst_usertbl] mu
                    LEFT JOIN [dbo].[map_userRole] mur ON mu.UserID = mur.UserID AND mur.IsActive = 1
                    LEFT JOIN [dbo].[mst_role] mr ON mur.RoleId = mr.RoleId
                    WHERE mu.UserID = %s
                """, [user_id])
                row = cursor.fetchone()
                if not row:
                    return send_encrypted_response({'success': False, 'message': 'User not found'}, status_code=404)

                old_contact, old_email, old_hoid, old_div, old_reg, old_hub, old_branch, old_butype, old_buid, old_role_id, old_role_name = row

                # ------ Resolve geographic fields from branch_id if role or branch changes ------
                new_div = old_div
                new_reg = old_reg
                new_hub = old_hub
                new_buid = old_buid
                new_butype = old_butype

                if new_branch_id is not None:
                    cursor.execute("""
                        SELECT DivisionID, RegionID, HubID, BranchID
                        FROM [dbo].[VW_Branch_To_GeographicalHierarchy]
                        WHERE BranchID = %s
                    """, [new_branch_id])
                    geo_row = cursor.fetchone()
                    if geo_row:
                        new_div, new_reg, new_hub, resolved_branch = geo_row
                        new_buid = resolved_branch   # Buid = BranchID from hierarchy
                        new_butype = 4               # Branch-level BUType = 4 (adjust if needed)
                    else:
                        return send_encrypted_response({'success': False, 'message': f'Branch ID {new_branch_id} not found in hierarchy'}, status_code=400)

                # ------ Update accounts_mst_usertbl ------
                cursor.execute("""
                    UPDATE [dbo].[accounts_mst_usertbl]
                    SET ContactNo = %s,
                        Email = %s,
                        DivisionID = %s,
                        RegionID = %s,
                        HubID = %s,
                        BranchID = %s,
                        BUType = %s,
                        Buid = %s,
                        UpdatedDate = GETDATE()
                    WHERE UserID = %s
                """, [
                    new_contact if new_contact is not None else old_contact,
                    new_email if new_email is not None else old_email,
                    new_div, new_reg, new_hub,
                    new_branch_id if new_branch_id is not None else old_branch,
                    new_butype, new_buid,
                    user_id
                ])

                # ------ Update role if changed ------
                if new_role_id is not None and int(new_role_id) != int(old_role_id or -1):
                    # Deactivate old role mapping
                    cursor.execute("""
                        UPDATE [dbo].[map_userRole]
                        SET IsActive = 0
                        WHERE UserID = %s
                    """, [user_id])
                    # Insert new active mapping
                    cursor.execute("""
                        INSERT INTO [dbo].[map_userRole] (UserID, RoleId, IsActive)
                        VALUES (%s, %s, 1)
                    """, [user_id, new_role_id])

                # Build change summary
                changes = []
                if new_role_id is not None and int(new_role_id) != int(old_role_id or -1):
                    changes.append({'field': 'Role', 'old': old_role_name, 'new': str(new_role_id)})
                if new_contact is not None and new_contact != old_contact:
                    changes.append({'field': 'ContactNo', 'old': old_contact, 'new': new_contact})
                if new_email is not None and new_email != old_email:
                    changes.append({'field': 'Email', 'old': old_email, 'new': new_email})
                if new_branch_id is not None and str(new_branch_id) != str(old_branch):
                    changes.append({'field': 'BranchID', 'old': str(old_branch), 'new': str(new_branch_id)})
                    changes.append({'field': 'Buid', 'old': str(old_buid), 'new': str(new_buid)})
                    changes.append({'field': 'DivisionID', 'old': str(old_div), 'new': str(new_div)})
                    changes.append({'field': 'RegionID', 'old': str(old_reg), 'new': str(new_reg)})
                    changes.append({'field': 'HubID', 'old': str(old_hub), 'new': str(new_hub)})

        log_info(f"Admin updated user {user_id}: {changes}")
        return send_encrypted_response({'success': True, 'message': 'User updated successfully', 'changes': changes})
    except Exception as ex:
        log_error(f"admin_save_user_view: failed: {str(ex)}")
        return send_encrypted_response({'success': False, 'message': f'Failed to update user: {str(ex)}'}, status_code=500)
