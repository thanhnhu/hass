#pragma once

#include "esphome/components/climate_ir/climate_ir.h"
#include "ir_dispatch.h"

namespace esphome {
namespace samsung_raw_climate {

class SamsungRawClimate : public climate_ir::ClimateIR {
 public:
  SamsungRawClimate()
      : climate_ir::ClimateIR(
            18.0f,  // min_temperature
            30.0f,  // max_temperature
            1.0f,   // step
            true,   // supports_dry
            true    // supports_fan_only
        ) {
    this->supports_cool_ = true;
    this->supports_heat_ = false;
  }

  void setup() override {
    climate_ir::ClimateIR::setup();
    if (std::isnan(this->target_temperature) || this->target_temperature < 18.0f || this->target_temperature > 30.0f) {
      this->target_temperature = 25.0f;
    }
  }

 protected:
  void transmit_state() override {
    if (this->mode == climate::CLIMATE_MODE_OFF) {
      this->transmit_code_("dieuhoa_tat");
      return;
    }

    if (this->mode == climate::CLIMATE_MODE_COOL) {
      int temp = static_cast<int>(this->target_temperature);
      if (temp < 18) temp = 18;
      if (temp > 30) temp = 30;
      std::string code = "dieuhoa_" + std::to_string(temp) + "c";
      this->transmit_code_(code);
    } else if (this->mode == climate::CLIMATE_MODE_DRY) {
      this->transmit_code_("dieuhoa_mode_kho");
    } else if (this->mode == climate::CLIMATE_MODE_FAN_ONLY) {
      this->transmit_code_("dieuhoa_mode_quat");
    } else if (this->mode == climate::CLIMATE_MODE_HEAT_COOL) {
      this->transmit_code_("dieuhoa_mode_auto");
    }
  }

  void transmit_code_(const std::string &code_name) {
    size_t len = 0;
    const int32_t *pulses = get_any_ir_code(code_name, len);
    if (pulses != nullptr && len > 0) {
      auto transmit = this->transmitter_->transmit();
      transmit.get_data()->set_carrier_frequency(38000);
      std::vector<int32_t> vec(pulses, pulses + len);
      transmit.get_data()->set_data(vec);
      transmit.perform();
      ESP_LOGI("samsung_climate", "Transmitted IR code '%s' (%d pulses)", code_name.c_str(), (int)len);
    } else {
      ESP_LOGW("samsung_climate", "Unknown IR code: '%s'", code_name.c_str());
    }
  }
};

}  // namespace samsung_raw_climate
}  // namespace esphome
