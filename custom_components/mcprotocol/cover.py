"""Cover platform for Mitsubishi PLC MC Protocol integration."""
import time
import logging
from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityFeature,
    ATTR_POSITION,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_ADDRESS,
    CONF_WRITE_ADDRESS,
    CONF_DATA_TYPE,
    CONF_SWAP_WORDS,
    CONF_SWAP_BYTES,
)
from .helpers import parse_address, format_address, decode_words, encode_words

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant, config: dict, async_add_entities, discovery_info=None
):
    """Set up the MC Protocol covers from YAML discovery."""
    if discovery_info is None:
        return

    plc_name = discovery_info["plc_name"]
    entities_config = discovery_info["entities"]

    coordinator = hass.data[DOMAIN][plc_name]["coordinator"]
    hub = hass.data[DOMAIN][plc_name]["hub"]

    covers = []
    for entity_config in entities_config:
        covers.append(MCProtocolCover(coordinator, hub, entity_config))

    async_add_entities(covers)


class MCProtocolCover(CoordinatorEntity, CoverEntity):
    """Representation of an MC Protocol Cover (Roller shutter/blind)."""

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

        # PLC position boundaries (e.g. 0 to 100 or 0 to 1000)
        self._position_closed = float(config["position_closed"])
        self._position_open = float(config["position_open"])

        # Optional command bit addresses for movement
        self._open_address_str = config.get("open_address")
        self._close_address_str = config.get("close_address")
        self._stop_address_str = config.get("stop_address")

        self._cmd_trigger_value = config["command_trigger_value"]
        self._cmd_reset_value = config["command_reset_value"]
        self._cmd_delay_ms = config["command_delay_ms"]

        # Parse PLC addresses
        self.read_device_type, self.read_offset, _ = parse_address(self._address_str)
        self.write_device_type, self.write_offset, _ = parse_address(
            self._write_address_str
        )

        # Word size required for position
        self._length = 1
        if self._data_type in ("int32", "uint32", "float32"):
            self._length = 2

        # Configure Entity details
        self._attr_name = self._name
        self._attr_unique_id = f"mcprotocol_{hub.name}_{self._address_str}_cover"
        self._attr_device_class = config.get("device_class")

        # Determine supported features based on parameters
        features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.SET_POSITION
        )
        if self._stop_address_str:
            features |= CoverEntityFeature.STOP

        self._attr_supported_features = features

    @property
    def current_cover_position(self) -> int | None:
        """Return current cover position (0 = Closed, 100 = Open)."""
        words = self.coordinator.get_value(
            self.read_device_type, self.read_offset, self._length
        )
        if words is None:
            return None

        if not isinstance(words, list):
            words = [words]

        plc_val = decode_words(
            words, self._data_type, self._swap_words, self._swap_bytes
        )
        if plc_val is None:
            return None

        # Scaling: Scale PLC value linearly to HA 0-100% position
        if self._position_open == self._position_closed:
            return 0

        pos = (
            (plc_val - self._position_closed)
            / (self._position_open - self._position_closed)
            * 100.0
        )
        pos_int = int(round(pos))
        return max(0, min(100, pos_int))

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed."""
        pos = self.current_cover_position
        if pos is None:
            return None
        return pos == 0

    async def async_open_cover(self, **kwargs):
        """Open the cover (Up)."""
        if self._open_address_str:
            # Trigger movement by bit command
            await self.hass.async_add_executor_job(
                self._sync_trigger_bit, self._open_address_str
            )
        else:
            # Trigger movement by writing Open Position value directly
            await self.async_set_cover_position(100)

    async def async_close_cover(self, **kwargs):
        """Close the cover (Down)."""
        if self._close_address_str:
            # Trigger movement by bit command
            await self.hass.async_add_executor_job(
                self._sync_trigger_bit, self._close_address_str
            )
        else:
            # Trigger movement by writing Closed Position value directly
            await self.async_set_cover_position(0)

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        if self._stop_address_str:
            await self.hass.async_add_executor_job(
                self._sync_trigger_bit, self._stop_address_str
            )

    async def async_set_cover_position(self, position: int, **kwargs):
        """Set the cover to a specific target position from HA UI."""
        # Scale 0-100% position back to PLC value range
        plc_val = self._position_closed + (position / 100.0) * (
            self._position_open - self._position_closed
        )

        await self.hass.async_add_executor_job(self._sync_write_position, plc_val)
        # Instantly request an update to quickly sync position in HA UI
        await self.coordinator.async_request_refresh()

    def _sync_write_position(self, plc_val: float):
        """Synchronously encode and write the position target to the PLC."""
        if not self.hub.connect():
            _LOGGER.error("PLC %s not connected for cover position write", self.hub.name)
            return

        try:
            words = encode_words(
                plc_val, self._data_type, self._swap_words, self._swap_bytes
            )
            self.hub.write_word_block(
                format_address(self.write_device_type, self.write_offset), words
            )
        except Exception as ex:
            _LOGGER.error(
                "Failed to write cover position to PLC %s: %s",
                self.hub.name,
                ex,
            )

    def _sync_trigger_bit(self, bit_addr_str: str):
        """Execute a momentary pulse on the specified PLC control bit."""
        if not self.hub.connect():
            _LOGGER.error("PLC %s not connected for cover bit command", self.hub.name)
            return

        try:
            dev_type, offset, bit_index = parse_address(bit_addr_str)
            if bit_index is not None:
                # Bit inside a word register (Read-Modify-Write under lock)
                words = self.hub.read_word_block(format_address(dev_type, offset), 1)
                if words:
                    curr_word = words[0]
                    if self._cmd_trigger_value:
                        new_word = curr_word | (1 << bit_index)
                    else:
                        new_word = curr_word & ~(1 << bit_index)
                    self.hub.write_word_block(
                        format_address(dev_type, offset), [new_word]
                    )

                    # Pulse hold duration
                    time.sleep(self._cmd_delay_ms / 1000.0)

                    # Reset bit
                    words = self.hub.read_word_block(format_address(dev_type, offset), 1)
                    if words:
                        curr_word = words[0]
                        if self._cmd_reset_value:
                            new_word = curr_word | (1 << bit_index)
                        else:
                            new_word = curr_word & ~(1 << bit_index)
                        self.hub.write_word_block(
                            format_address(dev_type, offset), [new_word]
                        )
            else:
                # Direct bit relay (X, Y, M, B)
                self.hub.write_bit_block(
                    format_address(dev_type, offset), [self._cmd_trigger_value]
                )
                time.sleep(self._cmd_delay_ms / 1000.0)
                self.hub.write_bit_block(
                    format_address(dev_type, offset), [self._cmd_reset_value]
                )
        except Exception as ex:
            _LOGGER.error(
                "Failed momentary pulse for cover command bit %s on PLC %s: %s",
                bit_addr_str,
                self.hub.name,
                ex,
            )
