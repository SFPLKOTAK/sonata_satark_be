import json
import decimal
import logging
from datetime import date, datetime
from django.db import connection
from django.db.models import Q
from satark.cqrs import Query, QueryHandler
from planner.models import AuditPlanCurrent
from authentication.utils import log_error
from .utils import decompress_file_backend

logger = logging.getLogger("audit.queries")


# Helper for auditee branches resolution (from views.py)
def get_user_branch_ids(cursor, user):
    branch_id = int(user.BranchID) if user.BranchID else 0
    buid = int(user.Buid) if user.Buid else 0
    butype = int(user.BUType) if user.BUType else 0

    branch_ids = []
    if butype == 2 and buid:
        cursor.execute("""
            SELECT DISTINCT branchid FROM VW_Branch_To_GeographicalHierarchy
            WHERE divisionid = %s
        """, [buid])
        branch_ids = [str(row[0]) for row in cursor.fetchall()]
    elif butype == 3 and buid:
        cursor.execute("""
            SELECT DISTINCT branchid FROM VW_Branch_To_GeographicalHierarchy
            WHERE regionid = %s
        """, [buid])
        branch_ids = [str(row[0]) for row in cursor.fetchall()]
    elif butype == 4 and buid:
        cursor.execute("""
            SELECT DISTINCT branchid FROM VW_Branch_To_GeographicalHierarchy
            WHERE hubid = %s
        """, [buid])
        branch_ids = [str(row[0]) for row in cursor.fetchall()]
    elif butype == 5 and buid:
        cursor.execute("""
            SELECT DISTINCT branchid FROM VW_Branch_To_GeographicalHierarchy
            WHERE branchid = %s
        """, [buid])
        branch_ids = [str(row[0]) for row in cursor.fetchall()]
    elif branch_id:
        branch_ids = [str(branch_id)]
    
    if not branch_ids:
        branch_ids = ['0']
    return branch_ids


class GetChecklistPointsQuery(Query):
    def __init__(self, report_type=None, section_code=None):
        self.report_type = None if report_type == 'All' else report_type
        self.section_code = None if section_code == 'All' else section_code


class GetChecklistPointsQueryHandler(QueryHandler):
    def execute(self, query: GetChecklistPointsQuery) -> dict:
        try:
            with connection.cursor() as cursor:
                sp_query = """
                    EXEC [dbo].[usp_manage_audit_checklist_master]
                        @expected_result = 'MANAGE',
                        @report_type = %s,
                        @section_code = %s
                """
                cursor.execute(sp_query, [query.report_type, query.section_code])
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()

            items = []
            for row in rows:
                row_dict = dict(zip(columns, row))
                for key, val in row_dict.items():
                    if isinstance(val, decimal.Decimal):
                        row_dict[key] = float(val)
                    elif hasattr(val, 'isoformat'):
                        row_dict[key] = val.isoformat()
                items.append(row_dict)

            return {'success': True, 'checklist_points': items}
        except Exception as e:
            log_error(f"GetChecklistPointsQueryHandler failed: {str(e)}")
            raise e


class GetReportTypesQuery(Query):
    pass


class GetReportTypesQueryHandler(QueryHandler):
    def execute(self, query: GetReportTypesQuery) -> dict:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT DISTINCT report_type FROM [dbo].[audit_branch_checklist_master] WHERE report_type IS NOT NULL")
                db_types = [row[0] for row in cursor.fetchall() if row[0]]

            default_types = ["Branch Audit", "Gold Loan Audit", "Concurrent Audit"]
            all_types = list(set(default_types + db_types))
            return {'success': True, 'report_types': all_types}
        except Exception as e:
            log_error(f"GetReportTypesQueryHandler failed: {str(e)}")
            raise e


class GetCenterChecklistPointsQuery(Query):
    pass


class GetCenterChecklistPointsQueryHandler(QueryHandler):
    def execute(self, query: GetCenterChecklistPointsQuery) -> dict:
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        center_checklist_id, serial_no, parameter_code, 
                        parameter_name, max_score, is_active, created_at, updated_at
                    FROM [dbo].[audit_center_checklist_master]
                    ORDER BY serial_no ASC
                """)
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()

            items = []
            for row in rows:
                row_dict = dict(zip(columns, row))
                for key, val in row_dict.items():
                    if isinstance(val, decimal.Decimal):
                        row_dict[key] = float(val)
                    elif hasattr(val, 'isoformat'):
                        row_dict[key] = val.isoformat()
                items.append(row_dict)

            return {'success': True, 'center_checklist_points': items}
        except Exception as e:
            log_error(f"GetCenterChecklistPointsQueryHandler failed: {str(e)}")
            raise e


class GetClientChecklistPointsQuery(Query):
    pass


class GetClientChecklistPointsQueryHandler(QueryHandler):
    def execute(self, query: GetClientChecklistPointsQuery) -> dict:
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        client_checklist_id, serial_no, parameter_code, 
                        parameter_name, max_score, is_active, created_at, updated_at
                    FROM [dbo].[audit_client_checklist_master]
                    ORDER BY serial_no ASC
                """)
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()

            items = []
            for row in rows:
                row_dict = dict(zip(columns, row))
                for key, val in row_dict.items():
                    if isinstance(val, decimal.Decimal):
                        row_dict[key] = float(val)
                    elif hasattr(val, 'isoformat'):
                        row_dict[key] = val.isoformat()
                items.append(row_dict)

            return {'success': True, 'client_checklist_points': items}
        except Exception as e:
            log_error(f"GetClientChecklistPointsQueryHandler failed: {str(e)}")
            raise e


class GetAssignedAuditsQuery(Query):
    def __init__(self, user):
        self.user = user


class GetAssignedAuditsQueryHandler(QueryHandler):
    def execute(self, query: GetAssignedAuditsQuery) -> dict:
        user = query.user
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    EXEC [dbo].[usp_ManageBranchAudit]
                        @ReportType = 'assigned-audits',
                        @UserID = %s
                """, [user.UserID])
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()

            audits = []
            for row in rows:
                audits.append(dict(zip(columns, row)))

            audit_ids = [a['auditId'] for a in audits if a.get('auditId')]
            selected_centers_map = {}
            if audit_ids:
                with connection.cursor() as cursor_centers:
                    placeholders = ', '.join(['%s'] * len(audit_ids))
                    cursor_centers.execute(f"""
                        SELECT audit_id, center_id, center_name 
                        FROM dbo.audit_branch_selected_centers
                        WHERE audit_id IN ({placeholders})
                    """, audit_ids)
                    for center_row in cursor_centers.fetchall():
                        aid, cid, cname = center_row
                        if aid not in selected_centers_map:
                            selected_centers_map[aid] = []
                        selected_centers_map[aid].append({
                            'centerId': cid,
                            'centerName': cname
                        })

            for a in audits:
                a['selectedCenters'] = selected_centers_map.get(a['auditId'], [])

            total_assigned = len(audits)
            completed_count = sum(1 for a in audits if a['status'] == 'completed')
            in_progress_count = sum(1 for a in audits if a.get('isStarted') and a['status'] != 'completed')
            completion_pct = int(completed_count / total_assigned * 100) if total_assigned > 0 else 0
            stats = {
                "branchesThisMonth": completed_count,
                "branchesTarget": total_assigned,
                "completionPct": completion_pct,
                "inProgressCount": in_progress_count
            }

            return {'success': True, 'audits': audits, 'stats': stats}
        except Exception as e:
            log_error(f"GetAssignedAuditsQueryHandler failed: {str(e)}")
            raise e


class GetAuditFeedbackQuery(Query):
    def __init__(self, branch_id, user, audit_id=None):
        self.branch_id = str(branch_id).strip() if branch_id is not None else ""
        self.user = user
        self.audit_id = audit_id


class GetAuditFeedbackQueryHandler(QueryHandler):
    def execute(self, query: GetAuditFeedbackQuery) -> dict:
        branch_id = query.branch_id
        user = query.user
        audit_id = query.audit_id

        # Numeric mapping resolve if name was passed
        try:
            int(branch_id)
        except ValueError:
            plan_obj = AuditPlanCurrent.objects.filter(branch=branch_id).first()
            if plan_obj and plan_obj.branch_id:
                branch_id = str(plan_obj.branch_id)

        if not audit_id:
            user_id_str = str(user.UserID) if user.UserID is not None else ""
            user_code = user.UserCode or ""
            plan = None
            try:
                val_int = int(branch_id)
                plan = AuditPlanCurrent.objects.filter(
                    Q(branch_id=val_int) & (Q(assigned_auditor=user_id_str) | Q(assigned_auditor=user_code))
                ).first()
            except ValueError:
                pass
                
            if not plan:
                plan = AuditPlanCurrent.objects.filter(
                    Q(branch=branch_id) & (Q(assigned_auditor=user_id_str) | Q(assigned_auditor=user_code))
                ).first()
                
            if plan:
                audit_id = plan.id

        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    EXEC [dbo].[usp_ManageBranchAudit]
                        @ReportType = 'feedback',
                        @BranchID = %s,
                        @AuditID = %s
                """, [branch_id, audit_id])
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()

            feedback_list = []
            feedback_audit_id = audit_id
            for row in rows:
                row_dict = dict(zip(columns, row))
                if row_dict.get("audit_id") and not feedback_audit_id:
                    feedback_audit_id = row_dict.get("audit_id")
                
                normal_file_id = row_dict.get("normal_file_id")
                confidential_file_id = row_dict.get("confidential_file_id")

                feedback_list.append({
                    "checklistId": row_dict.get("checklist_id"),
                    "answer": row_dict.get("answer"),
                    "normalRemark": row_dict.get("normal_remark"),
                    "status": row_dict.get("status"),
                    "confidentialRemark": row_dict.get("confidential_remark"),
                    "normalFile": {
                        "id": normal_file_id,
                        "filename": row_dict.get("normal_file_name")
                    } if normal_file_id else None,
                    "confidentialFile": {
                        "id": confidential_file_id,
                        "filename": row_dict.get("confidential_file_name")
                    } if confidential_file_id else None,
                })

            return {'success': True, 'feedback': feedback_list, 'auditId': feedback_audit_id}
        except Exception as e:
            log_error(f"GetAuditFeedbackQueryHandler failed: {str(e)}")
            raise e


class ViewFeedbackFileQuery(Query):
    def __init__(self, file_id, is_confidential=False):
        self.file_id = file_id
        self.is_confidential = is_confidential


class ViewFeedbackFileQueryHandler(QueryHandler):
    def execute(self, query: ViewFeedbackFileQuery) -> dict:
        import base64, mimetypes
        file_id = query.file_id
        # Correct actual DB table names:
        # Normal files:       dbo.audit_branch_normal_files       (PK: id, content: file_content)
        # Confidential files: dbo.audit_branch_confidential_files (PK: id, content: file_content)
        tbl = "audit_branch_confidential_files" if query.is_confidential else "audit_branch_normal_files"

        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT file_name, file_content FROM dbo.{tbl} WHERE id = %s", [file_id])
                row = cursor.fetchone()

            if not row:
                return {'success': False, 'message': 'File not found', 'status_code': 404}

            filename, payload = row
            if not payload:
                return {'success': False, 'message': 'File content is empty', 'status_code': 404}

            # Decompress if compressed
            file_bytes = decompress_file_backend(bytes(payload), filename)

            # Determine MIME type from filename
            mime_type, _ = mimetypes.guess_type(filename or '')
            if not mime_type:
                mime_type = 'application/octet-stream'

            # Encode to base64 dataUrl for frontend
            b64 = base64.b64encode(file_bytes).decode('utf-8')
            data_url = f"data:{mime_type};base64,{b64}"

            return {'success': True, 'filename': filename, 'dataUrl': data_url, 'status_code': 200}
        except Exception as e:
            log_error(f"ViewFeedbackFileQueryHandler failed: {str(e)}")
            raise e


class GetCenterRiskDetailsQuery(Query):
    def __init__(self, branch_name: str, as_on_date=None):
        self.branch_name = branch_name
        self.as_on_date = as_on_date


class GetCenterRiskDetailsQueryHandler(QueryHandler):
    def execute(self, query: GetCenterRiskDetailsQuery) -> dict:
        branch_name = query.branch_name
        as_on_date = query.as_on_date
        try:
            branch_id = None
            with connection.cursor() as cursor:
                # 1. Look up in CenterRiskScore directly
                cursor.execute("""
                    SELECT TOP 1 BRANCHID 
                    FROM CenterRiskScore 
                    WHERE BranchName = %s
                """, [branch_name])
                row = cursor.fetchone()
                if row:
                    branch_id = row[0]
                else:
                    # 2. Look up in VW_Branch_To_GeographicalHierarchy by exact name
                    cursor.execute("""
                        SELECT TOP 1 BranchID 
                        FROM [dbo].[VW_Branch_To_GeographicalHierarchy] 
                        WHERE Branch = %s
                    """, [branch_name])
                    row = cursor.fetchone()
                    if row:
                        branch_id = row[0]
                    else:
                        # 3. Strip B/_B suffix and look up in hierarchy view
                        stripped = branch_name.replace('_B', '').replace(' B', '').strip()
                        cursor.execute("""
                            SELECT TOP 1 BranchID 
                            FROM [dbo].[VW_Branch_To_GeographicalHierarchy] 
                            WHERE Branch = %s
                        """, [stripped])
                        row = cursor.fetchone()
                        if row:
                            branch_id = row[0]

            if not branch_id:
                return {
                    'success': True,
                    'center_risks': [],
                    'message': f"Branch '{branch_name}' not resolved to an ID."
                }

            with connection.cursor() as cursor:
                cursor.execute("""
                    EXEC SP_GetCenterRiskDetails @BranchID = %s, @AsOnDate = %s
                """, [branch_id, as_on_date if as_on_date else None])
                columns = [col[0] for col in cursor.description] if cursor.description else []
                rows = cursor.fetchall()

            items = []
            for row in rows:
                row_dict = dict(zip(columns, row))
                for key, val in row_dict.items():
                    if isinstance(val, decimal.Decimal):
                        row_dict[key] = float(val)
                    elif hasattr(val, 'isoformat'):
                        row_dict[key] = val.isoformat()
                items.append(row_dict)

            return {
                'success': True,
                'center_risks': items
            }
        except Exception as e:
            log_error(f"GetCenterRiskDetailsQueryHandler failed: {str(e)}")
            raise e


class GetBranchOverviewQuery(Query):
    def __init__(self, branch_name: str, as_on_date=None):
        self.branch_name = branch_name
        self.as_on_date = as_on_date


class GetBranchOverviewQueryHandler(QueryHandler):
    def execute(self, query: GetBranchOverviewQuery) -> dict:
        branch_name = query.branch_name
        as_on_date = query.as_on_date
        try:
            overview_data = {}
            with connection.cursor() as cursor:
                if as_on_date:
                    cursor.execute("""
                        EXEC SP_GetBranchOverview @BranchName = %s, @AsOnDate = %s
                    """, [branch_name, as_on_date])
                else:
                    cursor.execute("""
                        EXEC SP_GetBranchOverview @BranchName = %s
                    """, [branch_name])
                
                # Loop through multiple result sets returned by SP
                has_more = True
                while has_more:
                    columns = [col[0] for col in cursor.description] if cursor.description else []
                    rows = cursor.fetchall()
                    
                    items = []
                    for row in rows:
                        row_dict = dict(zip(columns, row))
                        for key, val in row_dict.items():
                            if isinstance(val, decimal.Decimal):
                                row_dict[key] = float(val)
                            elif hasattr(val, 'isoformat'):
                                row_dict[key] = val.isoformat()
                        items.append(row_dict)
                    
                    if items:
                        section = items[0].get('Section')
                        if section == 'OVERVIEW':
                            overview_data['overview'] = items[0]
                        elif section == 'HIERARCHY':
                            overview_data['hierarchy'] = items
                        elif section == 'PORTFOLIO_HEALTH':
                            overview_data['portfolio_health'] = items
                        elif section == 'DISBURSEMENTS':
                            overview_data['disbursements'] = items
                        elif section == 'STAFF':
                            overview_data['staff'] = items
                            
                    has_more = cursor.nextset()

            return {
                'success': True,
                'branch_overview': overview_data
            }
        except Exception as e:
            log_error(f"GetBranchOverviewQueryHandler failed: {str(e)}")
            raise e


class GetCustomerRiskDetailsQuery(Query):
    def __init__(self, center_id: str, as_on_date=None):
        self.center_id = center_id
        self.as_on_date = as_on_date


class GetCustomerRiskDetailsQueryHandler(QueryHandler):
    def execute(self, query: GetCustomerRiskDetailsQuery) -> dict:
        center_id = query.center_id
        as_on_date = query.as_on_date
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    EXEC SP_GetCustomerRiskDetails @CenterID = %s, @AsOnDate = %s
                """, [center_id, as_on_date])
                cols = [col[0] for col in cursor.description] if cursor.description else []
                rows = cursor.fetchall()

            customers = []
            for row in rows:
                row_dict = dict(zip(cols, row))
                for key, val in row_dict.items():
                    if isinstance(val, decimal.Decimal):
                        row_dict[key] = float(val)
                customers.append(row_dict)

            return {'success': True, 'customer_risks': customers}
        except Exception as e:
            log_error(f"GetCustomerRiskDetailsQueryHandler failed: {str(e)}")
            raise e


class GetCenterDisbursementsQuery(Query):
    def __init__(self, center_id: str, as_on_date=None):
        self.center_id = center_id
        self.as_on_date = as_on_date


class GetCenterDisbursementsQueryHandler(QueryHandler):
    def execute(self, query: GetCenterDisbursementsQuery) -> dict:
        center_id = query.center_id
        as_on_date = query.as_on_date or '2026-06-08'
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    EXEC SP_GetCenterOverview @CenterID = %s, @AsOnDate = %s, @ReportType = 'LAST_TO_CURRENT_DISBURSEMENTS'
                """, [center_id, as_on_date])
                cols = [col[0] for col in cursor.description] if cursor.description else []
                rows = cursor.fetchall()

            disbursements = []
            for row in rows:
                row_dict = dict(zip(cols, row))
                for key, val in row_dict.items():
                    if isinstance(val, decimal.Decimal):
                        row_dict[key] = float(val)
                    elif hasattr(val, 'isoformat'):
                        row_dict[key] = val.isoformat()
                disbursements.append(row_dict)

            return {'success': True, 'disbursements': disbursements}
        except Exception as e:
            log_error(f"GetCenterDisbursementsQueryHandler failed: {str(e)}")
            raise e


class GetCenterAuditFeedbackQuery(Query):
    def __init__(self, center_id: str, audit_id=None, user=None):
        self.center_id = center_id
        self.audit_id = audit_id
        self.user = user


class GetCenterAuditFeedbackQueryHandler(QueryHandler):
    def execute(self, query: GetCenterAuditFeedbackQuery) -> dict:
        center_id = query.center_id
        audit_id = query.audit_id
        user = query.user
        
        try:
            # Resolve audit_id if not explicitly provided
            if not audit_id and user:
                user_id_str = str(user.UserID) if user.UserID is not None else ""
                user_code = user.UserCode or ""
                branch_name = None
                with connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT TOP 1 BranchName 
                        FROM CenterRiskScore 
                        WHERE CenterID = %s OR CenterID = %s
                    """, [str(center_id), center_id])
                    row = cursor.fetchone()
                    if row:
                        branch_name = row[0]
                if branch_name:
                    plan = AuditPlanCurrent.objects.filter(
                        Q(branch=branch_name) & (Q(assigned_auditor=user_id_str) | Q(assigned_auditor=user_code))
                    ).first()
                    if plan:
                        audit_id = plan.id
                    else:
                        audit_id = 0
                else:
                    audit_id = 0

            query_sql = """
                SELECT 
                    f.audit_id, f.center_checklist_id, f.answer, f.normal_remark, f.status,
                    r.confidential_remark,
                    fl.id as confidential_file_id, fl.file_name as confidential_file_name,
                    nf.id as normal_file_id, nf.file_name as normal_file_name,
                    ev.id as evidence_file_id, ev.file_name as evidence_file_name,
                    ev.latitude as evidence_latitude, ev.longitude as evidence_longitude,
                    ev.image_text as evidence_text,
                    f.branchid
                FROM dbo.audit_center_checklist_feedback f
                LEFT JOIN dbo.audit_center_confidential_remarks r ON f.center_id = r.center_id AND f.center_checklist_id = r.center_checklist_id
                LEFT JOIN dbo.audit_center_confidential_files fl ON f.center_id = fl.center_id AND f.center_checklist_id = fl.center_checklist_id AND fl.is_archived = 0
                LEFT JOIN dbo.audit_center_normal_files nf ON f.center_id = nf.center_id AND f.center_checklist_id = nf.center_checklist_id AND nf.is_archived = 0
                LEFT JOIN dbo.audit_center_evidence ev ON f.center_id = ev.center_id AND f.center_checklist_id = ev.center_checklist_id AND ev.is_archived = 0
                WHERE f.center_id = %s
            """
            params = [center_id]
            if audit_id:
                query_sql += " AND f.audit_id = %s"
                params.append(audit_id)

            with connection.cursor() as cursor:
                cursor.execute(query_sql, params)
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()

            feedback_list = []
            feedback_audit_id = audit_id
            for row in rows:
                row_dict = dict(zip(columns, row))
                if row_dict.get("audit_id") and not feedback_audit_id:
                    feedback_audit_id = row_dict.get("audit_id")
                
                normal_file_id = row_dict.get("normal_file_id")
                confidential_file_id = row_dict.get("confidential_file_id")
                evidence_file_id = row_dict.get("evidence_file_id")

                # Convert decimals to float safely
                evidence_latitude = row_dict.get("evidence_latitude")
                if isinstance(evidence_latitude, decimal.Decimal):
                    evidence_latitude = float(evidence_latitude)
                evidence_longitude = row_dict.get("evidence_longitude")
                if isinstance(evidence_longitude, decimal.Decimal):
                    evidence_longitude = float(evidence_longitude)

                feedback_list.append({
                    "checklistId": row_dict.get("center_checklist_id"),
                    "answer": row_dict.get("answer"),
                    "normalRemark": row_dict.get("normal_remark"),
                    "status": row_dict.get("status"),
                    "confidentialRemark": row_dict.get("confidential_remark"),
                    "branchId": row_dict.get("branchid"),
                    "normalFile": {
                        "id": normal_file_id,
                        "filename": row_dict.get("normal_file_name")
                    } if normal_file_id else None,
                    "confidentialFile": {
                        "id": confidential_file_id,
                        "filename": row_dict.get("confidential_file_name")
                    } if confidential_file_id else None,
                    "evidenceImage": {
                        "id": evidence_file_id,
                        "filename": row_dict.get("evidence_file_name"),
                        "latitude": evidence_latitude,
                        "longitude": evidence_longitude,
                        "imageText": row_dict.get("evidence_text")
                    } if evidence_file_id else None,
                })

            return {
                'success': True,
                'feedback': feedback_list,
                'auditId': feedback_audit_id
            }
        except Exception as e:
            log_error(f"GetCenterAuditFeedbackQueryHandler failed: {str(e)}")
            raise e



class ViewCenterFeedbackFileQuery(Query):
    def __init__(self, file_id):
        self.file_id = file_id


class ViewCenterFeedbackFileQueryHandler(QueryHandler):
    def execute(self, query: ViewCenterFeedbackFileQuery) -> dict:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT file_name, file_payload FROM dbo.audit_center_checklist_feedback_files WHERE file_id = %s", [query.file_id])
                row = cursor.fetchone()

            if not row:
                return {'success': False, 'message': 'File not found', 'status_code': 404}

            filename, payload = row
            if payload:
                payload = decompress_file_backend(payload, filename)

            return {'success': True, 'filename': filename, 'payload': payload, 'status_code': 200}
        except Exception as e:
            log_error(f"ViewCenterFeedbackFileQueryHandler failed: {str(e)}")
            raise e


class GetClientAuditFeedbackQuery(Query):
    def __init__(self, audit_id: int, center_id: str, client_id: str):
        self.audit_id = audit_id
        self.center_id = center_id
        self.client_id = client_id


class GetClientAuditFeedbackQueryHandler(QueryHandler):
    def execute(self, query: GetClientAuditFeedbackQuery) -> dict:
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        id, client_checklist_id, parameter_code, parameter_name, 
                        answer, remarks, status
                    FROM dbo.audit_client_checklist_feedback
                    WHERE audit_id = %s AND center_id = %s AND client_id = %s
                """, [query.audit_id, query.center_id, query.client_id])
                cols = [d[0] for d in cursor.description]
                rows = cursor.fetchall()

            feedback_list = []
            for r in rows:
                rd = dict(zip(cols, r))
                feedback_list.append({
                    "feedbackId": rd.get('id'),
                    "checklistId": rd.get('client_checklist_id'),
                    "parameterCode": rd.get('parameter_code'),
                    "parameterName": rd.get('parameter_name'),
                    "answer": rd.get('answer'),
                    "remarks": rd.get('remarks'),
                    "status": rd.get('status')
                })

            return {'success': True, 'feedback': feedback_list}
        except Exception as e:
            log_error(f"GetClientAuditFeedbackQueryHandler failed: {str(e)}")
            raise e


class GetAuditorCapsQuery(Query):
    def __init__(self, user, month_start_date=None, report_type='CAP'):
        self.user = user
        self.month_start_date = month_start_date
        self.report_type = report_type


class GetAuditorCapsQueryHandler(QueryHandler):
    def execute(self, query: GetAuditorCapsQuery) -> dict:
        user = query.user
        try:
            with connection.cursor() as cursor:
                if query.month_start_date:
                    cursor.execute("""
                        EXEC dbo.usp_ManageAuditCAPs
                            @ReportType = %s,
                            @UserID = %s,
                            @MonthStartDate = %s
                    """, [query.report_type, user.UserID, query.month_start_date])
                else:
                    cursor.execute("""
                        EXEC dbo.usp_ManageAuditCAPs
                            @ReportType = %s,
                            @UserID = %s
                    """, [query.report_type, user.UserID])

                columns = [col[0] for col in cursor.description] if cursor.description else []
                rows = cursor.fetchall()

            caps = []
            for row in rows:
                cap = dict(zip(columns, row))
                for k, v in cap.items():
                    if isinstance(v, decimal.Decimal):
                        cap[k] = float(v)
                    elif hasattr(v, 'isoformat'):
                        cap[k] = v.isoformat()
                caps.append(cap)

            return {
                'success': True,
                'caps': caps,
                'total_caps': len(caps)
            }
        except Exception as e:
            log_error(f"GetAuditorCapsQueryHandler failed: {str(e)}")
            raise e


class GetCompletedAuditsQuery(Query):
    def __init__(self, user):
        self.user = user


class GetCompletedAuditsQueryHandler(QueryHandler):
    def execute(self, query: GetCompletedAuditsQuery) -> dict:
        user = query.user
        try:
            with connection.cursor() as cursor:
                sql_query = """
                    SET NOCOUNT ON;
                    DROP TABLE IF EXISTS #UserList;
                    CREATE TABLE #UserList
                    (
                        UserID   VARCHAR(255),
                        UserName NVARCHAR(255)
                    );

                    INSERT INTO #UserList (UserID, UserName)
                    SELECT DISTINCT CAST(fa_userid AS VARCHAR(255)), fa_username
                    FROM dbo.VW_Branch_To_GeographicalHierarchy_head_audit
                    WHERE (division_head_userid = %s OR zonal_userid = %s)
                      AND fa_userid IS NOT NULL;
             
                    INSERT INTO #UserList (UserID, UserName)
                    SELECT CAST(%s AS VARCHAR(255)), amt.UserName
                    FROM dbo.accounts_mst_usertbl amt
                    WHERE amt.UserID = %s
                      AND NOT EXISTS (SELECT 1 FROM #UserList WHERE UserID = CAST(%s AS VARCHAR(255)));

                    SELECT 
                        p.audit_id, 
                        p.audit_branch_id, 
                        p.audit_start_date, 
                        p.audit_end_date, 
                        p.audit_status, 
                        b.Branch,
                        b.Zone,
                        b.Division,
                        b.Region,
                        b.Hub
                    FROM dbo.audit_branch_progress p
                    LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON p.audit_branch_id = b.BranchID
                    WHERE p.audit_assigned_to IN (SELECT UserID FROM #UserList)
                      AND p.audit_end_date IS NOT NULL
                    ORDER BY p.audit_end_date DESC;
                """
                cursor.execute(sql_query, [user.UserID, user.UserID, user.UserID, user.UserID, user.UserID])
                rows = cursor.fetchall()

                completed_list = []
                for row in rows:
                    audit_id = row[0]
                    branch_id = row[1]
                    start_date = row[2]
                    end_date = row[3]
                    status = row[4]
                    branch_name = row[5] or f"Branch {branch_id}"
                    zone = row[6]
                    division = row[7]
                    region = row[8]
                    hub = row[9]

                    # Fetch final summary for scores
                    cursor.execute("""
                        SELECT total_max_score, total_score_obtained, final_score_pct
                        FROM dbo.audit_branch_final_summary
                        WHERE audit_id = %s
                    """, [audit_id])
                    sum_row = cursor.fetchone()

                    total_max = 0.0
                    total_obtained = 0.0
                    score_pct = 0.0

                    if sum_row:
                        total_max = float(sum_row[0]) if sum_row[0] is not None else 0.0
                        total_obtained = float(sum_row[1]) if sum_row[1] is not None else 0.0
                        score_pct = float(sum_row[2]) if sum_row[2] is not None else 0.0

                    # Compute Grade
                    if score_pct > 80.0:
                        grade = 'A'
                    elif score_pct >= 60.0:
                        grade = 'B'
                    elif score_pct >= 40.0:
                        grade = 'C'
                    else:
                        grade = 'D'

                    completed_list.append({
                        'audit_id': audit_id,
                        'branch_id': branch_id,
                        'branch_name': branch_name,
                        'start_date': start_date.strftime('%Y-%m-%d') if start_date else None,
                        'end_date': end_date.strftime('%Y-%m-%d') if end_date else None,
                        'status': status,
                        'zone': zone,
                        'division': division,
                        'region': region,
                        'hub': hub,
                        'total_max_score': total_max,
                        'total_score_obtained': total_obtained,
                        'score_pct': round(score_pct, 2),
                        'grade': grade
                    })

            return {'success': True, 'audits': completed_list}
        except Exception as e:
            log_error(f"GetCompletedAuditsQueryHandler failed: {str(e)}")
            raise e


class GetBranchReportDetailsQuery(Query):
    def __init__(self, audit_id: int):
        self.audit_id = audit_id


class GetBranchReportDetailsQueryHandler(QueryHandler):
    def execute(self, query: GetBranchReportDetailsQuery) -> dict:
        audit_id = query.audit_id
        try:
            with connection.cursor() as cursor:
                # 1. Fetch audit metadata & branch geo
                cursor.execute("""
                    SELECT 
                        p.audit_id, 
                        p.audit_branch_id, 
                        p.audit_start_date, 
                        p.audit_end_date, 
                        p.audit_status, 
                        b.Branch, b.Zone, b.Division, b.Region, b.Hub,
                        u.UserName
                    FROM dbo.audit_branch_progress p
                    LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON p.audit_branch_id = b.BranchID
                    LEFT JOIN dbo.accounts_mst_usertbl u ON p.audit_assigned_to = u.UserID
                    WHERE p.audit_id = %s
                """, [audit_id])
                meta_row = cursor.fetchone()

                if not meta_row:
                    return {'success': False, 'message': 'Audit progress record not found', 'status_code': 404}

                audit_meta = {
                    'audit_id': meta_row[0],
                    'branch_id': meta_row[1],
                    'start_date': meta_row[2].strftime('%Y-%m-%d') if meta_row[2] else None,
                    'end_date': meta_row[3].strftime('%Y-%m-%d') if meta_row[3] else None,
                    'status': meta_row[4],
                    'branch_name': meta_row[5],
                    'zone': meta_row[6],
                    'division': meta_row[7],
                    'region': meta_row[8],
                    'hub': meta_row[9],
                    'auditor_name': meta_row[10]
                }

                # 2. Fetch final summary scores
                cursor.execute("""
                    SELECT 
                        branch_max_score_final, branch_score_obtained,
                        center_count, center_max_score_final, center_score_obtained,
                        client_count, client_max_score_final, client_score_obtained,
                        total_max_score, total_score_obtained, final_score_pct
                    FROM dbo.audit_branch_final_summary
                    WHERE audit_id = %s
                """, [audit_id])
                summary_row = cursor.fetchone()

                scores = {}
                if summary_row:
                    scores = {
                        'branch_max_score_final': float(summary_row[0]) if summary_row[0] is not None else 0.0,
                        'branch_score_obtained': float(summary_row[1]) if summary_row[1] is not None else 0.0,
                        'center_count': int(summary_row[2]) if summary_row[2] is not None else 0,
                        'center_max_score_final': float(summary_row[3]) if summary_row[3] is not None else 0.0,
                        'center_score_obtained': float(summary_row[4]) if summary_row[4] is not None else 0.0,
                        'client_count': int(summary_row[5]) if summary_row[5] is not None else 0,
                        'client_max_score_final': float(summary_row[6]) if summary_row[6] is not None else 0.0,
                        'client_score_obtained': float(summary_row[7]) if summary_row[7] is not None else 0.0,
                        'total_max_score': float(summary_row[8]) if summary_row[8] is not None else 0.0,
                        'total_score_obtained': float(summary_row[9]) if summary_row[9] is not None else 0.0,
                        'final_score_pct': float(summary_row[10]) if summary_row[10] is not None else 0.0,
                    }
                    pct = scores['final_score_pct']
                    if pct > 80.0:
                        scores['grade'] = 'A'
                    elif pct >= 60.0:
                        scores['grade'] = 'B'
                    elif pct >= 40.0:
                        scores['grade'] = 'C'
                    else:
                        scores['grade'] = 'D'
                else:
                    scores = {
                        'branch_max_score_final': 0.0, 'branch_score_obtained': 0.0,
                        'center_count': 0, 'center_max_score_final': 0.0, 'center_score_obtained': 0.0,
                        'client_count': 0, 'client_max_score_final': 0.0, 'client_score_obtained': 0.0,
                        'total_max_score': 0.0, 'total_score_obtained': 0.0, 'final_score_pct': 0.0,
                        'grade': 'N/A'
                    }

                # 3. Fetch branch checklist scores
                cursor.execute("""
                    SELECT
                        s.section_code, s.section_name, s.intent_code, s.intent_title,
                        s.answer, s.max_score, s.score_obtained, s.feedback_id,
                        f.normal_remark AS auditor_remark
                    FROM dbo.audit_branch_checklist_score s
                    LEFT JOIN dbo.audit_branch_checklist_feedback f
                        ON f.audit_id = s.audit_id AND f.checklist_id = s.checklist_id
                    WHERE s.audit_id = %s
                    ORDER BY s.section_code, s.intent_code
                """, [audit_id])
                branch_cols = [d[0] for d in cursor.description]
                branch_scores = [dict(zip(branch_cols, r)) for r in cursor.fetchall()]

                # Formatting numbers
                for item in branch_scores:
                    for k in ('max_score', 'score_obtained'):
                        if item.get(k) is not None:
                            item[k] = float(item[k])

                # Fetch ALL reviewer remarks for branch from review log
                cursor.execute("""
                    SELECT feedback_id, cycle_id, decision, review_remark, decided_at
                    FROM dbo.audit_branch_checklist_review_log
                    WHERE audit_id = %s AND review_remark IS NOT NULL AND LTRIM(RTRIM(review_remark)) <> ''
                    ORDER BY feedback_id, log_id
                """, [audit_id])
                branch_review_log_rows = cursor.fetchall()
                branch_review_map = {}
                for row in branch_review_log_rows:
                    fid = row[0]
                    if fid not in branch_review_map:
                        branch_review_map[fid] = []
                    branch_review_map[fid].append({
                        'cycle_id': row[1],
                        'decision': row[2],
                        'remark': row[3],
                        'decided_at': row[4].isoformat() if hasattr(row[4], 'isoformat') else str(row[4]) if row[4] else None
                    })

                # Attach reviewer_remarks list to each branch score item
                for item in branch_scores:
                    fid = item.pop('feedback_id', None)
                    item['reviewer_remarks'] = branch_review_map.get(fid, [])

                # 4. Fetch center checklist scores
                cursor.execute("""
                    SELECT
                        s.center_id, s.parameter_code, s.parameter_name,
                        s.answer, s.max_score, s.score_obtained, s.feedback_id,
                        f.normal_remark AS auditor_remark
                    FROM dbo.audit_center_checklist_score s
                    LEFT JOIN dbo.audit_center_checklist_feedback f
                        ON f.audit_id = s.audit_id AND f.center_checklist_id = s.center_checklist_id AND f.center_id = s.center_id
                    WHERE s.audit_id = %s
                    ORDER BY s.center_id, s.parameter_code
                """, [audit_id])
                center_cols = [d[0] for d in cursor.description]
                center_scores = [dict(zip(center_cols, r)) for r in cursor.fetchall()]

                for item in center_scores:
                    for k in ('max_score', 'score_obtained'):
                        if item.get(k) is not None:
                            item[k] = float(item[k])

                # Fetch ALL reviewer remarks for center from review log
                try:
                    cursor.execute("""
                        SELECT feedback_id, cycle_id, decision, review_remark, decided_at
                        FROM dbo.audit_center_checklist_review_log
                        WHERE audit_id = %s AND review_remark IS NOT NULL AND LTRIM(RTRIM(review_remark)) <> ''
                        ORDER BY feedback_id, log_id
                    """, [audit_id])
                    center_review_log_rows = cursor.fetchall()
                    center_review_map = {}
                    for row in center_review_log_rows:
                        fid = row[0]
                        if fid not in center_review_map:
                            center_review_map[fid] = []
                        center_review_map[fid].append({
                            'cycle_id': row[1], 'decision': row[2], 'remark': row[3],
                            'decided_at': row[4].isoformat() if hasattr(row[4], 'isoformat') else str(row[4]) if row[4] else None
                        })
                except Exception:
                    center_review_map = {}

                for item in center_scores:
                    fid = item.pop('feedback_id', None)
                    item['reviewer_remarks'] = center_review_map.get(fid, [])

                # 5. Fetch client checklist scores
                cursor.execute("""
                    SELECT
                        s.center_id, s.client_id, s.client_name,
                        s.parameter_code, s.parameter_name,
                        s.answer, s.max_score, s.score_obtained, s.feedback_id,
                        f.remarks AS auditor_remark
                    FROM dbo.audit_client_checklist_score s
                    LEFT JOIN dbo.audit_client_checklist_feedback f
                        ON f.audit_id = s.audit_id AND f.client_checklist_id = s.client_checklist_id AND f.client_id = s.client_id
                    WHERE s.audit_id = %s
                    ORDER BY s.center_id, s.client_id, s.parameter_code
                """, [audit_id])
                client_cols = [d[0] for d in cursor.description]
                client_scores = [dict(zip(client_cols, r)) for r in cursor.fetchall()]

                for item in client_scores:
                    for k in ('max_score', 'score_obtained'):
                        if item.get(k) is not None:
                            item[k] = float(item[k])

                # Fetch ALL reviewer remarks for client from review log
                try:
                    cursor.execute("""
                        SELECT feedback_id, cycle_id, decision, review_remark, decided_at
                        FROM dbo.audit_client_checklist_review_log
                        WHERE audit_id = %s AND review_remark IS NOT NULL AND LTRIM(RTRIM(review_remark)) <> ''
                        ORDER BY feedback_id, log_id
                    """, [audit_id])
                    client_review_log_rows = cursor.fetchall()
                    client_review_map = {}
                    for row in client_review_log_rows:
                        fid = row[0]
                        if fid not in client_review_map:
                            client_review_map[fid] = []
                        client_review_map[fid].append({
                            'cycle_id': row[1], 'decision': row[2], 'remark': row[3],
                            'decided_at': row[4].isoformat() if hasattr(row[4], 'isoformat') else str(row[4]) if row[4] else None
                        })
                except Exception:
                    client_review_map = {}

                for item in client_scores:
                    fid = item.pop('feedback_id', None)
                    item['reviewer_remarks'] = client_review_map.get(fid, [])

            return {
                'success': True,
                'metadata': audit_meta,
                'scores': scores,
                'branch_details': branch_scores,
                'center_details': center_scores,
                'client_details': client_scores
            }
        except Exception as e:
            log_error(f"GetBranchReportDetailsQueryHandler failed: {str(e)}")
            raise e


class GetAuditorDashboardQuery(Query):
    def __init__(self, user):
        self.user = user


class GetAuditorDashboardQueryHandler(QueryHandler):
    def execute(self, query: GetAuditorDashboardQuery) -> dict:
        user = query.user
        try:
            with connection.cursor() as cursor:
                # Stats
                cursor.execute("""
                    SELECT 
                        COUNT(CASE WHEN audit_status = 'completed' THEN 1 END) AS completed,
                        COUNT(CASE WHEN audit_status = 'in-progress' THEN 1 END) AS in_progress,
                        COUNT(audit_id) AS total
                    FROM dbo.audit_branch_progress
                    WHERE audit_assigned_to = %s
                """, [user.UserID])
                stat_row = cursor.fetchone()
                
                stats = {
                    'completed': stat_row[0] if stat_row else 0,
                    'inProgress': stat_row[1] if stat_row else 0,
                    'total': stat_row[2] if stat_row else 0,
                }
                
                # Active audits list
                cursor.execute("""
                    SELECT top 5
                        p.audit_id, b.Branch, p.audit_start_date, p.audit_status
                    FROM dbo.audit_branch_progress p
                    LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON p.audit_branch_id = b.BranchID
                    WHERE p.audit_assigned_to = %s AND p.audit_status <> 'completed'
                    ORDER BY p.audit_start_date DESC
                """, [user.UserID])
                rows = cursor.fetchall()
                active_audits = []
                for r in rows:
                    active_audits.append({
                        'id': r[0],
                        'branch': r[1] or 'Unknown',
                        'startDate': r[2].strftime('%Y-%m-%d') if r[2] else '',
                        'status': r[3]
                    })

            return {'success': True, 'stats': stats, 'activeAudits': active_audits}
        except Exception as e:
            log_error(f"GetAuditorDashboardQueryHandler failed: {str(e)}")
            raise e


class GetSelectedCentersQuery(Query):
    def __init__(self, audit_id: int):
        self.audit_id = audit_id


class GetSelectedCentersQueryHandler(QueryHandler):
    def execute(self, query: GetSelectedCentersQuery) -> dict:
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    EXEC dbo.usp_ManageAuditorPlans
                        @Action = 'GET',
                        @AuditID = %s
                """, [query.audit_id])
                cols = [col[0] for col in cursor.description] if cursor.description else []
                rows = cursor.fetchall()
            
            centers = []
            for row in rows:
                centers.append(dict(zip(cols, row)))
            return {'success': True, 'centers': centers}
        except Exception as e:
            log_error(f"GetSelectedCentersQueryHandler failed: {str(e)}")
            raise e


class GetAuditorPlansQuery(Query):
    def __init__(self, user):
        self.user = user


class GetAuditorPlansQueryHandler(QueryHandler):
    def execute(self, query: GetAuditorPlansQuery) -> dict:
        user = query.user
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    EXEC dbo.usp_ManageAuditorPlans
                        @Action = 'GET_ALL',
                        @UserID = %s
                """, [user.UserID])
                
                columns = [col[0] for col in cursor.description] if cursor.description else []
                rows = cursor.fetchall()

            # Build list of centers and group by branch/audit in Python
            plans_map = {}
            for row in rows:
                row_dict = dict(zip(columns, row))
                audit_id = row_dict.get('auditId')
                
                if audit_id not in plans_map:
                    plans_map[audit_id] = {
                        'auditId': audit_id,
                        'branchId': row_dict.get('branchId'),
                        'branchName': row_dict.get('branchName'),
                        'division': row_dict.get('division'),
                        'startDate': row_dict.get('startDate').isoformat() if hasattr(row_dict.get('startDate'), 'isoformat') else row_dict.get('startDate'),
                        'endDate': row_dict.get('endDate').isoformat() if hasattr(row_dict.get('endDate'), 'isoformat') else row_dict.get('endDate'),
                        'auditStatus': row_dict.get('auditStatus'),
                        'selectedCenters': []
                    }
                
                center_id = row_dict.get('centerId')
                if center_id:
                    plans_map[audit_id]['selectedCenters'].append({
                        'centerId': center_id,
                        'centerName': row_dict.get('centerName'),
                        'selectedAt': row_dict.get('selectedAt').isoformat() if hasattr(row_dict.get('selectedAt'), 'isoformat') else row_dict.get('selectedAt')
                    })

            plans_list = list(plans_map.values())
            return {'success': True, 'plans': plans_list}
        except Exception as e:
            log_error(f"GetAuditorPlansQueryHandler failed: {str(e)}")
            raise e


class GetReviewQueueQuery(Query):
    def __init__(self, user):
        self.user = user


class GetReviewQueueQueryHandler(QueryHandler):
    def execute(self, query: GetReviewQueueQuery) -> dict:
        user = query.user
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        r.cycle_id AS review_id, 
                        r.audit_id, 
                        r.branch_id,
                        COALESCE(b.Branch, CAST(r.branch_id AS varchar)) AS branch_name, 
                        b.Division AS division,
                        u.UserName AS auditor_name, 
                        r.cycle_no,
                        r.cycle_no AS current_cycle, 
                        r.outcome AS status, 
                        r.outcome AS audit_status,
                        r.submitted_at,
                        r.updated_at
                    FROM dbo.audit_branch_review_cycle r
                    LEFT JOIN dbo.audit_branch_progress p ON r.audit_id = p.audit_id
                    LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON CAST(r.branch_id AS varchar) = b.BranchID
                    LEFT JOIN dbo.accounts_mst_usertbl u ON r.submitted_by = u.UserID
                    WHERE (r.reviewer_id = %s OR p.audit_pending_with = %s OR r.reviewer_id IS NULL OR r.submitted_by = %s)
                      AND LOWER(r.outcome) IN ('submitted_l1', 'submitted_l2', 'submitted_l3', 'pending', 'in-review', 'in_review')
                    ORDER BY r.updated_at DESC
                """, [user.UserID, user.UserID, user.UserID])
                cols = [d[0] for d in cursor.description]
                rows = cursor.fetchall()
            
            queue = []
            for r in rows:
                rd = dict(zip(cols, r))
                rd['Division'] = rd.get('division')
                if rd.get('submitted_at') and hasattr(rd['submitted_at'], 'isoformat'):
                    rd['submitted_at'] = rd['submitted_at'].isoformat()
                if rd.get('updated_at') and hasattr(rd['updated_at'], 'isoformat'):
                    rd['updated_at'] = rd['updated_at'].isoformat()
                queue.append(rd)

            return {'success': True, 'queue': queue, 'audits': queue}
        except Exception as e:
            log_error(f"GetReviewQueueQueryHandler failed: {str(e)}")
            raise e


class GetReviewPointsQuery(Query):
    def __init__(self, audit_id: int):
        self.audit_id = audit_id


class GetReviewPointsQueryHandler(QueryHandler):
    def execute(self, query: GetReviewPointsQuery) -> dict:
        audit_id = query.audit_id
        try:
            with connection.cursor() as cursor:
                # 1. Fetch audit metadata
                audit_meta = {}
                cursor.execute("""
                    SELECT 
                        p.audit_id, 
                        p.audit_branch_id AS branch_id,
                        COALESCE(b.Branch, CAST(p.audit_branch_id AS varchar)) AS branch_name,
                        b.Division AS division,
                        u.UserName AS auditor_name,
                        p.audit_status,
                        p.current_cycle_no,
                        rc.submitted_at
                    FROM dbo.audit_branch_progress p
                    LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON CAST(p.audit_branch_id AS varchar) = b.BranchID
                    LEFT JOIN dbo.accounts_mst_usertbl u ON p.audit_assigned_to = u.UserID
                    LEFT JOIN dbo.audit_branch_review_cycle rc ON p.audit_id = rc.audit_id AND p.current_cycle_no = rc.cycle_no
                    WHERE p.audit_id = %s
                """, [audit_id])
                meta_row = cursor.fetchone()
                if meta_row:
                    sub_at = meta_row[7]
                    if sub_at and hasattr(sub_at, 'isoformat'):
                        sub_at = sub_at.isoformat()
                    audit_meta = {
                        'audit_id': meta_row[0],
                        'branch_id': meta_row[1],
                        'branch_name': meta_row[2] or f"Branch {meta_row[1]}",
                        'division': meta_row[3] or '',
                        'Division': meta_row[3] or '',
                        'auditor_name': meta_row[4] or "Auditor",
                        'audit_status': meta_row[5],
                        'current_cycle_no': meta_row[6],
                        'submitted_at': sub_at
                    }

                # 2. Branch level points
                cursor.execute("""
                    SELECT
                        f.id AS feedback_id,
                        f.checklist_id,
                        f.section_code,
                        COALESCE(NULLIF(m.section_name, ''), f.section_name) AS section_name,
                        f.intent_code,
                        COALESCE(NULLIF(m.intent_description, ''), NULLIF(m.intent_title, ''), NULLIF(f.intent_title, ''), f.intent_code) AS intent_title,
                        COALESCE(NULLIF(m.intent_title, ''), NULLIF(f.intent_title, ''), f.intent_code) AS intent_title_short,
                        m.intent_description,
                        f.answer,
                        f.normal_remark AS auditor_remark,
                        f.normal_file_path,
                        nf.id AS normal_file_id,
                        nf.file_name AS normal_file_name,
                        cf.id AS confidential_file_id,
                        cf.file_name AS confidential_file_name,
                        f.total_sub_points,
                        f.sub_points_yes_count,
                        f.sub_points_no_count,
                        COALESCE(s.max_score, m.max_score, 1) AS max_score,
                        COALESCE(s.score_obtained, CASE WHEN f.answer = 'Yes' THEN COALESCE(s.max_score, m.max_score, 1) ELSE 0 END) AS score_obtained,
                        COALESCE(l.decision, f.review_status, 'pending_review') AS review_status,
                        COALESCE(l.decision, f.review_status, 'pending_review') AS last_decision,
                        COALESCE(l.review_remark, f.review_remark, '') AS review_remark,
                        COALESCE(l.review_remark, f.review_remark, '') AS last_remark
                    FROM dbo.audit_branch_checklist_feedback f
                    LEFT JOIN dbo.audit_branch_checklist_master m ON f.checklist_id = m.checklist_id
                    LEFT JOIN dbo.audit_branch_checklist_score s ON f.checklist_id = s.checklist_id AND f.audit_id = s.audit_id
                    LEFT JOIN (
                        SELECT feedback_id, MAX(id) AS id, MAX(file_name) AS file_name
                        FROM dbo.audit_branch_normal_files
                        WHERE is_archived = 0
                        GROUP BY feedback_id
                    ) nf ON f.id = nf.feedback_id
                    LEFT JOIN (
                        SELECT feedback_id, MAX(id) AS id, MAX(file_name) AS file_name
                        FROM dbo.audit_branch_confidential_files
                        WHERE is_archived = 0
                        GROUP BY feedback_id
                    ) cf ON f.id = cf.feedback_id
                    LEFT JOIN (
                        SELECT feedback_id, decision, review_remark,
                               ROW_NUMBER() OVER (PARTITION BY feedback_id ORDER BY log_id DESC) as rn
                        FROM dbo.audit_branch_checklist_review_log
                        WHERE audit_id = %s
                    ) l ON f.id = l.feedback_id AND l.rn = 1
                    WHERE f.audit_id = %s
                """, [audit_id, audit_id])
                b_cols = [d[0] for d in cursor.description]
                branch_points = [dict(zip(b_cols, row)) for row in cursor.fetchall()]

                # 3. Center level points
                cursor.execute("""
                    SELECT
                        f.id AS feedback_id,
                        f.center_id,
                        f.center_checklist_id AS checklist_id,
                        f.parameter_code,
                        COALESCE(NULLIF(m.parameter_name, ''), NULLIF(f.parameter_name, ''), f.parameter_code) AS parameter_name,
                        COALESCE(NULLIF(m.parameter_name, ''), NULLIF(f.parameter_name, ''), f.parameter_code) AS intent_title,
                        f.answer,
                        f.normal_remark AS auditor_remark,
                        f.normal_file_path,
                        cnf.id AS normal_file_id,
                        cnf.file_name AS normal_file_name,
                        ce.id AS evidence_file_id,
                        ce.file_name AS evidence_file_name,
                        1 AS max_score,
                        CASE WHEN f.answer = 'Yes' THEN 1 ELSE 0 END AS score_obtained,
                        COALESCE(l.decision, f.review_status, 'pending_review') AS review_status,
                        COALESCE(l.decision, f.review_status, 'pending_review') AS last_decision,
                        COALESCE(l.review_remark, f.review_remark, '') AS review_remark,
                        COALESCE(l.review_remark, f.review_remark, '') AS last_remark
                    FROM dbo.audit_center_checklist_feedback f
                    LEFT JOIN dbo.audit_center_checklist_master m ON f.center_checklist_id = m.center_checklist_id
                    LEFT JOIN (
                        SELECT feedback_id, MAX(id) AS id, MAX(file_name) AS file_name
                        FROM dbo.audit_center_normal_files
                        WHERE is_archived = 0
                        GROUP BY feedback_id
                    ) cnf ON f.id = cnf.feedback_id
                    LEFT JOIN (
                        SELECT feedback_id, MAX(id) AS id, MAX(file_name) AS file_name
                        FROM dbo.audit_center_evidence
                        WHERE is_archived = 0
                        GROUP BY feedback_id
                    ) ce ON f.id = ce.feedback_id
                    LEFT JOIN (
                        SELECT feedback_id, decision, review_remark,
                               ROW_NUMBER() OVER (PARTITION BY feedback_id ORDER BY log_id DESC) as rn
                        FROM dbo.audit_center_checklist_review_log
                        WHERE audit_id = %s
                    ) l ON f.id = l.feedback_id AND l.rn = 1
                    WHERE f.audit_id = %s
                """, [audit_id, audit_id])
                c_cols = [d[0] for d in cursor.description]
                center_points = [dict(zip(c_cols, row)) for row in cursor.fetchall()]

                # 4. Client level points
                cursor.execute("""
                    SELECT
                        f.id AS feedback_id,
                        f.center_id,
                        f.client_id,
                        f.client_name,
                        f.client_checklist_id AS checklist_id,
                        f.parameter_code,
                        COALESCE(NULLIF(m.parameter_name, ''), NULLIF(f.parameter_name, ''), f.parameter_code) AS parameter_name,
                        COALESCE(NULLIF(m.parameter_name, ''), NULLIF(f.parameter_name, ''), f.parameter_code) AS intent_title,
                        f.answer,
                        f.remarks AS auditor_remark,
                        1 AS max_score,
                        CASE WHEN f.answer = 'Yes' THEN 1 ELSE 0 END AS score_obtained,
                        COALESCE(l.decision, f.review_status, 'pending_review') AS review_status,
                        COALESCE(l.decision, f.review_status, 'pending_review') AS last_decision,
                        COALESCE(l.review_remark, f.review_remark, '') AS review_remark,
                        COALESCE(l.review_remark, f.review_remark, '') AS last_remark
                    FROM dbo.audit_client_checklist_feedback f
                    LEFT JOIN dbo.audit_client_checklist_master m ON f.client_checklist_id = m.client_checklist_id
                    LEFT JOIN (
                        SELECT feedback_id, decision, review_remark,
                               ROW_NUMBER() OVER (PARTITION BY feedback_id ORDER BY log_id DESC) as rn
                        FROM dbo.audit_client_checklist_review_log
                        WHERE audit_id = %s
                    ) l ON f.id = l.feedback_id AND l.rn = 1
                    WHERE f.audit_id = %s
                """, [audit_id, audit_id])
                cl_cols = [d[0] for d in cursor.description]
                client_points = [dict(zip(cl_cols, row)) for row in cursor.fetchall()]

            for pts in (branch_points, center_points, client_points):
                for p in pts:
                    for k in ('max_score', 'score_obtained'):
                        if p.get(k) is not None:
                            p[k] = float(p[k])

            return {
                'success': True,
                'audit_meta': audit_meta,
                'branch_points': branch_points,
                'center_points': center_points,
                'client_points': client_points
            }
        except Exception as e:
            log_error(f"GetReviewPointsQueryHandler failed: {str(e)}")
            raise e


class GetAuditReviewStatusQuery(Query):
    def __init__(self, audit_id: int, branch_id):
        self.audit_id = audit_id
        self.branch_id = str(branch_id).strip()


class GetAuditReviewStatusQueryHandler(QueryHandler):
    def execute(self, query: GetAuditReviewStatusQuery) -> dict:
        audit_id = query.audit_id
        branch_id = query.branch_id
        try:
            with connection.cursor() as cursor:
                # Fetch audit status + cycle info
                cursor.execute("""
                    SELECT
                        p.audit_status,
                        p.current_cycle_no,
                        p.audit_pending_with,
                        rc.submitted_at,
                        rc.review_started_at,
                        rc.review_completed_at,
                        rc.outcome,
                        u_rev.UserName AS reviewer_name
                    FROM dbo.audit_branch_progress p
                    LEFT JOIN dbo.audit_branch_review_cycle rc
                        ON rc.audit_id = p.audit_id
                       AND rc.branch_id = p.audit_branch_id
                       AND rc.cycle_no = p.current_cycle_no
                    LEFT JOIN dbo.accounts_mst_usertbl u_rev
                        ON u_rev.UserID = p.audit_pending_with
                    WHERE p.audit_id = %s AND p.audit_branch_id = %s
                """, [audit_id, branch_id])
                row = cursor.fetchone()
                if not row:
                    return {'success': False, 'message': 'Audit not found', 'status_code': 404}

                cols = [d[0] for d in cursor.description]
                status_info = dict(zip(cols, row))
                for k, v in status_info.items():
                    if hasattr(v, 'isoformat'):
                        status_info[k] = v.isoformat()

                # Fetch branch feedback with review remarks
                cursor.execute("""
                    SELECT
                        f.id AS feedback_id, f.checklist_id,
                        f.intent_code, f.intent_title,
                        f.answer, f.review_status, f.review_remark
                    FROM dbo.audit_branch_checklist_feedback f
                    WHERE f.audit_id = %s AND TRY_CAST(f.branch_id AS INT) = %s
                    ORDER BY f.section_code, f.intent_code
                """, [audit_id, branch_id])
                branch_review = [dict(zip([d[0] for d in cursor.description], r)) for r in cursor.fetchall()]

                # Fetch center feedback with review remarks
                cursor.execute("""
                    SELECT
                        f.id AS feedback_id, f.center_checklist_id AS checklist_id,
                        f.center_id, f.parameter_code, f.parameter_name,
                        f.answer, f.review_status, f.review_remark
                    FROM dbo.audit_center_checklist_feedback f
                    WHERE f.audit_id = %s AND TRY_CAST(f.branchid AS INT) = %s
                    ORDER BY f.center_id, f.parameter_code
                """, [audit_id, branch_id])
                center_review = [dict(zip([d[0] for d in cursor.description], r)) for r in cursor.fetchall()]

                # Fetch client feedback with review remarks
                cursor.execute("""
                    SELECT
                        f.id AS feedback_id, f.client_checklist_id AS checklist_id,
                        f.center_id, CAST(f.client_id AS NVARCHAR(50)) AS client_id,
                        f.client_name, f.parameter_code, f.parameter_name,
                        f.answer, CAST(f.review_status AS VARCHAR(20)) AS review_status, f.review_remark
                    FROM dbo.audit_client_checklist_feedback f
                    WHERE f.audit_id = %s AND TRY_CAST(f.branch_id AS INT) = %s
                    ORDER BY f.center_id, f.client_id, f.parameter_code
                """, [audit_id, branch_id])
                client_review = [dict(zip([d[0] for d in cursor.description], r)) for r in cursor.fetchall()]

            return {
                'success': True,
                'status_info': status_info,
                'branch_review': branch_review,
                'center_review': center_review,
                'client_review': client_review
            }
        except Exception as e:
            log_error(f"GetAuditReviewStatusQueryHandler failed: {str(e)}")
            raise e


class GetBranchReportExcelQuery(Query):
    def __init__(self, audit_id: int):
        self.audit_id = audit_id


class GetBranchReportExcelQueryHandler(QueryHandler):
    def execute(self, query: GetBranchReportExcelQuery) -> dict:
        audit_id = query.audit_id
        # Note: Handled by calling fetch metadata logic and returning the data package.
        # The view will handle calling generate_branch_audit_excel directly.
        try:
            with connection.cursor() as cursor:
                # 1. Fetch metadata
                cursor.execute("""
                    SELECT p.audit_branch_id, b.Branch, p.audit_start_date, p.audit_end_date, u.UserName, p.audit_status
                    FROM dbo.audit_branch_progress p
                    LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON p.audit_branch_id = b.BranchID
                    LEFT JOIN dbo.accounts_mst_usertbl u ON p.audit_assigned_to = u.UserID
                    WHERE p.audit_id = %s
                """, [audit_id])
                meta_row = cursor.fetchone()
                if not meta_row:
                    return {'success': False, 'message': 'Audit not found', 'status_code': 404}
                
                branch_id = meta_row[0]

                # Fetch summary
                cursor.execute("""
                    SELECT total_max_score, total_score, score_pct
                    FROM dbo.audit_branch_score_summary
                    WHERE audit_id = %s
                """, [audit_id])
                summary_row = cursor.fetchone()
                total_max = float(summary_row[0] or 0) if summary_row else 0.0
                total_obtained = float(summary_row[1] or 0) if summary_row else 0.0
                pct = float(summary_row[2] or 0) if summary_row else 0.0
                grade = 'D'
                if pct > 80.0: grade = 'A'
                elif pct >= 60.0: grade = 'B'
                elif pct >= 40.0: grade = 'C'

                metadata = {
                    'branch_name': meta_row[1] or 'Unknown',
                    'audit_period': f"{meta_row[2].strftime('%Y-%m-%d') if meta_row[2] else ''} to {meta_row[3].strftime('%Y-%m-%d') if meta_row[3] else ''}",
                    'auditor_name': meta_row[4] or 'Unknown',
                    'status': meta_row[5],
                    'total_score': total_obtained,
                    'total_max_score': total_max,
                    'percentage': pct,
                    'grade': grade
                }

                # 2. Fetch Branch Points
                cursor.execute("""
                    SELECT
                        f.id AS feedback_id,
                        f.section_code,
                        f.intent_title AS intent,
                        m.intent_description AS risk_issue,
                        m.category,
                        f.answer AS yes_no_na,
                        '' AS sample_verification,
                        '' AS correct_finding,
                        '' AS wrong_finding,
                        '' AS total_sample,
                        '' AS process_deviation,
                        s.max_score,
                        s.score_obtained AS obtained_score,
                        CASE WHEN s.score_obtained < s.max_score THEN 'Yes' ELSE 'No' END AS is_issue,
                        f.normal_remark AS auditor_remark
                    FROM dbo.audit_branch_checklist_feedback f
                    LEFT JOIN dbo.audit_branch_checklist_master m ON f.checklist_id = m.checklist_id
                    LEFT JOIN dbo.audit_branch_checklist_score s ON f.checklist_id = s.checklist_id AND f.audit_id = s.audit_id
                    WHERE f.audit_id = %s AND TRY_CAST(f.branch_id AS INT) = %s
                    ORDER BY f.section_code, f.intent_code
                """, [audit_id, branch_id])
                b_cols = [d[0] for d in cursor.description]
                branch_points = [dict(zip(b_cols, row)) for row in cursor.fetchall()]

                cursor.execute("""
                    SELECT feedback_id, cycle_id, decision, review_remark
                    FROM dbo.audit_branch_checklist_review_log
                    WHERE audit_id = %s AND review_remark IS NOT NULL AND LTRIM(RTRIM(review_remark)) <> ''
                    ORDER BY feedback_id, log_id
                """, [audit_id])
                b_review_map = {}
                for rrow in cursor.fetchall():
                    fid = rrow[0]
                    if fid not in b_review_map:
                        b_review_map[fid] = []
                    b_review_map[fid].append(f"Cycle {rrow[1]} ({rrow[2]}): {rrow[3]}")

                for pt in branch_points:
                    fid = pt.pop('feedback_id', None)
                    pt['reviewer_remark'] = '\n'.join(b_review_map.get(fid, []))

                # 3. Center Points
                cursor.execute("""
                    SELECT
                        f.id AS feedback_id, f.center_id, f.parameter_code, f.parameter_name, f.answer, f.normal_remark AS auditor_remark
                    FROM dbo.audit_center_checklist_feedback f
                    WHERE f.audit_id = %s AND TRY_CAST(f.branchid AS INT) = %s
                    ORDER BY f.center_id, f.parameter_code
                """, [audit_id, branch_id])
                c_cols = [d[0] for d in cursor.description]
                center_points = [dict(zip(c_cols, row)) for row in cursor.fetchall()]

                try:
                    cursor.execute("""
                        SELECT feedback_id, cycle_id, decision, review_remark
                        FROM dbo.audit_center_checklist_review_log
                        WHERE audit_id = %s AND review_remark IS NOT NULL AND LTRIM(RTRIM(review_remark)) <> ''
                        ORDER BY feedback_id, log_id
                    """, [audit_id])
                    c_review_map = {}
                    for rrow in cursor.fetchall():
                        fid = rrow[0]
                        if fid not in c_review_map:
                            c_review_map[fid] = []
                        c_review_map[fid].append(f"Cycle {rrow[1]} ({rrow[2]}): {rrow[3]}")
                except Exception:
                    c_review_map = {}

                for pt in center_points:
                    fid = pt.pop('feedback_id', None)
                    pt['reviewer_remark'] = '\n'.join(c_review_map.get(fid, []))

                # 4. Client Points
                cursor.execute("""
                    SELECT
                        f.id AS feedback_id, f.center_id, TRY_CAST(f.client_id AS INT) AS client_id, f.client_name, f.parameter_code, f.parameter_name, f.answer, f.remarks AS auditor_remark
                    FROM dbo.audit_client_checklist_feedback f
                    WHERE f.audit_id = %s AND TRY_CAST(f.branch_id AS INT) = %s
                    ORDER BY f.center_id, f.client_id, f.parameter_code
                """, [audit_id, branch_id])
                cl_cols = [d[0] for d in cursor.description]
                client_points = [dict(zip(cl_cols, row)) for row in cursor.fetchall()]

                try:
                    cursor.execute("""
                        SELECT feedback_id, cycle_id, decision, review_remark
                        FROM dbo.audit_client_checklist_review_log
                        WHERE audit_id = %s AND review_remark IS NOT NULL AND LTRIM(RTRIM(review_remark)) <> ''
                        ORDER BY feedback_id, log_id
                    """, [audit_id])
                    cl_review_map = {}
                    for rrow in cursor.fetchall():
                        fid = rrow[0]
                        if fid not in cl_review_map:
                            cl_review_map[fid] = []
                        cl_review_map[fid].append(f"Cycle {rrow[1]} ({rrow[2]}): {rrow[3]}")
                except Exception:
                    cl_review_map = {}

                for pt in client_points:
                    fid = pt.pop('feedback_id', None)
                    pt['reviewer_remark'] = '\n'.join(cl_review_map.get(fid, []))

            return {
                'success': True,
                'metadata': metadata,
                'branch_points': branch_points,
                'center_points': center_points,
                'client_points': client_points
            }
        except Exception as e:
            log_error(f"GetBranchReportExcelQueryHandler failed: {str(e)}")
            raise e


class GetAuditeeDashboardQuery(Query):
    def __init__(self, user):
        self.user = user


class GetAuditeeDashboardQueryHandler(QueryHandler):
    def execute(self, query: GetAuditeeDashboardQuery) -> dict:
        user = query.user
        try:
            with connection.cursor() as cursor:
                branch_ids = get_user_branch_ids(cursor, user)
                placeholders = ', '.join(['%s'] * len(branch_ids))

                # Count stats
                cursor.execute(f"""
                    SELECT 
                        COUNT(CASE WHEN audit_status = 'completed' THEN 1 END) AS completed,
                        COUNT(CASE WHEN audit_status = 'in-progress' THEN 1 END) AS in_progress,
                        COUNT(audit_id) AS total
                    FROM dbo.audit_branch_progress
                    WHERE audit_branch_id IN ({placeholders})
                """, branch_ids)
                stat_row = cursor.fetchone()

                stats = {
                    'completed': stat_row[0] if stat_row else 0,
                    'inProgress': stat_row[1] if stat_row else 0,
                    'total': stat_row[2] if stat_row else 0,
                }

                # Recent audits
                cursor.execute(f"""
                    SELECT top 5
                        p.audit_id, b.Branch, p.audit_start_date, p.audit_status
                    FROM dbo.audit_branch_progress p
                    LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON p.audit_branch_id = b.BranchID
                    WHERE p.audit_branch_id IN ({placeholders})
                    ORDER BY p.audit_start_date DESC
                """, branch_ids)
                rows = cursor.fetchall()
                active_audits = []
                for r in rows:
                    active_audits.append({
                        'id': r[0],
                        'branch': r[1] or 'Unknown',
                        'startDate': r[2].strftime('%Y-%m-%d') if r[2] else '',
                        'status': r[3]
                    })

            return {'success': True, 'stats': stats, 'activeAudits': active_audits}
        except Exception as e:
            log_error(f"GetAuditeeDashboardQueryHandler failed: {str(e)}")
            raise e


class GetAuditeeAuditsQuery(Query):
    def __init__(self, user):
        self.user = user


class GetAuditeeAuditsQueryHandler(QueryHandler):
    def execute(self, query: GetAuditeeAuditsQuery) -> dict:
        user = query.user
        try:
            with connection.cursor() as cursor:
                branch_ids = get_user_branch_ids(cursor, user)
                placeholders = ', '.join(['%s'] * len(branch_ids))

                sql_query = f"""
                    SELECT 
                        p.audit_id, 
                        p.audit_branch_id, 
                        p.audit_start_date, 
                        p.audit_end_date, 
                        p.audit_status,
                        b.Branch as branch_name, 
                        b.Division, 
                        b.Zone,
                        b.Region,
                        u.UserName as auditor_name,
                        c.grade,
                        s.score_pct,
                        s.total_max_score,
                        s.total_score,
                        c.audit_mode
                    FROM dbo.audit_branch_progress p
                    LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON p.audit_branch_id = b.BranchID
                    LEFT JOIN dbo.accounts_mst_usertbl u ON p.audit_assigned_to = u.UserID
                    LEFT JOIN dbo.audit_plan_current c ON p.audit_id = c.id
                    LEFT JOIN dbo.audit_branch_score_summary s ON p.audit_id = s.audit_id
                    WHERE (p.audit_status = 'completed' or p.audit_status='reverted' or p.audit_status='submitted') 
                      AND p.audit_branch_id IN ({placeholders})
                    ORDER BY p.audit_end_date DESC
                """
                cursor.execute(sql_query, branch_ids)
                columns = [col[0] for col in cursor.description] if cursor.description else []
                rows = cursor.fetchall()
                
            audits = []
            for row in rows:
                audit = dict(zip(columns, row))
                for k, v in audit.items():
                    if isinstance(v, decimal.Decimal):
                        audit[k] = float(v)
                    elif hasattr(v, 'isoformat'):
                        audit[k] = v.isoformat()
                audits.append(audit)

            return {
                'success': True,
                'audits': audits
            }
        except Exception as e:
            log_error(f"GetAuditeeAuditsQueryHandler failed: {str(e)}")
            raise e


class GetAuditeeCapsQuery(Query):
    def __init__(self, user):
        self.user = user


class GetAuditeeCapsQueryHandler(QueryHandler):
    def execute(self, query: GetAuditeeCapsQuery) -> dict:
        user = query.user
        try:
            with connection.cursor() as cursor:
                branch_ids = get_user_branch_ids(cursor, user)
                placeholders = ', '.join(['%s'] * len(branch_ids))

                # Branch-level CAPs
                cursor.execute(f"""
                    SELECT
                        'BRANCH'            AS cap_type,
                        bf.id               AS feedback_id,
                        bf.audit_id,
                        bf.branch_id,
                        NULL                AS center_id,
                        NULL                AS client_id,
                        NULL                AS client_name,
                        bf.intent_code      AS parameter_code,
                        bf.intent_title     AS parameter_name,
                        bf.section_code,
                        bf.section_name,
                        bf.answer,
                        bf.normal_remark    AS remark,
                        ISNULL(b.Branch, CONCAT('Branch ', bf.branch_id)) AS branch_name,
                        bf.created_at
                    FROM dbo.audit_branch_checklist_feedback bf
                    LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON TRY_CAST(bf.branch_id AS INT) = b.BranchID
                    WHERE bf.answer = 'Yes' AND TRY_CAST(bf.branch_id AS INT) IN ({placeholders})
                """, branch_ids)
                branch_cols = [col[0] for col in cursor.description] if cursor.description else []
                branch_rows = cursor.fetchall()

                # Center-level CAPs
                cursor.execute(f"""
                    SELECT
                        'CENTER'            AS cap_type,
                        cf.id               AS feedback_id,
                        cf.audit_id,
                        cf.branchid         AS branch_id,
                        cf.center_id,
                        NULL                AS client_id,
                        NULL                AS client_name,
                        cf.parameter_code,
                        cf.parameter_name,
                        NULL                AS section_code,
                        NULL                AS section_name,
                        cf.answer,
                        cf.normal_remark    AS remark,
                        ISNULL(b.Branch, CONCAT('Branch ', cf.branchid)) AS branch_name,
                        cf.created_at
                    FROM dbo.audit_center_checklist_feedback cf
                    LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON TRY_CAST(cf.branchid AS INT) = b.BranchID
                    WHERE cf.answer = 'Yes' AND TRY_CAST(cf.branchid AS INT) IN ({placeholders})
                """, branch_ids)
                center_rows = cursor.fetchall()

                # Client-level CAPs
                cursor.execute(f"""
                    SELECT
                        'CLIENT'            AS cap_type,
                        clf.id              AS feedback_id,
                        clf.audit_id,
                        clf.branch_id,
                        clf.center_id,
                        clf.client_id,
                        clf.client_name,
                        clf.parameter_code,
                        clf.parameter_name,
                        NULL                AS section_code,
                        NULL                AS section_name,
                        clf.answer,
                        clf.remarks         AS remark,
                        ISNULL(b.Branch, CONCAT('Branch ', clf.branch_id)) AS branch_name,
                        clf.created_at
                    FROM dbo.audit_client_checklist_feedback clf
                    LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON TRY_CAST(clf.branch_id AS INT) = b.BranchID
                    WHERE clf.answer = 'Yes' AND TRY_CAST(clf.branch_id AS INT) IN ({placeholders})
                """, branch_ids)
                client_rows = cursor.fetchall()

            caps = []
            for row in branch_rows + center_rows + client_rows:
                cap = dict(zip(branch_cols, row))
                for k, v in cap.items():
                    if isinstance(v, decimal.Decimal):
                        cap[k] = float(v)
                    elif hasattr(v, 'isoformat'):
                        cap[k] = v.isoformat()
                caps.append(cap)
                
            caps.sort(key=lambda x: x['created_at'] if x.get('created_at') else '', reverse=True)

            return {
                'success': True,
                'caps': caps
            }
        except Exception as e:
            log_error(f"GetAuditeeCapsQueryHandler failed: {str(e)}")
            raise e


# --- Compliance Queries ----------------------------------------------------


# --- Compliance Queries ----------------------------------------------------

class GetComplianceTicketsQuery(Query):
    def __init__(self, user_id: int):
        self.user_id = user_id

class GetComplianceTicketsQueryHandler(QueryHandler):
    def execute(self, query: GetComplianceTicketsQuery) -> dict:
        try:
            tickets = []
            with connection.cursor() as cursor:
                # Find role of user to filter if needed
                cursor.execute("""
                    SELECT r.RoleName FROM dbo.map_userRole mur
                    JOIN dbo.mst_role r ON mur.RoleId = r.RoleId
                    WHERE mur.UserID = %s AND mur.IsActive = 1
                """, [query.user_id])
                role_row = cursor.fetchone()
                role_name = role_row[0] if role_row else 'Unknown'


                class DummyUser:
                    def __init__(self, branch_id, buid, butype):
                        self.BranchID = branch_id
                        self.Buid = buid
                        self.BUType = butype

                cursor.execute("""
                    SELECT BranchID, Buid, BUType 
                    FROM dbo.accounts_mst_usertbl 
                    WHERE UserID = %s
                """, [query.user_id])
                user_row = cursor.fetchone()
                if user_row:
                    user_obj = DummyUser(user_row[0], user_row[1], user_row[2])
                else:
                    user_obj = DummyUser(None, None, None)

                branch_ids = get_user_branch_ids(cursor, user_obj)

                # If Auditee, only show their tickets
                # If Compliance, show all tickets
                where_clause = ""
                params = []
                if role_name not in ['Admin', 'Compliance Head']:
                    placeholders = ', '.join(['%s'] * len(branch_ids))
                    where_clause = f"WHERE ct.branchid IN ({placeholders}) OR ct.auditor_id = %s"
                    params = [int(bid) for bid in branch_ids] + [query.user_id]

                # Branch Tickets
                sql = f"""
                    SELECT ct.ticket_id, ct.cap_type, ct.status, ct.created_at, ct.updated_at,
                           b.Branch AS branch_name, bf.section_name, bf.intent_title AS parameter_name,
                           u1.UserName AS auditor_name, u1.ContactNo AS auditor_mobile, u2.UserName AS auditee_name, u2.ContactNo AS auditee_mobile, bf.normal_remark, ct.branchid, ct.centerid, ct.clientid, ct.feedback_id
                    FROM dbo.compliance_tickets ct
                    JOIN dbo.audit_branch_checklist_feedback bf ON ct.feedback_id = bf.id AND ct.cap_type = 'BRANCH'
                    LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON TRY_CAST(ct.branch_id AS INT) = b.BranchID
                    LEFT JOIN dbo.accounts_mst_usertbl u1 ON ct.auditor_id = u1.UserID
                    LEFT JOIN (SELECT u.UserID, u.UserName, u.BUID, u.ContactNo FROM dbo.accounts_mst_usertbl u JOIN dbo.map_userRole m ON u.UserID = m.UserID WHERE m.RoleId = 12 AND m.IsActive = 1) u2 ON TRY_CAST(u2.BUID AS INT) = TRY_CAST(ct.branch_id AS INT)
                    {where_clause}
                    
                    UNION ALL
                    
                    SELECT ct.ticket_id, ct.cap_type, ct.status, ct.created_at, ct.updated_at,
                           b.Branch AS branch_name, 'Center Level' AS section_name, cf.parameter_name,
                           u1.UserName AS auditor_name, u1.ContactNo AS auditor_mobile, u2.UserName AS auditee_name, u2.ContactNo AS auditee_mobile, cf.normal_remark, ct.branchid, ct.centerid, ct.clientid, ct.feedback_id
                    FROM dbo.compliance_tickets ct
                    JOIN dbo.audit_center_checklist_feedback cf ON ct.feedback_id = cf.id AND ct.cap_type = 'CENTER'
                    LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON TRY_CAST(ct.branch_id AS INT) = b.BranchID
                    LEFT JOIN dbo.accounts_mst_usertbl u1 ON ct.auditor_id = u1.UserID
                    LEFT JOIN (SELECT u.UserID, u.UserName, u.BUID, u.ContactNo FROM dbo.accounts_mst_usertbl u JOIN dbo.map_userRole m ON u.UserID = m.UserID WHERE m.RoleId = 12 AND m.IsActive = 1) u2 ON TRY_CAST(u2.BUID AS INT) = TRY_CAST(ct.branch_id AS INT)
                    {where_clause}
                    
                    UNION ALL
                    
                    SELECT ct.ticket_id, ct.cap_type, ct.status, ct.created_at, ct.updated_at,
                           b.Branch AS branch_name, 'Client Level' AS section_name, clf.parameter_name,
                           u1.UserName AS auditor_name, u1.ContactNo AS auditor_mobile, u2.UserName AS auditee_name, u2.ContactNo AS auditee_mobile, clf.remarks AS normal_remark, ct.branchid, ct.centerid, ct.clientid, ct.feedback_id
                    FROM dbo.compliance_tickets ct
                    JOIN dbo.audit_client_checklist_feedback clf ON ct.feedback_id = clf.id AND ct.cap_type = 'CLIENT'
                    LEFT JOIN dbo.VW_Branch_To_GeographicalHierarchy b ON TRY_CAST(ct.branch_id AS INT) = b.BranchID
                    LEFT JOIN dbo.accounts_mst_usertbl u1 ON ct.auditor_id = u1.UserID
                    LEFT JOIN (SELECT u.UserID, u.UserName, u.BUID, u.ContactNo FROM dbo.accounts_mst_usertbl u JOIN dbo.map_userRole m ON u.UserID = m.UserID WHERE m.RoleId = 12 AND m.IsActive = 1) u2 ON TRY_CAST(u2.BUID AS INT) = TRY_CAST(ct.branch_id AS INT)
                    {where_clause}
                    
                    ORDER BY ct.created_at DESC
                """
                
                # Adjust params for union
                final_params = params * 3 if params else []
                cursor.execute(sql, final_params)
                
                columns = [col[0] for col in cursor.description]
                for row in cursor.fetchall():
                    t = dict(zip(columns, row))
                    # Fetch alerts for this ticket
                    cursor.execute("""
                        SELECT a.message, a.created_at, u.UserName as sender_name 
                        FROM dbo.compliance_ticket_alerts a
                        LEFT JOIN dbo.accounts_mst_usertbl u ON a.sender_id = u.UserID
                        WHERE a.ticket_id = %s
                        ORDER BY a.created_at ASC
                    """, [t['ticket_id']])
                    al_cols = [c[0] for c in cursor.description]
                    t['alerts'] = [dict(zip(al_cols, r)) for r in cursor.fetchall()]

                    # Fetch reviewer remarks for this ticket
                    reviewer_remarks = []
                    fid = t.get('feedback_id')
                    cap_type = t.get('cap_type')
                    if fid and cap_type:
                        log_table = None
                        if cap_type == 'BRANCH':
                            log_table = 'dbo.audit_branch_checklist_review_log'
                        elif cap_type == 'CENTER':
                            log_table = 'dbo.audit_center_checklist_review_log'
                        elif cap_type == 'CLIENT':
                            log_table = 'dbo.audit_client_checklist_review_log'
                        
                        if log_table:
                            try:
                                cursor.execute(f"""
                                    SELECT review_remark, decided_at
                                    FROM {log_table}
                                    WHERE feedback_id = %s AND review_remark IS NOT NULL AND LTRIM(RTRIM(review_remark)) <> ''
                                    ORDER BY log_id DESC
                                """, [fid])
                                for r_row in cursor.fetchall():
                                    reviewer_remarks.append({
                                        'remark': r_row[0],
                                        'decided_at': r_row[1].isoformat() if hasattr(r_row[1], 'isoformat') else str(r_row[1]) if r_row[1] else None
                                    })
                            except Exception:
                                pass
                    t['reviewer_remarks'] = reviewer_remarks
                    
                    # Fetch BM/Compliance responses for this ticket
                    cursor.execute("""
                        SELECT r.response_id, r.sender_id, r.message, r.file_name, r.created_at, u.UserName as sender_name,
                               (SELECT TOP 1 rl.RoleName FROM dbo.map_userRole mur JOIN dbo.mst_role rl ON mur.RoleId = rl.RoleId WHERE mur.UserID = r.sender_id AND mur.IsActive = 1) as sender_role
                        FROM dbo.compliance_ticket_responses r
                        LEFT JOIN dbo.accounts_mst_usertbl u ON r.sender_id = u.UserID
                        WHERE r.ticket_id = %s
                        ORDER BY r.created_at ASC
                    """, [t['ticket_id']])
                    resp_cols = [c[0] for c in cursor.description]
                    responses = [dict(zip(resp_cols, r)) for r in cursor.fetchall()]
                    for r in responses:
                        r['created_at'] = r['created_at'].isoformat() if hasattr(r['created_at'], 'isoformat') else str(r['created_at'])
                        r['has_file'] = bool(r.get('file_name'))
                    t['responses'] = responses

                    tickets.append(t)
                    
            return {'success': True, 'tickets': tickets, 'status_code': 200}
        except Exception as e:
            log_error(f"GetComplianceTicketsQuery failed: {str(e)}")
            return {'success': False, 'message': str(e), 'status_code': 500}


class ViewTicketResponseFileQuery(Query):
    def __init__(self, response_id: int):
        self.response_id = response_id

class ViewTicketResponseFileQueryHandler(QueryHandler):
    def execute(self, query: ViewTicketResponseFileQuery) -> dict:
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT file_name, file_data 
                    FROM dbo.compliance_ticket_responses 
                    WHERE response_id = %s
                """, [query.response_id])
                row = cursor.fetchone()
                if not row or not row[1]:
                    return {'success': False, 'message': 'File not found.', 'status_code': 404}
                
                filename = row[0]
                file_bytes = decompress_file_backend(row[1], filename)
                
                return {
                    'success': True,
                    'file_name': filename,
                    'file_bytes': file_bytes,
                    'status_code': 200
                }
        except Exception as e:
            log_error(f"ViewTicketResponseFileQueryHandler failed: {str(e)}")
            return {'success': False, 'message': str(e), 'status_code': 500}
