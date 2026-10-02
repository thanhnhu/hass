"""Local IR control for a Tuya universal remote (S06 / CB3S / BK7231N).

Talks to the blaster over the LAN with its local_key, so nothing leaves the network
and the Tuya cloud is never involved. Everything the integration needs lives under
/config, which means a Home Assistant backup captures it and a restore brings it
back with no host-side setup.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

DOMAIN = "tuya_ir"
CODES_FILE = "tuya_ir_codes.json"

CONF_DEVICE_ID = "device_id"
CONF_HOST = "host"
CONF_LOCAL_KEY = "local_key"
CONF_VERSION = "version"
CONF_CONTROL_TYPE = "control_type"

SERVICE_SEND = "send_code"
SERVICE_LEARN = "learn_code"
SERVICE_DELETE = "delete_code"

EVENT_LEARNED = "tuya_ir_code_learned"

# Real frames from an AC decode to a few hundred pulses; ambient IR noise is far shorter.
MIN_GOOD_PULSES = 150

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): cv.string,
                vol.Required(CONF_HOST): cv.string,
                vol.Required(CONF_LOCAL_KEY): cv.string,
                vol.Optional(CONF_VERSION, default=3.5): vol.Coerce(float),
                vol.Optional(CONF_CONTROL_TYPE, default=1): vol.In([1, 2]),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

SEND_SCHEMA = vol.Schema({vol.Required("code"): cv.string})

LEARN_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("timeout", default=15): vol.All(
            vol.Coerce(int), vol.Range(min=5, max=60)
        ),
    }
)

DELETE_SCHEMA = vol.Schema({vol.Required("name"): cv.string})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    conf = config[DOMAIN]
    codes_path = Path(hass.config.path(CODES_FILE))

    def _device():
        # Imported lazily: tinytuya touches the filesystem on import, which is not
        # allowed in the event loop.
        from tinytuya.Contrib import IRRemoteControlDevice

        device = IRRemoteControlDevice(
            conf[CONF_DEVICE_ID],
            conf[CONF_HOST],
            conf[CONF_LOCAL_KEY],
            version=conf[CONF_VERSION],
            control_type=conf[CONF_CONTROL_TYPE],
            persist=True,
        )
        return device

    def _load_codes() -> dict[str, str]:
        if not codes_path.exists():
            return {}
        return json.loads(codes_path.read_text(encoding="utf-8"))

    def _save_codes(codes: dict[str, str]) -> None:
        codes_path.write_text(
            json.dumps(codes, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _pulse_count(code: str) -> int:
        from tinytuya.Contrib import IRRemoteControlDevice

        return len(IRRemoteControlDevice.base64_to_pulses(code))

    def _send(code_b64: str) -> None:
        device = _device()
        device.set_socketTimeout(6)
        device.send_button(code_b64)

    def _learn(timeout: int) -> str | None:
        device = _device()
        device.set_socketTimeout(timeout + 5)
        result = device.receive_button(timeout=timeout)
        return result if isinstance(result, str) else None

    async def handle_send(call: ServiceCall) -> None:
        name = call.data["code"]
        codes = await hass.async_add_executor_job(_load_codes)
        if name not in codes:
            raise HomeAssistantError(
                f"Unknown IR code '{name}'. Known: {', '.join(sorted(codes)) or 'none'}"
            )
        await hass.async_add_executor_job(_send, codes[name])
        _LOGGER.debug("Sent IR code %s", name)

    async def handle_learn(call: ServiceCall) -> None:
        name = call.data["name"]
        timeout = call.data["timeout"]
        _LOGGER.info("Learning '%s' — press the remote at the blaster now", name)

        code = await hass.async_add_executor_job(_learn, timeout)
        if not code:
            raise HomeAssistantError(f"No IR code received for '{name}' within {timeout}s")

        pulses = await hass.async_add_executor_job(_pulse_count, code)
        if pulses < MIN_GOOD_PULSES:
            raise HomeAssistantError(
                f"Rejected '{name}': only {pulses} pulses, that looks like noise. "
                "Hold the remote 10-15cm from the blaster and try again."
            )

        codes = await hass.async_add_executor_job(_load_codes)
        codes[name] = code
        await hass.async_add_executor_job(_save_codes, codes)
        _LOGGER.info("Learned '%s' (%d pulses)", name, pulses)
        hass.bus.async_fire(EVENT_LEARNED, {"name": name, "pulses": pulses})

    async def handle_delete(call: ServiceCall) -> None:
        name = call.data["name"]
        codes = await hass.async_add_executor_job(_load_codes)
        if codes.pop(name, None) is None:
            raise HomeAssistantError(f"Unknown IR code '{name}'")
        await hass.async_add_executor_job(_save_codes, codes)

    hass.services.async_register(DOMAIN, SERVICE_SEND, handle_send, schema=SEND_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_LEARN, handle_learn, schema=LEARN_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE, handle_delete, schema=DELETE_SCHEMA
    )

    codes = await hass.async_add_executor_job(_load_codes)
    _LOGGER.info("tuya_ir ready with %d saved codes", len(codes))
    return True
