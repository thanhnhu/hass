# Home Assistant — Điều khiển hồng ngoại local & trợ lý giọng nói

Điều khiển điều hoà Samsung và quạt bằng hồng ngoại **local trong LAN**, cộng thêm trợ lý giọng
nói tiếng Việt (micro ESP32-S3 → Home Assistant Assist → OpenClaw).

Hạ tầng hiện tại: Home Assistant trên TV Box `192.168.2.18`; Whisper, Piper, OpenClaw và
voice-router trên Oracle (`100.92.183.123`); TV Box phát âm thanh Bluetooth và chạy music-stream.
Firmware ESPHome build trong WSL Debian (virtualenv `esphome_v2`).

| Thư mục | Phần cứng | Hostname / IP | Vai trò hiện tại |
|---|---|---|---|
| `esp-12f/` | ESP-12F (ESP8266) | `esphome-hub-ir` / `192.168.2.15` | **Hub IR đang dùng**: phát/thu IR + cảm biến HDC1080 |
| `esp32-s3-aiagent/` | ESP32-S3 + micro INMP441 | `esphome-esp32-s3` / `192.168.2.13` | **Đang chạy trên board**: wake word + micro cho Assist |
| `esp32-s3/` | ESP32-S3 + module IR | `esphome-esp32-s3` / `192.168.2.13` | Firmware IR **thử nghiệm** trên board ESP32-S3 (luân phiên với aiagent) |
| `tuya-ir/` | Tuya Smart IR S06 | theo `secrets.yaml` của HA | Phát IR qua LAN bằng `local_key` |

> `esp32-s3` và `esp32-s3-aiagent` dùng chung một board và hostname — chỉ nạp một trong hai.
> Khi board chạy firmware micro, service `esphome.esphome_esp32_s3_send_ir_code` không tồn tại;
> các automation trong `tuya-ir/ha-package-tuya-ir.yaml` vẫn chạy nhờ `continue_on_error: true`.

WiFi của mọi firmware lấy từ `secrets.yaml` (`wifi_ssid`, `wifi_password`) trong từng thư mục —
file này đã được `.gitignore`, không commit.

### Build / nạp firmware (WSL Debian)

```bash
# Thay <dir>/<file>.yaml bằng esp-12f/esp-12f.yaml, esp32-s3-aiagent/aiagent.yaml, ...
wsl -d Debian -e /home/admin/esphome_v2/bin/esphome config  /mnt/d/Working/Projects/hass/<dir>/<file>.yaml
wsl -d Debian -e /home/admin/esphome_v2/bin/esphome run     /mnt/d/Working/Projects/hass/<dir>/<file>.yaml --device <IP> --no-logs
wsl -d Debian -e /home/admin/esphome_v2/bin/esphome logs    /mnt/d/Working/Projects/hass/<dir>/<file>.yaml --device <IP>
```

`run` = validate + compile + nạp OTA. Lần đầu (firmware chưa có `ota:`) phải nạp dây
`.esphome/build/<name>/build/firmware.factory.bin` qua https://web.esphome.io.

---

## 1. Trợ lý giọng nói (`esp32-s3-aiagent/`)

```
INMP441 ──I2S──► ESP32-S3 ──ESPHome API──► HA Assist pipeline "Trợ lý tiếng Việt"
                                             ├─ STT: Whisper  (Oracle `:10300`, base-int8, vi)
                                             ├─ Agent: OpenClaw (qua Extended OpenAI Conversation)
                                             └─ TTS: Piper    (Oracle `:10200`)
```

HA pipeline hiện vẫn chọn voice `vi_VN-vais1000-medium`, còn Piper trên Oracle đang chạy
`vi_VN-25hours_single-low` (model tiếng Việt dựa trên Ryan, chất lượng thấp). Hai cấu hình này
cần được đồng bộ nếu muốn chắc chắn dùng giọng nam.

| File | Nội dung |
|---|---|
| `aiagent.yaml` | Micro I2S (WS=GPIO6, SCK=GPIO5, SD=GPIO4), Hey Jarvis, Assist và OTA |
| `compose.yaml` | Tuỳ chọn chạy Whisper + Piper tại máy đích (host network, giới hạn RAM/CPU); không phải deployment hiện tại trên Oracle |
| `compat/extended_openai_conversation/manifest.json` | Bản vá cho Extended OpenAI Conversation 2.0.2 chấp nhận `openai` 2.x của HA |

- Bật nghe: `switch.esphome_esp32_s3_nghe_lenh` (mặc định tắt, tự tắt khi mất kết nối HA).
- Board không có loa; TTS và câu xác nhận wake word phát qua `media_player.tvbox_bluetooth`.
- `vad_threshold` đã bị ESPHome bỏ, không dùng lại.

`compose.yaml` dùng `network_mode: host` và Wyoming bind `0.0.0.0:10200/10300`. Chỉ triển khai
trên mạng tin cậy và giới hạn các cổng này bằng firewall; Wyoming không tự xác thực client.
Compose dùng image tag `latest`; nên pin version/digest và cập nhật có chủ đích để tránh đổi
phiên bản ngoài dự kiến khi pull/recreate container.

Triển khai Compose tuỳ chọn trên TV Box (không cần chạy khi đang dùng các dịch vụ Oracle):

```powershell
Get-Content -Raw .\esp32-s3-aiagent\compose.yaml | ssh root@192.168.2.18 'docker compose -p aiagent -f - up -d'
```

Nếu chuyển Whisper/Piper về TV Box, cập nhật host của các integration Wyoming trong HA sang
`192.168.2.18`; nếu không, pipeline vẫn dùng dịch vụ trên Oracle.

OpenClaw bật `gateway.http.endpoints.chatCompletions.enabled`, primary `router/voice-router`,
fallback `google/gemini-3.5-flash-lite`. Trong HA thêm **Extended OpenAI Conversation**:
Base URL `http://100.92.183.123:18789/v1`,
API key = OpenClaw gateway token, model `openclaw/default`; rồi chọn agent này trong pipeline.

> Cập nhật Extended OpenAI Conversation qua HACS sẽ ghi đè manifest — chép lại file trong `compat/`
> rồi restart HA.

### Security

- `secrets.yaml` bị ignore và hiện không có file secrets nào được Git track.
- ESPHome Native API và OTA trong `aiagent.yaml` chưa cấu hình encryption/password. Chúng chỉ nên
  dùng trên LAN tin cậy; thêm API encryption và OTA password từ `secrets.yaml` trước khi mở mạng.
- Firmware IR thử nghiệm bật Web Server port 80 không có xác thực.
- Voice-router port 8787 là HTTP không xác thực; `router-local` không được router kiểm tra. Oracle
  hiện bind cả `172.17.0.1` (default Docker bridge) và `172.19.0.1` (OpenClaw bridge). Firewall
  thêm ACCEPT cho OpenClaw bridge, nhưng INPUT policy mặc định là `ACCEPT`, nên đây chưa phải
  allowlist. Cần bỏ listener `172.17.0.1` hoặc chặn nó bằng firewall; không publish port 8787 ra LAN/public.
- Music-stream port 8788 bind all interfaces và không có xác thực; giới hạn bằng firewall cho
  các client cần dùng. OpenClaw UI/API hiện chỉ bind vào địa chỉ Tailscale.

---

## 2. Hub IR ESP-12F (`esp-12f/`)

- ESP8266, phát IR ở **GPIO13**, thu IR ở **GPIO12**, cảm biến HDC1080 (I2C SDA=GPIO2, SCL=GPIO0).
- Expose `climate.esphome_hub_ir_dieu_hoa_samsung` (dùng nhiệt độ/độ ẩm HDC1080), proxy IR, và
  service `esphome.esphome_hub_ir_send_ir_code` (tham số `code`).
- `esp-12f.init.yaml`: firmware tối giản để nạp lần đầu; `esp-12f.yaml`: firmware đầy đủ.
- Web server tắt để tiết kiệm RAM ESP8266.

---

## 3. Firmware IR ESP32-S3 — thử nghiệm (`esp32-s3/`)

### Cấu trúc thư mục

```
esp32-s3/
├── custom_components/
│   └── samsung_raw_climate/         # Custom Climate platform điều khiển Samsung Raw IR
├── devices/
│   ├── samsung_ac/
│   │   └── samsung_ac_codes.h       # Mảng xung điều khiển điều hoà Samsung (18°C-30°C, các chế độ, Bật/Tắt)
│   └── fan/
│       └── fan_codes.h              # Mảng xung quạt (tăng/giảm tốc độ, xoay)
├── ir_dispatch.h                    # Bộ định tuyến tìm mã IR theo tên gọi
├── esp32-s3.yaml                    # File cấu hình ESPHome cho ESP32-S3 (RMT, Web Server, WiFi, API Service)
├── ha-package-esphome-ir.yaml       # Package Home Assistant (helpers, automation gọi service ESPHome)
├── generate_ir_codes.py             # Script trích xuất và dịch mã từ Tuya JSON sang C++ header
└── tuya_ir_codes.json               # Mã nguồn hồng ngoại gốc dạng base64
```

### Điểm kỹ thuật quan trọng của Điều hoà Samsung & Phần cứng
- **Wake-up pulse**: Điều hoà Samsung yêu cầu xung mồi đầu tiên `+468us, -17827us` để đánh thức mắt nhận trước khi nhận các block dữ liệu.
- **RMT Driver trên ESP-IDF 5.x**: ESP32-S3 dùng streaming encoder, chỉ cần đặt `rmt_symbols: 64` (không đặt quá cao tránh lỗi `out of RMT symbol memory`).
- **Logic kích tín hiệu (Chân Signal)**:
  - Cấu hình hiện tại đặt `inverted: true` (kích mức **LOW** - Active LOW) phù hợp với các module dùng transistor PNP (mã dán `2TY` / `S8550` như `transmitter v1221`).
  - Khi kích mức LOW, chân `VCC` của module nên cắm vào **3.3V** của ESP32 (thay vì 5V) để mức HIGH từ GPIO ngắt hoàn toàn transistor.
  - Nếu module dùng transistor NPN (`J3Y` / `S8050`), đổi lại `inverted: false` và cắm `VCC` vào 5V.
  - *Mẹo test nhanh:* Rút dây `DAT`, chạm vào `GND` (nếu đèn báo sáng $\rightarrow$ kích LOW) hoặc `VCC` (nếu đèn sáng $\rightarrow$ kích HIGH).
- **Web Server**: firmware này bật `web_server: port: 80` — truy cập `http://192.168.2.13` khi board đang chạy firmware IR.

### Tích hợp Home Assistant (khi nạp firmware này)
1. Expose thực thể climate "Điều Hoà Samsung" (Cool, Dry, Fan only, Auto, 18–30°C) và service
   `esphome.esphome_esp32_s3_send_ir_code`.
2. `tuya-ir/ha-package-tuya-ir.yaml` bắn song song `tuya_ir.send_code` và
   `esphome.esphome_esp32_s3_send_ir_code`, cả hai có `continue_on_error: true`.
3. `esp32-s3/ha-package-esphome-ir.yaml` là package thay thế chỉ dùng ESP32-S3 (không dùng song song với `tuya_ir.yaml`).

---

## 4. Giải pháp Tuya Smart IR S06 (`tuya-ir/`)

Sau khi lấy `local_key` một lần, mọi lệnh đi thẳng từ Home Assistant tới thiết bị qua LAN — không qua cloud Tuya.

```
Home Assistant ──► custom_components/tuya_ir ──► tinytuya ──► LAN ──► S06 ──► IR ──► điều hoà / quạt
   (container)         (trong /config)           local_key
```

## Vì sao không dùng cách khác

| Cách | Kết quả |
|---|---|
| **LocalTuya (HACS)** | ❌ Không có platform cho IR blaster (DP 201/202) |
| **tuya-cloudcutter** (flash OpenBeken) | ❌ Cần WiFi adapter hỗ trợ AP mode; card Broadcom BCM43142 (driver `wl`) và Amlogic W1 đều không có — driver `aml_w1` còn treo kernel khi tranh chấp interface |
| **Universal Infrared Open API** | ❌ Tuya đã deprecated, project trả `28841107 - data center suspended` |
| **Virtual AC device** (`a3c133f3...`) | ❌ `ip` và `local_key` rỗng — thiết bị thuần cloud, không có đường LAN |
| **Bridge HTTP chạy systemd trên host** | ⚠️ Chạy được, nhưng nằm ngoài container nên HA backup không chứa → phải cài lại thủ công |
| **Custom component trong `/config`** | ✅ Đang dùng |

## Cấu trúc Tuya S06

```
tuya-ir/
├── custom_components/tuya_ir/     # chép vào /config/custom_components/
│   ├── __init__.py                #   services: send_code, learn_code, delete_code
│   ├── manifest.json              #   HA tự cài tinytuya từ requirements
│   └── services.yaml              #   mô tả service cho UI
├── ha-package-tuya-ir.yaml        # chép vào /config/packages/tuya_ir.yaml
├── ha-dashboard-remote.yaml       # dashboard dạng remote
└── tools/
    ├── tuya-get-local-key.py      # lấy local_key qua Tuya Cloud API (chạy 1 lần)
    └── tuya-get-ir-codes.py       # thử kéo mã đã học từ cloud (API đã deprecated)
```

Trong `/config` sau khi cài:

| File | Nội dung |
|---|---|
| `custom_components/tuya_ir/` | Integration |
| `packages/tuya_ir.yaml` | Helpers, automations, scripts |
| `tuya_ir_codes.json` | Mã IR đã học |
| `secrets.yaml` | `tuya_ir_device_id`, `tuya_ir_host`, `tuya_ir_local_key` |

Tất cả nằm trong `/config` → **nằm trong mọi bản HA backup**.

## Cài đặt

### 1. Lấy `local_key`

Cần Cloud Project trên [iot.tuya.com](https://iot.tuya.com) đã link tài khoản Smart Life,
và service **IoT Core** còn hiệu lực.

```bash
python3 tools/tuya-get-local-key.py
```

Nhập `endpoint` (theo **Data Center** ở tab Overview của project), `client_id`,
`client_secret`, `device_id`. Script tự ký HMAC-SHA256 — gọi API thủ công không ký đúng
sẽ nhận `1010 token invalid`.

### 2. Tìm IP thật của thiết bị

IP mà Cloud API trả về là IP WAN, không dùng được. Quét LAN:

```bash
pip install tinytuya && python3 -m tinytuya scan
```

### 3. Cài vào Home Assistant

```bash
cp -r custom_components/tuya_ir /config/custom_components/
cp ha-package-tuya-ir.yaml /config/packages/tuya_ir.yaml
```

Thêm các giá trị sau trực tiếp vào `/config/secrets.yaml` bằng File Editor/VS Code Server.
Không đưa `local_key` vào lệnh shell, shell history, log hay chat:

```yaml
tuya_ir_device_id: "..."
tuya_ir_host: "192.168.1.x"
tuya_ir_local_key: "..."
```

Bật packages trong `/config/configuration.yaml` nếu chưa có:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Restart Home Assistant — HA tự cài `tinytuya` theo `requirements` trong `manifest.json`.

### 4. Học mã IR

**Developer Tools → Actions → `tuya_ir.learn_code`**, điền `name` rồi bấm Perform. Trong
15 giây, chĩa remote vào mắt thu (cách **10–15 cm**) và bấm nút cần học.

Integration tự loại mã nhiễu: frame thật của điều hoà giải mã ra ~230–320 xung, nhiễu môi
trường thường dưới 150 và sẽ bị từ chối kèm thông báo.

Mã mới có hiệu lực ngay và tự nằm trong bản backup kế tiếp.

### 5. Dashboard

**Settings → Dashboards → + Add dashboard → New dashboard from scratch**, mở lên → ✏️ →
**⋮** → **Raw configuration editor** → dán `ha-dashboard-remote.yaml`.

## Services

| Service | Tham số |
|---|---|
| `tuya_ir.send_code` | `code` — tên mã đã lưu |
| `tuya_ir.learn_code` | `name`, `timeout` (5–60s, mặc định 15) |
| `tuya_ir.delete_code` | `name` |

## Cách hoạt động

IR là **một chiều** — điều hoà không báo trạng thái ngược lại. Home Assistant giữ trạng
thái bằng helper:

| Helper | Ý nghĩa |
|---|---|
| `input_boolean.dieuhoa_power` | Bật/tắt |
| `input_select.dieuhoa_mode` | Lạnh / Khô / Quạt / Auto |
| `input_number.dieuhoa_temp` | 18–30 °C |
| `input_number.quat_tocdo` | Tốc độ quạt |
| `input_boolean.quat_xoay` | Quạt xoay |

Mọi nút **chỉ ghi vào helper**; automation phát hiện helper đổi rồi mới gửi mã IR. Nhờ vậy
nút bấm, dropdown và ô nhập số dùng chung một đường, không bao giờ gửi trùng, và giao diện
luôn hiển thị đúng cái đang active.

## Lưu ý quan trọng

**Mã điều hoà mang toàn bộ trạng thái.** Mỗi frame chứa cả nguồn + mode + nhiệt độ + tốc
độ quạt, không có mã riêng cho "tăng 1 độ". Vì thế phải học từng mức nhiệt (18–30 °C = 13
mã), và khi học phải **giữ nguyên mode/tốc độ quạt** trong suốt quá trình.

**Không dùng mã bật riêng.** Frame nhiệt độ đã chứa bit nguồn ON, nên automation bật máy
bằng cách gửi frame nhiệt độ hiện tại — vừa bật vừa đặt đúng độ, và không phụ thuộc một
frame tĩnh dễ lỗi thời.

**Mã cũ có thể bị từ chối.** Nếu máy kêu bíp nhưng không thực hiện lệnh, nghĩa là frame
mang trạng thái không còn khớp — học lại nút đó khi máy đang ở trạng thái thực tế.

**Trạng thái có thể lệch.** Ai đó dùng remote thật chỉnh thì HA không biết. Bấm **Đồng bộ
lại** (`script.dieuhoa_dong_bo`) để gửi lại frame tuyệt đối.

**Quạt chỉ có mã tương đối.** `quat_tang_tocdo` / `quat_giam_tocdo` là lệnh tăng/giảm một
nấc, nên `input_number.quat_tocdo` chỉ là bộ đếm tham khảo, có thể lệch thực tế.

**Cố định IP thiết bị.** Đặt DHCP reservation trên router; nếu IP đổi phải sửa
`tuya_ir_host` trong `secrets.yaml`.

## Backup & khôi phục

Không cần làm gì thêm — HA backup đã chứa integration, mã IR, secrets, helpers và
dashboard. Khôi phục: restore bản backup, restart HA. HA tự cài lại `tinytuya`.

Đừng **xoá thiết bị khỏi app Smart Life** — `local_key` sẽ đổi và mất quyền điều khiển
LAN. Gỡ app khỏi điện thoại thì vô hại.

## Khắc phục sự cố

Bật log chi tiết trong `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.tuya_ir: debug
```

| Lỗi | Nguyên nhân |
|---|---|
| `Check device key or version` | Sai `local_key` hoặc sai `version` (thiết bị này là **3.5**) |
| `Timeout Waiting for Device` | Sai IP, hoặc thiết bị mất mạng |
| `Rejected ... looks like noise` | Bấm gần hơn, chĩa thẳng vào mắt thu |
| `No IR code received` | Bấm remote trễ — chạy lại service rồi bấm ngay |
| Máy bíp nhưng không làm gì | Frame mang trạng thái cũ — học lại nút đó ở đúng trạng thái hiện tại |
