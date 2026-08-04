import uuid
import json
import logging
import datetime
from django.db import connection, transaction
from django.utils import timezone

logger = logging.getLogger("authentication.user_tracking")

def ensure_tracking_tables_exist():
    """
    Ensures that user tracking tables exist in MSSQL DB.
    Uses raw SQL DDL with IF NOT EXISTS to safely create tables on startup.
    """
    sql_statements = [
        """
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'user_sessions')
        BEGIN
            CREATE TABLE [dbo].[user_sessions] (
                [session_id] NVARCHAR(64) PRIMARY KEY,
                [user_id] INT NOT NULL,
                [usercode] NVARCHAR(100) NOT NULL,
                [login_time] DATETIME NOT NULL DEFAULT GETDATE(),
                [logout_time] DATETIME NULL,
                [last_heartbeat] DATETIME NOT NULL DEFAULT GETDATE(),
                [total_active_seconds] INT NOT NULL DEFAULT 0,
                [total_idle_seconds] INT NOT NULL DEFAULT 0,
                [ip_address] NVARCHAR(45) NULL,
                [user_agent] NVARCHAR(500) NULL,
                [device_type] NVARCHAR(50) NULL,
                [browser] NVARCHAR(100) NULL,
                [os] NVARCHAR(100) NULL,
                [logout_reason] NVARCHAR(50) NULL DEFAULT 'MANUAL',
                [is_active] BIT NOT NULL DEFAULT 1
            );
        END;
        """,
        """
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'user_screen_logs')
        BEGIN
            CREATE TABLE [dbo].[user_screen_logs] (
                [log_id] BIGINT IDENTITY(1,1) PRIMARY KEY,
                [session_id] NVARCHAR(64) NOT NULL,
                [user_id] INT NOT NULL,
                [usercode] NVARCHAR(100) NOT NULL,
                [screen_name] NVARCHAR(150) NOT NULL,
                [path] NVARCHAR(255) NOT NULL,
                [enter_time] DATETIME NOT NULL DEFAULT GETDATE(),
                [leave_time] DATETIME NULL,
                [active_duration_seconds] INT NOT NULL DEFAULT 0,
                [idle_duration_seconds] INT NOT NULL DEFAULT 0
            );
        END;
        """,
        """
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'user_api_logs')
        BEGIN
            CREATE TABLE [dbo].[user_api_logs] (
                [log_id] BIGINT IDENTITY(1,1) PRIMARY KEY,
                [session_id] NVARCHAR(64) NULL,
                [user_id] INT NULL,
                [usercode] NVARCHAR(100) NULL,
                [endpoint] NVARCHAR(255) NOT NULL,
                [http_method] NVARCHAR(10) NOT NULL,
                [status_code] INT NOT NULL,
                [response_time_ms] INT NOT NULL DEFAULT 0,
                [created_at] DATETIME NOT NULL DEFAULT GETDATE(),
                [client_ip] NVARCHAR(45) NULL
            );
        END;
        """,
        """
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'user_activity_events')
        BEGIN
            CREATE TABLE [dbo].[user_activity_events] (
                [event_id] BIGINT IDENTITY(1,1) PRIMARY KEY,
                [session_id] NVARCHAR(64) NULL,
                [user_id] INT NOT NULL,
                [usercode] NVARCHAR(100) NOT NULL,
                [event_type] NVARCHAR(100) NOT NULL,
                [metadata_json] NVARCHAR(MAX) NULL,
                [created_at] DATETIME NOT NULL DEFAULT GETDATE()
            );
        END;
        """
    ]
    try:
        with connection.cursor() as cursor:
            for stmt in sql_statements:
                cursor.execute(stmt)
        logger.info("User tracking MSSQL tables verified/created successfully.")
    except Exception as e:
        logger.error(f"Error ensuring tracking tables: {str(e)}")

# Safe parse device / browser helpers
def parse_user_agent(ua_string):
    if not ua_string:
        return {'device': 'Desktop', 'browser': 'Unknown', 'os': 'Unknown'}
    ua = ua_string.lower()
    device = 'Mobile' if ('mobile' in ua or 'android' in ua or 'iphone' in ua) else 'Desktop'
    
    if 'chrome' in ua and 'edg' not in ua:
        browser = 'Chrome'
    elif 'edg' in ua:
        browser = 'Edge'
    elif 'firefox' in ua:
        browser = 'Firefox'
    elif 'safari' in ua and 'chrome' not in ua:
        browser = 'Safari'
    else:
        browser = 'Browser/Other'

    if 'windows' in ua:
        os_name = 'Windows'
    elif 'mac' in ua:
        os_name = 'macOS'
    elif 'linux' in ua:
        os_name = 'Linux'
    elif 'android' in ua:
        os_name = 'Android'
    elif 'iphone' in ua or 'ipad' in ua:
        os_name = 'iOS'
    else:
        os_name = 'Unknown OS'

    return {'device': device, 'browser': browser, 'os': os_name}


# --- Tracking Operations (Raw SQL) ---

def record_session_start(user_id, usercode, ip_address='', user_agent=''):
    """Initializes a new user tracking session in user_sessions table."""
    session_id = f"sess_{uuid.uuid4().hex[:20]}"
    parsed = parse_user_agent(user_agent)
    now = datetime.datetime.now()
    
    try:
        ensure_tracking_tables_exist()
        with connection.cursor() as cursor:
            # End any existing active sessions for this user to avoid ghost active sessions
            cursor.execute("""
                UPDATE [dbo].[user_sessions]
                SET [is_active] = 0, [logout_time] = %s, [logout_reason] = 'NEW_LOGIN_OVERWRITE'
                WHERE [user_id] = %s AND [is_active] = 1
            """, [now, user_id])
            
            cursor.execute("""
                INSERT INTO [dbo].[user_sessions]
                ([session_id], [user_id], [usercode], [login_time], [last_heartbeat],
                 [ip_address], [user_agent], [device_type], [browser], [os], [is_active])
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
            """, [session_id, user_id, usercode, now, now, ip_address, user_agent[:500],
                  parsed['device'], parsed['browser'], parsed['os']])
            
            # Record activity event
            cursor.execute("""
                INSERT INTO [dbo].[user_activity_events]
                ([session_id], [user_id], [usercode], [event_type], [metadata_json], [created_at])
                VALUES (%s, %s, %s, 'LOGIN', %s, %s)
            """, [session_id, user_id, usercode, json.dumps({'ip': ip_address, 'browser': parsed['browser']}), now])
            
        return session_id
    except Exception as e:
        logger.error(f"Failed to record session start: {str(e)}")
        return session_id


def record_session_heartbeat(session_id, active_delta=0, idle_delta=0):
    """Updates last heartbeat timestamp and increments active/idle seconds."""
    if not session_id:
        return False
    now = datetime.datetime.now()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE [dbo].[user_sessions]
                SET [last_heartbeat] = %s,
                    [total_active_seconds] = [total_active_seconds] + %s,
                    [total_idle_seconds] = [total_idle_seconds] + %s
                WHERE [session_id] = %s AND [is_active] = 1
            """, [now, max(0, int(active_delta)), max(0, int(idle_delta)), session_id])
        return True
    except Exception as e:
        logger.error(f"Failed to record heartbeat for session {session_id}: {str(e)}")
        return False


def record_session_end(session_id, reason='MANUAL'):
    """Marks session as closed with logout reason (MANUAL, IDLE_TIMEOUT, etc.)"""
    if not session_id:
        return False
    now = datetime.datetime.now()
    try:
        with connection.cursor() as cursor:
            # Fetch user details for log event
            cursor.execute("""
                SELECT [user_id], [usercode] FROM [dbo].[user_sessions] WHERE [session_id] = %s
            """, [session_id])
            row = cursor.fetchone()
            
            cursor.execute("""
                UPDATE [dbo].[user_sessions]
                SET [logout_time] = %s,
                    [logout_reason] = %s,
                    [is_active] = 0
                WHERE [session_id] = %s
            """, [now, reason, session_id])
            
            if row:
                u_id, u_code = row[0], row[1]
                cursor.execute("""
                    INSERT INTO [dbo].[user_activity_events]
                    ([session_id], [user_id], [usercode], [event_type], [metadata_json], [created_at])
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, [session_id, u_id, u_code, 'LOGOUT' if reason=='MANUAL' else reason, json.dumps({'reason': reason}), now])
        return True
    except Exception as e:
        logger.error(f"Failed to record session end: {str(e)}")
        return False


def record_screen_log(session_id, user_id, usercode, screen_name, path, active_sec=0, idle_sec=0):
    """Logs user visit to a specific frontend screen/route with active time spent."""
    if not user_id or not path:
        return False
    now = datetime.datetime.now()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO [dbo].[user_screen_logs]
                ([session_id], [user_id], [usercode], [screen_name], [path], [enter_time], [leave_time],
                 [active_duration_seconds], [idle_duration_seconds])
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, [session_id or '', user_id, usercode, screen_name or path, path, now, now, max(0, int(active_sec)), max(0, int(idle_sec))])
        return True
    except Exception as e:
        logger.error(f"Failed to record screen log: {str(e)}")
        return False


def record_api_log(session_id, user_id, usercode, endpoint, method, status_code, response_time_ms, client_ip=''):
    """Logs API call telemetry."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO [dbo].[user_api_logs]
                ([session_id], [user_id], [usercode], [endpoint], [http_method], [status_code], [response_time_ms], [created_at], [client_ip])
                VALUES (%s, %s, %s, %s, %s, %s, %s, GETDATE(), %s)
            """, [session_id or '', user_id, usercode or 'ANONYMOUS', endpoint, method, int(status_code), int(response_time_ms), client_ip])
        return True
    except Exception as e:
        logger.error(f"Failed to record API log: {str(e)}")
        return False


# --- Admin Telemetry & Aggregation Analytics Queries (Raw SQL) ---

def get_analytics_overview():
    """Generates high-level metrics for Admin Dashboard using Raw SQL."""
    ensure_tracking_tables_exist()
    overview = {
        'total_sessions': 0,
        'currently_active_users': 0,
        'total_active_hours': 0,
        'avg_session_duration_mins': 0,
        'top_screen': 'N/A',
        'top_api': 'N/A',
        'total_screen_views': 0,
        'total_api_calls': 0
    }
    try:
        with connection.cursor() as cursor:
            # Total sessions
            cursor.execute("SELECT COUNT(*) FROM [dbo].[user_sessions]")
            overview['total_sessions'] = cursor.fetchone()[0]

            # Currently active users (heartbeat within last 2 minutes)
            cursor.execute("""
                SELECT COUNT(DISTINCT user_id) 
                FROM [dbo].[user_sessions] 
                WHERE [is_active] = 1 AND DATEDIFF(second, last_heartbeat, GETDATE()) <= 120
            """)
            overview['currently_active_users'] = cursor.fetchone()[0]

            # Total active hours & avg session duration
            cursor.execute("""
                SELECT ISNULL(SUM([total_active_seconds]), 0), ISNULL(AVG([total_active_seconds]), 0)
                FROM [dbo].[user_sessions]
            """)
            row = cursor.fetchone()
            if row:
                overview['total_active_hours'] = round(row[0] / 3600.0, 1)
                overview['avg_session_duration_mins'] = round(row[1] / 60.0, 1)

            # Top screen
            cursor.execute("""
                SELECT TOP 1 [screen_name], COUNT(*) as cnt
                FROM [dbo].[user_screen_logs]
                GROUP BY [screen_name]
                ORDER BY cnt DESC
            """)
            top_s = cursor.fetchone()
            if top_s:
                overview['top_screen'] = top_s[0]

            # Top API (excluding internal tracking/telemetry APIs)
            cursor.execute("""
                SELECT TOP 1 [endpoint], COUNT(*) as cnt
                FROM [dbo].[user_api_logs]
                WHERE [endpoint] NOT LIKE '/auth/session/%' 
                  AND [endpoint] NOT LIKE '/auth/admin/analytics/%'
                  AND [endpoint] NOT LIKE '%/analytics/%'
                GROUP BY [endpoint]
                ORDER BY cnt DESC
            """)
            top_a = cursor.fetchone()
            if top_a:
                overview['top_api'] = top_a[0]

            # Screen view count
            cursor.execute("SELECT COUNT(*) FROM [dbo].[user_screen_logs]")
            overview['total_screen_views'] = cursor.fetchone()[0]

            # API call count (excluding internal tracking/telemetry APIs)
            cursor.execute("""
                SELECT COUNT(*) FROM [dbo].[user_api_logs]
                WHERE [endpoint] NOT LIKE '/auth/session/%' 
                  AND [endpoint] NOT LIKE '/auth/admin/analytics/%'
                  AND [endpoint] NOT LIKE '%/analytics/%'
            """)
            overview['total_api_calls'] = cursor.fetchone()[0]

    except Exception as e:
        logger.error(f"Error fetching analytics overview: {str(e)}")

    return overview


def get_screen_analytics():
    """Fetches top visited screens and screen usage matrix."""
    screens = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT [screen_name], [path],
                       COUNT(*) as visit_count,
                       COUNT(DISTINCT [user_id]) as unique_users,
                       ISNULL(SUM([active_duration_seconds]), 0) as total_active_sec,
                       ISNULL(AVG([active_duration_seconds]), 0) as avg_active_sec
                FROM [dbo].[user_screen_logs]
                GROUP BY [screen_name], [path]
                ORDER BY visit_count DESC
            """)
            rows = cursor.fetchall()
            for name, path, visits, users, total_sec, avg_sec in rows:
                screens.append({
                    'screen_name': name,
                    'path': path,
                    'visit_count': visits,
                    'unique_users': users,
                    'total_active_mins': round(total_sec / 60.0, 1),
                    'avg_duration_sec': int(avg_sec)
                })
    except Exception as e:
        logger.error(f"Error fetching screen analytics: {str(e)}")
    return screens


def get_api_analytics():
    """Fetches most frequently called APIs and response performance (excluding internal tracking/analytics APIs)."""
    apis = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT [endpoint], [http_method],
                       COUNT(*) as total_calls,
                       ISNULL(AVG([response_time_ms]), 0) as avg_latency_ms,
                       SUM(CASE WHEN [status_code] >= 400 THEN 1 ELSE 0 END) as error_count
                FROM [dbo].[user_api_logs]
                WHERE [endpoint] NOT LIKE '/auth/session/%' 
                  AND [endpoint] NOT LIKE '/auth/admin/analytics/%'
                  AND [endpoint] NOT LIKE '%/analytics/%'
                GROUP BY [endpoint], [http_method]
                ORDER BY total_calls DESC
            """)
            rows = cursor.fetchall()
            for ep, method, calls, avg_ms, errors in rows:
                apis.append({
                    'endpoint': ep,
                    'method': method,
                    'total_calls': calls,
                    'avg_latency_ms': int(avg_ms),
                    'error_count': errors,
                    'success_rate': round(((calls - errors) / max(1, calls)) * 100.0, 1)
                })
    except Exception as e:
        logger.error(f"Error fetching API analytics: {str(e)}")
    return apis


def get_user_analytics_list():
    """Fetches detailed telemetry breakdown per user."""
    user_list = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT s.[user_id], s.[usercode],
                       COUNT(DISTINCT s.[session_id]) as total_sessions,
                       ISNULL(SUM(s.[total_active_seconds]), 0) as total_active_sec,
                       MAX(s.[login_time]) as last_login,
                       MAX(s.[last_heartbeat]) as last_active,
                       (SELECT TOP 1 [screen_name] 
                        FROM [dbo].[user_screen_logs] sl 
                        WHERE sl.[user_id] = s.[user_id] 
                        GROUP BY [screen_name] 
                        ORDER BY COUNT(*) DESC) as top_screen
                FROM [dbo].[user_sessions] s
                GROUP BY s.[user_id], s.[usercode]
                ORDER BY total_active_sec DESC
            """)
            rows = cursor.fetchall()
            for u_id, u_code, sess_cnt, act_sec, last_log, last_act, top_scr in rows:
                user_list.append({
                    'user_id': u_id,
                    'usercode': u_code,
                    'total_sessions': sess_cnt,
                    'total_active_mins': round(act_sec / 60.0, 1),
                    'last_login': last_log.strftime('%Y-%m-%d %H:%M:%S') if last_log else 'N/A',
                    'last_active': last_act.strftime('%Y-%m-%d %H:%M:%S') if last_act else 'N/A',
                    'top_screen': top_scr or 'N/A'
                })
    except Exception as e:
        logger.error(f"Error fetching user analytics list: {str(e)}")
    return user_list


def get_live_users():
    """Fetches currently online active users."""
    live_users = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT [session_id], [user_id], [usercode], [login_time], [last_heartbeat],
                       [total_active_seconds], [ip_address], [browser], [os], [device_type]
                FROM [dbo].[user_sessions]
                WHERE [is_active] = 1 AND DATEDIFF(second, [last_heartbeat], GETDATE()) <= 120
                ORDER BY [last_heartbeat] DESC
            """)
            rows = cursor.fetchall()
            for sess_id, u_id, u_code, log_t, last_h, act_sec, ip, br, os_n, dev in rows:
                live_users.append({
                    'session_id': sess_id,
                    'user_id': u_id,
                    'usercode': u_code,
                    'login_time': log_t.strftime('%Y-%m-%d %H:%M:%S') if log_t else '',
                    'last_heartbeat': last_h.strftime('%Y-%m-%d %H:%M:%S') if last_h else '',
                    'active_mins': round(act_sec / 60.0, 1),
                    'ip': ip or 'N/A',
                    'browser': br or 'Unknown',
                    'os': os_n or 'Unknown',
                    'device': dev or 'Desktop'
                })
    except Exception as e:
        logger.error(f"Error fetching live users: {str(e)}")
    return live_users


def get_session_logs(limit=100):
    """Fetches recent session logs for audit stream."""
    logs = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"""
                SELECT TOP {int(limit)} [session_id], [user_id], [usercode], [login_time], [logout_time],
                       [total_active_seconds], [total_idle_seconds], [ip_address], [browser], [logout_reason], [is_active]
                FROM [dbo].[user_sessions]
                ORDER BY [login_time] DESC
            """)
            rows = cursor.fetchall()
            for s_id, u_id, u_code, log_t, out_t, act_s, idle_s, ip, br, reason, is_act in rows:
                logs.append({
                    'session_id': s_id,
                    'user_id': u_id,
                    'usercode': u_code,
                    'login_time': log_t.strftime('%Y-%m-%d %H:%M:%S') if log_t else '',
                    'logout_time': out_t.strftime('%Y-%m-%d %H:%M:%S') if out_t else ('ACTIVE' if is_act else 'N/A'),
                    'active_duration_mins': round(act_s / 60.0, 1),
                    'idle_duration_mins': round(idle_s / 60.0, 1),
                    'ip': ip or 'N/A',
                    'browser': br or 'N/A',
                    'logout_reason': reason or ('Active' if is_act else 'Closed'),
                    'is_active': is_act
                })
    except Exception as e:
        logger.error(f"Error fetching session logs: {str(e)}")
    return logs
