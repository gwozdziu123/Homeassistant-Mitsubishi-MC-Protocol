"""Constants for the MC Protocol PLC integration."""

DOMAIN = "mcprotocol"

CONF_PLC_TYPE = "plc_type"
CONF_COMM_TYPE = "comm_type"
CONF_ADDRESS = "address"
CONF_DATA_TYPE = "data_type"
CONF_SWAP_WORDS = "swap_words"
CONF_SWAP_BYTES = "swap_bytes"
CONF_SCALE = "scale"
CONF_OFFSET = "offset"
CONF_PRECISION = "precision"
CONF_MIN = "min"
CONF_MAX = "max"
CONF_STEP = "step"
CONF_WRITE_ADDRESS = "write_address"
CONF_STATE_ADDRESS = "state_address"

# Data Types
DATA_TYPE_INT16 = "int16"
DATA_TYPE_UINT16 = "uint16"
DATA_TYPE_INT32 = "int32"
DATA_TYPE_UINT32 = "uint32"
DATA_TYPE_FLOAT32 = "float32"
DATA_TYPE_STRING = "string"

DATA_TYPES = [
    DATA_TYPE_INT16,
    DATA_TYPE_UINT16,
    DATA_TYPE_INT32,
    DATA_TYPE_UINT32,
    DATA_TYPE_FLOAT32,
    DATA_TYPE_STRING,
]

CONF_COVERS = "covers"

# Mitsubishi device families
HEX_DEVICES = {"X", "Y", "B", "W"}
BIT_DEVICES = {"X", "Y", "M", "B", "L", "F", "S", "SM", "TS", "TC", "CS", "CC"}
WORD_DEVICES = {"D", "W", "R", "ZR", "SD", "TN", "CN"}
