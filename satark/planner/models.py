from django.db import models

class AuditPlanCurrent(models.Model):
    id = models.AutoField(primary_key=True)
    branch = models.CharField(max_length=255)
    branch_id = models.IntegerField(null=True)
    division = models.CharField(max_length=255, null=True, blank=True)
    grade = models.CharField(max_length=50, null=True, blank=True)
    size = models.CharField(max_length=50, null=True, blank=True)
    audit_mode = models.CharField(max_length=50, null=True, blank=True)
    duration = models.IntegerField(null=True, blank=True)
    assigned_auditor = models.CharField(max_length=255, null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    priority_score = models.IntegerField(null=True, blank=True)
    plan_month = models.CharField(max_length=7, null=True, blank=True) # e.g. "2026-07"
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_plan_current'

class AuditPlanHistory(models.Model):
    id = models.AutoField(primary_key=True)
    branch = models.CharField(max_length=255)
    branch_id = models.IntegerField(null=True)
    division = models.CharField(max_length=255, null=True, blank=True)
    grade = models.CharField(max_length=50, null=True, blank=True)
    size = models.CharField(max_length=50, null=True, blank=True)
    audit_mode = models.CharField(max_length=50, null=True, blank=True)
    duration = models.IntegerField(null=True, blank=True)
    assigned_auditor = models.CharField(max_length=255, null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    priority_score = models.IntegerField(null=True, blank=True)
    plan_month = models.CharField(max_length=7, null=True, blank=True) # e.g. "2026-07"
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_plan_history'

