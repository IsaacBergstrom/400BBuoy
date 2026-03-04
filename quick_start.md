# quick_start.md - Quick Start Guide for LORA Communications

## 5-Minute Setup

### Step 1: Flash MicroPython Firmware
```bash
# Install tools
pip install esptool

# Erase device
esptool.py --chip esp32 erase_flash

# Flash MicroPython
# Download from: https://micropython.org/download/esp32/
esptool.py --chip esp32 --port COM3 write_flash -z 0x1000 esp32-20240105-v1.22.1.bin
```

### Step 2: Upload LORA Code
```bash
# Install ampy
pip install adafruit-ampy

# Upload all files to device
ampy --port COM3 put boot.py
ampy --port COM3 put config.py
ampy --port COM3 put lora_comm.py
ampy --port COM3 put data_handler.py
ampy --port COM3 put main.py
```

### Step 3: Verify Hardware Connections
```
ESP32 LILYGO Pin -> SX1276 Module
GPIO 5    -> CLK
GPIO 27   -> MOSI
GPIO 19   -> MISO
GPIO 18   -> CS
GPIO 26   -> DIO0/IRQ
GPIO 14   -> RST
```

### Step 4: Run the Application
```bash
# Option 1: Via terminal
ampy --port COM3 run main.py

# Option 2: Via WebREPL editor
# https://micropython.org/webrepl/
# Execute: import main; main.main()
```

### Step 5: Monitor Output
```bash
# Using serial monitor
screen /dev/ttyUSB0 115200

# Expected output:
# ==================================================
# LORA Transmitter - BUOY_001
# Version: 1.0.0
# Mode: TRANSMITTER
# ==================================================
#
# [INIT] Starting initialization...
# [LORA] SPI initialized
# [LORA] Module reset complete
# [LORA] Module version: 0x12
# [LORA] Frequency set to 915.0 MHz
# [LORA] TX power set to 17 dBm
# [LORA] Modem config: BW=125kHz, SF=12, CR=5
# [LORA] Module initialized successfully!
#
# [MAIN] Starting transmission loop
# [MAIN] Interval: 10 seconds
```

## Testing Your Setup

### Test 1: Check Serial Connection
```python
# In WebREPL or serial console:
import machine
led = machine.Pin(2, machine.Pin.OUT)
led.on()   # Turn on built-in LED
led.off()  # Turn off
print("Device is responsive!")
```

### Test 2: Test SPI Bus
```python
# Check if LORA module responds
from lora_comm import LORARadio
radio = LORARadio()
radio.init_spi()
radio.reset()
version = radio.read_register(0x42)  # Read version register
print(f"Module version: 0x{version:02X}")
# Should print: 0x12 for SX1276/78
```

### Test 3: Transmit Single Packet
```python
# In console:
import main
app = main.LORATransmitter()
if app.initialize():
    app.transmit_packet()
else:
    print("Initialization failed!")
```

## Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| "Module not responding" | Check USB cable, verify pin numbers in config.py |
| "Transmission timeout" | Increase `tx_timeout` in config.py, check antenna |
| "Serial port not found" | Ensure CH340 drivers installed (Windows), try different USB port |
| "Permission denied COM3" (Windows) | Run as Administrator or use different port |
| "Cannot find module" | Verify all .py files uploaded: `ampy --port COM3 ls` |
| High current draw | Disable WiFi in boot.py, reduce TX power level |
| Weak reception range | Increase spreading_factor, check antenna installation |

## Verify Installation

```bash
# List files on device
ampy --port COM3 ls

# Should show:
# boot.py
# config.py
# data_handler.py
# lora_comm.py
# main.py
```

## Next Steps

1. **Set up a receiver** - Use receiver_example.py to receive transmissions
2. **Customize config.py** - Adjust TX interval, power, sensors
3. **Add more sensors** - DHT22, BME280, GPS, etc.
4. **Optimize for power** - Enable sleep mode, lower TX frequency
5. **Deploy** - Connect battery, run from boot.py

## Useful Commands

```python
# Monitor free memory
import micropython
micropython.mem_info()

# Restart device
import machine
machine.reset()

# Get device ID
import machine
print(machine.unique_id().hex())

# Set up REPL prompt
import micropython
micropython.alloc_emergency_exception_buf(100)

# Watch real-time execution
import gc
gc.collect()
print(f"Free memory: {gc.mem_free()} bytes")
```

## Reference Frequency Allocation

- **433 MHz**: Global (IoT friendly)
- **868 MHz**: Europe, Africa, Middle East
- **915 MHz**: North America, South America, Australia
- **923 MHz**: Asia-Pacific

Check your local laws before transmitting!

---

For detailed documentation, see [README.md](README.md)
