import json
import base64
import logging
import decimal
from django.db import connection, transaction
from django.db.models import Q
from satark.cqrs import Command, CommandHandler
from planner.models import AuditPlanCurrent
from authentication.utils import log_info, log_error
from .utils import compress_file_backend

logger = logging.getLogger("audit.commands")


class CreateChecklistPointCommand(Command):
    def __init__(self, report_type, section_code, section_name, section_weight_pct, section_display_order,
                 intent_title, intent_description, category, max_score, accepted_deviation_pct, sample_method=None, is_active=True):
        self.report_type = report_type
        self.section_code = section_code
        self.section_name = section_name
        self.section_weight_pct = float(section_weight_pct)
        self.section_display_order = int(section_display_order)
        self.intent_title = intent_title
        self.intent_description = intent_description
        self.category = category
        self.max_score = int(max_score)
        self.accepted_deviation_pct = float(accepted_deviation_pct)
        self.sample_method = sample_method
        self.is_active = is_active


class CreateChecklistPointCommandHandler(CommandHandler):
    def execute(self, command: CreateChecklistPointCommand) -> dict:
        try:
            with connection.cursor() as cursor:
                sp_query = """
                    EXEC [dbo].[usp_manage_audit_checklist_master]
                        @expected_result = 'ADD',
                        @report_type = %s,
                        @section_code = %s,
                        @section_name = %s,
                        @section_weight_pct = %s,
                        @section_display_order = %s,
                        @intent_title = %s,
                        @intent_description = %s,
                        @category = %s,
                        @max_score = %s,
                        @accepted_deviation_pct = %s,
                        @sample_method = %s,
                        @is_active = %s
                """
                cursor.execute(sp_query, [
                    command.report_type,
                    command.section_code,
                    command.section_name,
                    command.section_weight_pct,
                    command.section_display_order,
                    command.intent_title,
                    command.intent_description,
                    command.category,
                    command.max_score,
                    command.accepted_deviation_pct,
                    command.sample_method,
                    1 if command.is_active else 0
                ])
                columns = [col[0] for col in cursor.description] if cursor.description else []
                row = cursor.fetchone()

            if not row:
                return {'success': False, 'message': 'Stored procedure did not return any records'}

            created_item = dict(zip(columns, row))
            for key, val in created_item.items():
                if isinstance(val, decimal.Decimal):
                    created_item[key] = float(val)
                elif hasattr(val, 'isoformat'):
                    created_item[key] = val.isoformat()

            return {
                'success': True,
                'message': 'Checklist item created successfully',
                'checklist_point': created_item
            }
        except Exception as e:
            log_error(f"CreateChecklistPointCommandHandler failed: {str(e)}")
            raise e


class SaveCenterChecklistPointCommand(Command):
    def __init__(self, parameter_name, max_score, center_checklist_id=None, is_active=True):
        self.center_checklist_id = center_checklist_id
        self.parameter_name = parameter_name
        self.max_score = int(max_score)
        self.is_active = is_active


class SaveCenterChecklistPointCommandHandler(CommandHandler):
    def execute(self, command: SaveCenterChecklistPointCommand) -> dict:
        try:
            with connection.cursor() as cursor:
                sp_query = """
                    DECLARE @out_id INT;
                    EXEC [dbo].[usp_save_center_checklist_item]
                        @center_checklist_id = %s,
                        @parameter_name = %s,
                        @max_score = %s,
                        @is_active = %s,
                        @new_center_checklist_id = @out_id OUTPUT;
                    SELECT @out_id;
                """
                cursor.execute(sp_query, [
                    command.center_checklist_id,
                    command.parameter_name,
                    command.max_score,
                    1 if command.is_active else 0
                ])
                new_id = cursor.fetchone()[0]

                cursor.execute("""
                    SELECT 
                        center_checklist_id, serial_no, parameter_code, 
                        parameter_name, max_score, is_active, created_at, updated_at
                    FROM [dbo].[audit_center_checklist_master]
                    WHERE center_checklist_id = %s
                """, [new_id])
                columns = [col[0] for col in cursor.description]
                row = cursor.fetchone()

            if not row:
                return {'success': False, 'message': 'Failed to fetch the saved record'}

            saved_item = dict(zip(columns, row))
            for key, val in saved_item.items():
                if isinstance(val, decimal.Decimal):
                    saved_item[key] = float(val)
                elif hasattr(val, 'isoformat'):
                    saved_item[key] = val.isoformat()

            return {
                'success': True,
                'message': 'Center checklist item saved successfully',
                'center_checklist_point': saved_item
            }
        except Exception as e:
            log_error(f"SaveCenterChecklistPointCommandHandler failed: {str(e)}")
            raise e


class SaveClientChecklistPointCommand(Command):
    def __init__(self, parameter_name, max_score, client_checklist_id=None, is_active=True):
        self.client_checklist_id = client_checklist_id
        self.parameter_name = parameter_name
        self.max_score = int(max_score)
        self.is_active = is_active


class SaveClientChecklistPointCommandHandler(CommandHandler):
    def execute(self, command: SaveClientChecklistPointCommand) -> dict:
        try:
            with connection.cursor() as cursor:
                sp_query = """
                    DECLARE @out_id INT;
                    EXEC [dbo].[usp_save_client_checklist_item]
                        @client_checklist_id = %s,
                        @parameter_name = %s,
                        @max_score = %s,
                        @is_active = %s,
                        @new_client_checklist_id = @out_id OUTPUT;
                    SELECT @out_id;
                """
                cursor.execute(sp_query, [
                    command.client_checklist_id,
                    command.parameter_name,
                    command.max_score,
                    1 if command.is_active else 0
                ])
                new_id = cursor.fetchone()[0]

                cursor.execute("""
                    SELECT 
                        client_checklist_id, serial_no, parameter_code, 
                        parameter_name, max_score, is_active, created_at, updated_at
                    FROM [dbo].[audit_client_checklist_master]
                    WHERE client_checklist_id = %s
                """, [new_id])
                columns = [col[0] for col in cursor.description]
                row = cursor.fetchone()

            if not row:
                return {'success': False, 'message': 'Failed to fetch the saved record'}

            saved_item = dict(zip(columns, row))
            for key, val in saved_item.items():
                if isinstance(val, decimal.Decimal):
                    saved_item[key] = float(val)
                elif hasattr(val, 'isoformat'):
                    saved_item[key] = val.isoformat()

            return {
                'success': True,
                'message': 'Client checklist item saved successfully',
                'client_checklist_point': saved_item
            }
        except Exception as e:
            log_error(f"SaveClientChecklistPointCommandHandler failed: {str(e)}")
            raise e


class StartBranchAuditCommand(Command):
    def __init__(self, branch_id, user):
        self.branch_id = branch_id
        self.user = user


class StartBranchAuditCommandHandler(CommandHandler):
    def execute(self, command: StartBranchAuditCommand) -> dict:
        branch_id = command.branch_id
        user = command.user

        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT id, branch_id, start_date, end_date
                    FROM dbo.audit_plan_current
                    WHERE branch_id = %s OR id = %s
                """, [branch_id, branch_id])
                plan_row = cursor.fetchone()

                if not plan_row:
                    return {'success': False, 'message': 'Matching audit plan not found for this branch', 'status_code': 404}

                audit_id, plan_branch_id, start_date, end_date = plan_row

                cursor.execute("SELECT 1 FROM dbo.audit_branch_progress WHERE audit_id = %s", [audit_id])
                exists = cursor.fetchone()

                if exists:
                    cursor.execute("""
                        UPDATE dbo.audit_branch_progress
                        SET audit_status = 'in-progress',
                            audit_assigned_to = %s
                        WHERE audit_id = %s
                    """, [user.UserID, audit_id])
                else:
                    cursor.execute("""
                        INSERT INTO dbo.audit_branch_progress (
                            audit_id, audit_branch_id, audit_start_date, audit_end_date, audit_status, audit_assigned_to
                        ) VALUES (%s, %s, %s, NULL, 'in-progress', %s)
                    """, [audit_id, plan_branch_id, start_date, user.UserID])

            return {
                'success': True,
                'message': 'Audit progress started successfully',
                'audit_id': audit_id
            }
        except Exception as e:
            log_error(f"StartBranchAuditCommandHandler failed: {str(e)}")
            raise e


class EndBranchAuditCommand(Command):
    def __init__(self, audit_id: int, user):
        self.audit_id = audit_id
        self.user = user


class EndBranchAuditCommandHandler(CommandHandler):
    def execute(self, command: EndBranchAuditCommand) -> dict:
        audit_id = command.audit_id
        user = command.user
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT audit_id FROM dbo.audit_branch_progress
                    WHERE audit_id = %s AND audit_assigned_to = %s
                """, [audit_id, user.UserID])
                progress_row = cursor.fetchone()

                if not progress_row:
                    return {'success': False, 'message': 'Audit progress record not found for this user', 'status_code': 404}

                cursor.execute("""
                    UPDATE dbo.audit_branch_progress
                    SET audit_end_date = CAST(GETDATE() AS DATE),
                        audit_status = 'submitted'
                    WHERE audit_id = %s AND audit_assigned_to = %s
                """, [audit_id, user.UserID])

                score_error = None
                try:
                    cursor.execute("""
                        SELECT MAX(audit_end_date) FROM dbo.audit_branch_progress 
                        WHERE audit_id = %s
                    """, [audit_id])
                    row = cursor.fetchone()
                    as_on_date = row[0] if row and row[0] else None

                    cursor.execute("EXEC dbo.usp_PopulateAuditChecklistScores @AsOnDate = %s", [as_on_date])

                    # Auto-generate Compliance Tickets for non-compliant points
                    cursor.execute("EXEC dbo.usp_GenerateComplianceTickets @AuditID = %s", [audit_id])
                except Exception as sp_err:
                    log_error(f"end_branch_audit: SP execution failed: {str(sp_err)}")
                    score_error = str(sp_err)

            if score_error:
                return {
                    'success': True,
                    'message': 'Audit ended successfully but score calculation had an error.',
                    'audit_id': audit_id,
                    'score_error': score_error
                }

            return {
                'success': True,
                'message': 'Audit ended successfully. Scores have been calculated.',
                'audit_id': audit_id
            }
        except Exception as e:
            log_error(f"EndBranchAuditCommandHandler failed: {str(e)}")
            raise e


class SaveAuditFeedbackCommand(Command):
    def __init__(self, branch_id, audit_id, action: str, general_remarks: str, feedback_items: list, user):
        self.branch_id = str(branch_id).strip()  # cast to str — payload may send int
        self.audit_id = audit_id
        self.action = action
        self.general_remarks = general_remarks
        self.feedback_items = feedback_items
        self.user = user


class SaveAuditFeedbackCommandHandler(CommandHandler):
    def execute(self, command: SaveAuditFeedbackCommand) -> dict:
        branch_id = command.branch_id
        audit_id = command.audit_id
        action = command.action
        general_remarks = command.general_remarks
        feedback_items = command.feedback_items
        user = command.user

        # Resolve branch_id from name if non-numeric
        try:
            int(branch_id)
        except ValueError:
            plan_obj = None
            if audit_id and audit_id != 0:
                plan_obj = AuditPlanCurrent.objects.filter(id=audit_id).first()
            if not plan_obj:
                plan_obj = AuditPlanCurrent.objects.filter(branch=branch_id).first()
            if plan_obj and plan_obj.branch_id:
                branch_id = str(plan_obj.branch_id)

        # Resolve audit_id if not supplied
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
            audit_id = plan.id if plan else 0

        status_to = 'pending'
        if action == 'SUBMITTED':
            status_to = 'submitted'
        elif action == 'REJECTED':
            status_to = 'rejected'
        elif action == 'IN_REVIEW':
            status_to = 'inreview'
        elif action == 'DRAFT_SAVED':
            status_to = 'pending'

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    saved_files = {}
                    for item in feedback_items:
                        checklist_id = item.get('checklist_id')
                        section_code = item.get('section_code')
                        section_name = item.get('section_name')
                        intent_code = item.get('intent_code')
                        intent_title = item.get('intent_title')
                        answer = item.get('answer', 'N/A')
                        normal_remark = item.get('normal_remark')
                        confidential_remark = item.get('confidential_remark')

                        # Process normal file
                        normal_file = item.get('normal_file')
                        has_new_normal_file = False
                        normal_file_bytes = None
                        normal_file_name = None
                        if normal_file and isinstance(normal_file, dict) and normal_file.get('base64'):
                            has_new_normal_file = True
                            normal_file_name = normal_file.get('filename', 'upload.png')
                            base64_str = normal_file.get('base64')
                            if ';base64,' in base64_str:
                                _, base64_data = base64_str.split(';base64,')
                            else:
                                base64_data = base64_str
                            decoded_bytes = base64.b64decode(base64_data)
                            normal_file_bytes, normal_file_name = compress_file_backend(decoded_bytes, normal_file_name)

                        # Process confidential file
                        confidential_file = item.get('confidential_file')
                        has_new_confidential_file = False
                        confidential_file_bytes = None
                        confidential_file_name = None
                        if confidential_file and isinstance(confidential_file, dict) and confidential_file.get('base64'):
                            has_new_confidential_file = True
                            confidential_file_name = confidential_file.get('filename', 'upload_conf.png')
                            base64_str = confidential_file.get('base64')
                            if ';base64,' in base64_str:
                                _, base64_data = base64_str.split(';base64,')
                            else:
                                base64_data = base64_str
                            decoded_bytes = base64.b64decode(base64_data)
                            confidential_file_bytes, confidential_file_name = compress_file_backend(decoded_bytes, confidential_file_name)

                        # Parse subItems counts from normal_remark if present
                        total_sub_points = None
                        sub_points_yes_count = None
                        sub_points_no_count = None

                        if normal_remark and isinstance(normal_remark, str) and '_isSubItems' in normal_remark:
                            try:
                                parsed_rmk = json.loads(normal_remark)
                                if isinstance(parsed_rmk, dict) and parsed_rmk.get('_isSubItems'):
                                    sub_map = parsed_rmk.get('subItems')
                                    if isinstance(sub_map, dict) and sub_map:
                                        y_cnt = 0
                                        n_cnt = 0
                                        tot_cnt = 0
                                        for sub_obj in sub_map.values():
                                            if isinstance(sub_obj, dict):
                                                ans = (sub_obj.get('answer') or '').strip().lower()
                                                if ans == 'yes':
                                                    y_cnt += 1
                                                    tot_cnt += 1
                                                elif ans == 'no':
                                                    n_cnt += 1
                                                    tot_cnt += 1
                                                elif ans in ['n/a', 'na']:
                                                    tot_cnt += 1
                                        total_sub_points = tot_cnt
                                        sub_points_yes_count = y_cnt
                                        sub_points_no_count = n_cnt
                            except Exception as parse_err:
                                log_error(f"SaveAuditFeedbackCommandHandler subItems parse error: {str(parse_err)}")

                        # Check if feedback record exists — use actual DB columns
                        cursor.execute("""
                            SELECT id, normal_file_path, is_confidential_file_present
                            FROM dbo.audit_branch_checklist_feedback
                            WHERE branch_id = %s AND checklist_id = %s AND audit_id = %s
                        """, [branch_id, checklist_id, audit_id])
                        fb_row = cursor.fetchone()

                        is_confidential_remark_present = 1 if confidential_remark else 0
                        is_confidential_file_present = 1 if has_new_confidential_file else (fb_row[2] if fb_row else 0)

                        if fb_row:
                            fb_id = fb_row[0]
                            final_normal_file_path = normal_file_name if has_new_normal_file else fb_row[1]
                            cursor.execute("""
                                UPDATE dbo.audit_branch_checklist_feedback
                                SET answer = %s,
                                    normal_remark = %s,
                                    normal_file_path = %s,
                                    is_confidential_remark_present = %s,
                                    is_confidential_file_present = %s,
                                    status = %s,
                                    last_modified_by = %s,
                                    audit_id = %s,
                                    total_sub_points = %s,
                                    sub_points_yes_count = %s,
                                    sub_points_no_count = %s,
                                    updated_at = GETDATE()
                                WHERE id = %s
                            """, [answer, normal_remark, final_normal_file_path,
                                  is_confidential_remark_present, is_confidential_file_present,
                                  status_to, user.UserID, audit_id,
                                  total_sub_points, sub_points_yes_count, sub_points_no_count, fb_id])
                        else:
                            cursor.execute("""
                                INSERT INTO dbo.audit_branch_checklist_feedback (
                                    audit_id, branch_id, auditor_id, checklist_id, section_code, section_name,
                                    intent_code, intent_title, answer, normal_remark, normal_file_path,
                                    is_confidential_remark_present, is_confidential_file_present, status,
                                    total_sub_points, sub_points_yes_count, sub_points_no_count,
                                    last_modified_by, created_at, updated_at
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, GETDATE(), GETDATE())
                            """, [
                                audit_id, branch_id, user.UserID, checklist_id, section_code, section_name,
                                intent_code, intent_title, answer, normal_remark, normal_file_name,
                                is_confidential_remark_present, is_confidential_file_present,
                                status_to, total_sub_points, sub_points_yes_count, sub_points_no_count,
                                user.UserID
                            ])
                            cursor.execute("SELECT @@IDENTITY")
                            fb_id = int(cursor.fetchone()[0])

                        # Store normal file binary in dbo.audit_branch_normal_files
                        new_normal_file_id = None
                        if has_new_normal_file:
                            cursor.execute("""
                                UPDATE dbo.audit_branch_normal_files
                                SET is_archived = 1, updated_at = GETDATE()
                                WHERE branch_id = %s AND checklist_id = %s AND is_archived = 0
                            """, [branch_id, checklist_id])
                            cursor.execute("""
                                INSERT INTO dbo.audit_branch_normal_files (
                                    feedback_id, branch_id, checklist_id, file_name, file_content,
                                    is_archived, uploaded_by, created_at, updated_at
                                ) VALUES (%s, %s, %s, %s, %s, 0, %s, GETDATE(), GETDATE())
                            """, [fb_id, branch_id, checklist_id, normal_file_name, normal_file_bytes, user.UserID])
                            cursor.execute("SELECT @@IDENTITY")
                            new_normal_file_id = int(cursor.fetchone()[0])

                        # Handle confidential remark in dbo.audit_branch_confidential_remarks
                        if confidential_remark is not None:
                            cursor.execute("""
                                SELECT id FROM dbo.audit_branch_confidential_remarks
                                WHERE branch_id = %s AND checklist_id = %s
                            """, [branch_id, checklist_id])
                            cr_row = cursor.fetchone()
                            if cr_row:
                                cursor.execute("""
                                    UPDATE dbo.audit_branch_confidential_remarks
                                    SET confidential_remark = %s,
                                        user_id = %s,
                                        updated_at = GETDATE()
                                    WHERE id = %s
                                """, [confidential_remark, user.UserID, cr_row[0]])
                            else:
                                cursor.execute("""
                                    INSERT INTO dbo.audit_branch_confidential_remarks (
                                        feedback_id, branch_id, checklist_id, confidential_remark,
                                        user_id, created_at, updated_at
                                    ) VALUES (%s, %s, %s, %s, %s, GETDATE(), GETDATE())
                                """, [fb_id, branch_id, checklist_id, confidential_remark, user.UserID])

                        # Store confidential file binary in dbo.audit_branch_confidential_files
                        new_confidential_file_id = None
                        if has_new_confidential_file:
                            cursor.execute("""
                                UPDATE dbo.audit_branch_confidential_files
                                SET is_archived = 1, updated_at = GETDATE()
                                WHERE branch_id = %s AND checklist_id = %s AND is_archived = 0
                            """, [branch_id, checklist_id])
                            cursor.execute("""
                                INSERT INTO dbo.audit_branch_confidential_files (
                                    feedback_id, branch_id, checklist_id, confidential_file_path,
                                    file_name, file_content, is_archived, user_id, created_at, updated_at
                                ) VALUES (%s, %s, %s, NULL, %s, %s, 0, %s, GETDATE(), GETDATE())
                            """, [fb_id, branch_id, checklist_id, confidential_file_name,
                                  confidential_file_bytes, user.UserID])
                            cursor.execute("SELECT @@IDENTITY")
                            new_confidential_file_id = int(cursor.fetchone()[0])

                        # Build saved_files response
                        if new_normal_file_id or new_confidential_file_id:
                            saved_files[checklist_id] = {}
                            if new_normal_file_id:
                                saved_files[checklist_id]['normalFile'] = {
                                    'id': new_normal_file_id,
                                    'filename': normal_file_name
                                }
                            if new_confidential_file_id:
                                saved_files[checklist_id]['confidentialFile'] = {
                                    'id': new_confidential_file_id,
                                    'filename': confidential_file_name
                                }

                    # General Remarks — log to dbo.audit_activity_log (original pre-CQRS behaviour)
                    if general_remarks:
                        cursor.execute("""
                            INSERT INTO dbo.audit_activity_log (
                                branch_id, action, status_to, created_by, created_at, remarks
                            ) VALUES (%s, %s, %s, %s, GETDATE(), %s)
                        """, [branch_id, action, status_to, user.UserID, general_remarks])

            return {'success': True, 'message': 'Feedback saved successfully', 'auditId': audit_id, 'saved_files': saved_files}
        except Exception as e:
            log_error(f"SaveAuditFeedbackCommandHandler failed: {str(e)}")
            raise e


class ArchiveFeedbackFileCommand(Command):
    def __init__(self, file_id: int, is_confidential=False):
        self.file_id = file_id
        self.is_confidential = is_confidential


class ArchiveFeedbackFileCommandHandler(CommandHandler):
    def execute(self, command: ArchiveFeedbackFileCommand) -> dict:
        file_id = command.file_id
        is_confidential = command.is_confidential
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    if is_confidential:
                        # 1. Read payload
                        cursor.execute("SELECT file_name, file_payload FROM dbo.audit_branch_checklist_feedback_confidential_files WHERE confidential_file_id = %s", [file_id])
                        row = cursor.fetchone()
                        if not row:
                            return {'success': False, 'message': 'File not found', 'status_code': 404}
                        
                        fname, payload = row
                        # 2. Insert into archive
                        cursor.execute("""
                            INSERT INTO dbo.archive_audit_branch_checklist_feedback_confidential_files (confidential_file_id, file_name, file_payload)
                            VALUES (%s, %s, %s)
                        """, [file_id, fname, payload])
                        # 3. Delete original
                        cursor.execute("DELETE FROM dbo.audit_branch_checklist_feedback_confidential_files WHERE confidential_file_id = %s", [file_id])
                        # 4. Clear reference in feedback table
                        cursor.execute("UPDATE dbo.audit_branch_checklist_feedback SET confidential_file_id = NULL WHERE confidential_file_id = %s", [file_id])
                    else:
                        cursor.execute("SELECT file_name, file_payload FROM dbo.audit_branch_checklist_feedback_files WHERE file_id = %s", [file_id])
                        row = cursor.fetchone()
                        if not row:
                            return {'success': False, 'message': 'File not found', 'status_code': 404}
                        
                        fname, payload = row
                        cursor.execute("""
                            INSERT INTO dbo.archive_audit_branch_checklist_feedback_files (file_id, file_name, file_payload)
                            VALUES (%s, %s, %s)
                        """, [file_id, fname, payload])
                        cursor.execute("DELETE FROM dbo.audit_branch_checklist_feedback_files WHERE file_id = %s", [file_id])
                        cursor.execute("UPDATE dbo.audit_branch_checklist_feedback SET normal_file_id = NULL WHERE normal_file_id = %s", [file_id])

            return {'success': True, 'message': 'File archived successfully'}
        except Exception as e:
            log_error(f"ArchiveFeedbackFileCommandHandler failed: {str(e)}")
            raise e


class SaveCenterAuditFeedbackCommand(Command):
    def __init__(self, center_id, audit_id=None, branch_id=None, action='DRAFT_SAVED', general_remarks='', feedback_items=None, user=None):
        self.center_id = center_id
        self.audit_id = audit_id
        self.branch_id = branch_id
        self.action = action
        self.general_remarks = general_remarks
        self.feedback_items = feedback_items or []
        self.user = user


class SaveCenterAuditFeedbackCommandHandler(CommandHandler):
    def execute(self, command: SaveCenterAuditFeedbackCommand) -> dict:
        center_id_raw = command.center_id
        audit_id = command.audit_id
        branch_id = command.branch_id
        action = command.action or 'DRAFT_SAVED'
        general_remarks = command.general_remarks or ''
        feedback_items = command.feedback_items or []
        user = command.user

        if center_id_raw is None:
            return {'success': False, 'message': 'center_id is required'}

        try:
            center_id = int(center_id_raw)
        except ValueError:
            return {'success': False, 'message': 'center_id must be a valid integer'}

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

        # Resolve branch_id if not explicitly provided
        if not branch_id:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT TOP 1 BRANCHID 
                    FROM CenterRiskScore 
                    WHERE CenterID = %s OR CenterID = %s
                """, [str(center_id), center_id])
                row = cursor.fetchone()
                if row:
                    branch_id = row[0]

        # Determine status to set
        status_to = 'pending'
        if action == 'SUBMITTED':
            status_to = 'submitted'
        elif action == 'REJECTED':
            status_to = 'rejected'
        elif action == 'IN_REVIEW':
            status_to = 'inreview'
        elif action == 'DRAFT_SAVED':
            status_to = 'pending'

        user_id = user.UserID if user else None

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    saved_files = {}
                    for item in feedback_items:
                        checklist_id = item.get('checklist_id')
                        parameter_code = item.get('parameter_code', '')
                        parameter_name = item.get('parameter_name', '')
                        answer = item.get('answer', 'N/A')
                        normal_remark = item.get('normal_remark')
                        confidential_remark = item.get('confidential_remark')
                        
                        # Process normal file data
                        normal_file = item.get('normal_file')
                        has_new_normal_file = False
                        normal_file_bytes = None
                        normal_file_name = None
                        if normal_file and isinstance(normal_file, dict) and normal_file.get('base64'):
                            has_new_normal_file = True
                            normal_file_name = normal_file.get('filename', 'upload.png')
                            base64_str = normal_file.get('base64')
                            base64_data = base64_str.split(';base64,')[1] if ';base64,' in base64_str else base64_str
                            decoded_bytes = base64.b64decode(base64_data)
                            normal_file_bytes, normal_file_name = compress_file_backend(decoded_bytes, normal_file_name)

                        # Process confidential file data
                        confidential_file = item.get('confidential_file')
                        has_new_confidential_file = False
                        confidential_file_bytes = None
                        confidential_file_name = None
                        if confidential_file and isinstance(confidential_file, dict) and confidential_file.get('base64'):
                            has_new_confidential_file = True
                            confidential_file_name = confidential_file.get('filename', 'upload_conf.png')
                            base64_str = confidential_file.get('base64')
                            base64_data = base64_str.split(';base64,')[1] if ';base64,' in base64_str else base64_str
                            decoded_bytes = base64.b64decode(base64_data)
                            confidential_file_bytes, confidential_file_name = compress_file_backend(decoded_bytes, confidential_file_name)

                        # Process evidence image data
                        evidence_image = item.get('evidence_image')
                        has_new_evidence_image = False
                        evidence_image_bytes = None
                        evidence_image_name = None
                        evidence_latitude = None
                        evidence_longitude = None
                        evidence_text = None
                        if evidence_image and isinstance(evidence_image, dict) and evidence_image.get('base64'):
                            has_new_evidence_image = True
                            evidence_image_name = evidence_image.get('filename', 'captured.jpg')
                            evidence_latitude = evidence_image.get('latitude')
                            evidence_longitude = evidence_image.get('longitude')
                            evidence_text = evidence_image.get('image_text')
                            base64_str = evidence_image.get('base64')
                            base64_data = base64_str.split(';base64,')[1] if ';base64,' in base64_str else base64_str
                            decoded_bytes = base64.b64decode(base64_data)
                            evidence_image_bytes, evidence_image_name = compress_file_backend(decoded_bytes, evidence_image_name)

                        # Check if record exists in main feedback table
                        cursor.execute("""
                            SELECT id, normal_file_path, is_confidential_file_present 
                            FROM dbo.audit_center_checklist_feedback 
                            WHERE center_id = %s AND center_checklist_id = %s AND audit_id = %s
                        """, [center_id, checklist_id, audit_id])
                        fb_row = cursor.fetchone()

                        is_confidential_remark_present = 1 if confidential_remark else 0
                        is_confidential_file_present = 1 if has_new_confidential_file else (fb_row[2] if fb_row else 0)

                        if fb_row:
                            fb_id = fb_row[0]
                            final_normal_file_path = normal_file_name if has_new_normal_file else fb_row[1]
                            cursor.execute("""
                                UPDATE dbo.audit_center_checklist_feedback
                                SET answer = %s,
                                    normal_remark = %s,
                                    normal_file_path = %s,
                                    is_confidential_remark_present = %s,
                                    is_confidential_file_present = %s,
                                    status = %s,
                                    last_modified_by = %s,
                                    branchid = %s,
                                    audit_id = %s,
                                    updated_at = GETDATE()
                                WHERE id = %s
                            """, [answer, normal_remark, final_normal_file_path, is_confidential_remark_present, is_confidential_file_present, status_to, user_id, branch_id, audit_id, fb_id])
                        else:
                            cursor.execute("""
                                INSERT INTO dbo.audit_center_checklist_feedback (
                                    audit_id, center_id, auditor_id, center_checklist_id, parameter_code, parameter_name,
                                    answer, normal_remark, normal_file_path,
                                    is_confidential_remark_present, is_confidential_file_present, status, last_modified_by,
                                    branchid, created_at, updated_at
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, GETDATE(), GETDATE())
                            """, [
                                audit_id, center_id, user_id, checklist_id, parameter_code, parameter_name,
                                answer, normal_remark, normal_file_name,
                                is_confidential_remark_present, is_confidential_file_present, status_to, user_id,
                                branch_id
                            ])
                            cursor.execute("SELECT @@IDENTITY")
                            fb_id = int(cursor.fetchone()[0])

                        # Store normal file as binary in separate table
                        new_normal_file_id = None
                        if has_new_normal_file:
                            cursor.execute("""
                                UPDATE dbo.audit_center_normal_files
                                SET is_archived = 1, updated_at = GETDATE()
                                WHERE center_id = %s AND center_checklist_id = %s AND is_archived = 0
                            """, [center_id, checklist_id])
                            cursor.execute("""
                                INSERT INTO dbo.audit_center_normal_files (
                                    feedback_id, center_id, center_checklist_id, file_name, file_content, is_archived, uploaded_by, created_at, updated_at
                                ) VALUES (%s, %s, %s, %s, %s, 0, %s, GETDATE(), GETDATE())
                            """, [fb_id, center_id, checklist_id, normal_file_name, normal_file_bytes, user_id])
                            cursor.execute("SELECT @@IDENTITY")
                            new_normal_file_id = int(cursor.fetchone()[0])

                        # Process confidential remark
                        if confidential_remark is not None:
                            cursor.execute("""
                                SELECT id FROM dbo.audit_center_confidential_remarks
                                WHERE center_id = %s AND center_checklist_id = %s
                            """, [center_id, checklist_id])
                            cr_row = cursor.fetchone()
                            if cr_row:
                                cursor.execute("""
                                    UPDATE dbo.audit_center_confidential_remarks
                                    SET confidential_remark = %s,
                                        user_id = %s,
                                        updated_at = GETDATE()
                                    WHERE id = %s
                                """, [confidential_remark, user_id, cr_row[0]])
                            else:
                                cursor.execute("""
                                    INSERT INTO dbo.audit_center_confidential_remarks (
                                        feedback_id, center_id, center_checklist_id, confidential_remark, user_id, created_at, updated_at
                                    ) VALUES (%s, %s, %s, %s, %s, GETDATE(), GETDATE())
                                """, [fb_id, center_id, checklist_id, confidential_remark, user_id])

                        # Store confidential file as binary in database
                        new_confidential_file_id = None
                        if has_new_confidential_file:
                            cursor.execute("""
                                UPDATE dbo.audit_center_confidential_files
                                SET is_archived = 1, updated_at = GETDATE()
                                WHERE center_id = %s AND center_checklist_id = %s AND is_archived = 0
                            """, [center_id, checklist_id])
                            cursor.execute("""
                                INSERT INTO dbo.audit_center_confidential_files (
                                    feedback_id, center_id, center_checklist_id, confidential_file_path, file_name, file_content, is_archived, user_id, created_at, updated_at
                                ) VALUES (%s, %s, %s, NULL, %s, %s, 0, %s, GETDATE(), GETDATE())
                            """, [fb_id, center_id, checklist_id, confidential_file_name, confidential_file_bytes, user_id])
                            cursor.execute("SELECT @@IDENTITY")
                            new_confidential_file_id = int(cursor.fetchone()[0])

                        # Store evidence captured image in database
                        new_evidence_file_id = None
                        if has_new_evidence_image:
                            cursor.execute("""
                                UPDATE dbo.audit_center_evidence
                                SET is_archived = 1, updated_at = GETDATE()
                                WHERE center_id = %s AND center_checklist_id = %s AND is_archived = 0
                            """, [center_id, checklist_id])
                            cursor.execute("""
                                INSERT INTO dbo.audit_center_evidence (
                                    feedback_id, center_id, center_checklist_id, file_name, file_content,
                                    latitude, longitude, image_text, is_archived, uploaded_by, created_at, updated_at
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s, GETDATE(), GETDATE())
                            """, [fb_id, center_id, checklist_id, evidence_image_name, evidence_image_bytes,
                                  evidence_latitude, evidence_longitude, evidence_text, user_id])
                            cursor.execute("SELECT @@IDENTITY")
                            new_evidence_file_id = int(cursor.fetchone()[0])

                        if new_normal_file_id or new_confidential_file_id or new_evidence_file_id:
                            saved_files[checklist_id] = {}
                            if new_normal_file_id:
                                saved_files[checklist_id]['normalFile'] = {
                                    'id': new_normal_file_id,
                                    'filename': normal_file_name
                                }
                            if new_confidential_file_id:
                                saved_files[checklist_id]['confidentialFile'] = {
                                    'id': new_confidential_file_id,
                                    'filename': confidential_file_name
                                }
                            if new_evidence_file_id:
                                saved_files[checklist_id]['evidenceImage'] = {
                                    'id': new_evidence_file_id,
                                    'filename': evidence_image_name,
                                    'latitude': evidence_latitude,
                                    'longitude': evidence_longitude,
                                    'imageText': evidence_text
                                }

                    if general_remarks:
                        cursor.execute("""
                            INSERT INTO dbo.audit_center_activity_log (
                                center_id, action, status_to, created_by, created_at, remarks
                            ) VALUES (%s, %s, %s, %s, GETDATE(), %s)
                        """, [center_id, action, status_to, user_id, general_remarks])

            return {
                'success': True,
                'message': 'Center checklist feedback saved successfully',
                'saved_files': saved_files
            }
        except Exception as e:
            log_error(f"SaveCenterAuditFeedbackCommandHandler failed: {str(e)}")
            raise e


class ArchiveCenterFeedbackFileCommand(Command):
    def __init__(self, file_id: int):
        self.file_id = file_id


class ArchiveCenterFeedbackFileCommandHandler(CommandHandler):
    def execute(self, command: ArchiveCenterFeedbackFileCommand) -> dict:
        file_id = command.file_id
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT file_name, file_payload FROM dbo.audit_center_checklist_feedback_files WHERE file_id = %s", [file_id])
                    row = cursor.fetchone()
                    if not row:
                        return {'success': False, 'message': 'File not found', 'status_code': 404}
                    
                    fname, payload = row
                    cursor.execute("""
                        INSERT INTO dbo.archive_audit_center_checklist_feedback_files (file_id, file_name, file_payload)
                        VALUES (%s, %s, %s)
                    """, [file_id, fname, payload])
                    cursor.execute("DELETE FROM dbo.audit_center_checklist_feedback_files WHERE file_id = %s", [file_id])
                    cursor.execute("UPDATE dbo.audit_center_checklist_feedback SET file_id = NULL, file_name = NULL WHERE file_id = %s", [file_id])

            return {'success': True, 'message': 'File archived successfully'}
        except Exception as e:
            log_error(f"ArchiveCenterFeedbackFileCommandHandler failed: {str(e)}")
            raise e


class SaveClientAuditFeedbackCommand(Command):
    def __init__(self, audit_id=None, branch_id=None, center_id=None, client_id=None, client_name='', action='DRAFT_SAVED', feedback_items=None, user=None):
        self.audit_id = audit_id
        self.branch_id = branch_id
        self.center_id = center_id
        self.client_id = client_id
        self.client_name = client_name
        self.action = action
        self.feedback_items = feedback_items or []
        self.user = user


class SaveClientAuditFeedbackCommandHandler(CommandHandler):
    def execute(self, command: SaveClientAuditFeedbackCommand) -> dict:
        audit_id = command.audit_id
        center_id_raw = command.center_id
        branch_id = command.branch_id
        client_id = command.client_id
        client_name = command.client_name
        action = command.action or 'DRAFT_SAVED'
        feedback_items = command.feedback_items or []
        user = command.user

        if not client_id:
            return {'success': False, 'message': 'client_id is required'}

        try:
            center_id = int(center_id_raw) if center_id_raw is not None else None
        except (ValueError, TypeError):
            center_id = None

        status_to = 'pending'
        if action == 'SUBMITTED':
            status_to = 'submitted'
        elif action == 'DRAFT_SAVED':
            status_to = 'pending'

        user_id = user.UserID if user else None

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    for item in feedback_items:
                        checklist_id = item.get('client_checklist_id') or item.get('checklist_id')
                        parameter_code = item.get('parameter_code', '')
                        parameter_name = item.get('parameter_name', '')
                        answer = item.get('answer', 'N/A')
                        remarks = item.get('remarks', '')

                        if audit_id is not None:
                            cursor.execute("""
                                SELECT id
                                FROM dbo.audit_client_checklist_feedback
                                WHERE client_id = %s AND client_checklist_id = %s AND audit_id = %s
                            """, [client_id, checklist_id, audit_id])
                        else:
                            cursor.execute("""
                                SELECT id
                                FROM dbo.audit_client_checklist_feedback
                                WHERE client_id = %s AND client_checklist_id = %s AND audit_id IS NULL
                            """, [client_id, checklist_id])
                        existing = cursor.fetchone()

                        if existing:
                            cursor.execute("""
                                UPDATE dbo.audit_client_checklist_feedback
                                SET answer = %s,
                                    remarks = %s,
                                    status = %s,
                                    audit_id = %s,
                                    branch_id = %s,
                                    center_id = %s,
                                    client_name = %s,
                                    last_modified_by = %s,
                                    updated_at = GETDATE()
                                WHERE id = %s
                            """, [
                                answer, remarks, status_to,
                                audit_id, branch_id, center_id,
                                client_name, user_id, existing[0]
                            ])
                        else:
                            cursor.execute("""
                                INSERT INTO dbo.audit_client_checklist_feedback (
                                    audit_id, branch_id, center_id,
                                    client_id, client_name, auditor_id,
                                    client_checklist_id, parameter_code, parameter_name,
                                    answer, remarks, status, last_modified_by,
                                    created_at, updated_at
                                ) VALUES (
                                    %s, %s, %s,
                                    %s, %s, %s,
                                    %s, %s, %s,
                                    %s, %s, %s, %s,
                                    GETDATE(), GETDATE()
                                )
                            """, [
                                audit_id, branch_id, center_id,
                                client_id, client_name, user_id,
                                checklist_id, parameter_code, parameter_name,
                                answer, remarks, status_to, user_id
                            ])

            return {'success': True, 'message': f'Client checklist feedback {action.lower()} successfully'}
        except Exception as e:
            log_error(f"SaveClientAuditFeedbackCommandHandler failed: {str(e)}")
            raise e


class SaveSelectedCentersCommand(Command):
    def __init__(self, audit_id: int, branch_id: int, centers: list):
        self.audit_id = audit_id
        self.branch_id = branch_id
        self.centers = centers


class SaveSelectedCentersCommandHandler(CommandHandler):
    def execute(self, command: SaveSelectedCentersCommand) -> dict:
        audit_id = command.audit_id
        branch_id = command.branch_id
        centers = command.centers
        try:
            centers_json = json.dumps(centers)
            with connection.cursor() as cursor:
                cursor.execute("""
                    EXEC dbo.usp_ManageAuditorPlans
                        @Action = 'SAVE',
                        @AuditID = %s,
                        @BranchID = %s,
                        @CenterIDsJson = %s
                """, [audit_id, branch_id, centers_json])
                
                row = cursor.fetchone()
                success = row[0] if row else 0
                message = row[1] if row and len(row) > 1 else 'Centers saved'

            return {'success': bool(success), 'message': message}
        except Exception as e:
            log_error(f"SaveSelectedCentersCommandHandler failed: {str(e)}")
            raise e


class SubmitForReviewCommand(Command):
    def __init__(self, audit_id: int, user):
        self.audit_id = audit_id
        self.user = user


class SubmitForReviewCommandHandler(CommandHandler):
    def execute(self, command: SubmitForReviewCommand) -> dict:
        audit_id = command.audit_id
        user = command.user
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    # 1. Fetch branch_id and current progress from dbo.audit_branch_progress
                    cursor.execute("""
                        SELECT audit_branch_id, current_cycle_no, audit_status
                        FROM dbo.audit_branch_progress
                        WHERE audit_id = %s
                    """, [audit_id])
                    p_row = cursor.fetchone()

                    branch_id = None
                    current_cycle_no = 0
                    if p_row:
                        branch_id = p_row[0]
                        current_cycle_no = p_row[1] or 0

                    if not branch_id:
                        plan = AuditPlanCurrent.objects.filter(id=audit_id).first()
                        if plan:
                            branch_id = plan.branch_id

                    # 2. Resolve reviewer_id for this auditor/branch
                    reviewer_id = None
                    if branch_id:
                        try:
                            cursor.execute("""
                                SELECT TOP 1 division_head_userid, zonal_userid
                                FROM dbo.VW_Branch_To_GeographicalHierarchy_head_audit
                                WHERE division_buid = %s OR fa_buid = %s
                            """, [branch_id, branch_id])
                            rev_row = cursor.fetchone()
                            if rev_row:
                                reviewer_id = rev_row[0] or rev_row[1]
                        except Exception:
                            reviewer_id = None

                    # 3. Create review cycle entry in dbo.audit_branch_review_cycle
                    next_cycle_no = (current_cycle_no or 0) + 1

                    cursor.execute("""
                        INSERT INTO dbo.audit_branch_review_cycle (
                            audit_id, branch_id, cycle_no, submitted_by, submitted_at,
                            reviewer_id, outcome, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, GETDATE(), %s, 'submitted_l1', GETDATE(), GETDATE())
                    """, [audit_id, branch_id, next_cycle_no, user.UserID, reviewer_id])

                    # 4. Update audit_branch_progress
                    if p_row:
                        cursor.execute("""
                            UPDATE dbo.audit_branch_progress
                            SET audit_status = 'in-review',
                                audit_pending_with = %s,
                                current_cycle_no = %s
                            WHERE audit_id = %s
                        """, [reviewer_id, next_cycle_no, audit_id])
                    else:
                        cursor.execute("""
                            INSERT INTO dbo.audit_branch_progress (
                                audit_id, audit_branch_id, audit_assigned_to, audit_status,
                                audit_pending_with, current_cycle_no
                            ) VALUES (%s, %s, %s, 'in-review', %s, %s)
                        """, [audit_id, branch_id, user.UserID, reviewer_id, next_cycle_no])

                    # 5. Log activity in dbo.audit_activity_log
                    cursor.execute("""
                        INSERT INTO dbo.audit_activity_log (
                            branch_id, action, status_to, created_by, created_at, remarks
                        ) VALUES (%s, 'SUBMITTED', 'in-review', %s, GETDATE(), 'Audit submitted for review')
                    """, [branch_id, user.UserID])

            return {'success': True, 'message': 'Audit review submitted successfully'}
        except Exception as e:
            log_error(f"SubmitForReviewCommandHandler failed: {str(e)}")
            raise e


class RecordPointDecisionCommand(Command):
    def __init__(self, feedback_id: int, decision: str, entity_type: str = 'branch', review_remark: str = '', audit_id: int = None, user = None):
        self.feedback_id = feedback_id
        self.decision = decision
        self.entity_type = entity_type or 'branch'
        self.review_remark = review_remark or ''
        self.audit_id = audit_id
        self.user = user


class RecordPointDecisionCommandHandler(CommandHandler):
    def execute(self, command: RecordPointDecisionCommand) -> dict:
        feedback_id = command.feedback_id
        decision = command.decision
        point_type = (command.entity_type or 'branch').lower()
        review_remark = command.review_remark
        audit_id = command.audit_id
        user = command.user

        tbl_feedback = f"dbo.audit_{point_type}_checklist_feedback"
        tbl_log = f"dbo.audit_{point_type}_checklist_review_log"

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    # 1. Update review_status and review_remark directly on feedback record
                    cursor.execute(f"""
                        UPDATE {tbl_feedback}
                        SET review_status = %s,
                            review_remark = %s,
                            reviewed_by = %s,
                            reviewed_at = GETDATE()
                        WHERE id = %s
                    """, [decision, review_remark, user.UserID, feedback_id])

                    # 2. Select feedback record fields safely matching entity schema
                    branch_id, center_id, client_id = None, None, None
                    if point_type == 'center':
                        cursor.execute(f"SELECT audit_id, branchid, center_id FROM {tbl_feedback} WHERE id = %s", [feedback_id])
                        fb_row = cursor.fetchone()
                        if fb_row:
                            if not audit_id: audit_id = fb_row[0]
                            branch_id = fb_row[1]
                            center_id = fb_row[2]
                    elif point_type == 'client':
                        cursor.execute(f"SELECT audit_id, branch_id, center_id, client_id FROM {tbl_feedback} WHERE id = %s", [feedback_id])
                        fb_row = cursor.fetchone()
                        if fb_row:
                            if not audit_id: audit_id = fb_row[0]
                            branch_id = fb_row[1]
                            center_id = fb_row[2]
                            client_id = fb_row[3]
                    else:
                        cursor.execute(f"SELECT audit_id, branch_id FROM {tbl_feedback} WHERE id = %s", [feedback_id])
                        fb_row = cursor.fetchone()
                        if fb_row:
                            if not audit_id: audit_id = fb_row[0]
                            branch_id = fb_row[1]

                    # 3. Fetch latest cycle_id for this audit
                    cycle_id = None
                    if audit_id:
                        cursor.execute("""
                            SELECT TOP 1 cycle_id, branch_id
                            FROM dbo.audit_branch_review_cycle
                            WHERE audit_id = %s
                            ORDER BY cycle_no DESC
                        """, [audit_id])
                        rc_row = cursor.fetchone()
                        if rc_row:
                            cycle_id = rc_row[0]
                            if not branch_id:
                                branch_id = rc_row[1]

                    # 4. Insert into decision log table based on entity_type schema
                    try:
                        if point_type == 'branch':
                            cursor.execute(f"""
                                INSERT INTO {tbl_log} (audit_id, feedback_id, cycle_id, branch_id, reviewer_id, decision, review_remark, decided_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, GETDATE())
                            """, [audit_id, feedback_id, cycle_id, branch_id, user.UserID, decision, review_remark])
                        elif point_type == 'center':
                            cursor.execute(f"""
                                INSERT INTO {tbl_log} (audit_id, feedback_id, cycle_id, branch_id, center_id, reviewer_id, decision, review_remark, decided_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, GETDATE())
                            """, [audit_id, feedback_id, cycle_id, branch_id, center_id, user.UserID, decision, review_remark])
                        elif point_type == 'client':
                            digits = ''.join(filter(str.isdigit, str(client_id))) if client_id else ''
                            client_id_int = int(digits) if digits else 0
                            cursor.execute(f"""
                                INSERT INTO {tbl_log} (audit_id, feedback_id, cycle_id, branch_id, center_id, client_id, reviewer_id, decision, review_remark, decided_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, GETDATE())
                            """, [audit_id, feedback_id, cycle_id, branch_id, center_id, client_id_int, user.UserID, decision, review_remark])
                    except Exception as log_ex:
                        log_error(f"Could not insert into {tbl_log}: {str(log_ex)}")

            return {'success': True, 'message': 'Point decision recorded successfully'}
        except Exception as e:
            log_error(f"RecordPointDecisionCommandHandler failed: {str(e)}")
            raise e


class FinalizeReviewCommand(Command):
    def __init__(self, audit_id: int, branch_id: int = None, action: str = None, user = None):
        self.audit_id = audit_id
        self.branch_id = branch_id
        self.action = action
        self.user = user


class FinalizeReviewCommandHandler(CommandHandler):
    def execute(self, command: FinalizeReviewCommand) -> dict:
        audit_id = command.audit_id
        branch_id = command.branch_id
        action = command.action
        user = command.user

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    # Resolve branch_id if missing
                    if not branch_id:
                        cursor.execute("SELECT audit_branch_id FROM dbo.audit_branch_progress WHERE audit_id = %s", [audit_id])
                        b_row = cursor.fetchone()
                        if b_row: branch_id = b_row[0]

                    # 1. Attempt stored procedure execution
                    sp_success = False
                    try:
                        cursor.execute("""
                            EXEC dbo.usp_AuditWorkflow_Monolithic
                                @process_name = 'finalize_review',
                                @audit_id     = %s,
                                @branch_id    = %s,
                                @reviewer_id  = %s
                        """, [audit_id, branch_id or 0, user.UserID])
                        sp_success = True
                    except Exception as sp_err:
                        log_error(f"usp_AuditWorkflow_Monolithic execution skipped: {str(sp_err)}")

                    # 2. Fetch current audit_status
                    cursor.execute("""
                        SELECT audit_status FROM dbo.audit_branch_progress
                        WHERE audit_id = %s
                    """, [audit_id])
                    status_row = cursor.fetchone()
                    final_status = status_row[0] if status_row else None

                    # 3. Fallback logic if SP not executed or status unresolved
                    if not sp_success or not final_status or final_status in ('in-review', 'submitted', 'pending'):
                        cursor.execute("SELECT COUNT(*) FROM dbo.audit_branch_checklist_feedback WHERE audit_id = %s AND review_status = 'reverted'", [audit_id])
                        rev_b = cursor.fetchone()[0]
                        cursor.execute("SELECT COUNT(*) FROM dbo.audit_center_checklist_feedback WHERE audit_id = %s AND review_status = 'reverted'", [audit_id])
                        rev_c = cursor.fetchone()[0]
                        cursor.execute("SELECT COUNT(*) FROM dbo.audit_client_checklist_feedback WHERE audit_id = %s AND review_status = 'reverted'", [audit_id])
                        rev_cl = cursor.fetchone()[0]

                        if (rev_b + rev_c + rev_cl) > 0 or (action and (action.upper() in ('REJECT', 'REVERT', 'REVERTED'))):
                            final_status = 'reverted'
                            cursor.execute("SELECT audit_assigned_to FROM dbo.audit_branch_progress WHERE audit_id = %s", [audit_id])
                            auditor_row = cursor.fetchone()
                            next_assignee = auditor_row[0] if auditor_row else None
                            cursor.execute("UPDATE dbo.audit_branch_progress SET audit_status = 'reverted', audit_pending_with = %s WHERE audit_id = %s", [next_assignee, audit_id])
                        else:
                            final_status = 'completed'
                            cursor.execute("UPDATE dbo.audit_branch_progress SET audit_status = 'completed', audit_pending_with = NULL WHERE audit_id = %s", [audit_id])

                        cursor.execute("""
                            UPDATE dbo.audit_branch_review_cycle
                            SET outcome = %s,
                                reviewer_id = %s,
                                review_completed_at = GETDATE(),
                                updated_at = GETDATE()
                            WHERE audit_id = %s AND (outcome IS NULL OR outcome NOT IN ('completed', 'reverted'))
                        """, [final_status, user.UserID, audit_id])

            message_map = {
                'completed': 'Review finalized. Audit is now completed — all points validated.',
                'reverted': 'Review finalized. Audit reverted to auditor — some points need correction.',
            }
            message = message_map.get(final_status, f'Review finalized. Status: {final_status}')

            return {
                'success': True,
                'final_status': final_status,
                'message': message
            }
        except Exception as e:
            log_error(f"FinalizeReviewCommandHandler failed: {str(e)}")
            raise e


# --- Compliance Ticketing --------------------------------------------------

class SendTicketAlertCommand(Command):
    def __init__(self, ticket_id: int, sender_id: int, message: str):
        self.ticket_id = ticket_id
        self.sender_id = sender_id
        self.message = message

class SendTicketAlertCommandHandler(CommandHandler):
    def execute(self, command: SendTicketAlertCommand) -> dict:
        try:
            from .gupshup import send_whatsapp_alert
            with connection.cursor() as cursor:
                # Insert alert
                cursor.execute("""
                    INSERT INTO dbo.compliance_ticket_alerts (ticket_id, sender_id, message)
                    VALUES (%s, %s, %s)
                """, [command.ticket_id, command.sender_id, command.message])
                
                # Update ticket status
                cursor.execute("""
                    UPDATE dbo.compliance_tickets
                    SET status = 'ALERT_SENT', updated_at = GETDATE()
                    WHERE ticket_id = %s
                """, [command.ticket_id])

                # Get Auditee Mobile Number
                cursor.execute("""
                    SELECT TOP 1 u.ContactNo
                    FROM dbo.compliance_tickets t
                    JOIN dbo.accounts_mst_usertbl u ON TRY_CAST(u.BUID AS INT) = TRY_CAST(t.branch_id AS INT)
                    JOIN dbo.map_userRole m ON u.UserID = m.UserID
                    WHERE t.ticket_id = %s AND m.RoleId = 12 AND m.IsActive = 1
                """, [command.ticket_id])
                row = cursor.fetchone()
                if row and row[0]:
                    mobile = str(row[0])
                    # Call Gupshup API
                    send_whatsapp_alert(mobile, template_data={})

            log_info(f"Compliance alert sent for ticket {command.ticket_id} by user {command.sender_id}")
            return {'success': True, 'message': 'Alert sent successfully', 'status_code': 201}
        except Exception as e:
            log_error(f"SendTicketAlertCommand failed: {str(e)}")
            return {'success': False, 'message': str(e), 'status_code': 500}

class ResolveTicketCommand(Command):
    def __init__(self, ticket_id: int, resolver_id: int, status: str):
        self.ticket_id = ticket_id
        self.resolver_id = resolver_id
        self.status = status # 'RESOLVED' (by auditee) or 'CLOSED' (by compliance)

class ResolveTicketCommandHandler(CommandHandler):
    def execute(self, command: ResolveTicketCommand) -> dict:
        if command.status not in ['RESOLVED', 'CLOSED']:
            return {'success': False, 'message': 'Invalid status', 'status_code': 400}
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE dbo.compliance_tickets
                    SET status = %s, updated_at = GETDATE()
                    WHERE ticket_id = %s
                """, [command.status, command.ticket_id])
            log_info(f"Compliance ticket {command.ticket_id} marked as {command.status} by {command.resolver_id}")
            return {'success': True, 'message': f'Ticket {command.status} successfully', 'status_code': 200}
        except Exception as e:
            log_error(f"ResolveTicketCommand failed: {str(e)}")
            return {'success': False, 'message': str(e), 'status_code': 500}

from dataclasses import dataclass
@dataclass
class InitiateCallCommand(Command):
    ticket_id: int
    sender_number: str
    receiver_number: str
    sender_id: int

class InitiateCallCommandHandler(CommandHandler):
    def execute(self, command: InitiateCallCommand) -> dict:
        try:
            from .call_service import create_call_markytics, extract_call_id
            
            # Initiate the call
            resp, myuuid = create_call_markytics(command.sender_id, command.sender_number, command.receiver_number)
            
            call_id = "0"
            if resp and hasattr(resp, 'json'):
                try:
                    resp_json = resp.json()
                    call_id = extract_call_id("Markytics", resp_json)
                except Exception:
                    pass
            
            # Log the call in DB (optional, but good practice)
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO dbo.compliance_ticket_alerts (ticket_id, sender_id, message, call_id)
                    VALUES (%s, %s, %s, %s)
                """, [command.ticket_id, command.sender_id, f"Initiated VoIP call to {command.receiver_number} (Call ID: {call_id})", call_id])

            log_info(f"Compliance VoIP call initiated for ticket {command.ticket_id} by user {command.sender_id}")
            return {'success': True, 'message': 'Call initiated successfully', 'call_id': call_id, 'status_code': 201}
        except Exception as e:
            log_error(f"InitiateCallCommand failed: {str(e)}")
            return {'success': False, 'message': str(e), 'status_code': 500}


@dataclass
class SubmitTicketResponseCommand(Command):
    ticket_id: int
    sender_id: int
    message: str
    file_name: str = None
    file_data: bytes = None

class SubmitTicketResponseCommandHandler(CommandHandler):
    def execute(self, command: SubmitTicketResponseCommand) -> dict:
        try:
            with connection.cursor() as cursor:
                # Compress file if provided
                file_bytes = None
                file_name = command.file_name
                if command.file_data and command.file_name:
                    file_bytes, file_name = compress_file_backend(command.file_data, command.file_name)

                cursor.execute("""
                    INSERT INTO dbo.compliance_ticket_responses
                        (ticket_id, sender_id, message, file_name, file_data)
                    VALUES (%s, %s, %s, %s, %s)
                """, [command.ticket_id, command.sender_id, command.message, file_name, file_bytes])

                # Update ticket status to RESPONDED so compliance team sees it
                cursor.execute("""
                    UPDATE dbo.compliance_tickets
                    SET status = 'RESPONDED', updated_at = GETDATE()
                    WHERE ticket_id = %s AND status NOT IN ('CLOSED', 'RESOLVED')
                """, [command.ticket_id])

            log_info(f"Ticket {command.ticket_id} response submitted by user {command.sender_id}")
            return {'success': True, 'message': 'Response submitted successfully', 'status_code': 201}
        except Exception as e:
            log_error(f"SubmitTicketResponseCommand failed: {str(e)}")
            return {'success': False, 'message': str(e), 'status_code': 500}