"""Binary sensor platform for Mitsubishi PLC MC Protocol integration."""
import logging
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_ADDRESS
from .helpers import parse_address

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant, config: dict, async_add_entities, discovery_info=None
):
    """Set up the MC Protocol binary sensors from YAML discovery."""
    if discovery_info is None:
        return

    plc_name = discovery_info["plc_name"]
    entities_config = discovery_info["entities"]

    coordinator = hass.data[DOMAIN][plc_name]["coordinator"]
    hub = hass.data[DOMAIN][plc_name]["hub"]

    binary_sensors = []
    for entity_config in entities_config:
        binary_sensors.append(MCProtocolBinarySensor(coordinator, hub, entity_config))

    async_add_entities(binary_sensors)


class MCProtocolBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of an MC Protocol Binary Sensor."""

    def __init__(self, coordinator, hub, config: dict):
        super().__init__(coordinator)
        self.hub = hub
        self._config = config

        self._name = config["name"]
        self._address_str = config[CONF_ADDRESS]

        # Parse address to get device type, offset, and bit index
        self.device_type, self.offset, self.bit_index = parse_address(
            self._address_str
        )

        self._attr_name = self._name
        self._attr_unique_id = f"mcprotocol_{hub.name}_{self._address_str}"
        self._attr_device_class = config.get("device_class")

    @property
    def is_on(self) -> bool:
        """Return True if the binary sensor (bit) is set/ON."""
        # 1. Handle bit inside a word register (e.g. D100.5)
        if self.bit_index is not None:
            word_val = self.coordinator.get_value(self.device_type, self.offset, 1)
            if word_val is None:
                return False
            return bool((word_val >> self.bit_index) & 1)

        # 2. Handle a standard bit device (e.g. M100, X10, Y20)
        val = self.coordinator.get_value(self.device_type, self.offset)
        return bool(val)
