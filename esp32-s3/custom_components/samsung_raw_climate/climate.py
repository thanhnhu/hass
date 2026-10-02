"""Samsung Raw IR Climate component for ESPHome."""
import esphome.codegen as cg
from esphome.components import climate_ir
import esphome.config_validation as cv
from esphome.types import ConfigType

AUTO_LOAD = ["climate_ir"]

samsung_climate_ns = cg.esphome_ns.namespace("samsung_raw_climate")
SamsungRawClimate = samsung_climate_ns.class_("SamsungRawClimate", climate_ir.ClimateIR)

CONFIG_SCHEMA = climate_ir.climate_ir_schema(SamsungRawClimate)

async def to_code(config: ConfigType) -> None:
    await climate_ir.new_climate_ir(config)
