import os
import requests
import logging

logger = logging.getLogger("gupshup")

def send_whatsapp_alert(mobile, template_data=None):
    """
    Sends a WhatsApp message via Gupshup API using the requested URL format.
    mobile: receiver's phone number (e.g. '8329268591')
    """
    if not mobile:
        logger.error("Gupshup send failed: No mobile number provided")
        return

    mobile = '8329268591'

    # User provided credentials
    userid = "2000209909"
    password = "z24gzBUA"
    gupshup_url = "https://mediaapi.smsgupshup.com/GatewayAPI/rest"
    
    # We strip any non-digit characters from the mobile number just in case
    mobile = ''.join(filter(str.isdigit, str(mobile)))

    params = {
        "userid": userid,
        "password": password,
        "send_to": mobile,
        "v": "1.1",
        "format": "json",
        "msg_type": "TEXT",
        "method": "SENDMESSAGE",
        "msg": "HI THIS IS REGARDING YOUR NON COMPLIANT POINTS. PLEASE RESOLVE THEM INSTANTLY",
        "isTemplate": "true",
        "header": "Greetings From BSS SONATA MICROCREDIT!",
        "footer": "THANK YOU"
    }
    
    try:
        response = requests.get(gupshup_url, params=params, timeout=10)
        logger.info(f"Gupshup send response for {mobile}: {response.status_code} {response.text}")
        return response.status_code == 200 or response.status_code == 202
    except Exception as e:
        logger.error(f"Failed to send Gupshup alert to {mobile}: {str(e)}")
        return False
