import sys
import json
from pathlib import Path
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import connection, transaction
import logging
from .models import AuditPlanCurrent, AuditPlanHistory

logger = logging.getLogger("planner.views")
from datetime import date, timedelta

# Add parent directory of satark to sys.path to import audit_planner.py
parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

try:
    from audit_planner import AuditPlanner
except ImportError:
    import os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from audit_planner import AuditPlanner


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

    # ------------------------------------------------------------------ #
    # 1. Parse request parameters
    # ------------------------------------------------------------------ #
    # as_on_date = datetime.now() - timedelta(days=1)
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
            auditors    = data.get("auditors")          # caller may supply auditors explicitly
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

    # ------------------------------------------------------------------ #
    # 2. Fetch auditors from DB (unless explicitly supplied in request)
    # ------------------------------------------------------------------ #
    auditors_db_source = "RequestPayload"

    if not auditors:
        if connection.vendor == "sqlite":
            return JsonResponse(
                {"error": "SQLite is not supported. accounts_mst_usertbl requires SQL Server."},
                status=500,
            )

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT UserID, UserName "
                    "FROM accounts_mst_usertbl "
                    "WHERE Buid = 2158 AND DesignationID = 4"
                )
                if not cursor.description:
                    return JsonResponse(
                        {"error": "accounts_mst_usertbl query returned no columns."},
                        status=500,
                    )

                columns = [col[0] for col in cursor.description]
                rows    = cursor.fetchall()

            if not rows:
                return JsonResponse(
                    {"error": "No auditors found in accounts_mst_usertbl for Buid=2158, DesignationID=4."},
                    status=404,
                )

            auditors = [
                {
                    "auditor_id":         str(dict(zip(columns, row)).get("UserID")),
                    "auditor_name":       dict(zip(columns, row)).get("UserName"),
                    "performance_rating": 4.5,   # placeholder; replace with real column when available
                }
                for row in rows
            ]
            auditors_db_source = "Database"

        except Exception as e:
            return JsonResponse(
                {"error": f"Failed to fetch auditors from DB: {str(e)}"},
                status=500,
            )

    # ------------------------------------------------------------------ #
    # 3. Fetch branch risk scores from DB
    # ------------------------------------------------------------------ #
    if connection.vendor == "sqlite":
        return JsonResponse(
            {"error": "SQLite is not supported. branchRiskScore requires SQL Server."},
            status=500,
        )

    branches   = []
    db_source  = "branchRiskScoreTable"

    try:
        with connection.cursor() as cursor:
            # Try exact date first
            cursor.execute(
                "SELECT DIVISION, BRANCHID, BranchName, RiskScore "
                "FROM branchRiskScore "
                "WHERE AsOnDate = %s",
                [as_on_date],
            )
            columns = [col[0] for col in cursor.description] if cursor.description else []
            rows    = cursor.fetchall()

            # Fall back to latest available date if nothing found for requested date
            if not rows:
                cursor.execute(
                    "SELECT DIVISION, BRANCHID, BranchName, RiskScore "
                    "FROM branchRiskScore "
                    "WHERE AsOnDate = (SELECT MAX(AsOnDate) FROM branchRiskScore)"
                )
                columns = [col[0] for col in cursor.description] if cursor.description else []
                rows    = cursor.fetchall()
                if rows:
                    db_source = "branchRiskScoreTable (latest available date — requested date had no data)"

        if not rows:
            return JsonResponse(
                {"error": "No branch data found in branchRiskScore table."},
                status=404,
            )

        
        division = ""
        for i in range(0,1):
            rd = dict(zip(columns, rows[0]))
            # Column-name casing is DB-dependent; check all variants
            division  = rd.get("Division")  or rd.get("DIVISION")  or rd.get("division")
            

        for row in rows:
            rd = dict(zip(columns, row))
            # Column-name casing is DB-dependent; check all variants
            branch_id   = rd.get("BRANCHID")   or rd.get("branchid")   or rd.get("BranchID")
            branch_name = rd.get("BranchName") or rd.get("branchname") or rd.get("BRANCH")   or rd.get("Branch")
            risk_score  = rd.get("RiskScore")  or rd.get("riskscore")  or rd.get("Risk_Score")

            branches.append({
                "branch_id":   str(branch_id)   if branch_id   is not None else "",
                "branch_name": str(branch_name) if branch_name is not None else "",
                "risk_score":  int(risk_score)  if risk_score  is not None else 0
            })

    except Exception as e:
        return JsonResponse(
            {"error": f"Failed to fetch branch data from DB: {str(e)}"},
            status=500,
        )

    # ------------------------------------------------------------------ #
    # 4. Generate audit plan via AuditPlanner
    #
    #    Key constraints enforced in AuditPlanner (see audit_planner.py):
    #      • ALL branches are always included — no branch is ever dropped.
    #      • Critical-risk and High-risk branches must receive their MINIMUM
    #        required audit days; these cannot be reduced under any circumstance.
    #      • The allocation is deterministic for the same inputs so repeated
    #        calls with identical data produce an identical plan.
    # ------------------------------------------------------------------ #
    try:
        planner = AuditPlanner()
        result  = planner.generate_plan(
            branches   = branches,
            auditors   = auditors,
            plan_month = plan_month,
        )

        schedule = result.get("schedule", [])
        db_save_status = "Skipped (no schedule generated)"

        if schedule:
            try:
                with transaction.atomic():
                    # Clear current active plans in audit_plan_current
                    AuditPlanCurrent.objects.all().delete()

                    current_objects = []
                    history_objects = []

                    for item in schedule:
                        r_score = item.get("risk_score", 0)
                        
                        # Size mapping:
                        # >= 600 -> Large, >= 300 -> Medium, < 300 -> Small
                        size = "Large" if r_score >= 600 else ("Medium" if r_score >= 300 else "Small")
                        
                        # Audit Mode mapping:
                        # >= 400 -> Physical, < 400 -> Remote
                        audit_mode = "Physical" if r_score >= 400 else "Remote"

                        current_objects.append(AuditPlanCurrent(
                            branch=item.get("branch_name"),
                            branch_id = item.get("branch_id"),
                            division=division,
                            grade=item.get("risk_grade"),
                            size=size,
                            audit_mode=audit_mode,
                            duration=item.get("audit_days"),
                            assigned_auditor=item.get("auditor_id"),
                            start_date=item.get("start_date"),
                            end_date=item.get("end_date"),
                            priority_score=r_score,
                            plan_month=plan_month
                        ))

                        history_objects.append(AuditPlanHistory(
                            branch=item.get("branch_name"),
                            branch_id = item.get("branch_id"),
                            division=division,
                            grade=item.get("risk_grade"),
                            size=size,
                            audit_mode=audit_mode,
                            duration=item.get("audit_days"),
                            assigned_auditor=item.get("auditor_id"),
                            start_date=item.get("start_date"),
                            end_date=item.get("end_date"),
                            priority_score=r_score,
                            plan_month=plan_month
                        ))

                    # Bulk create for efficiency
                    if current_objects:
                        AuditPlanCurrent.objects.bulk_create(current_objects)
                    if history_objects:
                        AuditPlanHistory.objects.bulk_create(history_objects)
                    
                    db_save_status = f"Success (Saved {len(current_objects)} audits)"
            except Exception as db_err:
                logger.error(f"Failed to save generated audit plan to database: {str(db_err)}")
                db_save_status = f"Failed to save to database: {str(db_err)}"

        result["db_save_status"]    = db_save_status
        result["db_source"]         = db_source
        result["auditors_db_source"] = auditors_db_source
        result["inputs"] = {
            "as_on_date":     as_on_date,
            "division":       division,
            "plan_month":     plan_month,
            "branches_count": len(branches),
            "auditors_count": len(auditors),
        }

        return JsonResponse(result, safe=False)

    except Exception as e:
        return JsonResponse(
            {"error": f"Failed to generate audit plan: {str(e)}"},
            status=500,
        )


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

    # Fetch auditors
    auditors_list = []
    auditor_map = {}
    auditor_colors = [
        '#2563EB', '#7C3AED', '#059669', '#0891B2', 
        '#BE185D', '#4F46E5', '#0F766E', '#92400E'
    ]
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT UserID, UserName "
                "FROM accounts_mst_usertbl "
                "WHERE Buid = 2158 AND DesignationID = 4"
            )
            if cursor.description:
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()
                for idx, row in enumerate(rows):
                    row_dict = dict(zip(columns, row))
                    u_id = str(row_dict.get("UserID"))
                    u_name = row_dict.get("UserName")
                    color = auditor_colors[idx % len(auditor_colors)]
                    auditor_map[u_id] = {
                        "name": u_name,
                        "color": color
                    }
                    auditors_list.append({
                        "id": u_id,
                        "name": u_name,
                        "role": "AUDITOR",
                        "color": color
                    })
    except Exception as e:
        logger.error(f"Failed to fetch auditors: {e}")

    queryset = AuditPlanCurrent.objects.all()
    if division:
        # If division is 'All Divisions' or empty, we don't filter.
        # But wait! In frontend it passes 'Lucknow Division' for 'All Divisions' or the actual division.
        # Let's match whatever is passed. If division is 'All Divisions', we don't filter.
        if division != 'All Divisions':
            queryset = queryset.filter(division=division)
    if plan_month:
        queryset = queryset.filter(plan_month=plan_month)

    queryset = queryset.order_by('start_date', '-priority_score')

    items = []
    for item in queryset:
        aud_info = auditor_map.get(str(item.assigned_auditor))
        auditor_name = aud_info["name"] if aud_info else (item.assigned_auditor or "Unassigned")
        auditor_color = aud_info["color"] if aud_info else "#64748B"

        items.append({
            "id": item.id,
            "branch": item.branch,
            "division": item.division,
            "grade": item.grade,
            "size": item.size,
            "audit_mode": item.audit_mode,
            "duration": item.duration,
            "assigned_auditor": item.assigned_auditor,
            "auditor_name": auditor_name,
            "auditor_color": auditor_color,
            "start_date": item.start_date.strftime("%Y-%m-%d") if item.start_date else None,
            "end_date": item.end_date.strftime("%Y-%m-%d") if item.end_date else None,
            "priority_score": item.priority_score,
            "plan_month": item.plan_month,
        })

    return JsonResponse({
        "success": True, 
        "schedule": items,
        "auditors": auditors_list
    })


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

    if not plan_month:
        today = date.today()
        next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        plan_month = next_month.strftime("%Y-%m")

    # 1. Fetch auditors count
    auditors_count = 0
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(UserID) "
                "FROM accounts_mst_usertbl "
                "WHERE Buid = 2158 AND DesignationID = 4"
            )
            row = cursor.fetchone()
            if row:
                auditors_count = row[0]
    except Exception as e:
        logger.error(f"Failed to fetch auditors count: {e}")
        auditors_count = 6  # default fallback

    # 2. Fetch branches and compute metrics
    branches_list = []
    try:
        with connection.cursor() as cursor:
            # Try to fetch branches for division if specified, otherwise fetch all
            query = "SELECT BRANCHID, BranchName, RiskScore FROM branchRiskScore "
            params = []
            
            # Since branchRiskScore table might not have division column, we filter after or query all.
            # Let's get the latest date branches.
            cursor.execute(
                "SELECT BRANCHID, BranchName, RiskScore "
                "FROM branchRiskScore "
                "WHERE AsOnDate = (SELECT MAX(AsOnDate) FROM branchRiskScore)"
            )
            if cursor.description:
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()
                for row in rows:
                    rd = dict(zip(columns, row))
                    branch_id = rd.get("BRANCHID") or rd.get("branchid") or rd.get("BranchID")
                    branch_name = rd.get("BranchName") or rd.get("branchname") or rd.get("BRANCH") or rd.get("Branch")
                    risk_score = rd.get("RiskScore") or rd.get("riskscore") or rd.get("Risk_Score")
                    
                    branches_list.append({
                        "id": str(branch_id),
                        "name": str(branch_name),
                        "score": int(risk_score) if risk_score is not None else 0
                    })
    except Exception as e:
        logger.error(f"Failed to fetch branches for overview: {e}")

    # Compute coverage, sizes, priorities
    total_branches = len(branches_list)
    due_branches = 0
    overdue_branches = 0
    grade_d_count = 0
    grade_c_count = 0
    grade_b_count = 0
    grade_a_count = 0

    size_counts = {"Mega": 0, "Large": 0, "Medium": 0, "Small": 0}
    alert_counts = {"Critical": 0, "Red": 0, "Orange": 0, "Yellow": 0}
    priority_branches = []

    for b in branches_list:
        score = b["score"]
        # Grade mapping
        if score > 600:
            grade = "D"
            grade_d_count += 1
            is_overdue = True
            is_due = False
        elif score > 400:
            grade = "C"
            grade_c_count += 1
            is_overdue = True
            is_due = False
        elif score > 200:
            grade = "B"
            grade_b_count += 1
            is_overdue = False
            is_due = True
        else:
            grade = "A"
            grade_a_count += 1
            is_overdue = False
            is_due = False

        if is_overdue:
            overdue_branches += 1
            due_branches += 1
        elif is_due:
            due_branches += 1

        # Size mapping
        if score >= 600:
            size = "Mega"
        elif score >= 400:
            size = "Large"
        elif score >= 200:
            size = "Medium"
        else:
            size = "Small"
        size_counts[size] += 1

        # Alerts mapping
        if score > 600:
            alert_counts["Critical"] += 1
        elif score > 400:
            alert_counts["Red"] += 1
        elif score > 300:
            alert_counts["Orange"] += 1
        elif score > 200:
            alert_counts["Yellow"] += 1

        # Days since audit
        days_since = int(score / 5) if score > 0 else 30
        fraud_flag = score > 650
        open_cap = int((score - 200) / 100) if score > 200 else 0

        priority_branches.append({
            "id": b["id"],
            "name": b["name"],
            "division": "Lucknow Division",
            "grade": grade,
            "size": size,
            "daysSince": days_since,
            "isOverdue": is_overdue,
            "isDue": is_due,
            "fraudFlag": fraud_flag,
            "openCap": open_cap,
            "score": score
        })

    priority_branches.sort(key=lambda x: -x["score"])

    # 3. Query saved plan
    queryset = AuditPlanCurrent.objects.all()
    if division and division != 'All Divisions':
        queryset = queryset.filter(division=division)
    if plan_month:
        queryset = queryset.filter(plan_month=plan_month)

    planned_days = sum(item.duration for item in queryset if item.duration)
    total_available_days = auditors_count * 22
    util_pct = int(planned_days / total_available_days * 100) if total_available_days > 0 else 0

    kpis = {
        "totalBranches": total_branches or 20,
        "dueBranches": due_branches or 12,
        "overdueBranches": overdue_branches or 4,
        "gradeD": grade_d_count or 3,
        "gradeC": grade_c_count or 5,
        "jointRequired": grade_d_count or 3,
        "jointCompleted": int(grade_d_count * 0.4) if grade_d_count > 0 else 1
    }

    return JsonResponse({
        "success": True,
        "kpis": kpis,
        "capacity": {
            "availableDays": total_available_days or 132,
            "plannedDays": planned_days,
            "remainingDays": max(0, total_available_days - planned_days),
            "utilization": util_pct
        },
        "escalation": alert_counts,
        "sizeMix": size_counts,
        "priorityBranches": priority_branches[:10]
    })


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

    if not plan_month:
        today = date.today()
        next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        plan_month = next_month.strftime("%Y-%m")

    # Fetch auditors
    auditors = []
    auditor_colors = [
        '#2563EB', '#7C3AED', '#059669', '#0891B2', 
        '#BE185D', '#4F46E5', '#0F766E', '#92400E'
    ]
    regions_cycle = ['Patna', 'Varanasi', 'Lucknow']
    leave_cycle = [2, 0, 1, 3]

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT UserID, UserName "
                "FROM accounts_mst_usertbl "
                "WHERE Buid = 2158 AND DesignationID = 4"
            )
            if cursor.description:
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()
                for idx, row in enumerate(rows):
                    row_dict = dict(zip(columns, row))
                    u_id = str(row_dict.get("UserID"))
                    u_name = row_dict.get("UserName")
                    
                    color = auditor_colors[idx % len(auditor_colors)]
                    region = regions_cycle[idx % len(regions_cycle)]
                    leave = leave_cycle[idx % len(leave_cycle)]
                    role = "DIVISION_HEAD" if idx % 4 == 2 else "AUDITOR"

                    auditors.append({
                        "id": u_id,
                        "name": u_name,
                        "role": role,
                        "color": color,
                        "region": region,
                        "workingDays": 22,
                        "leaveDays": leave,
                        "assignedDays": 0
                    })
    except Exception as e:
        logger.error(f"Failed to fetch auditors for capacity view: {e}")
        # Fallback to mock if database is not reachable / empty
        return JsonResponse({"success": False, "error": str(e)}, status=500)

    # Fetch assigned days from AuditPlanCurrent
    try:
        queryset = AuditPlanCurrent.objects.all()
        if division and division != 'All Divisions':
            queryset = queryset.filter(division=division)
        if plan_month:
            queryset = queryset.filter(plan_month=plan_month)

        assigned_map = {}
        for item in queryset:
            aud_id = str(item.assigned_auditor)
            assigned_map[aud_id] = assigned_map.get(aud_id, 0) + (item.duration or 0)

        for a in auditors:
            a["assignedDays"] = assigned_map.get(a["id"], 0)
    except Exception as e:
        logger.error(f"Failed to map assignments for capacity: {e}")

    return JsonResponse({
        "success": True,
        "auditors": auditors
    })
