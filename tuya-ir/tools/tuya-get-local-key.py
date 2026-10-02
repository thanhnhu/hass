#!/usr/bin/env python3
"""Fetch a device's local_key from the Tuya Cloud API (one-time, LAN control only after this).

Usage:
    python3 tuya-get-local-key.py

You will be prompted for:
  - endpoint   (e.g. https://openapi.tuyaus.com  — use the region your Smart Life app account is in:
                openapi.tuyaus.com / openapi.tuyaeu.com / openapi.tuyacn.com / openapi.tuyain.com)
  - client_id     (Access ID, from the Tuya IoT Platform project Overview page)
  - client_secret (Access Secret, same page — never paste this into a chat/AI tool)
  - device_id     (from the device list, e.g. a36d7027db17bf84edvu5a)

Requires the Cloud project to have the "IoT Core" service subscribed and the device linked
under Devices > Link Tuya App Account.
"""
import hashlib
import hmac
import time
import urllib.request
import json
import getpass

def sign(msg: str, secret: str) -> str:
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest().upper()

def request(endpoint, path, client_id, client_secret, access_token=""):
    t = str(int(time.time() * 1000))
    nonce = ""
    content_sha256 = hashlib.sha256(b"").hexdigest()
    # Tuya signing: client_id + [access_token] + t + nonce + stringToSign
    string_to_sign = f"GET\n{content_sha256}\n\n{path}"
    sign_str = client_id + access_token + t + nonce + string_to_sign
    signature = sign(sign_str, client_secret)
    headers = {
        "client_id": client_id,
        "sign": signature,
        "t": t,
        "sign_method": "HMAC-SHA256",
        "nonce": nonce,
    }
    if access_token:
        headers["access_token"] = access_token
    req = urllib.request.Request(endpoint + path, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def main():
    endpoint = input("Endpoint [https://openapi.tuyaus.com]: ").strip() or "https://openapi.tuyaus.com"
    client_id = input("client_id (Access ID): ").strip()
    client_secret = getpass.getpass("client_secret (Access Secret, hidden input): ").strip()
    device_id = input("device_id: ").strip()

    token_resp = request(endpoint, "/v1.0/token?grant_type=1", client_id, client_secret)
    if not token_resp.get("success"):
        print("Token request failed:", token_resp)
        return
    access_token = token_resp["result"]["access_token"]

    dev_resp = request(endpoint, f"/v1.0/devices/{device_id}", client_id, client_secret, access_token)
    if not dev_resp.get("success"):
        print("Device request failed:", dev_resp)
        return

    result = dev_resp["result"]
    print("\n--- device info ---")
    print("name:      ", result.get("name"))
    print("ip:        ", result.get("ip"))
    print("local_key: ", result.get("local_key"))
    print("category:  ", result.get("category"))

if __name__ == "__main__":
    main()
