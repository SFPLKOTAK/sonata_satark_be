import sys
import json
from pathlib import Path
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import connection
from datetime import date, timedelta

# Add parent directory of satark to sys.path to import audit_planner.py
parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

try:
    from audit_planner import AuditPlanner
except ImportError:
    # Fallback in case path resolution differs
    import os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from audit_planner import AuditPlanner

# Mock data fallbacks
MOCK_AUDITORS = [
    {"auditor_id": "A001", "auditor_name": "Rajesh Kumar", "performance_rating": 4.8},
    {"auditor_id": "A002", "auditor_name": "Priya Singh", "performance_rating": 4.5},
    {"auditor_id": "A003", "auditor_name": "Amit Verma", "performance_rating": 4.2},
    {"auditor_id": "A004", "auditor_name": "Vivek Mishra", "performance_rating": 4.0},
    {"auditor_id": "A005", "auditor_name": "Deepa Rani", "performance_rating": 4.6},
]

MOCK_BRANCHES = [
    {"branch_id": "BR-001", "branch_name": "Kanpur Main Branch", "risk_score": 710},
    {"branch_id": "BR-002", "branch_name": "Lucknow North Branch", "risk_score": 580},
    {"branch_id": "BR-003", "branch_name": "Varanasi East Branch", "risk_score": 320},
    {"branch_id": "BR-004", "branch_name": "Gorakhpur Central Branch", "risk_score": 180},
    {"branch_id": "BR-005", "branch_name": "Lucknow West Branch", "risk_score": 490},
    {"branch_id": "BR-006", "branch_name": "Kanpur South Branch", "risk_score": 620},
]

@csrf_exempt
def generate_audit_plan(request):
    """
    API endpoint to generate audit plans.
    Can be called via POST with JSON:
    {
        "as_on_date": "2026-06-06",
        "division": "Lucknow Division",
        "plan_month": "2026-07",
        "auditors": [...] # optional
    }
    """
    if request.method not in ["POST", "GET"]:
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    # Parse request parameters
    as_on_date = None
    division = "Lucknow Division"
    plan_month = None
    auditors = None
    
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            as_on_date = data.get("as_on_date")
            division = data.get("division", division)
            plan_month = data.get("plan_month")
            auditors = data.get("auditors")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
    else: # GET
        as_on_date = request.GET.get("as_on_date")
        division = request.GET.get("division", division)
        plan_month = request.GET.get("plan_month")
    
    # Set default dates if not provided
    if not as_on_date:
        as_on_date = date.today().strftime("%Y-%m-%d")
        
    if not plan_month:
        today = date.today()
        next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        plan_month = next_month.strftime("%Y-%m")
        
    # 1. Fetch auditors if not explicitly provided
    auditors_db_source = "RequestPayload"
    if not auditors:
        auditors = []
        try:
            with connection.cursor() as cursor:
                # Check database engine
                if connection.vendor == 'sqlite':
                    raise Exception("SQLite fallback (accounts_mst_usertbl is only supported on SQL Server)")
                
                cursor.execute("SELECT UserID, UserName, Buid FROM accounts_mst_usertbl WHERE Buid = 2158 AND DesignationID = 4")
                if cursor.description:
                    columns = [col[0] for col in cursor.description]
                    rows = cursor.fetchall()
                    for row in rows:
                        row_dict = dict(zip(columns, row))
                        auditors.append({
                            "auditor_id": str(row_dict.get("UserID")),
                            "auditor_name": row_dict.get("UserName"),
                            "performance_rating": 4.5  # default placeholder rating
                        })
                
                if not auditors:
                    raise Exception("No auditors found in accounts_mst_usertbl matching criteria")
                auditors_db_source = "Database"
        except Exception as e:
            # Fallback to mock auditors
            auditors_db_source = f"MockData (Query failed/skipped: {str(e)})"
            auditors = MOCK_AUDITORS

    # 2. Fetch branch data from branchRiskScore table
    branches = []
    db_source = "branchRiskScoreTable"
    try:
        with connection.cursor() as cursor:
            # Check database engine
            if connection.vendor == 'sqlite':
                raise Exception("SQLite fallback (branchRiskScore table is only supported on SQL Server)")
            
            rows = []
            columns = []
            
            # Query branches for the given date
            cursor.execute(
                "SELECT BRANCHID, BranchName, RiskScore FROM branchRiskScore WHERE AsOnDate = %s",
                [as_on_date]
            )
            
            if cursor.description:
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()
                
            # If no rows found for that date, fall back to the latest date's data
            if not rows:
                cursor.execute(
                    "SELECT BRANCHID, BranchName, RiskScore FROM branchRiskScore "
                    "WHERE AsOnDate = (SELECT MAX(AsOnDate) FROM branchRiskScore)"
                )
                if cursor.description:
                    columns = [col[0] for col in cursor.description]
                    rows = cursor.fetchall()
                    
            for row in rows:
                row_dict = dict(zip(columns, row))
                # Handle flexible casing for database columns
                branch_id = row_dict.get("BRANCHID") or row_dict.get("branchid") or row_dict.get("BranchID")
                branch_name = row_dict.get("BranchName") or row_dict.get("branchname") or row_dict.get("BRANCH") or row_dict.get("Branch")
                risk_score = row_dict.get("RiskScore") or row_dict.get("riskscore") or row_dict.get("Risk_Score")
                
                branches.append({
                    "branch_id": str(branch_id) if branch_id is not None else "",
                    "branch_name": str(branch_name) if branch_name is not None else "",
                    "risk_score": int(risk_score) if risk_score is not None else 0
                })
            
            if not branches:
                raise Exception("No branches found in branchRiskScore table")
                
    except Exception as e:
        # Fallback to mock branches if DB call fails or is SQLite
        db_source = f"MockData (SP failed/skipped: {str(e)})"
        branches = MOCK_BRANCHES

    # 3. Use AuditPlanner to generate schedule via Groq API
    try:
        planner = AuditPlanner()
        result = planner.generate_plan(
            branches=branches,
            auditors=auditors,
            plan_month=plan_month
        )
        
        # Add metadata to response
        result["db_source"] = db_source
        result["auditors_db_source"] = auditors_db_source
        result["inputs"] = {
            "as_on_date": as_on_date,
            "division": division,
            "plan_month": plan_month,
            "branches_count": len(branches),
            "auditors_count": len(auditors)
        }
        
        return JsonResponse(result, safe=False)
        
    except Exception as e:
        return JsonResponse({
            "error": f"Failed to generate audit plan: {str(e)}",
            "db_source": db_source
        }, status=500)
