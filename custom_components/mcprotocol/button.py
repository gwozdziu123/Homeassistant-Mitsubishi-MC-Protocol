"""Button platform for Mitsubishi PLC MC Protocol integration."""
import time
import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_ADDRESS
from .helpers import parse_address, format_address

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant, config: dict, async_add_entities, discovery_info=None
):
    """Set up the MC Protocol buttons from YAML discovery."""
    if discovery_info is None:
        return

    plc_name = discovery_info["plc_name"]
    entities_config = discovery_info["entities"]

    hub = hass.data[DOMAIN][plc_name]["hub"]

    buttons = []
    for entity_config in entities_config:
        buttons.append(MCProtocolButton(hub, entity_config))

    async_add_entities(buttons)


class MCProtocolButton(ButtonEntity):
    """Representation of an MC Protocol Button (Momentary Trigger)."""

    def __init__(self, hub, config: dict):
        self.hub = hub
        self._config = config

        self._name = config["name"]
        self._address_str = config[CONF_ADDRESS]
        self.trigger_value = config["trigger_value"]
        self.reset_value = config["reset_value"]
        self.delay_ms = config["delay_ms"]

        # Parse PLC Address
        self.device_type, self.offset, self.bit_index = parse_address(
            self._address_str
        )

        self._attr_name = self._name
        self._attr_unique_id = f"mcprotocol_{hub.name}_{self._address_str}_btn"

    async def async_press(self):
        """Handle button press in the HA executor thread."""
        await self.hass.async_add_executor_job(self._sync_press)

    def _sync_press(self):
        """Synchronously execute a momentary pulse on the PLC."""
        if not self.hub.connect():
            _LOGGER.error("PLC %s not connected for button press", self.hub.name)
            return

        try:
            # 1. Momentary pulse on a bit inside a word register (e.g. D100.5)
            if self.bit_index is not None:
                # Read-Modify-Write to trigger
                words = self.hub.read_word_block(
                    format_address(self.device_type, self.offset), 1
                )
                if words:
                    curr_word = words[0]
                    if self.trigger_value:
                        new_word = curr_word | (1 << self.bit_index)
                    else:
                        new_word = curr_word & ~(1 << self.bit_index)

                    self.hub.write_word_block(
                        format_address(self.device_type, self.offset), [new_word]
                    )

                    # Wait for defined delay
                    time.sleep(self.delay_ms / 1000.0)

                    # Read-Modify-Write to reset
                    words = self.hub.read_word_block(
                        format_address(self.device_type, self.offset), 1
                    )
                    if words:
                        curr_word = words[0]
                        if self.reset_value:
                            new_word = curr_word | (1 << self.bit_index)
                        else:
                            new_word = curr_word & ~(1 << self.bit_index)

                        self.hub.write_word_block(
                            format_address(self.device_type, self.offset), [new_word]
                        )
            else:
                # 2. Momentary pulse on standard bit device (e.g. M100)
                self.hub.write_bit_block(
                    format_address(self.device_type, self.offset),
                    [self.trigger_value],
                )
                time.sleep(self.delay_ms / 1000.0)
                self.hub.write_bit_block(
                    format_address(self.device_type, self.offset),
                    [self.reset_value],
                )

            _LOGGER.info(
                "Button press triggered momentary pulse on PLC %s at address %s",
                self.hub.name,
                self._address_str,
            )
        except Exception as ex:
            _LOGGER.error(
                "Failed momentary pulse on PLC %s at address %s: %s",
                self.hub.name,
                self._address_str,
                ex,
            )
