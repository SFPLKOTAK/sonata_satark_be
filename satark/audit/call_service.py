import uuid
import os
import json
import requests
import logging

logger_voice = logging.getLogger(__name__)

def create_call_markytics(customer_id, agent_number, destination_number):
    print("calling from this")
    channel = f"0{agent_number}@sonata"
    channel2 = f"0{destination_number}@sonata"
    print("calling from this 111")
 
    # Generate UUID
    myuuid = str(uuid.uuid4())
    print("calling from this 222")
    print("myuuid", myuuid)
 
    logger_voice.info("Data patching initiate call...")
    print("calling from this 333")
    ASTERISK_DETAILS = {
        "IP": "10.53.213.198",
        "RECORDING_PATH": "/home/dtel",
        "USERNAME": "CitizenAI",
        "PASSWORD": "mypassword",
        "USERNAME2": "myuser",
        "PASSWORD2": "mypassword",
        "USERNAME3": "GetCalls",
        "PASSWORD3": "mypassword",
        "PREFIX": "0",
        "SUFIX": "+912065170007",
        "CONTEXT": "external",
        "BASE_DIR": "/home/pc/audiosocket_server/",
        "REC_DIR": "/var/spool/asterisk/monitor",
        "BUCKET_NAME": "voicebot-audio-files",
        "BlobPath": "sonata-dialer",
    }  
 
    print("calling from this 444")
    # Action to originate a call
    action = {
        "Action": "Originate",
        "Channel": f"PJSIP/{channel}",
        "Priority": "1",
        "Timeout": "20000",
        "CallerID": f"<sonata>",
        "ChannelId": myuuid,
        "Application": "Dial",
        "Data": f"PJSIP/{channel2},30",
        "async": "true",
        "variable": f"GROUP()=markytics-sonata",
    }
 
    print("action", action)
    print("calling from this 555")
    logger_voice.info("After action.")
    print("calling from this 666")
 
    mix_monitor = {
        'Action': 'MixMonitor',
        'Channel': myuuid,
        'File': f"/var/spool/asterisk/monitor/{myuuid}.wav",
        'Command': f'{os.path.join(ASTERISK_DETAILS["BASE_DIR"], "upload_call_patch_recording_sonata.py")} {ASTERISK_DETAILS["BUCKET_NAME"]} {myuuid}.wav {ASTERISK_DETAILS["BlobPath"]}',
    }
 
    print("mix_monitor", mix_monitor)
    print("calling from this 777")
 
    logger_voice.info(f"Originate: {action}")
    print("calling from this 888")
    logger_voice.info(f"MixMonitor: {mix_monitor}")
    print("calling from this 999")
 
    # Final payload
    payload = {
        "accountcode": "sonatafinance",
        "contact_number": str(agent_number),
        "action": action,
        "mixmonitor": mix_monitor,
        "server_name": "aws_sonata"
    }
 
    print("calling from this 1000")
    logger_voice.info(f"Final call payload: {json.dumps(payload)}")
    print("calling from this 1001")
 
    headers = {
        "Content-Type": "application/json",
        "x-api-key": "markytics_7_twrc8X77BJbl9hjRu6xskEUyWgaIcnnPlFJeysEgyBc"
    }    
    print("calling from this 1002")
    # Send to external API
    response = ''
    try:
        response = requests.post("https://sonata-novacaller.markytics.com/calling/api/v1/priority-queue/insert", headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        logger_voice.info(f"Call payload sent successfully: {response.text}")
        print("calling from this 1003")
        print("calling response", response)
    except requests.RequestException as e:
        print("calling from this 1004")
        logger_voice.error(f"Failed to send call payload: {str(e)}")
 
    print("calling from this 1005")
 
    return response, myuuid

def extract_call_id(service, resp):
    try:
        if service == "Smartping":
            return str(resp.get("TransId", 0))
        elif service == "Tatatele":
            return str(resp.get("call_id", 0))
        elif service == "Markytics":
            data = resp.get("data", {})
            return str(data.get("caller_id", resp.get("call_id", 0)))
    except Exception:
        return "0"
    return "0"
