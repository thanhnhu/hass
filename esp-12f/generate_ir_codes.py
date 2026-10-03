import json
import base64
import struct
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
json_path = BASE_DIR / "tuya_ir_codes.json"

devices_dir = BASE_DIR / "devices"
samsung_dir = devices_dir / "samsung_ac"
fan_dir = devices_dir / "fan"

samsung_dir.mkdir(parents=True, exist_ok=True)
fan_dir.mkdir(parents=True, exist_ok=True)

with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

samsung_codes = {}
fan_codes = {}

for name, val in data.items():
    raw = base64.b64decode(val)
    pulses = [struct.unpack("<H", raw[i:i+2])[0] for i in range(0, len(raw), 2)]
    if len(pulses) > 1 and pulses[-1] > 20000:
        pulses = pulses[:-1]
    signed = [p if i % 2 == 0 else -p for i, p in enumerate(pulses)]
    
    if name.startswith("dieuhoa"):
        samsung_codes[name] = signed
    elif name.startswith("quat"):
        fan_codes[name] = signed

def write_header(out_path: Path, prefix: str, codes_map: dict):
    with open(out_path, "w", encoding="utf-8") as out:
        out.write("""#pragma once
#include <vector>
#include <string>
#ifdef ESP8266
#include <pgmspace.h>
#define IR_PROGMEM PROGMEM
#else
#define IR_PROGMEM
#endif

""")
        for name, pulses in codes_map.items():
            joined = ", ".join(str(x) for x in pulses)
            out.write(f"static const int32_t IR_{name}[] IR_PROGMEM = {{{joined}}};\n")
            out.write(f"static const size_t IR_{name}_LEN = {len(pulses)};\n\n")
        
        out.write(f"""inline const int32_t* get_{prefix}_ir_code(const std::string& name, size_t& len) {{
""")
        for name in codes_map.keys():
            out.write(f'  if (name == "{name}") {{ len = IR_{name}_LEN; return IR_{name}; }}\n')
        out.write("  len = 0; return nullptr;\n}\n")
    print(f"Generated {out_path} ({len(codes_map)} codes)")

write_header(samsung_dir / "samsung_ac_codes.h", "samsung_ac", samsung_codes)
write_header(fan_dir / "fan_codes.h", "fan", fan_codes)

# Generate master ir_dispatch.h
dispatch_path = BASE_DIR / "ir_dispatch.h"
with open(dispatch_path, "w", encoding="utf-8") as out:
    out.write("""#pragma once
#include <string>
#include <vector>
#include "samsung_ac_codes.h"
#include "fan_codes.h"

inline const int32_t* get_any_ir_code(const std::string& name, size_t& len) {
  const int32_t* p = nullptr;
  p = get_samsung_ac_ir_code(name, len);
  if (p != nullptr) return p;
  p = get_fan_ir_code(name, len);
  if (p != nullptr) return p;
  len = 0;
  return nullptr;
}

inline std::vector<int32_t> load_ir_code_vector(const int32_t* progmem_ptr, size_t len) {
  std::vector<int32_t> vec;
  if (!progmem_ptr || len == 0) return vec;
  vec.resize(len);
  for (size_t i = 0; i < len; i++) {
#ifdef ESP8266
    vec[i] = (int32_t)pgm_read_dword(progmem_ptr + i);
#else
    vec[i] = progmem_ptr[i];
#endif
  }
  return vec;
}
""")
print(f"Generated {dispatch_path}")
