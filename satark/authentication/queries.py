import logging
from django.db import connection
from satark.cqrs import Query, QueryHandler
from .utils import log_error

logger = logging.getLogger("authentication.queries")


class GetMenuQuery(Query):
    """Query to retrieve active menu items for a specific user role"""
    def __init__(self, user_db_id: int):
        self.user_db_id = user_db_id


class GetMenuQueryHandler(QueryHandler):
    """Handles GetMenuQuery execution"""
    def execute(self, query: GetMenuQuery) -> dict:
        user_db_id = query.user_db_id

        db_role_id = None
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT RoleId
                    FROM [dbo].[map_userRole]
                    WHERE UserID = %s AND IsActive = 1
                """, [user_db_id])
                row = cursor.fetchone()
                if row:
                    db_role_id = row[0]
        except Exception as e:
            log_error(f"Failed to query database user role: {str(e)}")

        if not db_role_id:
            return {'success': True, 'items': [], 'status_code': 200}

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
            
            return {'success': True, 'items': items_list, 'status_code': 200}
        except Exception as e:
            log_error(f"Failed to load menu list: {str(e)}")
            return {'success': False, 'message': 'Internal Server Error', 'status_code': 500}


class GetAdminMenuQuery(Query):
    """Query to fetch complete menu configuration structure for admin view"""
    pass


class GetAdminMenuQueryHandler(QueryHandler):
    """Handles GetAdminMenuQuery execution"""
    def execute(self, query: GetAdminMenuQuery) -> dict:
        try:
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

            return {
                'success': True,
                'roles': roles,
                'items': items,
                'mappings': mappings,
                'status_code': 200
            }
        except Exception as e:
            log_error(f"Failed to fetch admin menu config: {str(e)}")
            return {'success': False, 'message': 'Internal Server Error', 'status_code': 500}


class GetUserListQuery(Query):
    """Query to fetch user list with roles — geo hierarchy is loaded separately via GetGeoHierarchyQuery"""
    pass


class GetUserListQueryHandler(QueryHandler):
    """Handles GetUserListQuery execution — fast query, no geo hierarchy"""
    def execute(self, query: GetUserListQuery) -> dict:
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

            return {
                'success': True,
                'users': users,
                'roles': roles,
                'status_code': 200
            }
        except Exception as e:
            log_error(f"admin_user_list_view: DB error: {str(e)}")
            return {'success': False, 'message': f'Internal Server Error: {str(e)}', 'status_code': 500}


class GetGeoHierarchyQuery(Query):
    """Query to fetch full geographic hierarchy — called lazily when edit modal opens"""
    pass


class GetGeoHierarchyQueryHandler(QueryHandler):
    """Handles GetGeoHierarchyQuery execution"""
    def execute(self, query: GetGeoHierarchyQuery) -> dict:
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT DISTINCT Zone, DivisionID, Division, RegionID, Region, HubID, Hub, BranchID, Branch
                    FROM [dbo].[VW_Branch_To_GeographicalHierarchy]
                    ORDER BY Zone, Division, Region, Hub, Branch
                """)
                geo_cols = [d[0] for d in cursor.description]
                geo_rows = [dict(zip(geo_cols, row)) for row in cursor.fetchall()]

            return {
                'success': True,
                'geo_hierarchy': geo_rows,
                'status_code': 200
            }
        except Exception as e:
            log_error(f"GetGeoHierarchyQuery: DB error: {str(e)}")
            return {'success': False, 'message': f'Internal Server Error: {str(e)}', 'status_code': 500}
