import json
import logging
from datetime import date, timedelta
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import connection

from satark.cqrs import dispatcher
from .commands import GenerateAuditPlanCommand, GenerateAuditPlanCommandHandler
from .queries import (
    GetCurrentPlanQuery, GetCurrentPlanQueryHandler,
    GetPlannerOverviewQuery, GetPlannerOverviewQueryHandler,
    GetCapacityDataQuery, GetCapacityDataQueryHandler
)

logger = logging.getLogger("planner.views")

# Register commands and queries with the global dispatcher
dispatcher.register_command(GenerateAuditPlanCommand, GenerateAuditPlanCommandHandler())
dispatcher.register_query(GetCurrentPlanQuery, GetCurrentPlanQueryHandler())
dispatcher.register_query(GetPlannerOverviewQuery, GetPlannerOverviewQueryHandler())
dispatcher.register_query(GetCapacityDataQuery, GetCapacityDataQueryHandler())


@csrf_exempt
def generate_audit_plan(request):
    """
    API endpoint to generate audit plans.
    POST JSON body:
    {
        "as_on_date": "2026-06-06",       # optional, defaults to today
        "division": "Lucknow Division",    # optional
        "plan_month": "2026-07",           # optional, defaults to next month
        "auditors": [...]                  # optional, fetched from DB if omitted
    }
    """
    if request.method not in ["POST", "GET"]:
        return JsonResponse({"error": "Method not allowed"}, status=405)

    as_on_date = '2026-06-08'
    division = None
    plan_month = None
    auditors = None

    if request.method == "POST":
        try:
            data = json.loads(request.body)
            as_on_date  = data.get("as_on_date")
            division    = data.get("division", division)
            plan_month  = data.get("plan_month")
            auditors    = data.get("auditors")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
    else:  # GET
        as_on_date = request.GET.get("as_on_date")
        division   = request.GET.get("division", division)
        plan_month = request.GET.get("plan_month")

    # Default dates
    if not as_on_date:
        as_on_date = date.today().strftime("%Y-%m-%d")

    if not plan_month:
        today      = date.today()
        next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        plan_month = next_month.strftime("%Y-%m")

    # Send command to generate the audit plan
    try:
        command = GenerateAuditPlanCommand(
            as_on_date=as_on_date,
            division=division,
            plan_month=plan_month,
            auditors=auditors
        )
        result = dispatcher.send(command)
        return JsonResponse(result, safe=False)
    except ValueError as val_err:
        return JsonResponse({"error": str(val_err)}, status=400)
    except Exception as e:
        logger.error(f"Failed to generate audit plan: {str(e)}")
        return JsonResponse({"error": f"Failed to generate audit plan: {str(e)}"}, status=500)


@csrf_exempt
def get_current_plan(request):
    """
    API endpoint to retrieve the current saved audit plan from audit_plan_current.
    Optional query parameters:
      - division (str)
      - plan_month (str) (format: YYYY-MM)
    """
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    division = request.GET.get("division")
    plan_month = request.GET.get("plan_month")

    # Extract user from token (HTTP Layer concern)
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    token = ''
    if auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]

    user_id = None
    role_id = None
    if token:
        import jwt
        from django.conf import settings
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            pk_id = payload.get('user_id')
            
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT UserID FROM [dbo].[accounts_mst_usertbl] WHERE id = %s
                """, [pk_id])
                u_row = cursor.fetchone()
                if u_row:
                    actual_user_id = str(u_row[0])
                    user_id = actual_user_id
                    
                    cursor.execute("""
                        SELECT RoleId
                        FROM [dbo].[map_userRole]
                        WHERE UserID = %s AND IsActive = 1
                    """, [actual_user_id])
                    row = cursor.fetchone()
                    if row:
                        role_id = row[0]
        except Exception as e:
            logger.error(f"Token validation failed in get_current_plan: {e}")

    try:
        query = GetCurrentPlanQuery(
            division=division,
            plan_month=plan_month,
            user_id=user_id,
            role_id=role_id
        )
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        logger.error(f"Failed to fetch current plan: {str(e)}")
        return JsonResponse({"error": f"Failed to fetch current plan: {str(e)}"}, status=500)


@csrf_exempt
def get_planner_overview(request):
    """
    GET API endpoint to retrieve dynamic planner overview KPIs from the database.
    Optional query parameters:
      - division (str)
      - plan_month (str) (format: YYYY-MM)
    """
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    division = request.GET.get("division")
    plan_month = request.GET.get("plan_month")

    try:
        query = GetPlannerOverviewQuery(division=division, plan_month=plan_month)
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        logger.error(f"Failed to fetch planner overview: {str(e)}")
        return JsonResponse({"error": f"Failed to fetch planner overview: {str(e)}"}, status=500)


@csrf_exempt
def get_capacity_data(request):
    """
    GET API endpoint to retrieve capacity data for auditors.
    Optional query parameters:
      - division (str)
      - plan_month (str) (format: YYYY-MM)
    """
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    division = request.GET.get("division")
    plan_month = request.GET.get("plan_month")

    try:
        query = GetCapacityDataQuery(division=division, plan_month=plan_month)
        result = dispatcher.query(query)
        return JsonResponse(result)
    except Exception as e:
        logger.error(f"Failed to fetch capacity data: {str(e)}")
        return JsonResponse({"error": f"Failed to fetch capacity data: {str(e)}"}, status=500)
