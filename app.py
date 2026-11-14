import time
import httpx
import json
import uuid
import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.protobuf import json_format, message
from google.protobuf.message import Message
from Crypto.Cipher import AES
import base64
import FreeFire_pb2

# === Settings ===
MAIN_KEY = base64.b64decode('WWcmdGMlREV1aDYlWmNeOA==')
MAIN_IV = base64.b64decode('Nm95WkRyMjJFM3ljaGpNJQ==')
RELEASEVERSION = "OB55"
CLIENT_VERSION = "2.133.21"
CLIENT_VERSION_CODE = "2019118527"
USERAGENT = "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"
LOGIN_URL = "https://loginbp.ppmainecoonghj.com/"
CLIENT_URL = "https://clientbp.freefireind.in/"
# New Garena OAuth endpoint (v2)
OAUTH_URL = "https://100067.connect.garena.com/api/v2/oauth/guest/token:grant"
CLIENT_SECRET = "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3"
CLIENT_ID = 100067

# === Flask App Setup ===
app = Flask(__name__)
CORS(app)


# === Helper Functions ===
def pad(text: bytes) -> bytes:
    padding_length = AES.block_size - (len(text) % AES.block_size)
    return text + bytes([padding_length] * padding_length)


def aes_cbc_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    aes = AES.new(key, AES.MODE_CBC, iv)
    return aes.encrypt(pad(plaintext))


def decode_protobuf(encoded_data: bytes, message_type: message.Message) -> message.Message:
    instance = message_type()
    instance.ParseFromString(encoded_data)
    return instance


def encode_varint(value: int) -> bytes:
    parts = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value & 0x7F)
    return bytes(parts)


def encode_key(field_number: int, wire_type: int) -> bytes:
    return encode_varint((field_number << 3) | wire_type)


def encode_string(field_number: int, value: str) -> bytes:
    if value is None:
        return b""
    data = value.encode("utf-8")
    return encode_key(field_number, 2) + encode_varint(len(data)) + data


def encode_bytes(field_number: int, value: bytes) -> bytes:
    return encode_key(field_number, 2) + encode_varint(len(value)) + value


def encode_varint_field(field_number: int, value: int) -> bytes:
    return encode_key(field_number, 0) + encode_varint(value)


def build_major_login_proto(
    open_id: str,
    login_token: str,
    open_id_type: str = "4",
    orign_platform_type: str = "4",
    device_model: str = "Xiaomi M2007J22C",
    os_info: str = "Android OS 10 / API-29 (QP1A.190711.020/V12.0.11.0.QJECNXM)",
    carrier: str = "Singtel",
    network: str = "WIFI",
    language: str = "en",
    device_id: str = None,
) -> bytes:
    """
    Build the new large LoginReq protobuf used by current MajorLogin.
    Field numbers reverse-engineered from live OB55 traffic.
    """
    if device_id is None:
        device_id = str(uuid.uuid4())

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    # signature_md5 style placeholder (32 hex) — real client computes from package
    sig_md5 = "1ac4b80ecf0478a44203bf8fac6120f5"

    parts = []
    # field 3: timestamp string
    parts.append(encode_string(3, now))
    # field 4: game name
    parts.append(encode_string(4, "free fire"))
    # field 5: ?
    parts.append(encode_varint_field(5, 1))
    # field 7: client_version
    parts.append(encode_string(7, CLIENT_VERSION))
    # field 8: OS string
    parts.append(encode_string(8, os_info))
    # field 9: form factor
    parts.append(encode_string(9, "Handheld"))
    # field 10: carrier
    parts.append(encode_string(10, carrier))
    # field 11: network
    parts.append(encode_string(11, network))
    # field 12: height
    parts.append(encode_varint_field(12, 1280))
    # field 13: width
    parts.append(encode_varint_field(13, 720))
    # field 14: dpi-ish
    parts.append(encode_string(14, "320"))
    # field 15: CPU features
    parts.append(encode_string(15, "ARM64 FP ASIMD AES | 2352 | 8"))
    # field 16: ?
    parts.append(encode_varint_field(16, 3275))
    # field 17: GPU
    parts.append(encode_string(17, "Mali-G610"))
    # field 18: GL version
    parts.append(encode_string(18, "OpenGL ES 3.2 v1.g12p0-01eac0.d80164e2f5b37cc3667103831c67a8c0"))
    # field 19: advertising id style
    parts.append(encode_string(19, f"Google|{device_id}"))
    # field 20: some IP-like (optional)
    parts.append(encode_string(20, "0.0.0.0"))
    # field 21: language
    parts.append(encode_string(21, language))
    # field 22: open_id   <<< critical
    parts.append(encode_string(22, open_id))
    # field 23: open_id_type
    parts.append(encode_string(23, open_id_type))
    # field 24: form factor again
    parts.append(encode_string(24, "Handheld"))
    # field 25: device model
    parts.append(encode_string(25, device_model))
    # field 29: login_token (access_token)  <<< critical
    parts.append(encode_string(29, login_token))
    # field 30: ?
    parts.append(encode_varint_field(30, 1))
    # field 41 / 42: carrier / network again
    parts.append(encode_string(41, carrier))
    parts.append(encode_string(42, network))
    # field 57: signature_md5
    parts.append(encode_string(57, sig_md5))
    # some numeric telemetry fields (values from capture, safe defaults)
    parts.append(encode_varint_field(60, 110357))
    parts.append(encode_varint_field(61, 30650))
    parts.append(encode_varint_field(62, 1945))
    parts.append(encode_varint_field(64, 30778))
    parts.append(encode_varint_field(65, 110357))
    parts.append(encode_varint_field(66, 30778))
    parts.append(encode_varint_field(67, 110357))
    parts.append(encode_varint_field(73, 1))
    # field 74: lib path
    parts.append(encode_string(74, "/data/app/com.dts.freefiremax-dummy/lib/arm64"))
    parts.append(encode_varint_field(76, 2))
    # field 77: apk path + hash style
    parts.append(encode_string(77, "38f4751a330688ab124c2c804cec90a5|/data/app/com.dts.freefiremax-dummy/base.apk"))
    parts.append(encode_varint_field(78, 2))
    parts.append(encode_varint_field(79, 2))
    # field 81: arch
    parts.append(encode_string(81, "64"))
    # field 83: client_version_code
    parts.append(encode_string(83, CLIENT_VERSION_CODE))
    # field 86: GL API
    parts.append(encode_string(86, "OpenGLES3"))
    parts.append(encode_varint_field(87, 4095))
    parts.append(encode_varint_field(88, 4))
    parts.append(encode_varint_field(92, 46470))
    # field 93: release_channel
    parts.append(encode_string(93, "android_max"))
    # field 94: long base64-ish token (device related)
    parts.append(encode_string(94, "KqsHT5aXk3cLelncn6Q4sM6vAUYzW29WWGQOYWWGps5e8LkOv0/5GDPetFgdg5+52cPYktSftSHSX8jrWjKG2qXU22QzMJjIi7KaJ2nAPcVA9gNhv+hV5nEQdUN/rfYijCRcTw=="))
    # field 96: json config
    parts.append(encode_string(96, '{"cur_rate":[30,45,60],"support_etc2":true}'))
    parts.append(encode_varint_field(97, 1))
    parts.append(encode_varint_field(98, 1))
    # field 99: orign_platform_type  <<< critical (was 0x63 in old proto)
    parts.append(encode_string(99, orign_platform_type))
    # field 100
    parts.append(encode_string(100, "4"))
    parts.append(encode_varint_field(104, 94787))
    parts.append(encode_varint_field(105, 1))
    # field 106: hot update CDN list
    parts.append(encode_string(106, "https://dl.cdn.freefiremobile.com/live/ABHotUpdates/|https://dl-core.cdn.freefiremobile.com/live/ABHotUpdates/|b6756df94c9ff39b46f783f0998378a7"))
    # field 107
    parts.append(encode_string(107, "1.f72b09d6d99c8ba3"))

    return b"".join(parts)


def get_access_token(uid: str, password: str, device_id: str = None):
    """
    New Garena OAuth v2 guest token grant (JSON).
    Returns (access_token, open_id)
    """
    if device_id is None:
        # format similar to capture: 02-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        device_id = "02-" + str(uuid.uuid4())

    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "client_type": 2,
        "device_id": device_id,
        "password": password,
        "response_type": "token",
        "uid": int(uid) if str(uid).isdigit() else uid,
    }

    headers = {
        "User-Agent": f"GarenaMSDK/4.0.44(Android; Android 10; en; US; app {CLIENT_VERSION} {CLIENT_VERSION_CODE};)",
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
    }

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(OAUTH_URL, json=payload, headers=headers)
        try:
            data = resp.json()
        except Exception:
            raise Exception(f"OAuth invalid JSON response: HTTP {resp.status_code} {resp.text[:300]}")

        if data.get("code") != 0 or "data" not in data:
            raise Exception(f"OAuth failed: {data}")

        d = data["data"]
        access_token = d.get("access_token") or "0"
        open_id = d.get("open_id") or "0"
        return access_token, open_id, device_id


def find_protobuf_start(data: bytes) -> int:
    """
    LoginRes protobuf usually starts near region markers.
    """
    # Method 1: "IND" / region pattern
    idx = data.find(b"\x12\x03IND")
    if idx != -1:
        for i in range(idx - 1, max(idx - 30, -1), -1):
            if data[i] == 0x08:
                return i

    # Method 2: JWT marker
    jwt_marker = data.find(b"eyJ")
    if jwt_marker != -1:
        for i in range(jwt_marker - 1, max(jwt_marker - 200, -1), -1):
            if data[i] == 0x08:
                return i

    # Fallback
    return data.find(b"\x08")


def generate_jwt_token(uid: str, password: str):
    # 1) Get access_token + open_id from new OAuth
    token_val, open_id, device_id = get_access_token(uid, password)

    if token_val == "0" or open_id == "0":
        raise Exception("Invalid UID or Password — access token not received")

    # 2) Build new large LoginReq protobuf and encrypt
    proto_bytes = build_major_login_proto(
        open_id=open_id,
        login_token=token_val,
        open_id_type="4",
        orign_platform_type="4",
        device_id=device_id,
    )
    payload = aes_cbc_encrypt(MAIN_KEY, MAIN_IV, proto_bytes)

    # 3) Send MajorLogin
    url = f"{LOGIN_URL}MajorLogin"
    headers = {
        "User-Agent": USERAGENT,
        "Accept": "*/*",
        "Accept-Encoding": "deflate, gzip",
        "X-Ga-Sv": str(int(time.time())),
        "Authorization": "Bearer",
        "X-Ga": "v1 1",
        "ReleaseVersion": RELEASEVERSION,
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.12f1",
    }

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, data=payload, headers=headers)

        print(f"=== HTTP {resp.status_code} | Content-Length: {len(resp.content)} ===")

        if resp.status_code != 200:
            raise Exception(f"MajorLogin HTTP {resp.status_code}: {resp.content[:200]}")

        start_idx = find_protobuf_start(resp.content)
        if start_idx == -1:
            raise Exception(f"Protobuf start not found. Raw: {resp.content[:300]}")

        proto_data = resp.content[start_idx:]
        print(f"=== Protobuf starts at index {start_idx} ===")

        try:
            msg = json.loads(
                json_format.MessageToJson(
                    decode_protobuf(proto_data, FreeFire_pb2.LoginRes)
                )
            )
        except Exception as parse_err:
            raise Exception(
                f"Failed to parse LoginRes from index {start_idx}. "
                f"Raw (from start): {resp.content[start_idx:start_idx+300]}. "
                f"Error: {parse_err}"
            )

        response_data = {
            "account_Id": msg.get("accountId", ""),
            "agoraEnvironment": msg.get("agoraEnvironment", "live"),
            "ipRegion": msg.get("ipRegion", ""),
            "lockRegion": msg.get("lockRegion", ""),
            "region": msg.get("notiRegion", ""),
            "serverUrl": msg.get("serverUrl", ""),
            "token": f"{msg.get('token', '')}",
            "open_id": open_id,
            "uid": uid,
        }
        return response_data


# === Flask Routes ===
@app.route("/token", methods=["GET"])
def get_jwt_token():
    uid = request.args.get("uid")
    password = request.args.get("password")

    if not uid or not password:
        return jsonify({"error": "Both uid and password parameters are required"}), 400

    try:
        token_data = generate_jwt_token(uid, password)
        return jsonify(token_data), 200
    except Exception as e:
        return jsonify({"error": f"Failed to generate token: {str(e)}"}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "release": RELEASEVERSION, "client": CLIENT_VERSION}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
