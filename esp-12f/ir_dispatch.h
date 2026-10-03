#pragma once
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
