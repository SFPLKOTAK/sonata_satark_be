from django.urls import path
from . import views

urlpatterns = [
    # ChatbotHierarchyPrompts (SBot main prompts)
    path("api/prompts/", views.get_all_prompts, name="marklytix_get_all_prompts"),
    path("api/prompts/<str:prompt_name>/", views.get_prompt_by_name, name="marklytix_get_prompt_by_name"),
    path("api/prompts/<str:prompt_name>/update/", views.update_prompt_content, name="marklytix_update_prompt"),

    # SBot management
    path("api/sbots/", views.list_sbots, name="marklytix_list_sbots"),
    path("api/sbots/create/", views.create_sbot, name="marklytix_create_sbot"),
    path("api/sbots/<str:prompt_name>/", views.get_sbot_details, name="marklytix_get_sbot"),
    path("api/sbots/<str:prompt_name>/delete/", views.delete_sbot, name="marklytix_delete_sbot"),

    # Subcategory Prompts
    path("api/subcategory-prompts/", views.get_all_subcategory_prompts, name="marklytix_subcat_prompts"),
    path("api/subcategory-prompts/create/", views.create_subcategory_prompt, name="marklytix_create_subcat_prompt"),
    path("api/subcategory-prompts/generate-prompt/", views.generate_subcategory_prompt, name="marklytix_generate_prompt"),
    path("api/subcategory-prompts/<int:prompt_id>/", views.get_subcategory_prompt_by_id, name="marklytix_get_subcat_prompt"),
    path("api/subcategory-prompts/<int:prompt_id>/update/", views.update_subcategory_prompt, name="marklytix_update_subcat_prompt"),
    path("api/subcategory-prompts/<int:prompt_id>/delete/", views.delete_subcategory_prompt, name="marklytix_delete_subcat_prompt"),
    path("api/subcategory-prompts/<int:prompt_id>/toggle-status/", views.toggle_subcategory_prompt_status, name="marklytix_toggle_subcat_prompt"),
    path("api/subcategory-prompts/<str:category>/<str:subcategory>/", views.get_subcategory_prompt_by_category_subcategory, name="marklytix_get_subcat_prompt_by_cat"),

    # Categories
    path("api/categories/", views.get_all_categories, name="marklytix_categories"),
    path("api/categories/create/", views.create_category, name="marklytix_create_category"),
    path("api/categories/<int:category_id>/update/", views.update_category, name="marklytix_update_category"),
    path("api/categories/<int:category_id>/delete/", views.delete_category, name="marklytix_delete_category"),

    # Subcategories
    path("api/subcategories/", views.get_all_subcategories, name="marklytix_subcategories"),
    path("api/subcategories/create/", views.create_subcategory, name="marklytix_create_subcategory"),
    path("api/subcategories/<int:subcategory_id>/update/", views.update_subcategory, name="marklytix_update_subcategory"),
    path("api/subcategories/<int:subcategory_id>/delete/", views.delete_subcategory, name="marklytix_delete_subcategory"),

    # Gap 5: Automated Feedback Loop & Continuous RAG Indexing
    path("api/feedback/", views.submit_query_feedback, name="marklytix_submit_feedback"),
]
