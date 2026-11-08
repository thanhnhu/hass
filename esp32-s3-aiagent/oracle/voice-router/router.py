"""OpenAI-compatible voice router: local tools and a small local model first, Gemini as fallback."""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("ROUTER_PORT", "8787"))
BIND_ADDRESSES = [address.strip() for address in os.environ.get("ROUTER_BIND", "127.0.0.1").split(",") if address.strip()]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen3:1.7b")
LOCAL_TIMEOUT = float(os.environ.get("LOCAL_TIMEOUT", "10"))
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_TIMEOUT = float(os.environ.get("GEMINI_TIMEOUT", "20"))
HA_URL = os.environ.get("HA_URL", "").rstrip("/")
HA_TOKEN = os.environ.get("HA_TOKEN", "")
HA_MEDIA_PLAYER = os.environ.get("HA_MEDIA_PLAYER", "media_player.tvbox_bluetooth")
# Music runs on the TV box: YouTube blocks Oracle's datacenter IP.
MUSIC_API = os.environ.get("MUSIC_API", "http://100.78.12.116:8788").rstrip("/")
MUSIC_STREAM_BASE = os.environ.get("MUSIC_STREAM_BASE", "http://127.0.0.1:8788").rstrip("/")
GOLD_TTL = 600
SEARCH_TTL = 86400
HISTORY_TURNS = 4
ESCALATE = "CHUYEN_GEMINI"

LOCAL_SYSTEM = (
    "Bạn là trợ lý giọng nói trong nhà. Luôn trả lời bằng tiếng Việt, tự nhiên, tối đa hai câu ngắn, "
    "không dùng ký hiệu hay danh sách. Không tuyên bố đã điều khiển thiết bị vì bạn không có công cụ điều khiển. "
    "Nếu câu hỏi cần thông tin mới, số liệu, tin tức, kiến thức chuyên sâu "
    f"hoặc bạn không chắc chắn, chỉ trả lời đúng một từ: {ESCALATE}"
)
GEMINI_SYSTEM = (
    "Bạn là trợ lý giọng nói trong nhà. Trả lời bằng tiếng Việt, ngắn gọn tối đa ba câu, "
    "không dùng markdown hay danh sách vì câu trả lời sẽ được đọc thành tiếng."
)

GOLD_RE = re.compile(r"giá\s*vàng|vàng\s*(sjc|pnj|nhẫn|miếng)")
MUSIC_STOP_RE = re.compile(r"(dừng|tắt|ngừng|tạm dừng)\s*(phát\s*)?(nhạc|bài|bài hát)")
MUSIC_RE = re.compile(r"^(?:hãy\s+)?(?:(?:phát|mở|bật)\s+(?:bài(?:\s+(?:hát|nhạc))?|nhạc|ca\s+khúc)|cho\s+(?:tôi\s+)?nghe|nghe)\s+(?P<query>.+)$")
OPENCLAW_TIMESTAMP_RE = re.compile(r"^\[[A-Za-z]{3}\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+[^\]]+\]\s*")
ROOM_RE = re.compile(r"(nhiệt độ|độ ẩm|pm\s*2[,.]?5|bụi mịn|chất lượng không khí|không khí).*(phòng|trong nhà)|phòng.*(nhiệt độ|độ ẩm|không khí)|trong phòng (nóng|ẩm)")
PURIFIER_RE = re.compile(r"máy lọc|lọc không khí|máy lọc khí")
PURIFIER_ALARM_RE = re.compile(r"báo động|chuông báo|cảnh báo")
DEVICE_LIST_RE = re.compile(
    r"\b(thiết bị|đồ dùng)\b.*\b(liệt kê|danh sách|nào|gì|trong|hiện có|online|offline)\b|"
    r"\b(liệt kê|danh sách)\b.*\b(thiết bị|đồ dùng)\b|"
    r"\bcó những\b.*\b(thiết bị|đồ dùng)\b"
)
AC_RE = re.compile(r"điều\s*hoà|điều\s*hòa|máy lạnh")
KNOWLEDGE_RE = re.compile(
    r"hôm nay|ngày mai|hiện tại|bây giờ|mới nhất|tin tức|thời tiết|tỷ giá|giá |bao nhiêu tuổi|là ai|"
    r"ở đâu|năm nào|tại sao|vì sao|như thế nào|cách |công thức|giải thích|so sánh"
)

_cache = {}
_cache_lock = threading.Lock()
_music_lock = threading.Lock()
_pending_music = None


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def cached(key, ttl, producer):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = producer()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def http_json(url, payload=None, headers=None, timeout=10, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    return json.loads(body) if body else None


def history_from(messages):
    turns = [m for m in messages if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"].strip()]
    return turns[-(HISTORY_TURNS * 2):]


def ask_local(history):
    result = http_json(
        f"{OLLAMA_URL}/api/chat",
        {
            "model": LOCAL_MODEL,
            "messages": [{"role": "system", "content": LOCAL_SYSTEM}, *history],
            "stream": False,
            "think": False,
            "keep_alive": -1,
            "options": {"num_predict": 120, "temperature": 0.3},
        },
        timeout=LOCAL_TIMEOUT,
    )
    return result["message"]["content"].strip()


def ask_gemini(history):
    if not GEMINI_KEY:
        raise RuntimeError("GEMINI_API_KEY missing")
    result = http_json(
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        {"model": GEMINI_MODEL, "messages": [{"role": "system", "content": GEMINI_SYSTEM}, *history], "max_tokens": 300},
        headers={"Authorization": f"Bearer {GEMINI_KEY}"},
        timeout=GEMINI_TIMEOUT,
    )
    return result["choices"][0]["message"]["content"].strip()


def format_million(thousands):
    return f"{thousands / 1000:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def gold_answer():
    def fetch():
        data = http_json("https://edge-api.pnj.io/ecom-frontend/v1/get-gold-price", timeout=10)
        items = {item["masp"]: item for item in data["data"]}
        return items, data.get("updateDate", "")

    items, updated = cached("gold", GOLD_TTL, fetch)
    parts = []
    for code, label in (("SJC", "vàng miếng SJC"), ("N24K", "nhẫn trơn 999.9")):
        item = items.get(code)
        if item and item.get("giamua") and item.get("giaban"):
            parts.append(f"{label} mua vào {format_million(float(item['giamua']))} triệu, bán ra {format_million(float(item['giaban']))} triệu một chỉ")
    if not parts:
        raise RuntimeError("gold data missing")
    when = updated.split(" ")
    stamp = f" Cập nhật lúc {when[1][:5]} ngày {when[0]}." if len(when) == 2 else ""
    return "Theo PNJ, " + "; ".join(parts) + "." + stamp


def ha_call(domain, service, data):
    if not (HA_URL and HA_TOKEN):
        raise RuntimeError("HA_URL/HA_TOKEN missing")
    http_json(f"{HA_URL}/api/services/{domain}/{service}", data, headers={"Authorization": f"Bearer {HA_TOKEN}"}, timeout=10)


def ha_state(entity_id):
    result = http_json(f"{HA_URL}/api/states/{entity_id}", headers={"Authorization": f"Bearer {HA_TOKEN}"}, timeout=5)
    return result.get("state", "unknown")


def ha_registry_snapshot():
    import websocket

    if not (HA_URL and HA_TOKEN):
        raise RuntimeError("HA_URL/HA_TOKEN missing")
    parsed_url = urllib.parse.urlparse(HA_URL)
    websocket_scheme = {"http": "ws", "https": "wss"}.get(parsed_url.scheme)
    if not websocket_scheme:
        raise RuntimeError("Unsupported HA_URL scheme")
    websocket_url = urllib.parse.urlunparse((
        websocket_scheme, parsed_url.netloc, parsed_url.path.rstrip("/") + "/api/websocket", "", "", ""
    ))
    connection = websocket.create_connection(websocket_url, timeout=8)
    try:
        greeting = json.loads(connection.recv())
        if greeting.get("type") != "auth_required":
            raise RuntimeError("Unexpected Home Assistant WebSocket greeting")
        connection.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        auth_result = json.loads(connection.recv())
        if auth_result.get("type") != "auth_ok":
            raise RuntimeError("Home Assistant WebSocket authentication failed")

        def command(command_id, command_type):
            connection.send(json.dumps({"id": command_id, "type": command_type}))
            while True:
                response = json.loads(connection.recv())
                if response.get("id") != command_id:
                    continue
                if not response.get("success"):
                    raise RuntimeError(f"Home Assistant command failed: {command_type}")
                return response.get("result", [])

        return {
            "areas": command(1, "config/area_registry/list"),
            "devices": command(2, "config/device_registry/list"),
            "entities": command(3, "config/entity_registry/list"),
            "states": command(4, "get_states"),
        }
    finally:
        connection.close()


def device_inventory_answer(text):
    snapshot = ha_registry_snapshot()
    areas = snapshot["areas"]
    lowered = text.lower()
    area_aliases = (
        (("phòng ngủ", "bedroom"), "bedroom"),
        (("phòng khách", "living room"), "living room"),
        (("nhà bếp", "phòng bếp", "bếp", "kitchen"), "kitchen"),
    )
    requested_area = next(
        (canonical for aliases, canonical in area_aliases if any(alias in lowered for alias in aliases)),
        "bedroom" if re.search(r"\bphòng\b", lowered) else None,
    )
    area = next((item for item in areas if item.get("name", "").lower() == requested_area), None)
    if area is None and requested_area is None and len(areas) == 1:
        area = areas[0]
    if area is None:
        return "Bạn muốn xem thiết bị trong phòng nào?"

    entity_by_device = {}
    for entity in snapshot["entities"]:
        if entity.get("disabled_by"):
            continue
        device_id = entity.get("device_id")
        if device_id:
            entity_by_device.setdefault(device_id, []).append(entity)
    state_by_entity = {item["entity_id"]: item.get("state", "unknown") for item in snapshot["states"]}

    devices = [item for item in snapshot["devices"] if item.get("area_id") == area["area_id"]]
    area_label = {"bedroom": "phòng ngủ", "living room": "phòng khách", "kitchen": "bếp"}.get(
        area["name"].lower(), area["name"]
    )
    entries = []
    for device in devices:
        entities = entity_by_device.get(device["id"], [])
        if entities and all(entity["entity_id"].startswith("weather.") for entity in entities):
            continue
        states = [state_by_entity[entity["entity_id"]] for entity in entities if entity["entity_id"] in state_by_entity]
        available_states = [state for state in states if state not in ("unavailable", "unknown")]
        if available_states:
            status = "online"
        elif entities and states:
            status = "offline"
        else:
            status = "chưa xác định trạng thái"
        name = device.get("name_by_user") or device.get("name") or "Thiết bị không tên"
        entries.append(f"{name}: {status}")

    if not entries:
        return f"Không có thiết bị nào được đăng ký trong khu vực {area_label}."
    return f"Thiết bị trong {area_label}: " + "; ".join(entries) + "."


def direct_home_answer(text):
    lowered = text.lower()
    purifier = PURIFIER_RE.search(lowered)
    ac = AC_RE.search(lowered)
    fan = re.search(r"\bquạt\b", lowered)

    if DEVICE_LIST_RE.search(lowered):
        return device_inventory_answer(lowered)

    if ROOM_RE.search(lowered) and not ac:
        temperature = ha_state("sensor.zhimi_sg_874668291_rmb1_temperature_p_3_7")
        humidity = ha_state("sensor.zhimi_sg_874668291_rmb1_relative_humidity_p_3_1")
        pm25 = ha_state("sensor.zhimi_sg_874668291_rmb1_pm2_5_density_p_3_4")
        return f"Trong phòng {temperature} độ, độ ẩm {humidity} phần trăm, bụi mịn PM2.5 là {pm25}."

    if purifier and PURIFIER_ALARM_RE.search(lowered):
        alarm_entity = "switch.zhimi_sg_874668291_rmb1_alarm_p_6_1"
        if re.search(r"\b(tắt|ngừng|vô hiệu hóa)\b", lowered):
            ha_call("switch", "turn_off", {"entity_id": alarm_entity})
            return "Đã tắt báo động máy lọc."
        if re.search(r"\b(bật|mở|kích hoạt)\b", lowered):
            ha_call("switch", "turn_on", {"entity_id": alarm_entity})
            return "Đã bật báo động máy lọc."
        return f"Báo động máy lọc hiện {'đang bật' if ha_state(alarm_entity) == 'on' else 'đang tắt'}."

    if purifier and re.search(r"\b(tắt|đóng|ngừng)\b", lowered):
        ha_call("switch", "turn_off", {"entity_id": "switch.zhimi_sg_874668291_rmb1_on_p_2_1"})
        return "Đã tắt máy lọc không khí."
    if purifier and re.search(r"\b(bật|mở)\b", lowered):
        ha_call("switch", "turn_on", {"entity_id": "switch.zhimi_sg_874668291_rmb1_on_p_2_1"})
        return "Đã bật máy lọc không khí."

    if ac and re.search(r"\b(tắt|đóng|ngừng)\b", lowered):
        ha_call("script", "turn_on", {"entity_id": "script.dieuhoa_tat"})
        return "Đã tắt điều hoà."
    if ac and re.search(r"\b(bật|mở)\b", lowered):
        ha_call("script", "turn_on", {"entity_id": "script.dieuhoa_bat"})
        return "Đã bật điều hoà."
    if ac and re.search(r"\b(đặt|chỉnh|để|chuyển)\b", lowered):
        mode = re.search(r"\b(lạnh|làm lạnh|mát|khô|hút ẩm|quạt|auto|tự động)\b", lowered)
        if mode and "độ" not in lowered:
            value = {"làm lạnh": "Lạnh", "mát": "Lạnh", "lạnh": "Lạnh",
                     "hút ẩm": "Khô", "khô": "Khô", "quạt": "Quạt",
                     "tự động": "Auto", "auto": "Auto"}[mode.group(1)]
            ha_call("input_select", "select_option", {"entity_id": "input_select.dieuhoa_mode", "option": value})
            return f"Đã chuyển điều hoà sang chế độ {value}."
        temperature = re.search(r"\b(\d{2})\s*độ\b", lowered)
        if temperature:
            value = min(30, max(18, int(temperature.group(1))))
            ha_call("input_number", "set_value", {"entity_id": "input_number.dieuhoa_temp", "value": value})
            return f"Đã đặt điều hoà {value} độ."
    if ac and re.search(r"\b(tăng|nâng)\b|lạnh quá", lowered):
        ha_call("script", "turn_on", {"entity_id": "script.dieuhoa_tang_nhiet"})
        return "Đã tăng nhiệt độ điều hoà."
    if ac and re.search(r"\b(giảm|hạ)\b|nóng quá", lowered):
        ha_call("script", "turn_on", {"entity_id": "script.dieuhoa_giam_nhiet"})
        return "Đã giảm nhiệt độ điều hoà."

    if fan and re.search(r"\b(tắt|dừng|ngừng)\b.*xoay|không xoay|đứng yên", lowered):
        ha_call("input_boolean", "turn_off", {"entity_id": "input_boolean.quat_xoay"})
        return "Đã tắt quạt xoay."
    if fan and re.search(r"\b(bật|mở)\b.*xoay|cho.*quạt xoay", lowered):
        ha_call("input_boolean", "turn_on", {"entity_id": "input_boolean.quat_xoay"})
        return "Đã bật quạt xoay."
    if fan and re.search(r"\b(tăng|nâng|mạnh|to)\b", lowered):
        ha_call("script", "turn_on", {"entity_id": "script.quat_tang_tocdo"})
        return "Đã tăng tốc độ quạt."
    if fan and re.search(r"\b(giảm|hạ|nhẹ|nhỏ|yếu)\b", lowered):
        ha_call("script", "turn_on", {"entity_id": "script.quat_giam_tocdo"})
        return "Đã giảm tốc độ quạt."
    return None


def search_music(query):
    def run():
        result = http_json(f"{MUSIC_API}/search?q={urllib.parse.quote(query)}", timeout=30)
        return result["id"], result["title"]

    return cached(f"music:{query.lower()}", SEARCH_TTL, run)


def play_later(video_id, delay):
    def run():
        try:
            ha_call("media_player", "play_media", {
                "entity_id": HA_MEDIA_PLAYER,
                "media_content_id": f"{MUSIC_STREAM_BASE}/stream/{video_id}",
                "media_content_type": "music",
            })
            log(f"music started {video_id}")
        except Exception as error:
            log(f"music play failed: {error}")

    global _pending_music
    with _music_lock:
        if _pending_music is not None:
            _pending_music.cancel()
        _pending_music = threading.Timer(delay, run)
        _pending_music.daemon = True
        _pending_music.start()


def search_and_play_music(query, confirmation_delay, started):
    try:
        video_id, _ = search_music(query)
    except Exception as error:
        log(f"music search failed {query[:80]}: {type(error).__name__}: {error}")
        return
    play_later(video_id, max(0, confirmation_delay - (time.time() - started)))


def music_answer(query):
    reply = f"Đang tìm bài {query} trên YouTube."
    started = time.time()
    confirmation_delay = 3 + len(reply) / 12
    threading.Thread(
        target=search_and_play_music,
        args=(query, confirmation_delay, started),
        daemon=True,
    ).start()
    return reply


def normalize_music_query(query):
    query = re.sub(r"\s+(?:trên|ở)\s+(?:youtube|you\s*tube|yt)\s*$", "", query, flags=re.IGNORECASE)
    return query.strip().strip("\"'“”‘’")


def music_stop_answer():
    global _pending_music
    with _music_lock:
        if _pending_music is not None:
            _pending_music.cancel()
            _pending_music = None
    ha_call("media_player", "media_stop", {"entity_id": HA_MEDIA_PLAYER})
    return "Đã dừng nhạc."


def answer(messages):
    history = history_from(messages)
    text = history[-1]["content"].strip() if history and history[-1]["role"] == "user" else ""
    text = OPENCLAW_TIMESTAMP_RE.sub("", text, count=1).strip()
    if history and history[-1]["role"] == "user":
        history[-1]["content"] = text
    lowered = text.lower()
    started = time.time()
    route = "local"
    try:
        direct_answer = direct_home_answer(text)
        if direct_answer is not None:
            route, reply = "home-direct", direct_answer
        elif GOLD_RE.search(lowered):
            route = "gold"
            reply = gold_answer()
        elif MUSIC_STOP_RE.search(lowered):
            route = "music_stop"
            reply = music_stop_answer()
        elif (match := MUSIC_RE.match(lowered)) and match.group('query').strip():
            route = "music"
            reply = music_answer(normalize_music_query(match.group('query')))
        elif KNOWLEDGE_RE.search(lowered):
            route = "gemini"
            reply = ask_gemini(history)
        else:
            reply = ask_local(history)
            if not reply or ESCALATE in reply:
                route = "local->gemini"
                reply = ask_gemini(history)
    except Exception as error:
        log(f"route {route} failed: {type(error).__name__}: {error}")
        reply = "Xin lỗi, hiện tôi chưa trả lời được, bạn thử lại sau nhé."
        if route == "gold":
            reply = "Hiện chưa lấy được giá vàng từ PNJ, bạn thử lại sau nhé."
        elif route in ("music", "music_stop"):
            reply = "Hiện chưa thực hiện được yêu cầu phát nhạc, bạn thử lại sau nhé."
        elif route == "local":
            try:
                route, reply = "local!->gemini", ask_gemini(history)
            except Exception as fallback_error:
                log(f"gemini failed: {type(fallback_error).__name__}: {fallback_error}")
    log(f"{route} {time.time() - started:.2f}s | {text[:80]} -> {reply[:120]}")
    return reply


def completion(reply, model):
    return {
        "id": f"chatcmpl-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self.send_json(200, {"ok": True})
        if self.path.rstrip("/") == "/v1/models":
            return self.send_json(200, {"object": "list", "data": [{"id": "voice-router", "object": "model", "owned_by": "local"}]})
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/v1/chat/completions":
            return self.send_json(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.send_json(400, {"error": "invalid content length"})
        if not 0 < length <= 262144:
            return self.send_json(413, {"error": "request size out of range"})
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self.send_json(400, {"error": "invalid json"})
        if not isinstance(request, dict) or not isinstance(request.get("messages"), list):
            return self.send_json(400, {"error": "messages must be a list"})
        if any(not isinstance(message, dict) for message in request["messages"]):
            return self.send_json(400, {"error": "invalid message"})
        reply = answer(request.get("messages", []))
        model = request.get("model", "voice-router")
        if not request.get("stream"):
            return self.send_json(200, completion(reply, model))
        chunk = completion(reply, model)
        chunk["object"] = "chat.completion.chunk"
        chunk["choices"] = [{"index": 0, "delta": {"role": "assistant", "content": reply}, "finish_reason": "stop"}]
        body = f"data: {json.dumps(chunk, ensure_ascii=False)}\n\ndata: [DONE]\n\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def warm_local_model():
    try:
        ask_local([{"role": "user", "content": "xin chào"}])
        log(f"warmed {LOCAL_MODEL}")
    except Exception as error:
        log(f"warmup failed: {error}")


if __name__ == "__main__":
    threading.Thread(target=warm_local_model, daemon=True).start()
    servers = []
    for address in BIND_ADDRESSES:
        server = ThreadingHTTPServer((address, PORT), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        log(f"voice router on {address}:{PORT}")
    log(f"local={LOCAL_MODEL}, fallback={GEMINI_MODEL}")
    threading.Event().wait()
