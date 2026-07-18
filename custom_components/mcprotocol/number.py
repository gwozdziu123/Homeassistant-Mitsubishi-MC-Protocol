"""Number platform for Mitsubishi PLC MC Protocol integration."""
import logging
from homeassistant.components.number import NumberEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_ADDRESS,
    CONF_WRITE_ADDRESS,
    CONF_DATA_TYPE,
    CONF_SWAP_WORDS,
    CONF_SWAP_BYTES,
    CONF_SCALE,
    CONF_OFFSET,
    CONF_MIN,
    CONF_MAX,
    CONF_STEP,
)
from .helpers import parse_address, format_address, decode_words, encode_words

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant, config: dict, async_add_entities, discovery_info=None
):
    """Set up the MC Protocol numbers from YAML discovery."""
    if discovery_info is None:
        return

    plc_name = discovery_info["plc_name"]
    entities_config = discovery_info["entities"]

    coordinator = hass.data[DOMAIN][plc_name]["coordinator"]
    hub = hass.data[DOMAIN][plc_name]["hub"]

    numbers = []
    for entity_config in entities_config:
        numbers.append(MCProtocolNumber(coordinator, hub, entity_config))

    async_add_entities(numbers)


class MCProtocolNumber(CoordinatorEntity, NumberEntity):
    """Representation of an MC Protocol Number."""

    def __init__(self, coordinator, hub, config: dict):
        super().__init__(coordinator)
        self.hub = hub
        self._config = config

        self._name = config["name"]
        self._address_str = config[CONF_ADDRESS]
        self._write_address_str = config.get(CONF_WRITE_ADDRESS, self._address_str)
        self._data_type = config[CONF_DATA_TYPE]
        self._swap_words = config[CONF_SWAP_WORDS]
        self._swap_bytes = config[CONF_SWAP_BYTES]
        self._scale = config[CONF_SCALE]
        self._offset = config[CONF_OFFSET]

        # Numerical input constraints
        self._attr_native_min_value = config[CONF_MIN]
        self._attr_native_max_value = config[CONF_MAX]
        self._attr_native_step = config[CONF_STEP]

        # Parse read/write PLC addresses
        self.read_device_type, self.read_offset, _ = parse_address(self._address_str)
        self.write_device_type, self.write_offset, _ = parse_address(
            self._write_address_str
        )

        # Word size required
        self._length = 1
        if self._data_type in ("int32", "uint32", "float32"):
            self._length = 2

        self._attr_name = self._name
        self._attr_unique_id = f"mcprotocol_{hub.name}_{self._address_str}"
        self._attr_native_unit_of_measurement = config.get("unit_of_measurement")

    @property
    def native_value(self) -> float | None:
        """Return the current numerical value from coordinator cache."""
        words = self.coordinator.get_value(
            self.read_device_type, self.read_offset, self._length
        )
        if words is None:
            return None

        if not isinstance(words, list):
            words = [words]

        raw_val = decode_words(
            words, self._data_type, self._swap_words, self._swap_bytes
        )
        if raw_val is None:
            return None

        # UI Value = (Raw PLC Value * Scale) + Offset
        scaled_val = raw_val * self._scale + self._offset
        return scaled_val

    async def async_set_native_value(self, value: float):
        """Set a new value to the PLC in the HA executor thread."""
        # Inverse scaling: Raw Value = (UI Value - Offset) / Scale
        raw_val = (value - self._offset) / self._scale
        await self.hass.async_add_executor_job(self._sync_write_value, raw_val)
        await self.coordinator.async_request_refresh()

    def _sync_write_value(self, raw_val: float):
        """Synchronously encode the numerical value and write to PLC."""
        if not self.hub.connect():
            _LOGGER.error("PLC %s not connected for number write", self.hub.name)
            return

        try:
            words = encode_words(
                raw_val, self._data_type, self._swap_words, self._swap_bytes
            )
            self.hub.write_word_block(
                format_address(self.write_device_type, self.write_offset), words
            )
        except Exception as ex:
            _LOGGER.error(
                "Failed to write number value to PLC %s at address %s: %s",
                self.hub.name,
                self._write_address_str,
                ex,
            )
