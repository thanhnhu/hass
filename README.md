# Home Assistant — Điều khiển hồng ngoại local (Tuya S06 & ESP32-S3 ESPHome)

Điều khiển điều hoà Samsung và quạt thông qua hồng ngoại hoàn toàn **Local trong mạng LAN**, không phụ thuộc cloud hay internet.

Gồm 2 giải pháp phần cứng:
1. **Tuya Smart IR S06 (module CB3S / BK7231N)**: Điều khiển qua LAN bằng `local_key` và custom component `tuya_ir`.
2. **ESP32-S3 (ESPHome)**: Điều khiển trực tiếp qua Native API của ESPHome, phát mã xung IR chuẩn (bao gồm cả Wake-up pulse) với module phát hồng ngoại gắn chân GPIO5.

---

## 1. Giải pháp ESP32-S3 (ESPHome)

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
- **Web Server trực tiếp**: Cấu hình bật `web_server: port: 80`, có thể truy cập thẳng `http://192.168.2.13` qua trình duyệt mà không cần Home Assistant.

### Hướng dẫn Build và Nạp (Flash / Update OTA qua WSL)

ESPHome được chạy trong môi trường WSL (Debian) với virtualenv `esphome_v2`.

#### 1. Kiểm tra cấu hình (Validate)
```bash
wsl -d Debian -e /home/admin/esphome_v2/bin/esphome config /mnt/d/Working/Projects/hass/esp32-s3/esp32-s3.yaml
```

#### 2. Biên dịch firmware (Compile)
```bash
wsl -d Debian -e /home/admin/esphome_v2/bin/esphome compile /mnt/d/Working/Projects/hass/esp32-s3/esp32-s3.yaml
```
Output firmware tạo ra tại: `esp32-s3/.esphome/build/esphome-web-5bc488/build/firmware.factory.bin` (nạp dây qua web.esphome.io hoặc esptool) và `firmware.ota.bin`.

#### 3. Nạp qua WiFi (Update OTA)
Khi ESP32-S3 đang nối cùng mạng WiFi (mặc định IP ví dụ `192.168.2.13` hoặc qua hostname `esphome-web-5bc488.local`):
```bash
wsl -d Debian -e /home/admin/esphome_v2/bin/esphome upload /mnt/d/Working/Projects/hass/esp32-s3/esp32-s3.yaml --device 192.168.2.13
```

#### 4. Xem log trực tiếp thời gian thực
```bash
wsl -d Debian -e /home/admin/esphome_v2/bin/esphome logs /mnt/d/Working/Projects/hass/esp32-s3/esp32-s3.yaml --device 192.168.2.13
```

### Tích hợp Home Assistant
1. **Thực thể Climate độc lập**: ESP32-S3 tự động expose thực thể `climate.dieu_hoa_samsung` lên Home Assistant, có đầy đủ các chế độ Cool, Dry, Fan only, Auto và dải nhiệt độ 18–30°C.
2. **Điều khiển song song với Tuya S06**: Trong file `tuya-ir/ha-package-tuya-ir.yaml`, các automation điều khiển quạt và điều hoà được cấu hình bắn đồng thời cả 2 service:
   - `tuya_ir.send_code` (Tuya S06)
   - `esphome.esphome_web_5bc488_send_ir_code` (ESP32-S3)
   (Có cờ `continue_on_error: true` giúp 1 trong 2 thiết bị mất điện thì thiết bị còn lại vẫn hoạt động bình thường).

---

## 2. Giải pháp Tuya Smart IR S06

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

cat >> /config/secrets.yaml <<EOF
tuya_ir_device_id: "xxxxxxxxxxxxxxxxxxxxxx"
tuya_ir_host: "192.168.1.x"
tuya_ir_local_key: "xxxxxxxxxxxxxxxx"
EOF
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
