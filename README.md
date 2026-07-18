## 1. How to Install the Integration in Home Assistant

To run the integration on your existing Home Assistant instance:
1. Copy the entire `mcprotocol` directory into your Home Assistant custom components directory: `/config/custom_components/mcprotocol/` (the path depends on your Home Assistant installation method, e.g., Docker or HAOS).
2. Ensure Home Assistant has network access with permission to install libraries from PyPI (`pymcprotocol` will be automatically downloaded and installed during the first startup thanks to the entry in the `manifest.json` file).
3. Restart Home Assistant.

---

## 2. Example Configuration in `configuration.yaml`

Below is a complete, heavily commented configuration example demonstrating the full range of integration capabilities (reading different data types, scaling, word bits, momentary buttons, and safe switches).

Add the following block to your Home Assistant `configuration.yaml` file and adjust the IP addresses and registers accordingly:

```yaml
mcprotocol:
  - name: "Main PLC"
    host: "192.168.1.15"       # IP address of your PLC controller
    port: 1025                 # Port configured in the PLC for MC Protocol (3E Frame)
    plc_type: "Q"              # PLC type: Q, L, QnA, iQ-L, iQ-R
    comm_type: "binary"        # Communication format: binary or ascii
    scan_interval: 5           # Poll registers every 5 seconds (blocks are automatically optimized!)

    # 1. Numeric and Text Sensors (Word Registers D, W, R, ZR)
    sensors:
      - name: "Boiler Temperature"
        address: "D100"
        data_type: "int16"      # Standard signed 16-bit value
        scale: 0.1             # Scaling: PLC value * 0.1 (e.g. 452 -> 45.2 °C)
        offset: 0.0
        precision: 1           # Round to one decimal place
        unit_of_measurement: "°C"
        state_class: "measurement"
        device_class: "temperature"

      - name: "Water Flow"
        address: "D102"
        data_type: "float32"   # 32-bit floating point (occupies D102 and D103)
        swap_words: false       # Swap word order (if required)
        swap_bytes: false       # Swap bytes within each word (e.g. Little/Big Endian)
        unit_of_measurement: "L/min"

      - name: "System Pressure"
        address: "D104"
        data_type: "uint32"    # Unsigned 32-bit integer (occupies D104 and D105)
        scale: 0.001
        precision: 2
        unit_of_measurement: "bar"

      - name: "Operating Status Text"
        address: "D200"
        data_type: "string"    # Read ASCII string from registers D200-D203
        length: 4              # Length in words (4 registers = up to 8 characters)

      - name: "Active Alarm (Bit in Word)"
        address: "D100.5"      # Reads bit 5 from word D100 (value 0 or 1)

    # 2. Binary Sensors (ON/OFF - M, X, Y, B, etc.)
    binary_sensors:
      - name: "Proximity Sensor"
        address: "X0"          # Physical PLC input (hexadecimal format for Q series)
        device_class: "motion"

      - name: "Circulation Pump Contact"
        address: "M100"         # PLC internal auxiliary relay
        device_class: "running"

      - name: "PLC Fault Detected"
        address: "D110.15"     # Read bit 15 of word D110 as a binary state
        device_class: "problem"

    # 3. Control Switches (Read/Write ON/OFF States)
    switches:
      - name: "Main Valve"
        address: "Y10"          # Physical PLC output (direct control)

      - name: "Automatic Mode"
        address: "M200"         # Internal PLC bit used to enable automation

      - name: "Safe Fan Switch"
        address: "D150.2"      # Switching modifies ONLY bit 2 in register D150!
                               # Uses a safe Read-Modify-Write procedure,
                               # without affecting the other 15 bits in the register.

    # 4. Sliders / Value Input Fields (Write D, W, R Registers)
    numbers:
      - name: "Central Heating Setpoint"
        address: "D250"
        write_address: "D250"
        data_type: "int16"
        min: 20
        max: 80
        step: 1
        scale: 10.0            # Entered value 45.0 °C will be sent to the PLC as 450 (value / scale)
        unit_of_measurement: "°C"

    # 5. Momentary Buttons (START / STOP Triggers)
    buttons:
      - name: "Reset PLC Alarms"
        address: "M50"          # PLC reset bit address
        trigger_value: 1        # Value sent when pressed
        reset_value: 0          # Value sent after the delay expires
        delay_ms: 150           # Pulse duration: 150 ms

      - name: "Start Machine"
        address: "D300.0"      # Pulse on bit 0 of word D300
        trigger_value: 1
        reset_value: 0
        delay_ms: 100

    # 6. Covers and Blinds (Position Read/Write)
    covers:
      - name: "Living Room Blind"
        address: "D500"         # Register containing the current position (e.g. 0-100%)
        write_address: "D502"   # Register used to write the target position (e.g. 0-100%)
        data_type: "int16"
        position_closed: 0      # PLC value representing fully closed
        position_open: 100      # PLC value representing fully open

      - name: "Patio Blinds (Movement Trigger Buttons)"
        address: "D510"         # Read blind position (0-1000 from PLC)
        write_address: "D512"   # Write target position (0-1000 to PLC)
        position_closed: 0
        position_open: 1000     # Linear scaling 0-1000 -> 0-100% in HA
        open_address: "M300"    # Optional bit triggering upward movement
        close_address: "M301"   # Optional bit triggering downward movement
        stop_address: "M302"    # Optional bit stopping movement
        command_delay_ms: 150   # Control bit pulses last 150 ms

```

---

## 3. Global Integration Services (Home Assistant Services)

The integration exposes three powerful services in the Developer Tools, which can be used in your automations, scripts, and Node-RED flows:

### A. `mcprotocol.write_register`
Allows writing any numeric, floating-point, or string value directly to a PLC register.
*   **address**: `"D100"`
*   **value**: `150` (or a list of values such as `[12, 34, 56]`, or a string such as `"AUTO"`)
*   **data_type**: `"int16"` (or `uint16`, `int32`, `uint32`, `float32`, `string`)
*   **swap_words**: `false`
*   **swap_bytes**: `false`

### B. `mcprotocol.write_bit`
Changes the state of a bit (M, Y, B, etc.) or a bit packed into a word register.
*   **address**: `"M50"` (or `"D100.5"`)
*   **value**: `true` (ON) or `false` (OFF)

### C. `mcprotocol.remote_command`
Allows controlling the operating mode of the PLC CPU.
*   **command**: `"run"`, `"stop"`, or `"pause"`

---

## 4. Architecture and Internal Optimization

1. **Lock Guarding (Thread Safety):** Since the native `pymcprotocol` library performs synchronous communication over TCP sockets, parallel requests could corrupt the network buffer. Our `MCProtocolHub` object uses a `threading.Lock()` mechanism to serialize all read and write operations.
2. **Batch Reading (Grouping):** During startup, the integration collects all configured addresses and groups them into optimal contiguous blocks.
   *   For example, if sensors read `D100`, `D101`, `D102`, and `D105`, the integration performs **one sequential read** of 6 registers (from D100 to D105) instead of 4 separate network requests.
   *   This reduces network traffic by more than **75%** and significantly lowers the CPU load on the PLC.
3. **Error Handling:** In the event of a socket error or PLC power loss, the hub automatically marks the connection as interrupted, and the coordinator attempts to reconnect during the next polling cycle, preventing Home Assistant from hanging.

The communication implementation is based on the following integration:
https://github.com/senrust/pymcprotocol
