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
    def __init__(self, branch_id: str, audit_id: int, action: str, general_remarks: str, feedback_items: list, user):
        self.branch_id = branch_id.strip()
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
            else:
                audit_id = 0

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
                    for item in feedback_items:
                        checklist_id = item.get('checklist_id')
                        section_code = item.get('section_code')
                        section_name = item.get('section_name')
                        intent_code = item.get('intent_code')
                        intent_title = item.get('intent_title')
                        answer = item.get('answer', 'N/A')
                        normal_remark = item.get('normal_remark')
                        confidential_remark = item.get('confidential_remark')
                        
                        # Normal file upload
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

                        # Confidential file upload
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

                        # Check existing feedback
                        cursor.execute("""
                            SELECT id, normal_file_id, confidential_file_id 
                            FROM dbo.audit_branch_checklist_feedback
                            WHERE audit_id = %s AND branch_id = %s AND checklist_id = %s
                        """, [audit_id, branch_id, checklist_id])
                        row = cursor.fetchone()

                        if row:
                            feedback_record_id, existing_normal_fid, existing_confidential_fid = row
                            
                            # Insert/Update normal file in DB
                            if has_new_normal_file:
                                if existing_normal_fid:
                                    cursor.execute("""
                                        UPDATE dbo.audit_branch_checklist_feedback_files
                                        SET file_name = %s, file_payload = %s
                                        WHERE file_id = %s
                                    """, [normal_file_name, normal_file_bytes, existing_normal_fid])
                                    normal_fid = existing_normal_fid
                                else:
                                    cursor.execute("""
                                        INSERT INTO dbo.audit_branch_checklist_feedback_files (file_name, file_payload)
                                        VALUES (%s, %s)
                                    """, [normal_file_name, normal_file_bytes])
                                    cursor.execute("SELECT @@IDENTITY")
                                    normal_fid = int(cursor.fetchone()[0])
                            else:
                                normal_fid = existing_normal_fid

                            # Insert/Update confidential file in DB
                            if has_new_confidential_file:
                                if existing_confidential_fid:
                                    cursor.execute("""
                                        UPDATE dbo.audit_branch_checklist_feedback_confidential_files
                                        SET file_name = %s, file_payload = %s
                                        WHERE confidential_file_id = %s
                                    """, [confidential_file_name, confidential_file_bytes, existing_confidential_fid])
                                    confidential_fid = existing_confidential_fid
                                else:
                                    cursor.execute("""
                                        INSERT INTO dbo.audit_branch_checklist_feedback_confidential_files (file_name, file_payload)
                                        VALUES (%s, %s)
                                    """, [confidential_file_name, confidential_file_bytes])
                                    cursor.execute("SELECT @@IDENTITY")
                                    confidential_fid = int(cursor.fetchone()[0])
                            else:
                                confidential_fid = existing_confidential_fid

                            cursor.execute("""
                                UPDATE dbo.audit_branch_checklist_feedback
                                SET answer = %s,
                                    normal_remark = %s,
                                    status = %s,
                                    confidential_remark = %s,
                                    normal_file_id = %s,
                                    confidential_file_id = %s
                                WHERE id = %s
                            """, [answer, normal_remark, status_to, confidential_remark, normal_fid, confidential_fid, feedback_record_id])

                        else:
                            # Insert new normal file in DB
                            normal_fid = None
                            if has_new_normal_file:
                                cursor.execute("""
                                    INSERT INTO dbo.audit_branch_checklist_feedback_files (file_name, file_payload)
                                    VALUES (%s, %s)
                                """, [normal_file_name, normal_file_bytes])
                                cursor.execute("SELECT @@IDENTITY")
                                normal_fid = int(cursor.fetchone()[0])

                            # Insert new confidential file in DB
                            confidential_fid = None
                            if has_new_confidential_file:
                                cursor.execute("""
                                    INSERT INTO dbo.audit_branch_checklist_feedback_confidential_files (file_name, file_payload)
                                    VALUES (%s, %s)
                                """, [confidential_file_name, confidential_file_bytes])
                                cursor.execute("SELECT @@IDENTITY")
                                confidential_fid = int(cursor.fetchone()[0])

                            cursor.execute("""
                                INSERT INTO dbo.audit_branch_checklist_feedback (
                                    audit_id, branch_id, checklist_id, section_code, section_name,
                                    intent_code, intent_title, answer, normal_remark, status,
                                    confidential_remark, normal_file_id, confidential_file_id
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, [
                                audit_id, branch_id, checklist_id, section_code, section_name,
                                intent_code, intent_title, answer, normal_remark, status_to,
                                confidential_remark, normal_fid, confidential_fid
                            ])

                    # General Remarks Update
                    cursor.execute("""
                        SELECT 1 FROM dbo.audit_branch_general_remarks
                        WHERE audit_id = %s AND TRY_CAST(branch_id AS INT) = %s
                    """, [audit_id, branch_id])
                    rem_exists = cursor.fetchone()
                    if rem_exists:
                        cursor.execute("""
                            UPDATE dbo.audit_branch_general_remarks
                            SET general_remarks = %s, updated_by = %s, updated_at = GETDATE()
                            WHERE audit_id = %s AND TRY_CAST(branch_id AS INT) = %s
                        """, [general_remarks, user.UserID, audit_id, branch_id])
                    else:
                        cursor.execute("""
                            INSERT INTO dbo.audit_branch_general_remarks (audit_id, branch_id, general_remarks, created_by, created_at)
                            VALUES (%s, %s, %s, %s, GETDATE())
                        """, [audit_id, branch_id, general_remarks, user.UserID])

            return {'success': True, 'message': 'Feedback saved successfully', 'auditId': audit_id}
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
    def __init__(self, audit_id: int, center_id: str, branch_id: str, feedback_items: list):
        self.audit_id = audit_id
        self.center_id = center_id
        self.branch_id = branch_id
        self.feedback_items = feedback_items


class SaveCenterAuditFeedbackCommandHandler(CommandHandler):
    def execute(self, command: SaveCenterAuditFeedbackCommand) -> dict:
        audit_id = command.audit_id
        center_id = command.center_id
        branch_id = command.branch_id
        feedback_items = command.feedback_items

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    for item in feedback_items:
                        checklist_id = item.get('checklist_id')
                        param_code = item.get('parameter_code')
                        param_name = item.get('parameter_name')
                        answer = item.get('answer', 'N/A')
                        normal_remark = item.get('normal_remark', '')
                        max_score = int(item.get('max_score', 0))
                        status = item.get('status', 'pending')

                        # Handle base64 file data
                        file_data = item.get('normal_file')
                        has_new_file = False
                        file_bytes = None
                        file_name = None
                        if file_data and isinstance(file_data, dict) and file_data.get('base64'):
                            has_new_file = True
                            file_name = file_data.get('filename', 'upload_center.png')
                            base64_str = file_data.get('base64')
                            base64_data = base64_str.split(';base64,')[1] if ';base64,' in base64_str else base64_str
                            decoded_bytes = base64.b64decode(base64_data)
                            file_bytes, file_name = compress_file_backend(decoded_bytes, file_name)

                        # Existing row check
                        cursor.execute("""
                            SELECT id, file_id 
                            FROM dbo.audit_center_checklist_feedback
                            WHERE audit_id = %s AND center_id = %s AND center_checklist_id = %s
                        """, [audit_id, center_id, checklist_id])
                        row = cursor.fetchone()

                        if row:
                            record_id, existing_fid = row
                            
                            if has_new_file:
                                if existing_fid:
                                    cursor.execute("""
                                        UPDATE dbo.audit_center_checklist_feedback_files
                                        SET file_name = %s, file_payload = %s
                                        WHERE file_id = %s
                                    """, [file_name, file_bytes, existing_fid])
                                    fid = existing_fid
                                else:
                                    cursor.execute("""
                                        INSERT INTO dbo.audit_center_checklist_feedback_files (file_name, file_payload)
                                        VALUES (%s, %s)
                                    """, [file_name, file_bytes])
                                    cursor.execute("SELECT @@IDENTITY")
                                    fid = int(cursor.fetchone()[0])
                            else:
                                fid = existing_fid

                            cursor.execute("""
                                UPDATE dbo.audit_center_checklist_feedback
                                SET answer = %s,
                                    normal_remark = %s,
                                    status = %s,
                                    max_score = %s,
                                    file_id = %s,
                                    file_name = %s
                                WHERE id = %s
                            """, [answer, normal_remark, status, max_score, fid, file_name if has_new_file else item.get('normal_file', {}).get('filename') if item.get('normal_file') else None, record_id])
                        else:
                            fid = None
                            if has_new_file:
                                cursor.execute("""
                                    INSERT INTO dbo.audit_center_checklist_feedback_files (file_name, file_payload)
                                    VALUES (%s, %s)
                                """, [file_name, file_bytes])
                                cursor.execute("SELECT @@IDENTITY")
                                fid = int(cursor.fetchone()[0])

                            cursor.execute("""
                                INSERT INTO dbo.audit_center_checklist_feedback (
                                    audit_id, branchid, center_id, center_checklist_id, parameter_code, 
                                    parameter_name, answer, normal_remark, status, max_score, file_id, file_name
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, [audit_id, branch_id, center_id, checklist_id, param_code, param_name, answer, normal_remark, status, max_score, fid, file_name])

            return {'success': True, 'message': 'Center feedback saved successfully'}
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
    def __init__(self, audit_id: int, center_id: str, branch_id: str, client_id: str, client_name: str, feedback_items: list):
        self.audit_id = audit_id
        self.center_id = center_id
        self.branch_id = branch_id
        self.client_id = client_id
        self.client_name = client_name
        self.feedback_items = feedback_items


class SaveClientAuditFeedbackCommandHandler(CommandHandler):
    def execute(self, command: SaveClientAuditFeedbackCommand) -> dict:
        audit_id = command.audit_id
        center_id = command.center_id
        branch_id = command.branch_id
        client_id = command.client_id
        client_name = command.client_name
        feedback_items = command.feedback_items

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    for item in feedback_items:
                        checklist_id = item.get('checklist_id')
                        param_code = item.get('parameter_code')
                        param_name = item.get('parameter_name')
                        answer = item.get('answer', 'N/A')
                        remarks = item.get('remarks', '')
                        max_score = int(item.get('max_score', 0))
                        status = item.get('status', 'pending')

                        cursor.execute("""
                            SELECT id 
                            FROM dbo.audit_client_checklist_feedback
                            WHERE audit_id = %s AND center_id = %s AND client_id = %s AND client_checklist_id = %s
                        """, [audit_id, center_id, client_id, checklist_id])
                        row = cursor.fetchone()

                        if row:
                            cursor.execute("""
                                UPDATE dbo.audit_client_checklist_feedback
                                SET answer = %s,
                                    remarks = %s,
                                    status = %s,
                                    max_score = %s
                                WHERE id = %s
                            """, [answer, remarks, status, max_score, row[0]])
                        else:
                            cursor.execute("""
                                INSERT INTO dbo.audit_client_checklist_feedback (
                                    audit_id, branch_id, center_id, client_id, client_name, client_checklist_id,
                                    parameter_code, parameter_name, answer, remarks, status, max_score
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, [audit_id, branch_id, center_id, client_id, client_name, checklist_id, param_code, param_name, answer, remarks, status, max_score])

            return {'success': True, 'message': 'Client feedback saved successfully'}
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
                    # 1. Fetch current review details or insert new master
                    cursor.execute("SELECT review_id, status, current_cycle FROM dbo.audit_review_master WHERE audit_id = %s", [audit_id])
                    row = cursor.fetchone()
                    
                    if row:
                        rev_id, cur_status, cycle = row
                        # Only allow submit if review is rejected or initial
                        if cur_status not in ('rejected_l1', 'rejected_l2', 'not_started', 'pending_submission'):
                            return {'success': False, 'message': f'Cannot submit review in current status: {cur_status}'}
                        
                        next_cycle = cycle + 1
                        next_status = 'submitted_l1'
                        
                        # Fetch the designated L1 reviewer for this auditor
                        cursor.execute("""
                            SELECT mur.ReportToID 
                            FROM dbo.map_userRole mur
                            WHERE mur.UserID = %s AND mur.IsActive = 1
                        """, [user.UserID])
                        l1_row = cursor.fetchone()
                        l1_reviewer = l1_row[0] if l1_row else None
                        
                        cursor.execute("""
                            UPDATE dbo.audit_review_master
                            SET status = %s,
                                current_cycle = %s,
                                assigned_to_user_id = %s,
                                updated_at = GETDATE()
                            WHERE review_id = %s
                        """, [next_status, next_cycle, l1_reviewer, rev_id])
                    else:
                        # Fetch designated L1 reviewer
                        cursor.execute("""
                            SELECT mur.ReportToID 
                            FROM dbo.map_userRole mur
                            WHERE mur.UserID = %s AND mur.IsActive = 1
                        """, [user.UserID])
                        l1_row = cursor.fetchone()
                        l1_reviewer = l1_row[0] if l1_row else None

                        cursor.execute("""
                            INSERT INTO dbo.audit_review_master (audit_id, status, current_cycle, assigned_to_user_id, created_at, updated_at)
                            VALUES (%s, 'submitted_l1', 1, %s, GETDATE(), GETDATE())
                        """, [audit_id, l1_reviewer])

                    # 5. Set branch progress status
                    cursor.execute("""
                        UPDATE dbo.audit_branch_progress
                        SET audit_status = 'in-review'
                        WHERE audit_id = %s
                    """, [audit_id])

            return {'success': True, 'message': 'Audit review submitted successfully'}
        except Exception as e:
            log_error(f"SubmitForReviewCommandHandler failed: {str(e)}")
            raise e


class RecordPointDecisionCommand(Command):
    def __init__(self, audit_id: int, feedback_id: int, point_type: str, decision: str, remark: str, user):
        self.audit_id = audit_id
        self.feedback_id = feedback_id
        self.point_type = point_type
        self.decision = decision
        self.remark = remark
        self.user = user


class RecordPointDecisionCommandHandler(CommandHandler):
    def execute(self, command: RecordPointDecisionCommand) -> dict:
        audit_id = command.audit_id
        feedback_id = command.feedback_id
        point_type = command.point_type
        decision = command.decision
        remark = command.remark
        user = command.user

        tbl_log = f"dbo.audit_{point_type.lower()}_checklist_review_log"
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    # 1. Fetch current review cycle
                    cursor.execute("SELECT current_cycle FROM dbo.audit_review_master WHERE audit_id = %s", [audit_id])
                    row = cursor.fetchone()
                    cycle = row[0] if row else 1

                    # 2. Insert into decision log
                    cursor.execute(f"""
                        INSERT INTO {tbl_log} (audit_id, feedback_id, cycle_id, reviewer_user_id, decision, review_remark, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, GETDATE())
                    """, [audit_id, feedback_id, cycle, user.UserID, decision, remark])

            return {'success': True, 'message': 'Point decision recorded successfully'}
        except Exception as e:
            log_error(f"RecordPointDecisionCommandHandler failed: {str(e)}")
            raise e


class FinalizeReviewCommand(Command):
    def __init__(self, audit_id: int, action: str, user):
        self.audit_id = audit_id
        self.action = action  # 'APPROVE' or 'REJECT'
        self.user = user


class FinalizeReviewCommandHandler(CommandHandler):
    def execute(self, command: FinalizeReviewCommand) -> dict:
        audit_id = command.audit_id
        action = command.action
        user = command.user

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    # 1. Fetch current review master
                    cursor.execute("SELECT status, current_cycle FROM dbo.audit_review_master WHERE audit_id = %s", [audit_id])
                    row = cursor.fetchone()
                    if not row:
                        return {'success': False, 'message': 'Review master not found for this audit', 'status_code': 404}
                    
                    status, cycle = row

                    # Resolve reporting lines of reviewer to escalate or fallback
                    cursor.execute("SELECT ReportToID, RoleId FROM dbo.map_userRole WHERE UserID = %s AND IsActive = 1", [user.UserID])
                    reviewer_row = cursor.fetchone()
                    report_to_id = reviewer_row[0] if reviewer_row else None
                    role_id = reviewer_row[1] if reviewer_row else None

                    # Workflow levels logic
                    if action == 'APPROVE':
                        if status == 'submitted_l1':
                            next_status = 'submitted_l2'
                            next_assignee = report_to_id
                        elif status == 'submitted_l2':
                            next_status = 'submitted_l3'
                            next_assignee = report_to_id
                        elif status == 'submitted_l3':
                            next_status = 'approved'
                            next_assignee = None
                            
                            # Finalize audit status to completed
                            cursor.execute("UPDATE dbo.audit_branch_progress SET audit_status = 'completed' WHERE audit_id = %s", [audit_id])
                        else:
                            return {'success': False, 'message': f'Cannot approve in current status: {status}'}
                    else:  # REJECT
                        if status == 'submitted_l1':
                            next_status = 'rejected_l1'
                        elif status == 'submitted_l2':
                            next_status = 'rejected_l2'
                        elif status == 'submitted_l3':
                            next_status = 'rejected_l3'
                        else:
                            return {'success': False, 'message': f'Cannot reject in current status: {status}'}
                        
                        # Assign back to auditor
                        cursor.execute("SELECT audit_assigned_to FROM dbo.audit_branch_progress WHERE audit_id = %s", [audit_id])
                        auditor_row = cursor.fetchone()
                        next_assignee = auditor_row[0] if auditor_row else None

                        # Set progress status back to in-progress (re-audit/fix feedback points)
                        cursor.execute("UPDATE dbo.audit_branch_progress SET audit_status = 'in-progress' WHERE audit_id = %s", [audit_id])

                    # Update review master status
                    cursor.execute("""
                        UPDATE dbo.audit_review_master
                        SET status = %s,
                            assigned_to_user_id = %s,
                            updated_at = GETDATE()
                        WHERE audit_id = %s
                    """, [next_status, next_assignee, audit_id])

            return {'success': True, 'message': f'Review finalized successfully with decision: {action}'}
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