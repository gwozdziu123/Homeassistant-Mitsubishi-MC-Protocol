"""Sensor platform for Mitsubishi PLC MC Protocol integration."""
import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_ADDRESS,
    CONF_DATA_TYPE,
    CONF_SWAP_WORDS,
    CONF_SWAP_BYTES,
    CONF_SCALE,
    CONF_OFFSET,
    CONF_PRECISION,
)
from .helpers import parse_address, decode_words

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant, config: dict, async_add_entities, discovery_info=None
):
    """Set up the MC Protocol sensors from YAML discovery."""
    if discovery_info is None:
        return

    plc_name = discovery_info["plc_name"]
    entities_config = discovery_info["entities"]

    coordinator = hass.data[DOMAIN][plc_name]["coordinator"]
    hub = hass.data[DOMAIN][plc_name]["hub"]

    sensors = []
    for entity_config in entities_config:
        sensors.append(MCProtocolSensor(coordinator, hub, entity_config))

    async_add_entities(sensors)


class MCProtocolSensor(CoordinatorEntity, SensorEntity):
    """Representation of an MC Protocol Sensor."""

    def __init__(self, coordinator, hub, config: dict):
        super().__init__(coordinator)
        self.hub = hub
        self._config = config

        self._name = config["name"]
        self._address_str = config[CONF_ADDRESS]
        self._data_type = config[CONF_DATA_TYPE]
        self._swap_words = config[CONF_SWAP_WORDS]
        self._swap_bytes = config[CONF_SWAP_BYTES]
        self._scale = config[CONF_SCALE]
        self._offset = config[CONF_OFFSET]
        self._precision = config.get(CONF_PRECISION)

        # Parse the address to understand device type, offset, and bit index
        self.device_type, self.offset, self.bit_index = parse_address(
            self._address_str
        )

        # Calculate word size required
        self._length = config.get("length", 1)
        if self._data_type in ("int32", "uint32", "float32"):
            self._length = 2

        self._attr_name = self._name
        self._attr_unique_id = f"mcprotocol_{hub.name}_{self._address_str}"
        self._attr_native_unit_of_measurement = config.get("unit_of_measurement")
        self._attr_device_class = config.get("device_class")
        self._attr_state_class = config.get("state_class")

    @property
    def native_value(self) -> any:
        """Return the value of the sensor from the coordinator's cached data."""
        # 1. Handle bit inside a word register (e.g. D100.5)
        if self.bit_index is not None:
            word_val = self.coordinator.get_value(self.device_type, self.offset, 1)
            if word_val is None:
                return None
            return (word_val >> self.bit_index) & 1

        # 2. Handle normal word registers (e.g. D100)
        words = self.coordinator.get_value(
            self.device_type, self.offset, self._length
        )
        if words is None:
            return None

        # Wrap single integer response in list if returned as standalone
        if not isinstance(words, list):
            words = [words]

        # Decode the registers using helper utility
        raw_val = decode_words(
            words, self._data_type, self._swap_words, self._swap_bytes
        )
        if raw_val is None:
            return None

        if self._data_type == "string":
            return raw_val

        # Scaling, offset and rounding for numerical states
        scaled_val = raw_val * self._scale + self._offset
        if self._precision is not None:
            scaled_val = round(scaled_val, self._precision)

        return scaled_val
