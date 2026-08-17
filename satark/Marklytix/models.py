from django.db import models


class MarklytixChatbotHierarchyPrompts(models.Model):
    """Maps to dbo.Marklytix_ChatbotHierarchyPrompts — main LLM system prompts per SBot"""
    id = models.AutoField(primary_key=True, db_column="Id")
    prompt_name = models.CharField(max_length=100, unique=True, db_column="PromptName")
    prompt_content = models.TextField(db_column="PromptContent")
    is_active = models.BooleanField(default=True, db_column="IsActive")
    created_by = models.CharField(max_length=100, null=True, blank=True, db_column="CreatedBy")
    modified_by = models.CharField(max_length=100, null=True, blank=True, db_column="ModifiedBy")
    created_date = models.DateTimeField(auto_now_add=True, db_column="CreatedDate")
    modified_date = models.DateTimeField(auto_now=True, db_column="ModifiedDate")

    class Meta:
        managed = False
        db_table = "Marklytix_ChatbotHierarchyPrompts"

    def __str__(self):
        return self.prompt_name


class MarklytixSubcategoryPrompts(models.Model):
    """Maps to dbo.Marklytix_SubcategoryPrompts — specialized prompts per Category/Subcategory"""
    id = models.AutoField(primary_key=True, db_column="Id")
    category = models.CharField(max_length=200, db_column="Category")
    subcategory = models.CharField(max_length=200, db_column="Subcategory")
    table_list = models.TextField(null=True, blank=True, db_column="Table_List")
    prompt_content = models.TextField(null=True, blank=True, db_column="PromptContent")
    query_patterns = models.TextField(null=True, blank=True, db_column="Query_Patterns")
    is_active = models.BooleanField(default=True, db_column="IsActive")
    created_by = models.CharField(max_length=100, null=True, blank=True, db_column="CreatedBy")
    modified_by = models.CharField(max_length=100, null=True, blank=True, db_column="ModifiedBy")
    created_date = models.DateTimeField(auto_now_add=True, db_column="CreatedDate")
    modified_date = models.DateTimeField(auto_now=True, db_column="ModifiedDate")

    class Meta:
        managed = False
        db_table = "Marklytix_SubcategoryPrompts"

    def __str__(self):
        return f"{self.category} > {self.subcategory}"


class MarklytixCategories(models.Model):
    """Maps to dbo.Marklytix_Categories — category keywords for routing"""
    id = models.AutoField(primary_key=True, db_column="Id")
    category_name = models.CharField(max_length=200, db_column="CategoryName")
    keywords = models.TextField(null=True, blank=True, db_column="Keywords")
    description = models.TextField(null=True, blank=True, db_column="Description")
    is_active = models.BooleanField(default=True, db_column="IsActive")
    created_date = models.DateTimeField(auto_now_add=True, db_column="CreatedDate")
    modified_date = models.DateTimeField(auto_now=True, db_column="ModifiedDate")

    class Meta:
        managed = False
        db_table = "Marklytix_Categories"

    def __str__(self):
        return self.category_name


class MarklytixSubcategories(models.Model):
    """Maps to dbo.Marklytix_Subcategories — subcategory keywords"""
    id = models.AutoField(primary_key=True, db_column="Id")
    category_name = models.CharField(max_length=200, db_column="CategoryName")
    subcategory_name = models.CharField(max_length=200, db_column="SubcategoryName")
    keywords = models.TextField(null=True, blank=True, db_column="Keywords")
    description = models.TextField(null=True, blank=True, db_column="Description")
    is_active = models.BooleanField(default=True, db_column="IsActive")
    created_date = models.DateTimeField(auto_now_add=True, db_column="CreatedDate")
    modified_date = models.DateTimeField(auto_now=True, db_column="ModifiedDate")

    class Meta:
        managed = False
        db_table = "Marklytix_Subcategories"

    def __str__(self):
        return f"{self.category_name} > {self.subcategory_name}"


class MarklytixChatHistory(models.Model):
    """Maps to dbo.Marklytix_ChatHistory — conversation log"""
    id = models.AutoField(primary_key=True, db_column="Id")
    chat_id = models.IntegerField(db_column="ChatID")
    user_id = models.IntegerField(db_column="UserID")
    username = models.CharField(max_length=200, db_column="Username")
    sender = models.CharField(max_length=20, db_column="Sender")
    question = models.TextField(null=True, blank=True, db_column="Question")
    generated_query = models.TextField(null=True, blank=True, db_column="Generated_Query")
    result_generated = models.TextField(null=True, blank=True, db_column="Result_Generated")
    response_table = models.TextField(null=True, blank=True, db_column="Response_Table")
    query_creation_time = models.FloatField(null=True, blank=True, db_column="Query_Creation_Time")
    query_execution_time = models.FloatField(null=True, blank=True, db_column="Query_Execution_Time")
    created_at = models.DateTimeField(auto_now_add=True, db_column="Created_At")

    class Meta:
        managed = False
        db_table = "Marklytix_ChatHistory"
