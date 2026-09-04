from django.urls import path
from . import views

urlpatterns = [
    path('call-recordings/', views.fetch_call_center_recordings, name='fetch_call_recordings'),
    path('call-center-recordings/', views.fetch_call_center_recordings, name='fetch_call_center_recordings'),
    path('gemma-transcribe/', views.gemma_transcribe_audio, name='gemma_transcribe_audio'),
    path('convert-audio/', views.gemma_transcribe_audio, name='convert_audio_to_text'),
    path('gemma-summary/', views.gemma_generate_summary, name='gemma_generate_summary'),
    path('generate-summary/', views.gemma_generate_summary, name='generate_summary'),
    path('export-excel/', views.bulk_analyze_export_excel, name='export_excel'),
    path('bulk-analyze-excel/', views.bulk_analyze_export_excel, name='bulk_analyze_excel'),
]
