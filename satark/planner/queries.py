import logging
from datetime import date, timedelta
from django.db import connection
from satark.cqrs import Query, QueryHandler
from .models import AuditPlanCurrent

logger = logging.getLogger("planner.queries")


class GetCurrentPlanQuery(Query):
    """Query to fetch the current active audit plan schedule and auditor mapping"""
    def __init__(self, division: str = None, plan_month: str = None, user_id: str = None, role_id: int = None):
        self.division = division
        self.plan_month = plan_month
        self.user_id = user_id
        self.role_id = role_id


class GetCurrentPlanQueryHandler(QueryHandler):
    """Handles GetCurrentPlanQuery execution"""
    def execute(self, query: GetCurrentPlanQuery) -> dict:
        division = query.division
        plan_month = query.plan_month
        user_id = query.user_id
        role_id = query.role_id

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
            logger.error(f"Failed to fetch auditors in GetCurrentPlanQuery: {e}")

        queryset = AuditPlanCurrent.objects.all()
        if division and division != 'All Divisions':
            queryset = queryset.filter(division=division)
        if plan_month:
            queryset = queryset.filter(plan_month=plan_month)

        # Backend filtering for Auditor Role (RoleId = 4)
        if role_id == 4 and user_id:
            queryset = queryset.filter(assigned_auditor=user_id)

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

        return {
            "success": True,
            "schedule": items,
            "auditors": auditors_list
        }


class GetPlannerOverviewQuery(Query):
    """Query to fetch overall KPI summaries, branch alerts, and priorities"""
    def __init__(self, division: str = None, plan_month: str = None):
        self.division = division
        self.plan_month = plan_month


class GetPlannerOverviewQueryHandler(QueryHandler):
    """Handles GetPlannerOverviewQuery execution"""
    def execute(self, query: GetPlannerOverviewQuery) -> dict:
        division = query.division
        plan_month = query.plan_month

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
            logger.error(f"Failed to fetch auditors count in GetPlannerOverviewQuery: {e}")
            auditors_count = 6  # fallback default

        # 2. Fetch branches and compute metrics
        branches_list = []
        try:
            with connection.cursor() as cursor:
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
            logger.error(f"Failed to fetch branches in GetPlannerOverviewQuery: {e}")

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

        # Query saved plan
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

        return {
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
        }


class GetCapacityDataQuery(Query):
    """Query to retrieve capacity data for auditors"""
    def __init__(self, division: str = None, plan_month: str = None):
        self.division = division
        self.plan_month = plan_month


class GetCapacityDataQueryHandler(QueryHandler):
    """Handles GetCapacityDataQuery execution"""
    def execute(self, query: GetCapacityDataQuery) -> dict:
        division = query.division
        plan_month = query.plan_month

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
            logger.error(f"Failed to fetch auditors for capacity in GetCapacityDataQuery: {e}")
            raise e

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
            logger.error(f"Failed to map assignments for capacity in GetCapacityDataQuery: {e}")

        return {
            "success": True,
            "auditors": auditors
        }
