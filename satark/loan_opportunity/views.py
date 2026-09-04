import json
import logging
from datetime import date, datetime
from decimal import Decimal
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt

from .db import get_read_connection
from .gemma_service import transcribe_audio_with_gemma
from .gemma_summary_service import generate_english_collection_summary
from .bulk_analysis_service import bulk_analyze_and_generate_excel, process_single_recording_analysis
from .excel_service import create_call_analysis_excel

logger = logging.getLogger("loan_opportunity.views")


def json_serializer(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)


@csrf_exempt
def fetch_call_center_recordings(request):
    """
    API to fetch call center recordings from the Read DB (172.17.130.232 / sonata_connect).
    """
    if request.method not in ["GET", "POST"]:
        return JsonResponse({"error": "Method not allowed. Use GET or POST."}, status=405)

    try:
        params = {}
        if request.method == "POST":
            try:
                params = json.loads(request.body.decode('utf-8')) if request.body else {}
            except Exception:
                params = {}
        else:
            params = request.GET.dict()

        limit = int(params.get("limit", 10))
        start_date = params.get("start_date", "2026-08-01")
        end_date = params.get("end_date", "2026-08-30")
        status = params.get("status", "answered")
        min_call_duration = 120
        int(params.get("min_call_duration", 60))

        start_date = '2026-07-01'
        end_date = '2026-08-31'


        sql_query = f"""
            SELECT 
                recording_url, 
                agent_number, 
                status, 
                date, 
                client_number, 
                circle_operator, 
                circle_circle, 
                DisbursementID as disbursementid, 
                BranchID as branchhid, 
                UserID as userid, 
                CustomerInfoId as customerinfoid 
            FROM accounts_tatacallingrecords 
            WHERE date BETWEEN '2026-07-01' AND '2026-08-31'
              AND status = ? 
              and call_duration > ?
              AND call_duration > 120 and call_duration < 300
              AND recording_url IS NOT NULL
        """

        conn = get_read_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql_query, (status, 120))
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                row_dict = {}
                for col_name, val in zip(columns, row):
                    if isinstance(val, (date, datetime)):
                        val = val.isoformat()
                    elif isinstance(val, Decimal):
                        val = float(val)
                    elif isinstance(val, str):
                        val = val.strip()
                    row_dict[col_name] = val
                results.append(row_dict)
                
            return JsonResponse({
                "status": "success",
                "count": len(results),
                "data": results
            }, status=200)
            
        finally:
            conn.close()

    except Exception as e:
        logger.exception("Error fetching call center recordings")
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=500)


@csrf_exempt
def gemma_transcribe_audio(request):
    """
    API endpoint that accepts audio input (uploaded file or audio_url string)
    and uses the Gemma LLM Gateway to perform Voice-to-Text conversion.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed. Use POST."}, status=405)

    try:
        audio_url = None
        audio_bytes = None
        prompt_instruction = None

        if request.FILES.get('audio'):
            audio_bytes = request.FILES['audio'].read()
        elif request.FILES.get('file'):
            audio_bytes = request.FILES['file'].read()

        call_category = None
        if request.content_type and "application/json" in request.content_type and request.body:
            try:
                body = json.loads(request.body.decode('utf-8'))
                audio_url = body.get('audio_url')
                prompt_instruction = body.get('prompt_instruction')
                call_category = body.get('call_category')
            except Exception:
                pass
        else:
            if not audio_url:
                audio_url = request.POST.get('audio_url')
            if not prompt_instruction:
                prompt_instruction = request.POST.get('prompt_instruction')
            if not call_category:
                call_category = request.POST.get('call_category')

        if not audio_bytes and not audio_url:
            return JsonResponse({
                "status": "error",
                "message": "Missing audio input. Please upload an 'audio' file or provide an 'audio_url' string."
            }, status=400)

        result = transcribe_audio_with_gemma(
            audio_bytes=audio_bytes,
            audio_url=audio_url,
            prompt_instruction=prompt_instruction,
            call_category=call_category
        )

        return JsonResponse({
            "status": "success",
            "data": result
        }, status=200)

    except Exception as e:
        logger.exception("Error in gemma_transcribe_audio API")
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=500)


@csrf_exempt
def gemma_generate_summary(request):
    """
    SEPARATE API Endpoint:
    Takes full transcript text (in Hindi/Hinglish) and sends it to Gemma with domain context:
    'The call was a collection call from Sonata Microfinance for loan EMI collection.'
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed. Use POST."}, status=405)

    try:
        transcript_text = None
        customer_name = None
        agent_name = None
        call_category = None

        if request.content_type and "application/json" in request.content_type and request.body:
            try:
                body = json.loads(request.body.decode('utf-8'))
                transcript_text = body.get('transcript_text') or body.get('transcript') or body.get('raw_transcript')
                customer_name = body.get('customer_name')
                agent_name = body.get('agent_name')
                call_category = body.get('call_category')
            except Exception:
                pass
        else:
            transcript_text = request.POST.get('transcript_text') or request.POST.get('transcript')
            customer_name = request.POST.get('customer_name')
            agent_name = request.POST.get('agent_name')
            call_category = request.POST.get('call_category')

        if not transcript_text:
            return JsonResponse({
                "status": "error",
                "message": "Missing 'transcript_text' parameter in POST body."
            }, status=400)

        result = generate_english_collection_summary(
            transcript_text=transcript_text,
            customer_name=customer_name,
            agent_name=agent_name,
            call_category=call_category
        )

        return JsonResponse(result, status=200)

    except Exception as e:
        logger.exception("Error in gemma_generate_summary API")
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=500)


@csrf_exempt
def bulk_analyze_export_excel(request):
    """
    API endpoint that performs Bulk Voice-to-Data Analysis across call recordings
    and returns a downloadable Excel file (.xlsx) containing all requested columns:
    
    Columns:
      1. Call Date
      2. Client / Customer Number
      3. Agent / Staff Number
      4. Customer Info ID
      5. Disbursement ID
      6. User ID
      7. Branch ID
      8. Circle / Operator
      9. Customer Ready to Pay (1/0)
      10. Promised EMI Amount
      11. Promised PTP Date
      12. Reason for Non-Payment / Delay
      13. Customer Financial Situation
      14. Collection Outcome
      15. Recommended BRO / Manager Action
      16. Raw Hindi Transcript
      17. Staff & User Interaction
      18. English Executive Summary
      19. Recording Audio URL
    """
    if request.method not in ["GET", "POST"]:
        return JsonResponse({"error": "Method not allowed. Use GET or POST."}, status=405)

    try:
        recordings_list = []

        # 1. Check if recordings list is passed in JSON POST
        if request.method == "POST" and request.body:
            try:
                body = json.loads(request.body.decode('utf-8'))
                recordings_list = body.get("recordings", [])
            except Exception:
                pass

        # 2. If list not provided, fetch from Read DB accounts_tatacallingrecords
        if not recordings_list:
            limit_raw = request.GET.get("limit") or request.POST.get("limit")
            top_clause = ""
            if limit_raw and str(limit_raw).strip().isdigit() and int(limit_raw) > 0:
                top_clause = f"TOP {int(limit_raw)}"

            start_date = request.GET.get("start_date") or request.POST.get("start_date") or "2026-08-01"
            end_date = request.GET.get("end_date") or request.POST.get("end_date") or "2026-08-21"
            status = request.GET.get("status") or request.POST.get("status") or "answered"
            min_call_duration = int(request.GET.get("min_call_duration") or request.POST.get("min_call_duration") or 60)

            sql_query = f"""
                SELECT {top_clause} 
                    recording_url, 
                    agent_number, 
                    status, 
                    date, 
                    client_number, 
                    circle_operator, 
                    circle_circle, 
                    DisbursementID as disbursementid, 
                    BranchID as branchhid, 
                    UserID as userid, 
                    CustomerInfoId as customerinfoid 
                FROM accounts_tatacallingrecords 
                WHERE date BETWEEN ? AND ? 
                  AND status = ? 
                  AND call_duration > ? 
                  AND recording_url IS NOT NULL
                ORDER BY date DESC
            """
            conn = get_read_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(sql_query, (start_date, end_date, status, min_call_duration))
                columns = [c[0] for c in cursor.description]
                for r in cursor.fetchall():
                    row_dict = {}
                    for col_name, val in zip(columns, r):
                        if isinstance(val, (date, datetime)):
                            val = val.isoformat()
                        elif isinstance(val, Decimal):
                            val = float(val)
                        elif isinstance(val, str):
                            val = val.strip()
                        row_dict[col_name] = val
                    recordings_list.append(row_dict)
            finally:
                conn.close()

        if not recordings_list:
            return JsonResponse({"status": "error", "message": "No recordings found to analyze."}, status=400)

        # 3. Check format preference (json vs xlsx stream)
        format_type = request.GET.get("format") or request.POST.get("format")
        if format_type == "json":
            # Process single item or array for JSON preview
            results = []
            for rec in recordings_list:
                results.append(process_single_recording_analysis(rec))
            return JsonResponse({"status": "success", "count": len(results), "data": results}, status=200)

        # 4. Generate Excel binary stream
        excel_bytes, analyzed_rows = bulk_analyze_and_generate_excel(recordings_list)

        response = HttpResponse(
            excel_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response['Content-Disposition'] = 'attachment; filename="Sonata_Call_Opportunity_Analysis_Report.xlsx"'
        return response

    except Exception as e:
        logger.exception("Error in bulk_analyze_export_excel API")
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=500)
