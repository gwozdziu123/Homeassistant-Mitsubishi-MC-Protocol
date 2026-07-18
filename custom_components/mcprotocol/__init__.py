"""Home Assistant custom component for Mitsubishi PLC MC Protocol communication."""
from datetime import timedelta
import logging
import threading
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_SENSORS,
    CONF_SWITCHES,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_PLC_TYPE,
    CONF_COMM_TYPE,
    CONF_ADDRESS,
    CONF_DATA_TYPE,
    CONF_SWAP_WORDS,
    CONF_SWAP_BYTES,
    CONF_SCALE,
    CONF_OFFSET,
    CONF_PRECISION,
    CONF_MIN,
    CONF_MAX,
    CONF_STEP,
    CONF_WRITE_ADDRESS,
    CONF_STATE_ADDRESS,
    DATA_TYPES,
    BIT_DEVICES,
    CONF_COVERS,
)
from .helpers import (
    parse_address,
    format_address,
    group_addresses,
    decode_words,
    encode_words,
)

_LOGGER = logging.getLogger(__name__)

# Config validation schemas
SENSOR_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ADDRESS): cv.string,
        vol.Optional(CONF_DATA_TYPE, default="int16"): vol.In(DATA_TYPES),
        vol.Optional(CONF_SWAP_WORDS, default=False): cv.boolean,
        vol.Optional(CONF_SWAP_BYTES, default=False): cv.boolean,
        vol.Optional(CONF_SCALE, default=1.0): vol.Coerce(float),
        vol.Optional(CONF_OFFSET, default=0.0): vol.Coerce(float),
        vol.Optional(CONF_PRECISION): cv.positive_int,
        vol.Optional("unit_of_measurement"): cv.string,
        vol.Optional("device_class"): cv.string,
        vol.Optional("state_class"): cv.string,
        vol.Optional("length", default=1): cv.positive_int,
    }
)

BINARY_SENSOR_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ADDRESS): cv.string,
        vol.Optional("device_class"): cv.string,
    }
)

SWITCH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ADDRESS): cv.string,
        vol.Optional(CONF_WRITE_ADDRESS): cv.string,
        vol.Optional(CONF_STATE_ADDRESS): cv.string,
        vol.Optional("device_class"): cv.string,
    }
)

NUMBER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ADDRESS): cv.string,
        vol.Optional(CONF_WRITE_ADDRESS): cv.string,
        vol.Optional(CONF_DATA_TYPE, default="int16"): vol.In(DATA_TYPES),
        vol.Optional(CONF_SWAP_WORDS, default=False): cv.boolean,
        vol.Optional(CONF_SWAP_BYTES, default=False): cv.boolean,
        vol.Optional(CONF_MIN, default=0.0): vol.Coerce(float),
        vol.Optional(CONF_MAX, default=100.0): vol.Coerce(float),
        vol.Optional(CONF_STEP, default=1.0): vol.Coerce(float),
        vol.Optional(CONF_SCALE, default=1.0): vol.Coerce(float),
        vol.Optional(CONF_OFFSET, default=0.0): vol.Coerce(float),
        vol.Optional("unit_of_measurement"): cv.string,
    }
)

BUTTON_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ADDRESS): cv.string,
        vol.Optional("trigger_value", default=1): cv.positive_int,
        vol.Optional("reset_value", default=0): cv.positive_int,
        vol.Optional("delay_ms", default=100): cv.positive_int,
    }
)

COVER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ADDRESS): cv.string,  # Position feedback address (e.g. D100)
        vol.Optional(CONF_WRITE_ADDRESS): cv.string,  # Position target address (e.g. D100)
        vol.Optional(CONF_DATA_TYPE, default="int16"): vol.In(DATA_TYPES),
        vol.Optional(CONF_SWAP_WORDS, default=False): cv.boolean,
        vol.Optional(CONF_SWAP_BYTES, default=False): cv.boolean,
        vol.Optional("position_closed", default=0.0): vol.Coerce(float),
        vol.Optional("position_open", default=100.0): vol.Coerce(float),
        # Optional command bits to trigger movement up/down/stop
        vol.Optional("open_address"): cv.string,
        vol.Optional("close_address"): cv.string,
        vol.Optional("stop_address"): cv.string,
        vol.Optional("command_trigger_value", default=1): cv.positive_int,
        vol.Optional("command_reset_value", default=0): cv.positive_int,
        vol.Optional("command_delay_ms", default=100): cv.positive_int,
        vol.Optional("device_class"): cv.string,
    }
)

PLC_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PORT, default=1025): cv.port,
        vol.Optional(CONF_NAME, default="PLC"): cv.string,
        vol.Optional(CONF_PLC_TYPE, default="Q"): vol.In(["Q", "L", "QnA", "iQ-L", "iQ-R"]),
        vol.Optional(CONF_COMM_TYPE, default="binary"): vol.In(["binary", "ascii"]),
        vol.Optional(CONF_SCAN_INTERVAL, default=5): cv.positive_int,
        vol.Optional(CONF_SENSORS): vol.All(cv.ensure_list, [SENSOR_SCHEMA]),
        vol.Optional("binary_sensors"): vol.All(cv.ensure_list, [BINARY_SENSOR_SCHEMA]),
        vol.Optional(CONF_SWITCHES): vol.All(cv.ensure_list, [SWITCH_SCHEMA]),
        vol.Optional("numbers"): vol.All(cv.ensure_list, [NUMBER_SCHEMA]),
        vol.Optional("buttons"): vol.All(cv.ensure_list, [BUTTON_SCHEMA]),
        vol.Optional(CONF_COVERS): vol.All(cv.ensure_list, [COVER_SCHEMA]),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(cv.ensure_list, [PLC_CONFIG_SCHEMA])
    },
    extra=vol.ALLOW_EXTRA,
)


class MCProtocolHub:
    """Thread-safe connection wrapper for pymcprotocol Type3E."""

    def __init__(self, name: str, host: str, port: int, plc_type: str, comm_type: str):
        self.name = name
        self.host = host
        self.port = port
        self.plc_type = plc_type
        self.comm_type = comm_type

        self.plc = None
        self._lock = threading.Lock()
        self._connected = False

    def connect(self) -> bool:
        """Establish a connection to the PLC. Must run in executor thread."""
        with self._lock:
            if self._connected and self.plc:
                return True

            import pymcprotocol

            _LOGGER.info(
                "Connecting to PLC %s at %s:%s...",
                self.name,
                self.host,
                self.port,
            )
            try:
                self.plc = pymcprotocol.Type3E(plctype=self.plc_type)
                self.plc.setaccessopt(commtype=self.comm_type)
                self.plc.connect(self.host, self.port)
                self._connected = True
                _LOGGER.info("Successfully connected to PLC %s", self.name)
                return True
            except Exception as ex:
                _LOGGER.error(
                    "Connection failed to PLC %s at %s:%s: %s",
                    self.name,
                    self.host,
                    self.port,
                    ex,
                )
                self._connected = False
                self.plc = None
                return False

    def close(self):
        """Close connection to the PLC."""
        with self._lock:
            if self.plc:
                try:
                    self.plc.close()
                except Exception as ex:
                    _LOGGER.warning("Error closing PLC %s connection: %s", self.name, ex)
                self.plc = None
            self._connected = False

    def read_word_block(self, start_address: str, size: int) -> list[int]:
        """Read a block of word registers. Thread-safe."""
        with self._lock:
            if not self._connected or not self.plc:
                raise ConnectionError(f"PLC {self.name} is not connected")
            try:
                return self.plc.batchread_wordunits(headdevice=start_address, readsize=size)
            except Exception as ex:
                self._connected = False
                raise ex

    def read_bit_block(self, start_address: str, size: int) -> list[int]:
        """Read a block of bit relays. Thread-safe."""
        with self._lock:
            if not self._connected or not self.plc:
                raise ConnectionError(f"PLC {self.name} is not connected")
            try:
                return self.plc.batchread_bitunits(headdevice=start_address, readsize=size)
            except Exception as ex:
                self._connected = False
                raise ex

    def write_word_block(self, start_address: str, values: list[int]):
        """Write a block of word registers. Thread-safe."""
        with self._lock:
            if not self._connected or not self.plc:
                raise ConnectionError(f"PLC {self.name} is not connected")
            try:
                self.plc.batchwrite_wordunits(headdevice=start_address, values=values)
            except Exception as ex:
                self._connected = False
                raise ex

    def write_bit_block(self, start_address: str, values: list[int]):
        """Write a block of bit relays. Thread-safe."""
        with self._lock:
            if not self._connected or not self.plc:
                raise ConnectionError(f"PLC {self.name} is not connected")
            try:
                self.plc.batchwrite_bitunits(headdevice=start_address, values=values)
            except Exception as ex:
                self._connected = False
                raise ex

    def run_remote_command(self, cmd: str):
        """Execute a remote management command (RUN, STOP, PAUSE). Thread-safe."""
        with self._lock:
            if not self._connected or not self.plc:
                raise ConnectionError(f"PLC {self.name} is not connected")
            try:
                if cmd == "run":
                    self.plc.remote_run()
                elif cmd == "stop":
                    self.plc.remote_stop()
                elif cmd == "pause":
                    self.plc.remote_pause()
                else:
                    raise ValueError(f"Unknown remote command: {cmd}")
            except Exception as ex:
                self._connected = False
                raise ex


class MCProtocolCoordinator(DataUpdateCoordinator):
    """Coordinator that fetches all PLC data using optimized batch reads."""

    def __init__(
        self,
        hass: HomeAssistant,
        hub: MCProtocolHub,
        scan_interval: int,
        bit_requests: dict[str, dict[int, int]],
        word_requests: dict[str, dict[int, int]],
    ):
        self.hub = hub
        self.bit_requests = bit_requests
        self.word_requests = word_requests
        self.data_cache = {}

        # Precompute the optimal batch read blocks once
        self.bit_blocks = {}
        for dev_type, reqs in self.bit_requests.items():
            self.bit_blocks[dev_type] = group_addresses(reqs, max_gap=64)

        self.word_blocks = {}
        for dev_type, reqs in self.word_requests.items():
            self.word_blocks[dev_type] = group_addresses(reqs, max_gap=16)

        super().__init__(
            hass,
            _LOGGER,
            name=f"mcprotocol_{hub.name}",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self):
        """Fetch all configured registers in the HA executor threads."""
        return await self.hass.async_add_executor_job(self._sync_update_data)

    def _sync_update_data(self) -> dict[tuple[str, int], int]:
        """Perform sequential batch reads on the PLC in a thread-safe manner."""
        if not self.hub.connect():
            raise UpdateFailed(f"Failed to connect to PLC {self.hub.name}")

        new_data = {}

        # 1. Read grouped word blocks
        for dev_type, blocks in self.word_blocks.items():
            for start_offset, size in blocks:
                addr_str = format_address(dev_type, start_offset)
                try:
                    vals = self.hub.read_word_block(addr_str, size)
                    for i, val in enumerate(vals):
                        new_data[(dev_type, start_offset + i)] = val
                except Exception as ex:
                    _LOGGER.error(
                        "Error reading word block %s (size %d) from PLC %s: %s",
                        addr_str,
                        size,
                        self.hub.name,
                        ex,
                    )
                    raise UpdateFailed(
                        f"Communication error with PLC {self.hub.name}: {ex}"
                    )

        # 2. Read grouped bit blocks
        for dev_type, blocks in self.bit_blocks.items():
            for start_offset, size in blocks:
                addr_str = format_address(dev_type, start_offset)
                try:
                    vals = self.hub.read_bit_block(addr_str, size)
                    for i, val in enumerate(vals):
                        new_data[(dev_type, start_offset + i)] = val
                except Exception as ex:
                    _LOGGER.error(
                        "Error reading bit block %s (size %d) from PLC %s: %s",
                        addr_str,
                        size,
                        self.hub.name,
                        ex,
                    )
                    raise UpdateFailed(
                        f"Communication error with PLC {self.hub.name}: {ex}"
                    )

        self.data_cache = new_data
        return new_data

    def get_value(self, device_type: str, offset: int, size: int = 1) -> any:
        """Get the cached value(s) for the given device and offset."""
        if device_type in BIT_DEVICES:
            return self.data_cache.get((device_type, offset))
        else:
            if size == 1:
                return self.data_cache.get((device_type, offset))
            else:
                return [
                    self.data_cache.get((device_type, offset + i))
                    for i in range(size)
                ]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the MC Protocol integration from YAML configuration."""
    if DOMAIN not in config:
        return True

    hass.data.setdefault(DOMAIN, {})

    # Process each configured PLC connection
    for plc_config in config[DOMAIN]:
        plc_name = plc_config[CONF_NAME]
        host = plc_config[CONF_HOST]
        port = plc_config[CONF_PORT]
        plc_type = plc_config[CONF_PLC_TYPE]
        comm_type = plc_config[CONF_COMM_TYPE]
        scan_interval = plc_config[CONF_SCAN_INTERVAL]

        # Initialize thread-safe Hub
        hub = MCProtocolHub(plc_name, host, port, plc_type, comm_type)

        # Track what registers we need to read to optimize batch reading
        bit_requests = {}  # {device_type: {offset: 1}}
        word_requests = {}  # {device_type: {offset: max_size}}

        def register_read(addr_str: str, data_type: str = None, length: int = 1):
            """Parse and register address for coordinator polling."""
            try:
                dev_type, offset, _ = parse_address(addr_str)
            except ValueError as ex:
                _LOGGER.error("Failed to parse config address '%s': %s", addr_str, ex)
                return

            if dev_type in BIT_DEVICES:
                bit_requests.setdefault(dev_type, {})
                bit_requests[dev_type][offset] = 1
            else:
                size = length
                if data_type in ("int32", "uint32", "float32"):
                    size = 2
                word_requests.setdefault(dev_type, {})
                current_size = word_requests[dev_type].get(offset, 0)
                word_requests[dev_type][offset] = max(current_size, size)

        # 1. Register Sensors
        sensors_conf = plc_config.get(CONF_SENSORS, [])
        for conf in sensors_conf:
            register_read(conf[CONF_ADDRESS], conf[CONF_DATA_TYPE], conf.get("length", 1))

        # 2. Register Binary Sensors
        binary_sensors_conf = plc_config.get("binary_sensors", [])
        for conf in binary_sensors_conf:
            register_read(conf[CONF_ADDRESS])

        # 3. Register Switches (read state addresses)
        switches_conf = plc_config.get(CONF_SWITCHES, [])
        for conf in switches_conf:
            state_addr = conf.get(CONF_STATE_ADDRESS, conf[CONF_ADDRESS])
            register_read(state_addr)

        # 4. Register Numbers
        numbers_conf = plc_config.get("numbers", [])
        for conf in numbers_conf:
            register_read(conf[CONF_ADDRESS], conf[CONF_DATA_TYPE])

        # 5. Register Covers (read position addresses)
        covers_conf = plc_config.get(CONF_COVERS, [])
        for conf in covers_conf:
            register_read(conf[CONF_ADDRESS], conf[CONF_DATA_TYPE])

        # Create the data coordinator
        coordinator = MCProtocolCoordinator(
            hass, hub, scan_interval, bit_requests, word_requests
        )

        # Start initial polling in HA executor
        await coordinator.async_refresh()

        hass.data[DOMAIN][plc_name] = {
            "hub": hub,
            "coordinator": coordinator,
        }

        # Dispatch platforms
        if sensors_conf:
            hass.async_create_task(
                async_load_platform(
                    hass,
                    "sensor",
                    DOMAIN,
                    {"plc_name": plc_name, "entities": sensors_conf},
                    config,
                )
            )
        if binary_sensors_conf:
            hass.async_create_task(
                async_load_platform(
                    hass,
                    "binary_sensor",
                    DOMAIN,
                    {"plc_name": plc_name, "entities": binary_sensors_conf},
                    config,
                )
            )
        if switches_conf:
            hass.async_create_task(
                async_load_platform(
                    hass,
                    "switch",
                    DOMAIN,
                    {"plc_name": plc_name, "entities": switches_conf},
                    config,
                )
            )
        if numbers_conf:
            hass.async_create_task(
                async_load_platform(
                    hass,
                    "number",
                    DOMAIN,
                    {"plc_name": plc_name, "entities": numbers_conf},
                    config,
                )
            )
        buttons_conf = plc_config.get("buttons", [])
        if buttons_conf:
            hass.async_create_task(
                async_load_platform(
                    hass,
                    "button",
                    DOMAIN,
                    {"plc_name": plc_name, "entities": buttons_conf},
                    config,
                )
            )
        if covers_conf:
            hass.async_create_task(
                async_load_platform(
                    hass,
                    "cover",
                    DOMAIN,
                    {"plc_name": plc_name, "entities": covers_conf},
                    config,
                )
            )

    # Register custom Home Assistant services
    setup_services(hass)

    return True


def setup_services(hass: HomeAssistant):
    """Register custom PLC services inside Home Assistant."""

    def get_hub(plc_name: str | None) -> MCProtocolHub | None:
        """Find the requested PLC hub."""
        plcs = hass.data.get(DOMAIN, {})
        if not plcs:
            _LOGGER.error("No PLCs configured for services")
            return None
        if not plc_name:
            # Default to the first configured PLC
            return list(plcs.values())[0]["hub"]
        if plc_name in plcs:
            return plcs[plc_name]["hub"]
        _LOGGER.error("PLC '%s' not found", plc_name)
        return None

    def handle_write_register(call: ServiceCall):
        """Write raw values to PLC registers."""
        plc_name = call.data.get("plc_name")
        address = call.data.get("address")
        value = call.data.get("value")
        data_type = call.data.get("data_type", "int16")
        swap_words = call.data.get("swap_words", False)
        swap_bytes = call.data.get("swap_bytes", False)

        hub = get_hub(plc_name)
        if not hub:
            return

        def _write():
            if not hub.connect():
                return
            try:
                dev_type, offset, _ = parse_address(address)
                # If value is string or already a list of ints, encode appropriately
                if isinstance(value, list):
                    words = [int(v) & 0xFFFF for v in value]
                elif data_type == "string" or not isinstance(value, (int, float)):
                    words = encode_words(value, "string", swap_words, swap_bytes)
                else:
                    words = encode_words(value, data_type, swap_words, swap_bytes)

                hub.write_word_block(format_address(dev_type, offset), words)
                _LOGGER.info(
                    "Service write_register: wrote %s to %s on PLC %s",
                    words,
                    address,
                    hub.name,
                )
            except Exception as ex:
                _LOGGER.error(
                    "Service write_register error on PLC %s for address %s: %s",
                    hub.name,
                    address,
                    ex,
                )

        hass.add_job(_write)

    def handle_write_bit(call: ServiceCall):
        """Write a state to a PLC bit."""
        plc_name = call.data.get("plc_name")
        address = call.data.get("address")
        value = 1 if call.data.get("value") else 0

        hub = get_hub(plc_name)
        if not hub:
            return

        def _write():
            if not hub.connect():
                return
            try:
                dev_type, offset, bit_index = parse_address(address)
                if bit_index is not None:
                    # Write bit in word register (read-modify-write under lock)
                    words = hub.read_word_block(format_address(dev_type, offset), 1)
                    if words:
                        curr = words[0]
                        if value:
                            new_word = curr | (1 << bit_index)
                        else:
                            new_word = curr & ~(1 << bit_index)
                        hub.write_word_block(format_address(dev_type, offset), [new_word])
                else:
                    # Write directly to bit relay
                    hub.write_bit_block(format_address(dev_type, offset), [value])

                _LOGGER.info(
                    "Service write_bit: wrote %d to %s on PLC %s",
                    value,
                    address,
                    hub.name,
                )
            except Exception as ex:
                _LOGGER.error(
                    "Service write_bit error on PLC %s for address %s: %s",
                    hub.name,
                    address,
                    ex,
                )

        hass.add_job(_write)

    def handle_remote_command(call: ServiceCall):
        """Execute a remote management command (RUN/STOP/PAUSE)."""
        plc_name = call.data.get("plc_name")
        command = call.data.get("command").lower()

        hub = get_hub(plc_name)
        if not hub:
            return

        def _cmd():
            if not hub.connect():
                return
            try:
                hub.run_remote_command(command)
                _LOGGER.info(
                    "Service remote_command: executed '%s' on PLC %s",
                    command,
                    hub.name,
                )
            except Exception as ex:
                _LOGGER.error(
                    "Service remote_command '%s' failed on PLC %s: %s",
                    command,
                    hub.name,
                    ex,
                )

        hass.add_job(_cmd)

    # Register services with HA
    hass.services.async_register(DOMAIN, "write_register", handle_write_register)
    hass.services.async_register(DOMAIN, "write_bit", handle_write_bit)
    hass.services.async_register(DOMAIN, "remote_command", handle_remote_command)
