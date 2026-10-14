"""Switch platform for Mitsubishi PLC MC Protocol integration."""
import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_ADDRESS,
    CONF_WRITE_ADDRESS,
    CONF_STATE_ADDRESS,
)
from .helpers import parse_address, format_address

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant, config: dict, async_add_entities, discovery_info=None
):
    """Set up the MC Protocol switches from YAML discovery."""
    if discovery_info is None:
        return

    plc_name = discovery_info["plc_name"]
    entities_config = discovery_info["entities"]

    coordinator = hass.data[DOMAIN][plc_name]["coordinator"]
    hub = hass.data[DOMAIN][plc_name]["hub"]

    switches = []
    for entity_config in entities_config:
        switches.append(MCProtocolSwitch(coordinator, hub, entity_config))

    async_add_entities(switches)


class MCProtocolSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of an MC Protocol Switch."""

    def __init__(self, coordinator, hub, config: dict):
        super().__init__(coordinator)
        self.hub = hub
        self._config = config

        self._name = config["name"]
        self._address_str = config[CONF_ADDRESS]
        self._write_address_str = config.get(CONF_WRITE_ADDRESS, self._address_str)
        self._state_address_str = config.get(CONF_STATE_ADDRESS, self._address_str)

        # Parse read (state) address
        self.read_device_type, self.read_offset, self.read_bit_index = parse_address(
            self._state_address_str
        )

        # Parse write address
        self.write_device_type, self.write_offset, self.write_bit_index = (
            parse_address(self._write_address_str)
        )

        self._attr_name = self._name
        self._attr_unique_id = f"mcprotocol_{hub.name}_{self._address_str}"
        self._attr_device_class = config.get("device_class")

    @property
    def is_on(self) -> bool:
        """Return True if switch is ON."""
        # 1. State is a bit inside a word register (e.g. D100.5)
        if self.read_bit_index is not None:
            word_val = self.coordinator.get_value(
                self.read_device_type, self.read_offset, 1
            )
            if word_val is None:
                return False
            return bool((word_val >> self.read_bit_index) & 1)

        # 2. State is a standard bit device (e.g. M100)
        val = self.coordinator.get_value(self.read_device_type, self.read_offset)
        return bool(val)

    async def async_turn_on(self, **kwargs):
        """Turn switch ON."""
        await self._async_write_value(1)

    async def async_turn_off(self, **kwargs):
        """Turn switch OFF."""
        await self._async_write_value(0)

    async def _async_write_value(self, val: int):
        """Write the bit/word value to the PLC in the HA executor thread."""
        await self.hass.async_add_executor_job(self._sync_write_value, val)
        # Immediately refresh coordinator to quickly update visual state in HA UI
        await self.coordinator.async_request_refresh()

    def _sync_write_value(self, val: int):
        """Synchronously write to PLC, handling bit-in-word Read-Modify-Write."""
        if not self.hub.connect():
            _LOGGER.error("PLC %s not connected for switch write", self.hub.name)
            return

        try:
            # 1. If writing to a bit inside a word register (e.g., D100.5)
            if self.write_bit_index is not None:
                # Read current word, modify bit, write back (safe under Hub lock)
                words = self.hub.read_word_block(
                    format_address(self.write_device_type, self.write_offset), 1
                )
                if words:
                    curr_word = words[0]
                    if val:
                        new_word = curr_word | (1 << self.write_bit_index)
                    else:
                        new_word = curr_word & ~(1 << self.write_bit_index)

                    self.hub.write_word_block(
                        format_address(self.write_device_type, self.write_offset),
                        [new_word],
                    )
            else:
                # 2. Writing to standard bit device (e.g. M100)
                self.hub.write_bit_block(
                    format_address(self.write_device_type, self.write_offset),
                    [val],
                )
        except Exception as ex:
            _LOGGER.error(
                "Failed to write switch state to PLC %s at address %s: %s",
                self.hub.name,
                self._write_address_str,
                ex,
            )
