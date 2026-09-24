import requests
import pandas as pd
import json

# 1. API Configuration
API_URL = "https://marketingai.markytics.ai/backend/api/campaigns/call-history/"

# Add any Authorization headers here if your API requires authentication (e.g. Bearer token)
HEADERS = {
    "Content-Type": "application/json",
    # "Authorization": "Bearer YOUR_TOKEN_HERE"  # Uncomment if API requires auth
}

# 2. Request Payload
payload = {
    "campaign_id": "CMP-271",
    "page": 1,
    "limit": 10000000,  # You can increase the limit or loop pages
    "sentiment": "",
    "show_test_calls": False,
    "call_tried": "",
    "call_connected_only": False,
    "channel_id": 1,
    "start_date": "2026-05-01",
    "end_date": "2026-09-01"
}

def fetch_and_save_to_excel():
    print(f"Sending POST request to {API_URL}...")
    response = requests.post(API_URL, json=payload, headers=HEADERS)
    
    if response.status_code == 200:
        data = response.json()
        print("✅ API Response Received Successfully!")
        
        # 3. Extract items/records list from JSON response
        # Adjust key if your response wraps items inside 'data', 'results', or 'calls'
        if isinstance(data, dict):
            records = data.get("data") or data.get("results") or data.get("calls") or [data]
        elif isinstance(data, list):
            records = data
        else:
            records = [data]
            
        # 4. Convert JSON records to DataFrame & Export to Excel / CSV
        df = pd.json_normalize(records)
        
        excel_filename = "campaign_call_history_CMP-271_from_may.xlsx"
        csv_filename = "campaign_call_history_CMP-271_from_may.csv"
        
        # Save as Excel
        try:
            df.to_excel(excel_filename, index=False)
            print(f"🎉 Saved data to Excel file: {excel_filename}")
        except Exception as e:
            print(f"Notice: Excel export notice ({e}), saving to CSV...")
        
        # Save as CSV
        try:
            df.to_csv(csv_filename, index=False)
            print(f"🎉 Saved data to CSV file: {csv_filename}")
        except Exception as e:
            print(f"⚠️ Could not save CSV file ({e}). If the file is open in Excel, please close it.")
        
    else:
        print(f"❌ Failed with status code: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    fetch_and_save_to_excel()
