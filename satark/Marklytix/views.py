
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


def _fetch_table_column_schemas(table_names):
    """
    Fetch exact column schemas from INFORMATION_SCHEMA.COLUMNS for specified tables.
    Returns formatted string schema representation and structured dictionary.
    """
    if not table_names:
        return "", {}
    
    clean_tables = [t.strip().lower() for t in table_names if t.strip()]
    if not clean_tables:
        return "", {}

    placeholders = ", ".join(["%s"] * len(clean_tables))
    sql = f"""
        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE LOWER(TABLE_NAME) IN ({placeholders})
        ORDER BY TABLE_NAME, ORDINAL_POSITION
    """
    try:
        rows = _exec(sql, clean_tables)
    except Exception as e:
        rows = []

    if not rows:
        return "", {}

    table_schemas = {}
    for r in rows:
        tbl = r["TABLE_NAME"]
        if tbl not in table_schemas:
            table_schemas[tbl] = []
        table_schemas[tbl].append({
            "COLUMN_NAME": r["COLUMN_NAME"],
            "DATA_TYPE": r["DATA_TYPE"],
            "CHARACTER_MAXIMUM_LENGTH": r["CHARACTER_MAXIMUM_LENGTH"] if r["CHARACTER_MAXIMUM_LENGTH"] is not None else "NULL",
            "IS_NULLABLE": r["IS_NULLABLE"]
        })

    formatted_schema = ""
    for tbl, cols in table_schemas.items():
        formatted_schema += f"### TABLE: dbo.{tbl}\n"
        formatted_schema += "COLUMN_NAME\tDATA_TYPE\tCHARACTER_MAXIMUM_LENGTH\tIS_NULLABLE\n"
        for col in cols:
            formatted_schema += f"{col['COLUMN_NAME']}\t{col['DATA_TYPE']}\t{col['CHARACTER_MAXIMUM_LENGTH']}\t{col['IS_NULLABLE']}\n"
        formatted_schema += "\n"

    return formatted_schema, table_schemas


@csrf_exempt
def generate_subcategory_prompt(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only"}, status=405)
    try:
        data = json.loads(request.body)
        db_schema_input = data.get("db_schema", "")
        category = data.get("category", "")
        subcategory = data.get("subcategory", "")
        table_list_input = data.get("table_list", "") or data.get("tables", "")

        # 1. Determine target table names
        target_tables = []
        if table_list_input:
            target_tables = [t.strip() for t in table_list_input.split(",") if t.strip()]
        
        if not target_tables and category and subcategory:
            # Query existing prompt or staging tables for Table_List
            rows = _exec("SELECT Table_List FROM dbo.Marklytix_SubcategoryPrompts WHERE LOWER(Category) = LOWER(%s) AND LOWER(Subcategory) = LOWER(%s) AND IsActive = 1", [category, subcategory])
            if rows and rows[0].get("Table_List"):
                target_tables = [t.strip() for t in rows[0]["Table_List"].split(",") if t.strip()]
            else:
                rows_stg = _exec("SELECT TableName FROM dbo.Marklytix_Staging_Subcategories WHERE LOWER(CategoryName) = LOWER(%s) AND LOWER(SubcategoryName) = LOWER(%s)", [category, subcategory])
                if rows_stg:
                    target_tables = list(set([r["TableName"].strip() for r in rows_stg if r.get("TableName")]))

        if not target_tables and db_schema_input:
            # Extract potential table names from input string
            extracted = re.findall(r'[a-zA-Z0-9_]{3,}', db_schema_input)
            if extracted:
                placeholders = ", ".join(["%s"] * len(extracted))
                try:
                    valid_rows = _exec(f"SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE LOWER(TABLE_NAME) IN ({placeholders})", [t.lower() for t in extracted])
                    target_tables = list(set([r["TABLE_NAME"] for r in valid_rows]))
                except Exception:
                    pass

        # 2. Fetch exact INFORMATION_SCHEMA column schemas
        formatted_schema, table_schemas = _fetch_table_column_schemas(target_tables)
        if not formatted_schema and db_schema_input:
            formatted_schema = db_schema_input

        table_list_str = ", ".join(target_tables) if target_tables else ""

        # 3. Call Gemma Gateway AI Model
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=os.getenv("GEMMA_API_KEY", "sk-Y82UGER7Dw97we65RxwfnjRsiWb1CFH0vBB_zqgszUk"),
                base_url=os.getenv("GEMMA_BASE_URL", "http://43.242.226.49:8100/v1")
            )
            model = os.getenv("GEMMA_MODEL_ID", "google/gemma-4-E4B-it")
            
            sys_prompt = (
                "You are an expert SQL Server prompt engineer for Enterprise Financial Audits. "
                "Generate a detailed specialized system prompt and 5 to 10 FEW-SHOT T-SQL query examples for SQL Server based on the table column schemas provided."
            )
            
            user_msg = f"""
Target Category: {category or 'General'}
Target Subcategory: {subcategory or 'General'}
Tables List: {table_list_str}

DETAILED DATABASE SCHEMAS (INFORMATION_SCHEMA.COLUMNS):
{formatted_schema}

INSTRUCTIONS:
1. Generate a specialized T-SQL system prompt that includes the exact table schemas, data types, nullability, and guidelines for generating queries.
2. Provide 5-10 realistic FEW-SHOT T-SQL example queries (using SELECT TOP 100, JOINs between tables where applicable, WHERE filtering on status/dates/IDs, and GROUP BY aggregations).
3. Return a JSON object with:
   - "prompt_content": System prompt instructions containing the schemas and query guidelines.
   - "query_patterns": Few-shot T-SQL query templates with comments describing each query.
   - "table_list": Comma-separated string of all table names.
"""
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.2,
                max_tokens=2500
            )
            ai_text = response.choices[0].message.content.strip()
            
            prompt_content = ai_text
            query_patterns = ""
            if "```json" in ai_text:
                json_str = ai_text.split("```json")[1].split("```")[0].strip()
                try:
                    parsed = json.loads(json_str)
                    prompt_content = parsed.get("prompt_content", ai_text)
                    query_patterns = parsed.get("query_patterns", "")
                    if parsed.get("table_list"):
                        table_list_str = parsed.get("table_list")
                except Exception:
                    pass
            elif ai_text.startswith("{") and ai_text.endswith("}"):
                try:
                    parsed = json.loads(ai_text)
                    prompt_content = parsed.get("prompt_content", ai_text)
                    query_patterns = parsed.get("query_patterns", "")
                except Exception:
                    pass

        except Exception as e_ai:
            prompt_content = f"You are a specialized T-SQL query generator for {category} -> {subcategory}.\n\n[AVAILABLE SCHEMAS]\n{formatted_schema}\n\nGenerate accurate T-SQL queries using proper SQL Server syntax."
            query_patterns = f"-- FEW-SHOT T-SQL QUERY EXAMPLES\n\n1. Select top 100 records:\nSELECT TOP 100 * FROM {target_tables[0] if target_tables else 'table_name'};"

        return JsonResponse({
            "success": True,
            "data": {
                "prompt_content": prompt_content,
                "table_list": table_list_str,
                "query_patterns": query_patterns,
                "schema_definitions": formatted_schema
            },
            "generated_prompt": prompt_content,
            "table_list": table_list_str,
            "query_patterns": query_patterns
        })
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


# ============================================================
# Gap 5: Automated Feedback Loop & Continuous RAG Indexing
# ============================================================

@csrf_exempt
def submit_query_feedback(request):
    """
    Gap 5: Automated Feedback Loop & Continuous RAG Indexing.
    When a user likes/approves a query (or an admin verifies it),
    updates chat history and vectorizes the (Question, SQL) pair into
    ChromaDB collection `marklytix_sql_examples`.
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only"}, status=405)
    try:
        import hashlib
        data = json.loads(request.body)
        chat_id = data.get("chat_id")
        question = (data.get("question") or "").strip()
        generated_query = (data.get("generated_query") or "").strip()
        rating = (data.get("rating") or "like").lower()
        category = data.get("category") or ""
        subcategory = data.get("subcategory") or ""
        tables_used = data.get("tables_used") or ""
        feedback_text = data.get("feedback_text") or ""
        
        # 1. Update feedback in dbo.Marklytix_ChatHistory if chat_id exists
        try:
            if chat_id:
                _exec("""
                    UPDATE dbo.Marklytix_ChatHistory
                    SET UserFeedback = %s, FeedbackComments = %s, FeedbackDate = GETDATE()
                    WHERE ChatID = %s
                """, [rating, feedback_text, str(chat_id)], fetch="none")
        except Exception as dbe:
            # Continue even if table column is slightly different
            pass
            
        indexed = False
        evicted = False
        trust_score = 1
        doc_id = f"sql_ex_{hashlib.md5(f'{question}_{generated_query}'.encode('utf-8')).hexdigest()[:12]}" if question and generated_query else ""
        storage_dir = os.path.join(os.path.dirname(__file__), "scratch", "chroma_db_storage")

        # 2. Handle Positive Rating (👍 Like / Verified)
        if rating in ("like", "thumbs_up", "positive", "verified") and question and generated_query:
            try:
                existing = _exec("""
                    SELECT Id, COALESCE(LikeCount, 0), COALESCE(DislikeCount, 0)
                    FROM dbo.Marklytix_VerifiedQueryExamples
                    WHERE LOWER(UserQuestion) = LOWER(%s)
                """, [question], fetch="one")

                if existing:
                    new_likes = existing[1] + 1
                    dislikes = existing[2]
                    trust_score = new_likes - (2 * dislikes)
                    is_active = 1 if trust_score > 0 else 0
                    status = 'Active' if trust_score > 0 else 'Flagged_Poison'

                    _exec("""
                        UPDATE dbo.Marklytix_VerifiedQueryExamples
                        SET GeneratedSQL = %s, Category = COALESCE(NULLIF(%s, ''), Category),
                            Subcategory = COALESCE(NULLIF(%s, ''), Subcategory), TablesUsed = COALESCE(NULLIF(%s, ''), TablesUsed),
                            Rating = %s, FeedbackComments = COALESCE(NULLIF(%s, ''), FeedbackComments),
                            LikeCount = %s, DislikeCount = %s, TrustScore = %s, Status = %s,
                            ModifiedDate = GETDATE(), IsActive = %s
                        WHERE Id = %s
                    """, [generated_query, category, subcategory, tables_used, rating, feedback_text,
                          new_likes, dislikes, trust_score, status, is_active, existing[0]], fetch="none")
                else:
                    trust_score = 1
                    _exec("""
                        INSERT INTO dbo.Marklytix_VerifiedQueryExamples
                        (UserQuestion, GeneratedSQL, Category, Subcategory, TablesUsed, Rating, FeedbackComments, LikeCount, DislikeCount, TrustScore, Status, IsActive)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 1, 0, 1, 'Active', 1)
                    """, [question, generated_query, category, subcategory, tables_used, rating, feedback_text], fetch="none")

                print(f"[CENTRAL DB SYNC] Persisted verified SQL example (TrustScore: {trust_score}) into dbo.Marklytix_VerifiedQueryExamples")
            except Exception as dbe2:
                print(f"[CENTRAL DB SYNC ERROR]: {dbe2}")

            # Upsert into ChromaDB if TrustScore > 0
            if trust_score > 0 and os.path.exists(storage_dir):
                import chromadb
                client = chromadb.PersistentClient(path=storage_dir)
                sql_coll = client.get_or_create_collection(
                    name="marklytix_sql_examples",
                    metadata={"description": "Few-Shot Verified SQL Query Examples for Dynamic RAG Ingestion"}
                )
                
                doc_text = f"User Question: {question}\nTarget Subcategory: {subcategory}\nVerified T-SQL Query:\n{generated_query}"
                if feedback_text:
                    doc_text += f"\nUser Feedback Notes: {feedback_text}"
                
                sql_coll.upsert(
                    ids=[doc_id],
                    documents=[doc_text],
                    metadatas=[{
                        "question": question,
                        "sql_query": generated_query,
                        "category": category,
                        "subcategory": subcategory.lower() if subcategory else "",
                        "tables_used": tables_used,
                        "rating": rating,
                        "feedback_comments": feedback_text or "",
                        "trust_score": int(trust_score),
                        "timestamp": datetime.now().isoformat()
                    }]
                )
                indexed = True
                print(f"[GAP 5 FEEDBACK FLYWHEEL] Indexed consensus SQL query into ChromaDB ({doc_id}) [TrustScore: {trust_score}]")

        # 3. Handle Negative Rating (👎 Dislike / Demotion & Poison Eviction)
        elif rating in ("dislike", "thumbs_down", "negative") and question:
            try:
                existing = _exec("""
                    SELECT Id, COALESCE(LikeCount, 0), COALESCE(DislikeCount, 0)
                    FROM dbo.Marklytix_VerifiedQueryExamples
                    WHERE LOWER(UserQuestion) = LOWER(%s)
                """, [question], fetch="one")

                if existing:
                    likes = existing[1]
                    new_dislikes = existing[2] + 1
                    trust_score = likes - (2 * new_dislikes)
                    is_active = 1 if trust_score > 0 else 0
                    status = 'Active' if trust_score > 0 else 'Flagged_Poison'

                    _exec("""
                        UPDATE dbo.Marklytix_VerifiedQueryExamples
                        SET Rating = %s, DislikeCount = %s, TrustScore = %s, Status = %s,
                            FeedbackComments = COALESCE(NULLIF(%s, ''), FeedbackComments),
                            ModifiedDate = GETDATE(), IsActive = %s
                        WHERE Id = %s
                    """, [rating, new_dislikes, trust_score, status, feedback_text, is_active, existing[0]], fetch="none")
                    print(f"[CENTRAL DB DEMOTION] Updated query with Dislike. New TrustScore: {trust_score} (Active: {is_active})")
                else:
                    trust_score = -2
                    _exec("""
                        INSERT INTO dbo.Marklytix_VerifiedQueryExamples
                        (UserQuestion, GeneratedSQL, Category, Subcategory, TablesUsed, Rating, FeedbackComments, LikeCount, DislikeCount, TrustScore, Status, IsActive)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 1, -2, 'Flagged_Poison', 0)
                    """, [question, generated_query, category, subcategory, tables_used, rating, feedback_text], fetch="none")

                # If TrustScore <= 0, automatically evict/purge from ChromaDB few-shot SQL store
                if trust_score <= 0 and os.path.exists(storage_dir):
                    import chromadb
                    client = chromadb.PersistentClient(path=storage_dir)
                    try:
                        sql_coll = client.get_collection(name="marklytix_sql_examples")
                        sql_coll.delete(where={"question": question})
                        evicted = True
                        print(f"[POISON EVICTION] Successfully evicted/purged poisoned query '{question}' from few-shot ChromaDB!")
                    except Exception as del_err:
                        print(f"[POISON EVICTION NOTICE]: {del_err}")

                # Store user dislike correction note in marklytix_dislike_feedback for warning injection
                if feedback_text and os.path.exists(storage_dir):
                    import chromadb
                    client = chromadb.PersistentClient(path=storage_dir)
                    try:
                        dislike_coll = client.get_or_create_collection(
                            name="marklytix_dislike_feedback",
                            metadata={"description": "Negative Feedback and Correction Notes for LLM Anti-Pattern Warnings"}
                        )
                        d_id = f"dislike_{hashlib.md5(question.encode('utf-8')).hexdigest()[:12]}"
                        dislike_coll.upsert(
                            ids=[d_id],
                            documents=[f"User Question: {question}\nDislike Correction Note: {feedback_text}"],
                            metadatas=[{
                                "question": question,
                                "feedback_comments": feedback_text,
                                "category": category or "",
                                "subcategory": subcategory.lower() if subcategory else "",
                                "timestamp": datetime.now().isoformat()
                            }]
                        )
                        print(f"[DISLIKE FEEDBACK FLYWHEEL] Stored dislike warning note for '{question}': '{feedback_text}'")
                    except Exception as dis_err:
                        print(f"[DISLIKE FEEDBACK INDEX ERROR]: {dis_err}")

            except Exception as dbe3:
                print(f"[CENTRAL DB DISLIKE ERROR]: {dbe3}")

        return JsonResponse({
            "success": True,
            "message": "Feedback recorded successfully." + (" Query promoted to verified consensus knowledge base." if indexed else (" Query demoted and evicted from vector memory." if evicted else "")),
            "indexed": indexed,
            "evicted": evicted,
            "trust_score": trust_score
        })
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


# ============================================================
# Shared Chat System (Claude-style Share Links)
# ============================================================

def _ensure_shared_chats_table():
    sql = """
    IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Marklytix_SharedChats')
    BEGIN
        CREATE TABLE dbo.Marklytix_SharedChats (
            ShareId VARCHAR(64) PRIMARY KEY,
            ChatId INT NULL,
            Username NVARCHAR(200) NOT NULL,
            Title NVARCHAR(500) NULL,
            MessagesSnapshot NVARCHAR(MAX) NOT NULL,
            AccessLevel VARCHAR(20) NOT NULL DEFAULT 'internal',
            IsPublic BIT NOT NULL DEFAULT 1,
            CreatedAt DATETIME DEFAULT GETDATE(),
            ModifiedAt DATETIME DEFAULT GETDATE()
        );
    END
    ELSE
    BEGIN
        IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('dbo.Marklytix_SharedChats') AND name = 'AccessLevel')
        BEGIN
            ALTER TABLE dbo.Marklytix_SharedChats ADD AccessLevel VARCHAR(20) NOT NULL DEFAULT 'internal';
        END
    END
    """
    try:
        with connection.cursor() as c:
            c.execute(sql)
    except Exception as e:
        print(f"[Marklytix_SharedChats Table Init Notice]: {e}")


@csrf_exempt
def create_shared_chat(request):
    """Creates or updates a shared chat link snapshot with access level ('internal' or 'public')."""
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only"}, status=405)
    try:
        _ensure_shared_chats_table()
        data = json.loads(request.body)
        chat_id = data.get("chat_id")
        username = data.get("username", "Anonymous")
        title = data.get("title", "Marklytix Chat")
        messages = data.get("messages", [])
        access_level = data.get("access_level", "internal")  # 'internal' or 'public'

        if not messages:
            return JsonResponse({"success": False, "message": "Messages snapshot cannot be empty"}, status=400)

        import uuid
        messages_json = json.dumps(messages)

        existing = None
        if chat_id:
            existing = _exec("SELECT ShareId, IsPublic, AccessLevel FROM dbo.Marklytix_SharedChats WHERE ChatId = %s", [chat_id], fetch="one")

        if existing and existing[0]:
            share_id = existing[0]
            _exec(
                "UPDATE dbo.Marklytix_SharedChats SET MessagesSnapshot = %s, Title = %s, Username = %s, AccessLevel = %s, IsPublic = 1, ModifiedAt = GETDATE() WHERE ShareId = %s",
                [messages_json, title, username, access_level, share_id],
                fetch=None
            )
        else:
            share_id = str(uuid.uuid4())
            _exec(
                "INSERT INTO dbo.Marklytix_SharedChats (ShareId, ChatId, Username, Title, MessagesSnapshot, AccessLevel, IsPublic, CreatedAt, ModifiedAt) VALUES (%s, %s, %s, %s, %s, %s, 1, GETDATE(), GETDATE())",
                [share_id, chat_id, username, title, messages_json, access_level],
                fetch=None
            )

        return JsonResponse({
            "success": True,
            "share_id": share_id,
            "title": title,
            "access_level": access_level,
            "is_public": True,
            "message": f"Chat shared successfully as {access_level.upper()}"
        })
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def get_shared_chat(request, share_id):
    """Fetches a shared chat snapshot by share_id."""
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only"}, status=405)
    try:
        _ensure_shared_chats_table()
        row = _exec("SELECT ShareId, ChatId, Username, Title, MessagesSnapshot, IsPublic, AccessLevel, CreatedAt FROM dbo.Marklytix_SharedChats WHERE ShareId = %s", [share_id], fetch="one")
        if not row:
            return JsonResponse({"success": False, "message": "Shared conversation not found."}, status=404)

        is_public = bool(row[5])
        if not is_public:
            return JsonResponse({"success": False, "message": "This shared link has been disabled by the author.", "is_private": True}, status=403)

        access_level = row[6] if row[6] else "internal"
        messages = json.loads(row[4]) if row[4] else []
        return JsonResponse({
            "success": True,
            "data": {
                "share_id": row[0],
                "chat_id": row[1],
                "username": row[2],
                "title": row[3],
                "access_level": access_level,
                "messages": messages,
                "created_at": row[7].isoformat() if row[7] else None
            }
        })
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def revoke_shared_chat(request, share_id):
    """Revokes / disables a shared chat link."""
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST only"}, status=405)
    try:
        _ensure_shared_chats_table()
        _exec("UPDATE dbo.Marklytix_SharedChats SET IsPublic = 0, ModifiedAt = GETDATE() WHERE ShareId = %s", [share_id], fetch=None)
        return JsonResponse({"success": True, "message": "Shared link disabled."})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def get_shared_chat_status(request, chat_id):
    """Checks if a chat has an active share link."""
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only"}, status=405)
    try:
        _ensure_shared_chats_table()
        row = _exec("SELECT ShareId, IsPublic, Title, AccessLevel, CreatedAt FROM dbo.Marklytix_SharedChats WHERE ChatId = %s", [chat_id], fetch="one")
        if row and row[0]:
            return JsonResponse({
                "success": True,
                "has_share": True,
                "share_id": row[0],
                "is_public": bool(row[1]),
                "title": row[2],
                "access_level": row[3] if row[3] else "internal"
            })
        return JsonResponse({"success": True, "has_share": False})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@csrf_exempt
def get_user_branch_context(request):
    """
    Fetches the distinct BranchID and UserID for the user from accounts_mst_usertbl.
    """
    if request.method != "GET":
        return JsonResponse({"success": False, "message": "GET only"}, status=405)
    try:
        user_id = request.GET.get("user_id") or request.GET.get("userid") or request.GET.get("id")

        # If not passed as query param, try decoding from JWT Authorization header
        auth_header = request.headers.get("Authorization") or ""
        if not user_id and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                import base64
                parts = token.split(".")
                if len(parts) == 3:
                    padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
                    payload_bytes = base64.b64decode(padded.replace("-", "+").replace("_", "/"))
                    payload = json.loads(payload_bytes.decode("utf-8"))
                    user_id = payload.get("user_id") or payload.get("id") or payload.get("userid")
            except Exception:
                pass

        if not user_id:
            return JsonResponse({"success": False, "message": "user_id is required"}, status=400)

        # Query SQL Server accounts_mst_usertbl
        row = _exec(
            """
            SELECT DISTINCT 
                CAST(BranchID AS VARCHAR(50)) AS BranchID, 
                CAST(UserID AS VARCHAR(50)) AS UserID, 
                UserName, 
                UserCode, 
                CAST(DivisionID AS VARCHAR(50)) AS DivisionID, 
                CAST(RegionID AS VARCHAR(50)) AS RegionID 
            FROM dbo.accounts_mst_usertbl 
            WHERE UserID = %s OR id = %s OR UserCode = %s
            """,
            [str(user_id), str(user_id), str(user_id)],
            fetch="one"
        )

        if row:
            branch_id = str(row[0]).strip() if row[0] is not None else ""
            db_user_id = str(row[1]).strip() if row[1] is not None else str(user_id)
            user_name = str(row[2]).strip() if row[2] is not None else ""
            user_code = str(row[3]).strip() if row[3] is not None else ""
            division_id = str(row[4]).strip() if row[4] is not None else ""
            region_id = str(row[5]).strip() if row[5] is not None else ""

            return JsonResponse({
                "success": True,
                "branch_id": branch_id,
                "user_id": db_user_id,
                "user_name": user_name,
                "user_code": user_code,
                "division_id": division_id,
                "region_id": region_id
            })
        else:
            return JsonResponse({
                "success": True,
                "branch_id": "",
                "user_id": str(user_id),
                "message": "User not found in accounts_mst_usertbl"
            })
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)



