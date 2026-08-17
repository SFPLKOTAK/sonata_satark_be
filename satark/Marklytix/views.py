
import json
import os
import re
from datetime import datetime

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.db import connection


def _exec(sql, params=None, fetch="all"):
    with connection.cursor() as c:
        c.execute(sql, params or [])
        if fetch == "one":
            return c.fetchone()
        if fetch == "all":
            cols = [d[0] for d in c.description]
            return [dict(zip(cols, row)) for row in c.fetchall()]
        return None


# ============================================================
# ChatbotHierarchyPrompts (SBot main prompts)
# ============================================================

@csrf_exempt
def get_all_prompts(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only"}, status=405)
    try:
        rows = _exec("SELECT Id, PromptName, PromptContent, IsActive, CreatedBy, ModifiedBy, CreatedDate, ModifiedDate FROM dbo.Marklytix_ChatbotHierarchyPrompts WHERE IsActive = 1")
        return JsonResponse({"success": True, "data": rows})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def get_prompt_by_name(request, prompt_name):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only"}, status=405)
    try:
        row = _exec("SELECT Id, PromptName, PromptContent, IsActive, CreatedBy, ModifiedBy, CreatedDate, ModifiedDate FROM dbo.Marklytix_ChatbotHierarchyPrompts WHERE PromptName = %s AND IsActive = 1", [prompt_name], fetch="one")
        if row:
            cols = ["id", "prompt_name", "prompt_content", "is_active", "created_by", "modified_by", "created_date", "modified_date"]
            return JsonResponse({"success": True, "data": dict(zip(cols, row))})
        return JsonResponse({"success": False, "message": f'Prompt "{prompt_name}" not found'}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def update_prompt_content(request, prompt_name):
    if request.method != "PUT":
        return JsonResponse({"success": False, "message": "PUT only"}, status=405)
    try:
        data = json.loads(request.body)
        prompt_content = data.get("prompt_content")
        modified_by = data.get("modified_by", "admin")
        if not prompt_content:
            return JsonResponse({"success": False, "message": "prompt_content required"}, status=400)
        _exec("UPDATE dbo.Marklytix_ChatbotHierarchyPrompts SET PromptContent = %s, ModifiedBy = %s, ModifiedDate = GETDATE() WHERE PromptName = %s AND IsActive = 1", [prompt_content, modified_by, prompt_name], fetch="none")
        return JsonResponse({"success": True, "message": "Prompt updated successfully"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


# ============================================================
# SBot management (HierarchyPrompts CRUD)
# ============================================================

@csrf_exempt
def list_sbots(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only"}, status=405)
    try:
        rows = _exec("SELECT Id, PromptName, PromptContent, IsActive, CreatedBy, ModifiedBy, CreatedDate, ModifiedDate FROM dbo.Marklytix_ChatbotHierarchyPrompts WHERE IsActive = 1 ORDER BY CreatedDate DESC")
        sbots = [{"id": r["Id"], "sbot_name": r["PromptName"], "description": r["PromptContent"][:200] if r["PromptContent"] else "", "prompt_name": r["PromptName"], "is_active": r["IsActive"], "created_by": r["CreatedBy"], "updated_at": str(r["ModifiedDate"] or r["CreatedDate"])} for r in rows]
        return JsonResponse({"success": True, "sbots": sbots})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def create_sbot(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only"}, status=405)
    try:
        data = json.loads(request.body)
        name = data.get("name") or data.get("sbot_name")
        prompt_name = data.get("prompt_name") or name
        prompt_content = data.get("prompt_content") or data.get("description", "")
        created_by = data.get("created_by", "admin")
        if not name or not prompt_name:
            return JsonResponse({"success": False, "message": "name and prompt_name required"}, status=400)
        _exec("INSERT INTO dbo.Marklytix_ChatbotHierarchyPrompts (PromptName, PromptContent, IsActive, CreatedBy) VALUES (%s, %s, 1, %s)", [prompt_name, prompt_content, created_by], fetch="none")
        return JsonResponse({"success": True, "message": f"SBot '{name}' created successfully"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def get_sbot_details(request, prompt_name):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only"}, status=405)
    try:
        row = _exec("SELECT Id, PromptName, PromptContent, IsActive, CreatedDate, ModifiedDate FROM dbo.Marklytix_ChatbotHierarchyPrompts WHERE PromptName = %s AND IsActive = 1", [prompt_name], fetch="one")
        if row:
            return JsonResponse({"success": True, "data": {"id": row[0], "prompt_name": row[1], "prompt_content": row[2], "is_active": row[3], "created_at": str(row[4]), "updated_at": str(row[5])}})
        return JsonResponse({"success": False, "message": "SBot not found"}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def delete_sbot(request, prompt_name):
    if request.method != "DELETE":
        return JsonResponse({"success": False, "message": "DELETE only"}, status=405)
    try:
        _exec("UPDATE dbo.Marklytix_ChatbotHierarchyPrompts SET IsActive = 0, ModifiedDate = GETDATE() WHERE PromptName = %s", [prompt_name], fetch="none")
        return JsonResponse({"success": True, "message": f"SBot '{prompt_name}' deleted"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


# ============================================================
# Subcategory Prompts
# ============================================================

@csrf_exempt
def get_all_subcategory_prompts(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only"}, status=405)
    try:
        rows = _exec("SELECT Id, Category, Subcategory, Table_List, PromptContent, Query_Patterns, IsActive, CreatedDate, ModifiedDate FROM dbo.Marklytix_SubcategoryPrompts WHERE IsActive = 1 ORDER BY Category, Subcategory")
        return JsonResponse({"success": True, "data": rows})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def get_subcategory_prompt_by_id(request, prompt_id):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only"}, status=405)
    try:
        rows = _exec("SELECT Id, Category, Subcategory, Table_List, PromptContent, Query_Patterns, IsActive, CreatedDate, ModifiedDate FROM dbo.Marklytix_SubcategoryPrompts WHERE Id = %s AND IsActive = 1", [prompt_id])
        if rows:
            return JsonResponse({"success": True, "data": rows[0]})
        return JsonResponse({"success": False, "message": "Prompt not found"}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def get_subcategory_prompt_by_category_subcategory(request, category, subcategory):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only"}, status=405)
    try:
        rows = _exec("SELECT Id, Category, Subcategory, Table_List, PromptContent, Query_Patterns, IsActive, CreatedDate, ModifiedDate FROM dbo.Marklytix_SubcategoryPrompts WHERE LOWER(Category) = LOWER(%s) AND LOWER(Subcategory) = LOWER(%s) AND IsActive = 1", [category, subcategory])
        if rows:
            return JsonResponse({"success": True, "data": rows[0]})
        return JsonResponse({"success": False, "message": "Prompt not found"}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def create_subcategory_prompt(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only"}, status=405)
    try:
        data = json.loads(request.body)
        cat = data.get("category", "")
        sub = data.get("subcategory", "")
        table_list = data.get("table_list", "")
        prompt_content = data.get("prompt_content", "")
        query_patterns = data.get("query_patterns", "")
        created_by = data.get("created_by", "admin")
        if not cat or not sub:
            return JsonResponse({"success": False, "message": "category and subcategory required"}, status=400)
        _exec("INSERT INTO dbo.Marklytix_SubcategoryPrompts (Category, Subcategory, Table_List, PromptContent, Query_Patterns, IsActive, CreatedBy) VALUES (%s, %s, %s, %s, %s, 1, %s)", [cat, sub, table_list, prompt_content, query_patterns, created_by], fetch="none")
        return JsonResponse({"success": True, "message": "Subcategory prompt created"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def update_subcategory_prompt(request, prompt_id):
    if request.method != "PUT":
        return JsonResponse({"success": False, "message": "PUT only"}, status=405)
    try:
        data = json.loads(request.body)
        cat = data.get("category")
        sub = data.get("subcategory")
        table_list = data.get("table_list")
        prompt_content = data.get("prompt_content")
        query_patterns = data.get("query_patterns")
        modified_by = data.get("modified_by", "admin")
        _exec("UPDATE dbo.Marklytix_SubcategoryPrompts SET Category = COALESCE(%s, Category), Subcategory = COALESCE(%s, Subcategory), Table_List = COALESCE(%s, Table_List), PromptContent = COALESCE(%s, PromptContent), Query_Patterns = COALESCE(%s, Query_Patterns), ModifiedBy = %s, ModifiedDate = GETDATE() WHERE Id = %s AND IsActive = 1", [cat, sub, table_list, prompt_content, query_patterns, modified_by, prompt_id], fetch="none")
        return JsonResponse({"success": True, "message": "Subcategory prompt updated"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def delete_subcategory_prompt(request, prompt_id):
    if request.method != "DELETE":
        return JsonResponse({"success": False, "message": "DELETE only"}, status=405)
    try:
        _exec("UPDATE dbo.Marklytix_SubcategoryPrompts SET IsActive = 0, ModifiedDate = GETDATE() WHERE Id = %s", [prompt_id], fetch="none")
        return JsonResponse({"success": True, "message": "Subcategory prompt deleted"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def toggle_subcategory_prompt_status(request, prompt_id):
    if request.method != "PATCH":
        return JsonResponse({"success": False, "message": "PATCH only"}, status=405)
    try:
        data = json.loads(request.body)
        is_active = data.get("is_active", True)
        modified_by = data.get("modified_by", "admin")
        _exec("UPDATE dbo.Marklytix_SubcategoryPrompts SET IsActive = %s, ModifiedBy = %s, ModifiedDate = GETDATE() WHERE Id = %s", [1 if is_active else 0, modified_by, prompt_id], fetch="none")
        return JsonResponse({"success": True, "message": f"Status toggled to {'active' if is_active else 'inactive'}"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def generate_subcategory_prompt(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only"}, status=405)
    try:
        data = json.loads(request.body)
        db_schema = data.get("db_schema", "")
        if not db_schema:
            return JsonResponse({"success": False, "message": "db_schema required"}, status=400)
        # Use Gateway AI to generate prompt
        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.getenv("GEMMA_API_KEY", "sk-Y82UGER7Dw97we65RxwfnjRsiWb1CFH0vBB_zqgszUk"), base_url=os.getenv("GEMMA_BASE_URL", "http://43.242.226.49:8100/v1"))
            model = os.getenv("GEMMA_MODEL_ID", "google/gemma-4-E4B-it")
            sys_prompt = "You are an expert SQL Server prompt engineer. Generate a specialized T-SQL query generator prompt based on the provided database schema."
            user_msg = f"Database Schema:\n{db_schema}\n\nGenerate a detailed specialized prompt that will help an AI model generate accurate T-SQL queries for this schema."
            response = client.chat.completions.create(model=model, messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_msg}], temperature=0.3, max_tokens=2000)
            generated = response.choices[0].message.content
        except Exception as e_ai:
            generated = f"You are a specialized SQL generator for the following schema:\n{db_schema}\n\nGenerate accurate T-SQL queries based on user questions. Always use proper SQL Server syntax."
        return JsonResponse({"success": True, "generated_prompt": generated})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


# ============================================================
# Categories
# ============================================================

@csrf_exempt
def get_all_categories(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only"}, status=405)
    try:
        rows = _exec("SELECT Id, CategoryName, Keywords, Description, IsActive, CreatedDate, ModifiedDate FROM dbo.Marklytix_Categories WHERE IsActive = 1 ORDER BY CategoryName")
        return JsonResponse({"success": True, "data": rows})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def create_category(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only"}, status=405)
    try:
        data = json.loads(request.body)
        cat = data.get("category_name", "")
        keywords = data.get("keywords", "")
        description = data.get("description", "")
        if not cat:
            return JsonResponse({"success": False, "message": "category_name required"}, status=400)
        _exec("INSERT INTO dbo.Marklytix_Categories (CategoryName, Keywords, Description, IsActive) VALUES (%s, %s, %s, 1)", [cat, keywords, description], fetch="none")
        return JsonResponse({"success": True, "message": f"Category '{cat}' created"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def update_category(request, category_id):
    if request.method != "PUT":
        return JsonResponse({"success": False, "message": "PUT only"}, status=405)
    try:
        data = json.loads(request.body)
        cat = data.get("category_name")
        keywords = data.get("keywords")
        description = data.get("description")
        _exec("UPDATE dbo.Marklytix_Categories SET CategoryName = COALESCE(%s, CategoryName), Keywords = COALESCE(%s, Keywords), Description = COALESCE(%s, Description), ModifiedDate = GETDATE() WHERE Id = %s AND IsActive = 1", [cat, keywords, description, category_id], fetch="none")
        return JsonResponse({"success": True, "message": "Category updated"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def delete_category(request, category_id):
    if request.method != "DELETE":
        return JsonResponse({"success": False, "message": "DELETE only"}, status=405)
    try:
        _exec("UPDATE dbo.Marklytix_Categories SET IsActive = 0, ModifiedDate = GETDATE() WHERE Id = %s", [category_id], fetch="none")
        return JsonResponse({"success": True, "message": "Category deleted"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


# ============================================================
# Subcategories
# ============================================================

@csrf_exempt
def get_all_subcategories(request):
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only"}, status=405)
    try:
        cat_filter = request.GET.get("category", "")
        if cat_filter:
            rows = _exec("SELECT Id, CategoryName, SubcategoryName, Keywords, Description, IsActive, CreatedDate, ModifiedDate FROM dbo.Marklytix_Subcategories WHERE IsActive = 1 AND LOWER(CategoryName) = LOWER(%s) ORDER BY CategoryName, SubcategoryName", [cat_filter])
        else:
            rows = _exec("SELECT Id, CategoryName, SubcategoryName, Keywords, Description, IsActive, CreatedDate, ModifiedDate FROM dbo.Marklytix_Subcategories WHERE IsActive = 1 ORDER BY CategoryName, SubcategoryName")
        return JsonResponse({"success": True, "data": rows})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def create_subcategory(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only"}, status=405)
    try:
        data = json.loads(request.body)
        cat = data.get("category_name", "")
        sub = data.get("subcategory_name", "")
        keywords = data.get("keywords", "")
        description = data.get("description", "")
        if not cat or not sub:
            return JsonResponse({"success": False, "message": "category_name and subcategory_name required"}, status=400)
        _exec("INSERT INTO dbo.Marklytix_Subcategories (CategoryName, SubcategoryName, Keywords, Description, IsActive) VALUES (%s, %s, %s, %s, 1)", [cat, sub, keywords, description], fetch="none")
        return JsonResponse({"success": True, "message": f"Subcategory '{sub}' created under '{cat}'"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def update_subcategory(request, subcategory_id):
    if request.method != "PUT":
        return JsonResponse({"success": False, "message": "PUT only"}, status=405)
    try:
        data = json.loads(request.body)
        cat = data.get("category_name")
        sub = data.get("subcategory_name")
        keywords = data.get("keywords")
        description = data.get("description")
        _exec("UPDATE dbo.Marklytix_Subcategories SET CategoryName = COALESCE(%s, CategoryName), SubcategoryName = COALESCE(%s, SubcategoryName), Keywords = COALESCE(%s, Keywords), Description = COALESCE(%s, Description), ModifiedDate = GETDATE() WHERE Id = %s AND IsActive = 1", [cat, sub, keywords, description, subcategory_id], fetch="none")
        return JsonResponse({"success": True, "message": "Subcategory updated"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def delete_subcategory(request, subcategory_id):
    if request.method != "DELETE":
        return JsonResponse({"success": False, "message": "DELETE only"}, status=405)
    try:
        _exec("UPDATE dbo.Marklytix_Subcategories SET IsActive = 0, ModifiedDate = GETDATE() WHERE Id = %s", [subcategory_id], fetch="none")
        return JsonResponse({"success": True, "message": "Subcategory deleted"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)
