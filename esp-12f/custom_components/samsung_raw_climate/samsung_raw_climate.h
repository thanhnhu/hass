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
    this->swing_mode = climate::CLIMATE_SWING_OFF;
    this->fan_mode = climate::CLIMATE_FAN_AUTO;
  }

  climate::ClimateTraits traits() override {
    auto traits = climate_ir::ClimateIR::traits();
    traits.set_visual_min_temperature(18.0f);
    traits.set_visual_max_temperature(30.0f);
    traits.set_visual_temperature_step(1.0f);

    traits.set_supported_modes({
      climate::CLIMATE_MODE_OFF,
      climate::CLIMATE_MODE_COOL,
      climate::CLIMATE_MODE_DRY,
      climate::CLIMATE_MODE_FAN_ONLY,
      climate::CLIMATE_MODE_HEAT_COOL  // Auto
    });

    traits.set_supported_swing_modes({
      climate::CLIMATE_SWING_OFF,
      climate::CLIMATE_SWING_VERTICAL
    });

    traits.set_supported_fan_modes({
      climate::CLIMATE_FAN_AUTO,
      climate::CLIMATE_FAN_LOW,
      climate::CLIMATE_FAN_MEDIUM,
      climate::CLIMATE_FAN_HIGH
    });

    return traits;
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

    // Đảo cánh gió (Swing)
    if (this->swing_mode == climate::CLIMATE_SWING_VERTICAL) {
      this->transmit_code_("quat_xoay_toggle");
    }
  }

  bool on_receive(remote_base::RemoteReceiveData data) override {
    const auto &pulses = data.get_raw_data();
    if (pulses.size() < 100) return false;

    // Decode sections: tìm header mark ~3000us (dương), space ~8900us (âm)
    std::vector<std::vector<uint8_t>> sections;
    size_t i = 0;
    while (i + 1 < pulses.size()) {
      if (pulses[i] >= 2200 && pulses[i] <= 3800 && pulses[i + 1] <= -7500 && pulses[i + 1] >= -10500) {
        i += 2;
        std::vector<uint8_t> bytes;
        uint8_t cur = 0;
        uint8_t cnt = 0;
        while (i + 1 < pulses.size()) {
          int32_t sp = pulses[i + 1];
          if (sp < -2500) break; // Khoảng cách giữa các section hoặc kết thúc
          uint8_t bit = (sp < -900) ? 1 : 0;
          cur |= (bit << cnt);
          cnt++;
          if (cnt == 8) {
            bytes.push_back(cur);
            cur = 0;
            cnt = 0;
          }
          i += 2;
        }
        if (cnt > 0) bytes.push_back(cur);
        sections.push_back(bytes);
      } else {
        i++;
      }
    }

    if (sections.empty()) return false;

    // Nhận dạng Section 0 của Samsung AC
    if (sections[0].size() >= 7 && sections[0][0] == 0x02) {
      if (sections[0][1] == 0xB2) {
        // Lệnh TẮT
        ESP_LOGI("samsung_climate", "Remote IR detected: AC OFF");
        this->mode = climate::CLIMATE_MODE_OFF;
        this->publish_state();
        return true;
      } else if (sections[0][1] == 0x92 && sections.size() >= 2 && sections[1].size() >= 7) {
        // Lệnh BẬT / Đổi nhiệt độ / Mode
        uint8_t b4 = sections[1][4];
        uint8_t b5 = sections[1][5];
        int temp = (b4 >> 4) + 16;
        if (temp >= 18 && temp <= 30) {
          this->target_temperature = temp;
        }
        if (b5 == 0x21 || b5 == 0x11) {
          this->mode = climate::CLIMATE_MODE_COOL;
        } else if (b5 == 0x35) {
          this->mode = climate::CLIMATE_MODE_FAN_ONLY;
        } else if (b5 == 0x0D) {
          this->mode = climate::CLIMATE_MODE_HEAT_COOL;
        } else {
          this->mode = climate::CLIMATE_MODE_COOL;
        }
        ESP_LOGI("samsung_climate", "Remote IR detected: Mode %d, Temp %d C", (int)this->mode, temp);
        this->publish_state();
        return true;
      }
    }
    return false;
  }

  void transmit_code_(const std::string &code_name) {
    size_t len = 0;
    const int32_t *pulses = get_any_ir_code(code_name, len);
    if (pulses != nullptr && len > 0) {
      std::vector<int32_t> vec = load_ir_code_vector(pulses, len);
      auto transmit = this->transmitter_->transmit();
      transmit.get_data()->set_carrier_frequency(38000);
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

