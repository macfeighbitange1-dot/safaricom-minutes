import os
import base64
import time
from datetime import datetime
import requests
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

# Load credentials from .env file
load_dotenv()

app = Flask(__name__)

# CONFIGURATION FROM .ENV
CONSUMER_KEY = os.getenv("DARAJA_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("DARAJA_CONSUMER_SECRET")
SHORTCODE = os.getenv("DARAJA_SHORTCODE", "174379")
PASSKEY = os.getenv("DARAJA_PASSKEY")
CALLBACK_URL = os.getenv("DARAJA_CALLBACK_URL")

OFFERS = [
    {"id": 1, "price": 10, "mins": 100, "duration": "24 Hours"}, 
    {"id": 2, "price": 10, "mins": 20, "duration": "1 Hour"},
    {"id": 3, "price": 20, "mins": 45, "duration": "3 Hours"},
    {"id": 4, "price": 50, "mins": 150, "duration": "24 Hours"},
]

def get_access_token():
    """Gets the M-Pesa API Access Token with detailed error reporting"""
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(
            api_url, 
            auth=(CONSUMER_KEY.strip(), CONSUMER_SECRET.strip()), 
            headers=headers
        )
        if r.status_code == 401:
            print("CRITICAL: Invalid Consumer Key or Secret.")
            return None
        r.raise_for_status()
        return r.json().get('access_token')
    except Exception as e:
        print(f"Connection Error: {e}")
        return None

def generate_password(timestamp):
    """Generates the password for STK Push"""
    data_to_encode = SHORTCODE + PASSKEY + timestamp
    encoded_string = base64.b64encode(data_to_encode.encode())
    return encoded_string.decode('utf-8')

@app.route('/')
def index():
    return render_template('index.html', offers=OFFERS)

@app.route('/batch')
def batch_page():
    return render_template('batch.html')

@app.route('/upload_batch', methods=['POST'])
def upload_batch():
    if 'file' not in request.files:
        return "No file uploaded", 400
    
    file = request.files['file']
    amount = request.form.get('amount', 1) # Default to 1 KES if not set
    
    if file.filename == '':
        return "No file selected", 400

    # Read the file and get phone numbers
    content = file.read().decode('utf-8')
    phone_numbers = [n.strip() for n in content.split('\n') if n.strip()]

    # Limit to 50 for safety on Render Free Tier
    batch = phone_numbers[:50]
    
    access_token = get_access_token()
    if not access_token:
        return "Authentication Failed", 500

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password = generate_password(timestamp)
    stk_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    
    results = []
    for phone in batch:
        # Clean phone number
        clean_phone = phone
        if clean_phone.startswith("0"):
            clean_phone = "254" + clean_phone[1:]
        elif clean_phone.startswith("+"):
            clean_phone = clean_phone[1:]

        stk_payload = {
            "BusinessShortCode": SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": clean_phone,
            "PartyB": SHORTCODE,
            "PhoneNumber": clean_phone,
            "CallBackURL": CALLBACK_URL,
            "AccountReference": "BatchPayment",
            "TransactionDesc": "Bulk STK Push"
        }

        try:
            requests.post(stk_url, json=stk_payload, headers=headers)
            results.append(f"Sent to {clean_phone}")
        except Exception as e:
            results.append(f"Failed for {clean_phone}: {str(e)}")
        
        # 0.5s delay to stay within Safaricom's rate limits
        time.sleep(0.5)

    return jsonify({"status": "complete", "processed": len(results), "details": results})

@app.route('/initiate_payment', methods=['POST'])
def initiate_payment():
    data = request.json
    phone = data.get('phone')
    offer_id = data.get('offer_id')
    selected_offer = next((item for item in OFFERS if item["id"] == int(offer_id)), None)
    
    if not selected_offer:
        return jsonify({"status": "error", "message": "Invalid Offer"}), 400

    if phone.startswith("0"):
        phone = "254" + phone[1:]
    elif phone.startswith("+"):
        phone = phone[1:]

    access_token = get_access_token()
    if not access_token:
        return jsonify({"status": "error", "message": "Authentication Failed."}), 500

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password = generate_password(timestamp)
    stk_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    
    stk_payload = {
        "BusinessShortCode": SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": selected_offer['price'],
        "PartyA": phone,
        "PartyB": SHORTCODE,
        "PhoneNumber": phone,
        "CallBackURL": CALLBACK_URL,
        "AccountReference": "SafaricomMinutes",
        "TransactionDesc": f"Payment for {selected_offer['mins']} mins"
    }

    try:
        response = requests.post(stk_url, json=stk_payload, headers=headers)
        res_data = response.json()
        if res_data.get("ResponseCode") == "0":
            return jsonify({"status": "success", "message": "STK Push sent!"})
        else:
            return jsonify({"status": "error", "message": res_data.get("CustomerMessage", "Failed")})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)