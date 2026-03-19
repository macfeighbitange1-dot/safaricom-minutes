import os
import base64
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
    """Gets the M-Pesa API Access Token with updated headers to bypass 404/Firewall"""
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        r = requests.get(api_url, auth=(CONSUMER_KEY, CONSUMER_SECRET), headers=headers)
        r.raise_for_status()
        return r.json().get('access_token')
    except Exception as e:
        print(f"Token Error: {e}")
        return None

def generate_password(timestamp):
    """Generates the password for STK Push"""
    data_to_encode = SHORTCODE + PASSKEY + timestamp
    encoded_string = base64.b64encode(data_to_encode.encode())
    return encoded_string.decode('utf-8')

@app.route('/')
def index():
    return render_template('index.html', offers=OFFERS)

@app.route('/initiate_payment', methods=['POST'])
def initiate_payment():
    data = request.json
    phone = data.get('phone')
    offer_id = data.get('offer_id')
    
    selected_offer = next((item for item in OFFERS if item["id"] == int(offer_id)), None)
    
    if not selected_offer:
        return jsonify({"status": "error", "message": "Invalid Offer"}), 400

    # Clean phone number (Ensure it starts with 254)
    if phone.startswith("0"):
        phone = "254" + phone[1:]
    elif phone.startswith("+"):
        phone = phone[1:]

    # Prepare STK Push Handshake
    access_token = get_access_token()
    if not access_token:
        return jsonify({"status": "error", "message": "Authentication Failed. Check your .env keys."}), 500

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password = generate_password(timestamp)
    
    # Updated Headers and correct STK URL
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
        "PartyA": phone, # The user paying
        "PartyB": SHORTCODE, # The destination shortcode
        "PhoneNumber": phone,
        "CallBackURL": CALLBACK_URL,
        "AccountReference": "SafaricomMinutes",
        "TransactionDesc": f"Payment for {selected_offer['mins']} mins"
    }

    try:
        response = requests.post(stk_url, json=stk_payload, headers=headers)
        res_data = response.json()
        print(f"M-Pesa Response: {res_data}")
        
        if res_data.get("ResponseCode") == "0":
            return jsonify({"status": "success", "message": "STK Push sent! Enter PIN on your phone."})
        else:
            return jsonify({"status": "error", "message": res_data.get("CustomerMessage", "Request failed")})
            
    except Exception as e:
        print(f"STK Error: {e}")
        return jsonify({"status": "error", "message": "Connection to Safaricom failed."}), 500

if __name__ == '__main__':
    app.run(debug=True)