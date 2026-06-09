from django.db import models

class AccountsMstUsertbl(models.Model):
    id = models.BigAutoField(primary_key=True)
    UserID = models.IntegerField(null=True, blank=True)
    EmpID = models.CharField(max_length=255, null=True, blank=True)
    DesignationID = models.IntegerField(null=True, blank=True)
    UserName = models.CharField(max_length=255)
    UserCode = models.CharField(max_length=255, null=True, blank=True)
    ContactNo = models.CharField(max_length=255, null=True, blank=True)
    Email = models.CharField(max_length=255, null=True, blank=True)
    Hoid = models.IntegerField(null=True, blank=True)
    DivisionID = models.FloatField(null=True, blank=True)
    RegionID = models.CharField(max_length=255, null=True, blank=True)
    HubID = models.CharField(max_length=255, null=True, blank=True)
    BranchID = models.CharField(max_length=255, null=True, blank=True)
    BranchJoinDate = models.CharField(max_length=255, null=True, blank=True)
    BranchExitDate = models.CharField(max_length=255, null=True, blank=True)
    Comment = models.CharField(max_length=255, null=True, blank=True)
    IsActive = models.CharField(max_length=255, null=True, blank=True)
    CreatedBy = models.FloatField(null=True, blank=True)
    CreatedDate = models.CharField(max_length=255, null=True, blank=True)
    UpdatedBy = models.CharField(max_length=255, null=True, blank=True)
    UpdatedDate = models.CharField(max_length=255, null=True, blank=True)
    Locked = models.CharField(max_length=255, null=True, blank=True)
    LastPasswordDate = models.CharField(max_length=255, null=True, blank=True)
    BUType = models.FloatField(null=True, blank=True)
    Buid = models.FloatField(null=True, blank=True)
    IsLoggedin = models.CharField(max_length=255, null=True, blank=True)
    DeviceNo = models.CharField(max_length=255, null=True, blank=True)
    Session_Token_Id = models.CharField(max_length=255, null=True, blank=True)
    LoginDevice = models.CharField(max_length=255, null=True, blank=True)
    New = models.FloatField(null=True, blank=True)
    NewBranchId = models.FloatField(null=True, blank=True)
    EmpDOB = models.CharField(max_length=255, null=True, blank=True)
    GLAccountId = models.FloatField(null=True, blank=True)
    AccountId = models.FloatField(null=True, blank=True)
    IsDropout = models.CharField(max_length=255, null=True, blank=True)
    DropoutDate = models.CharField(max_length=255, null=True, blank=True)
    IsHelpDeskStaff = models.CharField(max_length=255, null=True, blank=True)
    registration_authenticated = models.BooleanField(default=False)
    
    date_joined = models.DateTimeField(null=True, blank=True)
    last_login = models.DateTimeField(null=True, blank=True)
    
    is_admin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    deactivated = models.BooleanField(default=False)
    password = models.CharField(max_length=255)

    class Meta:
        db_table = 'accounts_mst_usertbl'
        managed = False

class JWTToken(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(AccountsMstUsertbl, on_delete=models.CASCADE, db_column='UserID_fk')
    access_token = models.TextField(null=True, blank=True)
    refresh_token = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    access_expires_at = models.DateTimeField()
    refresh_expires_at = models.DateTimeField()

    class Meta:
        db_table = 'accounts_jwt_tbl'
        managed = False

class MstMenuItem(models.Model):
    id = models.AutoField(primary_key=True)
    label = models.CharField(max_length=100)
    icon = models.CharField(max_length=50)
    to_path = models.CharField(max_length=200)
    badge_text = models.CharField(max_length=50, null=True, blank=True)
    sort_order = models.IntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'accounts_menu_item'
        managed = False

class MapRoleMenuItem(models.Model):
    id = models.AutoField(primary_key=True)
    role_id = models.IntegerField()
    menu_item = models.ForeignKey(MstMenuItem, on_delete=models.CASCADE, db_column='menu_item_id')

    class Meta:
        db_table = 'accounts_role_menu_mapping'
        managed = False
