# LORA ESP32 LILYGO - MicroPython Communications Setup

Complete MicroPython implementation for LORA communications on ESP32 LILYGO board with SX1276/SX1278 radio module.

## Hardware Setup

### LILYGO LORA32 V2.1 Specifications
- **MCU**: ESP32 (Dual-core 240MHz)
- **LORA Module**: SX1276/SX1278 (433/868/915 MHz)
- **Memory**: 4MB Flash, 520KB SRAM
- **Interfaces**: SPI, UART, I2C, GPIO
- **USB**: Type-C for programming and serial communication

### Pin Configuration
```
ESP32 Pin -> LORA Module (SX1276/SX1278)
GPIO 5    -> CLK (SCK)
GPIO 27   -> MOSI
GPIO 19   -> MISO
GPIO 18   -> CS (NSS)
GPIO 26   -> DIO0 (IRQ)
GPIO 14   -> RST (Reset)
GPIO 35   -> ADC (Battery voltage measurement)
```

## Software Components

### File Structure
```
├── boot.py              # Startup configuration (runs before main.py)
├── config.py            # All configuration parameters
├── lora_comm.py         # LORA radio driver (SX1276/SX1278)
├── data_handler.py      # Sensor data collection & formatting
├── main.py              # Main transmitter application
├── ampy_upload.py       # Upload utility for development
└── README.md            # This file
```

### Key Modules

**lora_comm.py** - `LORARadio` class
- Low-level SPI communication with SX1276/SX1278
- Register read/write operations
- Frequency, power, and modulation configuration
- TX/RX mode control
- RSSI (signal strength) measurement

**data_handler.py** - `DataHandler` class
- Temperature reading from ESP32 internal sensor
- Battery voltage measurement via ADC
- Humidity sensor support (placeholder for DHT/BME280)
- JSON and binary message formatting
- Packet counter and timestamp management

**main.py** - `LORATransmitter` class
- System initialization and health checks
- Periodic transmission loop
- Success/failure statistics
- Graceful shutdown

## Installation & Setup

### 1. Install Firmware

Download the latest MicroPython for ESP32:
```bash
# Visit: https://micropython.org/download/esp32/
# Or use esptool:
pip install esptool
esptool.py --chip esp32 erase_flash
esptool.py --chip esp32 --port COM3 write_flash -z 0x1000 esp32-20240105-v1.22.1.bin
```

### 2. Upload Code

**Option A: Using ampy**
```bash
pip install adafruit-ampy
python ampy_upload.py --port COM3
```

**Option B: Using WebREPL**
1. Connect ESP32 via USB
2. Open WebREPL: https://micropython.org/webrepl/
3. Click "Connect" and select serial port
4. Upload files via the file browser

**Option C: Using thonny**
1. Install Thonny IDE
2. Select MicroPython > ESP32 interpreter
3. Copy files to the device

### 3. Configuration

Edit `config.py` to customize:

**LORA Settings**
```python
LORA_CONFIG = {
    'frequency': 915000000,      # 915 MHz (Americas)
    'tx_power_level': 17,         # 2-20 dBm
    'bandwidth': 125000,          # 125/250/500 kHz
    'spreading_factor': 12,       # 6-12 (higher = longer range)
    'coding_rate': 5,             # 5-8 (error correction)
}
```

**Transmission Settings**
```python
TX_CONFIG = {
    'tx_interval': 10,            # Send every 10 seconds
    'tx_timeout': 5000,           # Timeout in ms
}
```

**Sensor Configuration**
```python
DATA_SENSORS = {
    'temperature': True,          # Internal ESP32 sensor
    'battery_voltage': True,      # ADC on GPIO35
    'humidity': False,            # Add DHT/BME280 if needed
}
```

## Running the Application

### Via Serial Console
```bash
# Using ampy
ampy --port COM3 run main.py

# Using screen (Linux)
screen /dev/ttyUSB0 115200

# Using PuTTY (Windows)
# Select Serial, set Port: COM3, Speed: 115200
```

### Via WebREPL
```bash
# In WebREPL console:
import main
```

### Auto-start on Boot
Edit `boot.py` to add:
```python
import main
app = main.LORATransmitter()
app.run()
```

## Message Formats

### JSON Format (Default)
```json
{
  "device_id": "BUOY_001",
  "device_type": "buoy_transmitter",
  "timestamp": 1234567890,
  "packet_counter": 42,
  "temperature_c": 22.50,
  "battery_v": 4.12,
  "rssi_dbm": -95
}
```

### Binary Format
```
[Device ID (4B)] [Counter (2B)] [Temp (2B)] [Battery (2B)] [RSSI (1B)] = 11 bytes
```

**Change in config.py**:
```python
MESSAGE_CONFIG = {
    'packet_format': 'binary',  # or 'json'
}
```

## Connecting a Receiver

To receive transmissions, set up a receiver with matching parameters:

```python
# receiver.py example
from lora_comm import LORARadio

radio = LORARadio()
radio.init_spi()
radio.reset()
radio.init_module()

# Set to RX continuous mode
radio.set_mode(radio.MODE_RXCONT)

while True:
    # Check for received data
    irq = radio.read_register(radio.REG_IRQ_FLAGS)
    if irq & 0x40:  # RX done
        length = radio.read_register(radio.REG_RX_NB_BYTES)
        data = radio.read_registers(radio.REG_FIFO, length)
        print(f"Received: {data}")
```

## Troubleshooting

### Module Not Responding
- Check SPI pin connections
- Verify pin numbers in `config.py`
- Check USB cable and driver installation
- Try lowering SPI speed in `lora_comm.py`

### Transmission Failures
- Increase `tx_timeout` in config
- Check TX power level (should be 2-20 dBm)
- Verify antenna connection
- Test with shorter range first

### Memory Issues
- Use binary message format instead of JSON
- Reduce debug output
- Monitor free memory: `import micropython; micropython.mem_info()`

### Serial Connection Issues
- Update CH340 drivers (Windows)
- Check correct port (COM3, /dev/ttyUSB0, etc.)
- Use 115200 baud rate
- Try different USB cable or port

## Performance Tips

1. **Range Optimization**
   - Increase `spreading_factor` (6-12, higher = longer range)
   - Reduce `bandwidth` (125 kHz offers best range)
   - Increase `tx_power_level` (up to 20 dBm)

2. **Power Consumption**
   - Enable sleep mode between transmissions
   - Use binary format instead of JSON
   - Reduce transmission frequency
   - Disable WiFi in boot.py

3. **Reliability**
   - Enable CRC in LORA_CONFIG
   - Use error correction codes (coding_rate)
   - Add packet counter to detect lost messages
   - Increase preamble length if interference occurs

## Frequency Allocation

- **433 MHz**: Asia, EU, India
- **868 MHz**: EU, Africa
- **915 MHz**: Americas, Australia, Japan

**Always check local regulations before operating!**

## References

- [MicroPython Documentation](https://micropython.org/)
- [ESP32 Pinout](https://esp32.com/pin-layout)
- [SX1276 Datasheet](https://www.semtech.com/uploads/documents/DS_SX1276-7-8-9_W_APP_V5.pdf)
- [LILYGO LORA32 Schematic](https://github.com/Xinyuan-LilyGO/TTGO-Lora32)

## License

Open-source implementation for educational and hobbyist use.

## Support

For issues or improvements, check:
1. Serial console output for error messages
2. LORA module version and pin connections
3. Antenna installation (SMA connector)
4. Nearby interference (WiFi, Bluetooth)
