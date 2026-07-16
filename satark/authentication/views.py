import json
import datetime
import logging
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import jwt

from satark.cqrs import dispatcher
from .models import AccountsMstUsertbl, JWTToken
from .utils import log_info, log_error
from .commands import (
    LoginCommand, LoginCommandHandler,
    RefreshCommand, RefreshCommandHandler,
    SaveMenuCommand, SaveMenuCommandHandler,
    SaveUserCommand, SaveUserCommandHandler,
    CreateRoleCommand, CreateRoleCommandHandler,
    MapUserRoleCommand, MapUserRoleCommandHandler,
    CreateUserCommand, CreateUserCommandHandler,
)
from .queries import (
    GetMenuQuery, GetMenuQueryHandler,
    GetAdminMenuQuery, GetAdminMenuQueryHandler,
    GetUserListQuery, GetUserListQueryHandler,
    GetGeoHierarchyQuery, GetGeoHierarchyQueryHandler
)

logger = logging.getLogger("authentication.views")

# Register commands and queries with the dispatcher
dispatcher.register_command(LoginCommand, LoginCommandHandler())
dispatcher.register_command(RefreshCommand, RefreshCommandHandler())
dispatcher.register_command(SaveMenuCommand, SaveMenuCommandHandler())
dispatcher.register_command(SaveUserCommand, SaveUserCommandHandler())
dispatcher.register_command(CreateRoleCommand, CreateRoleCommandHandler())
dispatcher.register_command(MapUserRoleCommand, MapUserRoleCommandHandler())
dispatcher.register_command(CreateUserCommand, CreateUserCommandHandler())

dispatcher.register_query(GetMenuQuery, GetMenuQueryHandler())
dispatcher.register_query(GetAdminMenuQuery, GetAdminMenuQueryHandler())
dispatcher.register_query(GetUserListQuery, GetUserListQueryHandler())
dispatcher.register_query(GetGeoHierarchyQuery, GetGeoHierarchyQueryHandler())


# --- Reusable Security Helpers ---

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

def send_encrypted_response(data_dict, status_code=200):
    return JsonResponse(data_dict, status=status_code)


# --- View Endpoints ---

@csrf_exempt
def login_view(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body) if request.body else {}
        usercode = data.get('username', '').strip()
        password = data.get('password', '')
    except Exception as e:
        log_error(f"Login request parsing failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Invalid request body'}, status_code=400)

    if not usercode or not password:
        log_error("Login failed: usercode or password missing")
        return send_encrypted_response({'success': False, 'message': 'usercode and password are required'}, status_code=400)

    try:
        command = LoginCommand(usercode=usercode, password=password)
        result = dispatcher.send(command)
        status_code = result.pop('status_code', 200)
        return send_encrypted_response(result, status_code=status_code)
    except Exception as e:
        log_error(f"Login view failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Internal Server Error'}, status_code=500)


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

    try:
        command = RefreshCommand(refresh_token=refresh_token)
        result = dispatcher.send(command)
        status_code = result.pop('status_code', 200)
        return send_encrypted_response(result, status_code=status_code)
    except Exception as e:
        log_error(f"Refresh view failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Internal Server Error'}, status_code=500)


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

    try:
        query = GetMenuQuery(user_db_id=user.UserID)
        result = dispatcher.query(query)
        status_code = result.pop('status_code', 200)
        return send_encrypted_response(result, status_code=status_code)
    except Exception as e:
        log_error(f"Menu view failed: {str(e)}")
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
        query = GetAdminMenuQuery()
        result = dispatcher.query(query)
        status_code = result.pop('status_code', 200)
        return send_encrypted_response(result, status_code=status_code)
    except Exception as e:
        log_error(f"Admin menu view failed: {str(e)}")
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

    try:
        command = SaveMenuCommand(items=items, mappings=mappings)
        result = dispatcher.send(command)
        status_code = result.pop('status_code', 200)
        return send_encrypted_response(result, status_code=status_code)
    except Exception as e:
        log_error(f"Admin menu save view failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Internal Server Error'}, status_code=500)


@csrf_exempt
def admin_user_list_view(request):
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

    try:
        query = GetUserListQuery()
        result = dispatcher.query(query)
        status_code = result.pop('status_code', 200)
        return send_encrypted_response(result, status_code=status_code)
    except Exception as e:
        log_error(f"Admin user list view failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Internal Server Error'}, status_code=500)


@csrf_exempt
def admin_geo_hierarchy_view(request):
    """Lazy-loaded geographic hierarchy — called only when edit modal opens"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        log_error(f"admin_geo_hierarchy_view: parse failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Invalid request body'}, status_code=400)

    user = validate_token_user(token)
    if not user:
        return send_encrypted_response({'success': False, 'message': 'Invalid token'}, status_code=401)

    if not is_user_admin(user):
        return send_encrypted_response({'success': False, 'message': 'Access denied'}, status_code=403)

    try:
        query = GetGeoHierarchyQuery()
        result = dispatcher.query(query)
        status_code = result.pop('status_code', 200)
        return send_encrypted_response(result, status_code=status_code)
    except Exception as e:
        log_error(f"Admin geo hierarchy view failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Internal Server Error'}, status_code=500)


@csrf_exempt
def admin_save_user_view(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
        user_id = data.get('user_id')
        new_role_id = data.get('role_id')
        new_branch_id = data.get('branch_id')
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

    try:
        command = SaveUserCommand(
            user_id=user_id,
            role_id=new_role_id,
            branch_id=new_branch_id,
            contact_no=new_contact,
            email=new_email
        )
        result = dispatcher.send(command)
        status_code = result.pop('status_code', 200)
        return send_encrypted_response(result, status_code=status_code)
    except Exception as e:
        log_error(f"Admin save user view failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Internal Server Error'}, status_code=500)


@csrf_exempt
def create_role_view(request):
    """Create a new role in mst_role"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)
    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        return send_encrypted_response({'success': False, 'message': 'Invalid request body'}, status_code=400)

    user = validate_token_user(token)
    if not user:
        return send_encrypted_response({'success': False, 'message': 'Invalid token'}, status_code=401)
    if not is_user_admin(user):
        return send_encrypted_response({'success': False, 'message': 'Access denied'}, status_code=403)

    try:
        command = CreateRoleCommand(
            role_name=data.get('role_name', ''),
            description=data.get('description', '')
        )
        result = dispatcher.send(command)
        status_code = result.pop('status_code', 200)
        return send_encrypted_response(result, status_code=status_code)
    except Exception as e:
        log_error(f"create_role_view failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Internal Server Error'}, status_code=500)


@csrf_exempt
def map_user_role_view(request):
    """Map a UserID to a RoleID in map_userrole"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)
    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        return send_encrypted_response({'success': False, 'message': 'Invalid request body'}, status_code=400)

    user = validate_token_user(token)
    if not user:
        return send_encrypted_response({'success': False, 'message': 'Invalid token'}, status_code=401)
    if not is_user_admin(user):
        return send_encrypted_response({'success': False, 'message': 'Access denied'}, status_code=403)

    try:
        command = MapUserRoleCommand(
            user_id=data.get('user_id'),
            role_id=data.get('role_id'),
            is_active=data.get('is_active', True)
        )
        result = dispatcher.send(command)
        status_code = result.pop('status_code', 200)
        return send_encrypted_response(result, status_code=status_code)
    except Exception as e:
        log_error(f"map_user_role_view failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Internal Server Error'}, status_code=500)


@csrf_exempt
def create_user_view(request):
    """Create a new user in accounts_mst_usertbl with role mapping"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)
    try:
        data = json.loads(request.body) if request.body else {}
        token = data.get('token', '')
    except Exception as e:
        return send_encrypted_response({'success': False, 'message': 'Invalid request body'}, status_code=400)

    user = validate_token_user(token)
    if not user:
        return send_encrypted_response({'success': False, 'message': 'Invalid token'}, status_code=401)
    if not is_user_admin(user):
        return send_encrypted_response({'success': False, 'message': 'Access denied'}, status_code=403)

    try:
        command = CreateUserCommand(
            user_id=data.get('user_id'),
            user_name=data.get('user_name', ''),
            user_code=data.get('user_code', ''),
            contact_no=data.get('contact_no', ''),
            email=data.get('email', ''),
            branch_id=data.get('branch_id'),
            role_id=data.get('role_id'),
            is_active=data.get('is_active', True)
        )
        result = dispatcher.send(command)
        status_code = result.pop('status_code', 200)
        return send_encrypted_response(result, status_code=status_code)
    except Exception as e:
        log_error(f"create_user_view failed: {str(e)}")
        return send_encrypted_response({'success': False, 'message': 'Internal Server Error'}, status_code=500)

