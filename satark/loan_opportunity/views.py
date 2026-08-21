import json
import logging
from datetime import date, datetime
from decimal import Decimal
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .db import get_read_connection

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
    
    Default Query Executed:
    select top 10 recording_url, agent_number, status, date, client_number, circle_operator, 
           circle_circle, DisbursementID, BranchID as branchhid, UserID, CustomerInfoId 
    from accounts_tatacallingrecords 
    where date between '2026-08-01' and '2026-08-21' 
      and status = 'answered' 
      and call_duration > 60 
      and recording_url is not null
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
        end_date = params.get("end_date", "2026-08-21")
        status = params.get("status", "answered")
        min_call_duration = int(params.get("min_call_duration", 60))

        sql_query = f"""
            SELECT TOP {limit} 
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
        """

        conn = get_read_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql_query, (start_date, end_date, status, min_call_duration))
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
