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
