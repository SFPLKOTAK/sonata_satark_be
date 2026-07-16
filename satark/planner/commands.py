import logging
import sys
from pathlib import Path
from django.db import connection, transaction
from satark.cqrs import Command, CommandHandler
from .models import AuditPlanCurrent, AuditPlanHistory

# Set up logging
logger = logging.getLogger("planner.commands")

# Ensure parent directory of satark is in sys.path to import audit_planner
parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

try:
    from audit_planner import AuditPlanner
except ImportError:
    import os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from audit_planner import AuditPlanner


class GenerateAuditPlanCommand(Command):
    """Command representing intent to generate and save a new audit plan"""
    def __init__(self, as_on_date: str, division: str = None, plan_month: str = None, auditors: list = None):
        self.as_on_date = as_on_date
        self.division = division
        self.plan_month = plan_month
        self.auditors = auditors


class GenerateAuditPlanCommandHandler(CommandHandler):
    """Handles the execution of GenerateAuditPlanCommand"""
    def execute(self, command: GenerateAuditPlanCommand) -> dict:
        as_on_date = command.as_on_date
        division = command.division
        plan_month = command.plan_month
        auditors = command.auditors

        # 1. Fetch auditors from DB if not supplied
        auditors_db_source = "RequestPayload"
        if not auditors:
            if connection.vendor == "sqlite":
                raise ValueError("SQLite is not supported. accounts_mst_usertbl requires SQL Server.")

            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT UserID, UserName "
                    "FROM accounts_mst_usertbl "
                    "WHERE Buid = 2158 AND DesignationID = 4"
                )
                if not cursor.description:
                    raise RuntimeError("accounts_mst_usertbl query returned no columns.")

                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()

            if not rows:
                raise ValueError("No auditors found in accounts_mst_usertbl for Buid=2158, DesignationID=4.")

            auditors = [
                {
                    "auditor_id": str(dict(zip(columns, row)).get("UserID")),
                    "auditor_name": dict(zip(columns, row)).get("UserName"),
                    "performance_rating": 4.5,
                }
                for row in rows
            ]
            auditors_db_source = "Database"

        # 2. Fetch branch risk scores from DB
        if connection.vendor == "sqlite":
            raise ValueError("SQLite is not supported. branchRiskScore requires SQL Server.")

        branches = []
        db_source = "branchRiskScoreTable"

        with connection.cursor() as cursor:
            # Try exact date first
            cursor.execute(
                "SELECT DIVISION, BRANCHID, BranchName, RiskScore "
                "FROM branchRiskScore "
                "WHERE AsOnDate = %s",
                [as_on_date],
            )
            columns = [col[0] for col in cursor.description] if cursor.description else []
            rows = cursor.fetchall()

            # Fall back to latest available date if nothing found
            if not rows:
                cursor.execute(
                    "SELECT DIVISION, BRANCHID, BranchName, RiskScore "
                    "FROM branchRiskScore "
                    "WHERE AsOnDate = (SELECT MAX(AsOnDate) FROM branchRiskScore)"
                )
                columns = [col[0] for col in cursor.description] if cursor.description else []
                rows = cursor.fetchall()
                if rows:
                    db_source = "branchRiskScoreTable (latest available date — requested date had no data)"

        if not rows:
            raise ValueError("No branch data found in branchRiskScore table.")

        for row in rows:
            rd = dict(zip(columns, row))
            branch_id = rd.get("BRANCHID") or rd.get("branchid") or rd.get("BranchID")
            branch_name = rd.get("BranchName") or rd.get("branchname") or rd.get("BRANCH") or rd.get("Branch")
            risk_score = rd.get("RiskScore") or rd.get("riskscore") or rd.get("Risk_Score")

            branches.append({
                "branch_id": str(branch_id) if branch_id is not None else "",
                "branch_name": str(branch_name) if branch_name is not None else "",
                "risk_score": int(risk_score) if risk_score is not None else 0
            })

        # 3. Generate plan
        planner = AuditPlanner()
        result = planner.generate_plan(
            branches=branches,
            auditors=auditors,
            plan_month=plan_month,
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
                        size = "Large" if r_score >= 600 else ("Medium" if r_score >= 300 else "Small")
                        audit_mode = "Physical" if r_score >= 400 else "Remote"

                        current_objects.append(AuditPlanCurrent(
                            branch=item.get("branch_name"),
                            branch_id=item.get("branch_id"),
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
                            branch_id=item.get("branch_id"),
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

        result["db_save_status"] = db_save_status
        result["db_source"] = db_source
        result["auditors_db_source"] = auditors_db_source
        result["inputs"] = {
            "as_on_date": as_on_date,
            "division": division,
            "plan_month": plan_month,
            "branches_count": len(branches),
            "auditors_count": len(auditors),
        }

        return result
