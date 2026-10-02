#!/usr/bin/env python3
"""Pull already-learned IR codes for a Smart IR hub from the Tuya Cloud API.

This is a ONE-TIME cloud call to recover codes you already learned through the
Smart Life app (useful when the physical remote is now broken). The codes it
returns are the same raw base64 IR blobs tinytuya's IRRemoteControlDevice.send_button()
uses, so playback afterwards is fully local -- no cloud needed again.

Usage:
    python3 tuya-get-ir-codes.py
"""
import hashlib
import hmac
import time
import json
import getpass
import urllib.request
import urllib.parse


def sign(msg: str, secret: str) -> str:
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest().upper()


def request(endpoint, path, client_id, client_secret, access_token="", method="GET", body=None):
    t = str(int(time.time() * 1000))
    nonce = ""
    body_bytes = json.dumps(body).encode() if body is not None else b""
    content_sha256 = hashlib.sha256(body_bytes).hexdigest()
    string_to_sign = f"{method}\n{content_sha256}\n\n{path}"
    sign_str = client_id + access_token + t + nonce + string_to_sign
    signature = sign(sign_str, client_secret)
    headers = {
        "client_id": client_id,
        "sign": signature,
        "t": t,
        "sign_method": "HMAC-SHA256",
        "nonce": nonce,
        "Content-Type": "application/json",
    }
    if access_token:
        headers["access_token"] = access_token
    req = urllib.request.Request(endpoint + path, data=body_bytes if body is not None else None,
                                  headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def get_token(endpoint, client_id, client_secret):
    resp = request(endpoint, "/v1.0/token?grant_type=1", client_id, client_secret)
    if not resp.get("success"):
        raise SystemExit(f"Token request failed: {resp}")
    return resp["result"]["access_token"]


def main():
    endpoint = input("Endpoint [https://openapi.tuyaus.com]: ").strip() or "https://openapi.tuyaus.com"
    client_id = input("client_id (Access ID): ").strip()
    client_secret = getpass.getpass("client_secret (hidden): ").strip()
    infrared_id = input("infrared_id (the S6 device_id): ").strip()

    token = get_token(endpoint, client_id, client_secret)

    remotes_resp = request(endpoint, f"/v1.0/infrareds/{infrared_id}/remotes", client_id, client_secret, token)
    if not remotes_resp.get("success"):
        print("Failed to list remotes:", remotes_resp)
        return
    remotes = remotes_resp["result"]
    if not remotes:
        print("No remotes bound to this hub.")
        return

    all_codes = {}
    for r in remotes:
        remote_id = r["remote_id"]
        print(f"\n=== remote_id={remote_id} name={r.get('remote_name')} category_id={r.get('category_id')} "
              f"brand_id={r.get('brand_id')} remote_index={r.get('remote_index')} ===")

        # DIY-learned raw codes (works regardless of brand library)
        learn_resp = request(endpoint, f"/v1.0/infrareds/{infrared_id}/remotes/{remote_id}/learning-codes",
                              client_id, client_secret, token)
        if learn_resp.get("success") and learn_resp.get("result"):
            for item in learn_resp["result"]:
                key = f"{remote_id}:{item.get('key_name') or item.get('name')}"
                all_codes[key] = item["code"]
                print(f"  learned code -> {key} ({len(item['code'])} chars)")
        else:
            print("  (no DIY-learned codes for this remote)")

        # Library-matched code matrix (only if this remote came from brand library)
        cat_id, brand_id, remote_index = r.get("category_id"), r.get("brand_id"), r.get("remote_index")
        if brand_id and remote_index:
            rules_resp = request(
                endpoint,
                f"/v1.0/infrareds/{infrared_id}/categories/{cat_id}/brands/{brand_id}/remotes/{remote_index}/rules",
                client_id, client_secret, token,
            )
            if rules_resp.get("success") and rules_resp.get("result"):
                for item in rules_resp["result"]:
                    key = f"{remote_id}:{item.get('key_name') or item.get('desc')}"
                    all_codes[key] = item["code"]
                print(f"  library code matrix -> {len(rules_resp['result'])} entries")

    out_path = "codes_from_cloud.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_codes, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(all_codes)} codes to {out_path}")


if __name__ == "__main__":
    main()
