"""Helper functions for address parsing, grouping, and encoding/decoding."""
import re
import struct
import logging
from .const import HEX_DEVICES, BIT_DEVICES

_LOGGER = logging.getLogger(__name__)

# Address regex: parses device type prefix (letters), numerical offset, and optional bit index
# e.g., D100, M101, X2A, D100.5, D100.F
ADDRESS_RE = re.compile(r"^([A-Za-z]+)(\d+|[0-9A-Fa-f]+)(?:\.(\d+|[0-9A-Fa-f]+))?$")


def parse_address(address_str: str) -> tuple[str, int, int | None]:
    """Parse a PLC address string.

    Returns (device_type, numeric_offset, bit_index) or raises ValueError.
    """
    match = ADDRESS_RE.match(address_str.strip().upper())
    if not match:
        raise ValueError(f"Invalid PLC address format: {address_str}")

    device_type = match.group(1).upper()
    offset_str = match.group(2)
    bit_index_str = match.group(3)

    # Check if this device uses hex addressing (X, Y, B, W)
    is_hex = device_type in HEX_DEVICES

    try:
        if is_hex:
            numeric_offset = int(offset_str, 16)
        else:
            numeric_offset = int(offset_str, 10)
    except ValueError:
        raise ValueError(
            f"Invalid address offset '{offset_str}' for device type {device_type}"
        )

    bit_index = None
    if bit_index_str is not None:
        try:
            # Bit index within a word register (e.g. 0-15 or 0-F)
            if any(c in bit_index_str.lower() for c in "abcdef"):
                bit_index = int(bit_index_str, 16)
            else:
                bit_index = int(bit_index_str, 10)
        except ValueError:
            raise ValueError(
                f"Invalid bit index '{bit_index_str}' in address {address_str}"
            )

    return device_type, numeric_offset, bit_index


def format_address(device_type: str, offset: int) -> str:
    """Format a device type and numeric offset back into a PLC address string."""
    if device_type in HEX_DEVICES:
        return f"{device_type}{hex(offset)[2:].upper()}"
    else:
        return f"{device_type}{offset}"


def group_addresses(requests: dict[int, int], max_gap: int) -> list[tuple[int, int]]:
    """Group requested offsets for a device type into optimal blocks.

    `requests` is a dict mapping `offset` (int) to its required `size` (int).
    `max_gap` is the maximum allowed gap between adjacent registers to keep
    them in the same block. Returns a list of tuples: (start_offset, size).
    """
    if not requests:
        return []

    sorted_offsets = sorted(requests.keys())
    blocks = []

    current_start = sorted_offsets[0]
    current_end = current_start + requests[current_start]

    for offset in sorted_offsets[1:]:
        size = requests[offset]
        if offset - current_end <= max_gap:
            current_end = max(current_end, offset + size)
        else:
            blocks.append((current_start, current_end - current_start))
            current_start = offset
            current_end = offset + size

    blocks.append((current_start, current_end - current_start))
    return blocks


def decode_words(
    words: list[int],
    data_type: str,
    swap_words: bool = False,
    swap_bytes: bool = False,
) -> any:
    """Decode a list of 16-bit words into the specified data type."""
    if not words or any(w is None for w in words):
        return None

    processed_words = []
    for w in words:
        if swap_bytes:
            w = ((w & 0xFF) << 8) | ((w >> 8) & 0xFF)
        processed_words.append(w)

    if data_type in ("int16", "uint16"):
        word = processed_words[0]
        if data_type == "int16":
            return struct.unpack("<h", struct.pack("<H", word))[0]
        return word

    elif data_type in ("int32", "uint32", "float32"):
        if len(processed_words) < 2:
            return None
        low, high = processed_words[0], processed_words[1]
        if swap_words:
            low, high = high, low
        combined = (high << 16) | low

        if data_type == "int32":
            return struct.unpack("<i", struct.pack("<I", combined))[0]
        elif data_type == "uint32":
            return combined
        elif data_type == "float32":
            return struct.unpack("<f", struct.pack("<I", combined))[0]

    elif data_type == "string":
        chars = []
        for w in processed_words:
            chars.append(w & 0xFF)
            chars.append((w >> 8) & 0xFF)
        try:
            # Decode ASCII/UTF-8, drop trailing nulls and spaces
            return (
                bytes(chars)
                .split(b"\x00")[0]
                .decode("utf-8", errors="ignore")
                .strip()
            )
        except Exception:
            return ""

    return None


def encode_words(
    value: any,
    data_type: str,
    swap_words: bool = False,
    swap_bytes: bool = False,
) -> list[int]:
    """Encode a value into a list of 16-bit words based on the specified data
    type.
    """
    if data_type == "int16":
        val = int(value)
        packed = struct.pack("<h", val)
        words = list(struct.unpack("<H", packed))
    elif data_type == "uint16":
        words = [int(value) & 0xFFFF]
    elif data_type in ("int32", "uint32", "float32"):
        if data_type == "int32":
            packed = struct.pack("<i", int(value))
        elif data_type == "uint32":
            packed = struct.pack("<I", int(value))
        elif data_type == "float32":
            packed = struct.pack("<f", float(value))

        combined = struct.unpack("<I", packed)[0]
        low = combined & 0xFFFF
        high = (combined >> 16) & 0xFFFF
        if swap_words:
            words = [high, low]
        else:
            words = [low, high]
    elif data_type == "string":
        val_str = str(value)
        encoded_bytes = val_str.encode("utf-8", errors="ignore")
        if len(encoded_bytes) % 2 != 0:
            encoded_bytes += b"\x00"
        words = []
        for i in range(0, len(encoded_bytes), 2):
            low = encoded_bytes[i]
            high = encoded_bytes[i + 1]
            words.append((high << 8) | low)
    else:
        raise ValueError(f"Unsupported data type for encoding: {data_type}")

    if swap_bytes:
        words = [(((w & 0xFF) << 8) | ((w >> 8) & 0xFF)) for w in words]

    return words
