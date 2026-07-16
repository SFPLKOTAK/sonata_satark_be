import json
import datetime
import logging
import jwt
from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.db import connection, transaction
from django.utils import timezone
from satark.cqrs import Command, CommandHandler
from .models import AccountsMstUsertbl, JWTToken
from .utils import log_info, log_error

logger = logging.getLogger("authentication.commands")

# Helper functions originally in views.py
def get_current_ist():
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


class LoginCommand(Command):
    """Command representing user login credentials"""
    def __init__(self, usercode: str, password: str):
        self.usercode = usercode
        self.password = password


class LoginCommandHandler(CommandHandler):
    """Handles execution of LoginCommand"""
    def execute(self, command: LoginCommand) -> dict:
        usercode = command.usercode
        password = command.password

        try:
            user = AccountsMstUsertbl.objects.get(UserCode=usercode)
        except AccountsMstUsertbl.DoesNotExist:
            log_error(f"Login failed: User {usercode} not found")
            return {'success': False, 'message': 'Invalid usercode or password', 'status_code': 401}

        if user.password is None or not check_password(password, user.password):
            log_error(f"Login failed: Invalid password for user {usercode}")
            return {'success': False, 'message': 'Invalid usercode or password', 'status_code': 401}

        if not user.is_active:
            log_error(f"Login failed: User {usercode} account is inactive")
            return {'success': False, 'message': 'User account is inactive', 'status_code': 403}

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
            13: 'COMPLIANCE_HEAD',
        }

        ROLE_LABELS = {
            'ADMIN': 'Administrator',
            'AUDIT_HEAD': 'Audit Head (HO)',
            'ZONAL_HEAD': 'Zonal Audit Head',
            'DIVISION_HEAD': 'Division Audit Head',
            'AUDITOR': 'Field Auditor',
            'AUDITEE': 'Auditee (Branch Mgr)',
            'COMPLIANCE_HEAD': 'Compliance Head',
        }

        LEVEL_MAPPING = {
            'ADMIN': 'Admin',
            'AUDIT_HEAD': 'L1',
            'ZONAL_HEAD': 'L2',
            'DIVISION_HEAD': 'L3',
            'AUDITOR': 'L4',
            'AUDITEE': 'BM',
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

        return {
            'success': True,
            'access_token': access_token,
            'refresh_token': refresh_token,
            'user': user_details,
            'status_code': 200
        }


class RefreshCommand(Command):
    """Command representing intent to refresh an expired access token"""
    def __init__(self, refresh_token: str):
        self.refresh_token = refresh_token


class RefreshCommandHandler(CommandHandler):
    """Handles execution of RefreshCommand"""
    def execute(self, command: RefreshCommand) -> dict:
        refresh_token = command.refresh_token

        try:
            token_record = JWTToken.objects.get(refresh_token=refresh_token)
        except JWTToken.DoesNotExist:
            log_error("Refresh failed: Token record not found in database")
            return {'success': False, 'message': 'Invalid refresh token', 'status_code': 401}

        now_ist = get_current_ist()

        # Check if refresh token is expired in DB
        if token_record.refresh_expires_at < now_ist:
            log_error(f"Refresh failed: Token expired in database at {token_record.refresh_expires_at}")
            token_record.delete()
            return {'success': False, 'message': 'Refresh token expired', 'status_code': 401}

        # Verify signature and expiration via PyJWT
        try:
            jwt.decode(refresh_token, settings.SECRET_KEY, algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            log_error("Refresh failed: JWT signature expired")
            token_record.delete()
            return {'success': False, 'message': 'Refresh token signature expired', 'status_code': 401}
        except jwt.InvalidTokenError:
            log_error("Refresh failed: JWT signature invalid")
            return {'success': False, 'message': 'Invalid refresh token signature', 'status_code': 401}

        user = token_record.user
        new_access_token = generate_access_token(user)

        try:
            token_record.access_token = new_access_token
            token_record.access_expires_at = now_ist + datetime.timedelta(hours=1)
            token_record.save()
        except Exception as e:
            log_error(f"Failed to update database access token during refresh: {str(e)}")

        log_info(f"Token refresh successful for user: {user.UserCode}")

        return {
            'success': True,
            'access_token': new_access_token,
            'status_code': 200
        }


class SaveMenuCommand(Command):
    """Command representing intent to save menu structure and mappings"""
    def __init__(self, items: list, mappings: list):
        self.items = items
        self.mappings = mappings


class SaveMenuCommandHandler(CommandHandler):
    """Handles execution of SaveMenuCommand"""
    def execute(self, command: SaveMenuCommand) -> dict:
        items = command.items
        mappings = command.mappings

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
            return {'success': True, 'message': 'Menu configuration saved successfully', 'status_code': 200}
        except Exception as ex:
            log_error(f"Failed to save menu configuration: {str(ex)}")
            return {'success': False, 'message': f'Failed to save configuration: {str(ex)}', 'status_code': 500}


class SaveUserCommand(Command):
    """Command representing intent to update/save user details and role mapping"""
    def __init__(self, user_id, role_id=None, branch_id=None, contact_no=None, email=None):
        self.user_id = user_id
        self.role_id = role_id
        self.branch_id = branch_id
        self.contact_no = contact_no
        self.email = email


class SaveUserCommandHandler(CommandHandler):
    """Handles execution of SaveUserCommand"""
    def execute(self, command: SaveUserCommand) -> dict:
        user_id = command.user_id
        new_role_id = command.role_id
        new_branch_id = command.branch_id
        new_contact = command.contact_no
        new_email = command.email

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
                        return {'success': False, 'message': 'User not found', 'status_code': 404}

                    old_contact, old_email, old_hoid, old_div, old_reg, old_hub, old_branch, old_butype, old_buid, old_role_id, old_role_name = row

                    # ------ Resolve geographic fields ------
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
                            new_buid = resolved_branch
                            new_butype = 4
                        else:
                            return {'success': False, 'message': f'Branch ID {new_branch_id} not found in hierarchy', 'status_code': 400}

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
                        cursor.execute("""
                            UPDATE [dbo].[map_userRole]
                            SET IsActive = 0
                            WHERE UserID = %s
                        """, [user_id])
                        cursor.execute("""
                            INSERT INTO [dbo].[map_userRole] (UserID, RoleId, IsActive)
                            VALUES (%s, %s, 1)
                        """, [user_id, new_role_id])

                    # Build changes summary
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
            return {'success': True, 'message': 'User updated successfully', 'changes': changes, 'status_code': 200}
        except Exception as ex:
            log_error(f"admin_save_user_view: failed: {str(ex)}")
            return {'success': False, 'message': f'Failed to update user: {str(ex)}', 'status_code': 500}


# ─── Create Role ──────────────────────────────────────────────────────────────

class CreateRoleCommand(Command):
    """Command to insert a new role into mst_role"""
    def __init__(self, role_name: str, description: str):
        self.role_name = role_name
        self.description = description


class CreateRoleCommandHandler(CommandHandler):
    """Handles CreateRoleCommand — inserts into mst_role"""
    def execute(self, command: CreateRoleCommand) -> dict:
        role_name = (command.role_name or '').strip()
        description = (command.description or '').strip() or role_name
        if not role_name:
            return {'success': False, 'message': 'Role name is required', 'status_code': 400}
        try:
            with connection.cursor() as cursor:
                # Check duplicate
                cursor.execute("SELECT COUNT(*) FROM [dbo].[mst_role] WHERE RoleName = %s", [role_name])
                if cursor.fetchone()[0] > 0:
                    return {'success': False, 'message': f"Role '{role_name}' already exists", 'status_code': 409}

                cursor.execute("""
                    INSERT INTO [dbo].[mst_role] (RoleName, Description, CreatedDate, UpdatedDate, CreatedBy, UpdatedBy, IsDeleted, Approved)
                    VALUES (%s, %s, GETDATE(), GETDATE(), 1, 1, 0, 1)
                """, [role_name, description])

                cursor.execute("SELECT RoleId, RoleName FROM [dbo].[mst_role] WHERE RoleName = %s", [role_name])
                row = cursor.fetchone()
                new_role_id = row[0] if row else None

            log_info(f"New role created: {role_name} (ID={new_role_id})")
            return {
                'success': True,
                'message': f"Role '{role_name}' created successfully",
                'role_id': new_role_id,
                'role_name': role_name,
                'status_code': 201
            }
        except Exception as ex:
            log_error(f"CreateRoleCommand failed: {str(ex)}")
            return {'success': False, 'message': f'Failed to create role: {str(ex)}', 'status_code': 500}


# ─── Map User Role ─────────────────────────────────────────────────────────────

class MapUserRoleCommand(Command):
    """Command to map a UserID to a RoleID in map_userrole"""
    def __init__(self, user_id: int, role_id: int, is_active: bool = True):
        self.user_id = user_id
        self.role_id = role_id
        self.is_active = is_active


class MapUserRoleCommandHandler(CommandHandler):
    """Handles MapUserRoleCommand — inserts/updates map_userrole"""
    def execute(self, command: MapUserRoleCommand) -> dict:
        user_id = command.user_id
        role_id = command.role_id
        is_active = 1 if command.is_active else 0

        if not user_id or not role_id:
            return {'success': False, 'message': 'user_id and role_id are required', 'status_code': 400}
        try:
            with connection.cursor() as cursor:
                # Check user exists
                cursor.execute("SELECT COUNT(*) FROM [dbo].[accounts_mst_usertbl] WHERE UserID = %s", [user_id])
                if cursor.fetchone()[0] == 0:
                    return {'success': False, 'message': f'UserID {user_id} does not exist in accounts_mst_usertbl', 'status_code': 404}

                # Check role exists
                cursor.execute("SELECT RoleName FROM [dbo].[mst_role] WHERE RoleId = %s", [role_id])
                role_row = cursor.fetchone()
                if not role_row:
                    return {'success': False, 'message': f'RoleID {role_id} does not exist', 'status_code': 404}
                role_name = role_row[0]

                # Deactivate existing mappings for user
                cursor.execute("UPDATE [dbo].[map_userRole] SET IsActive = 0 WHERE UserID = %s", [user_id])

                # Insert new mapping
                cursor.execute("""
                    INSERT INTO [dbo].[map_userRole] (RoleId, UserID, IsActive, CreatedDate)
                    VALUES (%s, %s, %s, GETDATE())
                """, [role_id, user_id, is_active])

            log_info(f"User {user_id} mapped to role {role_name} (ID={role_id}), IsActive={is_active}")
            return {
                'success': True,
                'message': f'User {user_id} mapped to role "{role_name}" successfully',
                'status_code': 200
            }
        except Exception as ex:
            log_error(f"MapUserRoleCommand failed: {str(ex)}")
            return {'success': False, 'message': f'Failed to map user role: {str(ex)}', 'status_code': 500}


# ─── Create User ───────────────────────────────────────────────────────────────

class CreateUserCommand(Command):
    """Command to create a new user in accounts_mst_usertbl and optionally map their role"""
    def __init__(self, user_id: int, user_name: str, user_code: str,
                 contact_no: str, email: str, branch_id,
                 role_id, is_active: bool = True):
        self.user_id = user_id
        self.user_name = user_name
        self.user_code = user_code
        self.contact_no = contact_no
        self.email = email
        self.branch_id = branch_id
        self.role_id = role_id
        self.is_active = is_active


class CreateUserCommandHandler(CommandHandler):
    """Handles CreateUserCommand — inserts into accounts_mst_usertbl and maps role"""
    def execute(self, command: CreateUserCommand) -> dict:
        user_id   = command.user_id
        user_name = (command.user_name or '').strip()
        user_code = (command.user_code or f'UC_{user_id}').strip()
        contact   = command.contact_no or '0'
        email     = command.email or ''
        branch_id = command.branch_id
        role_id   = command.role_id
        is_active = 1 if command.is_active else 0

        if not user_id:
            return {'success': False, 'message': 'user_id (EmpID) is required', 'status_code': 400}
        if not user_name:
            return {'success': False, 'message': 'user_name is required', 'status_code': 400}

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    # Check duplicate UserID
                    cursor.execute("SELECT COUNT(*) FROM [dbo].[accounts_mst_usertbl] WHERE UserID = %s", [user_id])
                    if cursor.fetchone()[0] > 0:
                        return {'success': False, 'message': f'UserID {user_id} already exists', 'status_code': 409}

                    # Check duplicate UserCode
                    cursor.execute("SELECT COUNT(*) FROM [dbo].[accounts_mst_usertbl] WHERE UserCode = %s", [user_code])
                    if cursor.fetchone()[0] > 0:
                        return {'success': False, 'message': f'UserCode "{user_code}" already exists', 'status_code': 409}

                    # Resolve role designation
                    designation_id = int(role_id) if role_id else 0
                    buid = float(branch_id) if branch_id else 0.0

                    cursor.execute("""
                        INSERT INTO [dbo].[accounts_mst_usertbl] (
                            UserID, EmpID, DesignationID, UserName, UserCode, ContactNo,
                            Hoid, DivisionID, RegionID, HubID, BranchID,
                            BranchJoinDate, BranchExitDate, Comment, Email,
                            IsActive, CreatedBy, CreatedDate, Locked, LastPasswordDate,
                            BUType, Buid, IsLoggedin, New, NewBranchId,
                            EmpDOB, GLAccountId, AccountId, IsDropout, DropoutDate,
                            IsHelpDeskStaff, registration_authenticated,
                            date_joined, last_login, is_admin,
                            is_active, is_staff, is_superuser, deactivated
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s,
                            1,  0,  0,  0,  %s,
                            GETDATE(), NULL, NULL, %s,
                            %s, 1, GETDATE(), 0, GETDATE(),
                            0, %s, 1, 0, NULL,
                            NULL, NULL, NULL, 0, NULL,
                            0, 1,
                            GETDATE(), GETDATE(), 0,
                            %s, 0, 0, 0
                        )
                    """, [
                        user_id, user_id, designation_id, user_name, user_code, contact,
                        str(branch_id) if branch_id else None,
                        email, is_active,
                        buid,
                        is_active
                    ])

                    # Map role if provided
                    if role_id:
                        cursor.execute("UPDATE [dbo].[map_userRole] SET IsActive = 0 WHERE UserID = %s", [user_id])
                        cursor.execute("""
                            INSERT INTO [dbo].[map_userRole] (RoleId, UserID, IsActive, CreatedDate)
                            VALUES (%s, %s, 1, GETDATE())
                        """, [role_id, user_id])

            log_info(f"New user created: {user_name} (ID={user_id}, Code={user_code}, Role={role_id})")
            return {
                'success': True,
                'message': f'User "{user_name}" created successfully',
                'user_id': user_id,
                'user_code': user_code,
                'status_code': 201
            }
        except Exception as ex:
            log_error(f"CreateUserCommand failed: {str(ex)}")
            return {'success': False, 'message': f'Failed to create user: {str(ex)}', 'status_code': 500}

