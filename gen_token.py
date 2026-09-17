import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import json
from colorama import Fore


def get_token(password, uid):
    url = "https://ffmconnect.live.gop.garenanow.com/oauth/guest/token/grant"
    headers = {
        "Host": "ffmconnect.live.gop.garenanow.com",
        "User-Agent": "GarenaMSDK/4.0.19P9(ASUS_Z01QD ;Android 9;en;US;)",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "Keep-Alive",
    }
    data = {
        "uid": uid,
        "password": password,
        "response_type": "token",
        "client_type": "2",
        "client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        "client_id": "100067",
    }
    response = requests.post(url, headers=headers, data=data, verify=False, timeout=10)
    if response.status_code != 200:
        print(Fore.RED + f"Failed to retrieve token for UID {uid}: {response.text}")
        return None
    return response.json()


def encrypt_message(key, iv, plaintext):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded_message = pad(plaintext, AES.block_size)
    encrypted_message = cipher.encrypt(padded_message)
    return encrypted_message


def load_tokens(file_path, limit=None):
    try:
        with open(file_path, "r") as file:
            data = json.load(file)
            tokens = list(data.items())
            if limit is not None:
                tokens = tokens[:limit]  # Set token limit
            return tokens
    except Exception as e:
        print(Fore.RED + f"Failed to load tokens: {e}")
        return []