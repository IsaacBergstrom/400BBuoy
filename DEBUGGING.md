# DEBUGGING.md - Troubleshooting Guide for LORA Communications

## Common Issues and Solutions

### 1. Module Not Responding

**Symptom**: "Module not responding" or "invalid version 0x00/0xFF"

**Check**:
1. **USB Connection**
   - Is the ESP32 properly connected to your computer?
   - Try different USB port or cable
   - Check Device Manager for the COM port (Windows) or `ls /dev/tty*` (Linux)

2. **Hardware Connections**
   - Verify all SPI pins are correctly wired
   - Check for loose connections or damaged wires
   - Ensure antenna is securely attached to SMA connector

3. **Pin Configuration**
   ```python
   # In WebREPL, verify pins work:
   import machine
   
   # Test each pin
   pins_to_test = [5, 27, 19, 18, 26, 14]
   for pin_num in pins_to_test:
       try:
           pin = machine.Pin(pin_num, machine.Pin.IN)
           print(f"GPIO {pin_num}: OK")
       except Exception as e:
           print(f"GPIO {pin_num}: ERROR - {e}")
   ```

4. **SPI Speed**
   - Try lowering SPI baudrate in `lora_comm.py`:
   ```python
   self.spi = machine.SPI(..., baudrate=500000)  # Reduced from 1MHz
   ```

5. **Module Version**
   - Check what version is being read:
   ```python
   from lora_comm import LORARadio
   radio = LORARadio()
   radio.init_spi()
   version = radio.read_register(0x42)
   print(f"Version: 0x{version:02X}")
   # Should be 0x12 for SX1276/SX1278
   ```

### 2. Transmission Timeout

**Symptom**: "[TX] TX timeout" message

**Solutions**:
1. **Increase TX Timeout**
   ```python
   # In config.py
   TX_CONFIG = {
       'timeout': 10000,  # Increase from 5000ms
   }
   ```

2. **Check Antenna**
   - Ensure antenna is connected to SMA jack
   - Try a different antenna
   - Check for visible damage

3. **Verify TX Power Setting**
   ```python
   # Test transmit power
   from lora_comm import LORARadio
   radio = LORARadio()
   radio.init_spi()
   radio.reset()
   radio.init_module()
   
   # Set higher TX power
   radio.set_tx_power(20)  # Max 20 dBm
   ```

4. **Check FIFO Register**
   ```python
   # Verify FIFO is accessible
   radio.write_register(0x0E, 0x00)  # Set TX FIFO base
   value = radio.read_register(0x0E)
   print(f"FIFO base: 0x{value:02X}")
   ```

### 3. Serial Connection Issues

**Symptom**: "Permission denied" or "Cannot open port"

**Windows**:
- Run terminal as Administrator
- Install CH340 driver: https://www.wemos.cc/en/latest/Ch340.html
- Check Device Manager for the correct COM port

**Linux**:
- Give permission: `sudo usermod -a -G dialout $USER`
- Check port: `ls /dev/tty*`
- Try: `sudo ampy --port /dev/ttyUSB0 ls`

**macOS**:
- Install driver if needed
- Try: `/dev/tty.wchusbserial*` instead of `/dev/ttyUSB*`

### 4. Memory Issues

**Symptom**: "Memory error" or frequent crashes

**Check Memory**:
```python
import gc
gc.collect()
print(f"Free memory: {gc.mem_free()} bytes")

# Should have > 100KB free
```

**Optimize**:
1. Use binary message format (smaller than JSON)
2. Disable WiFi in boot.py
3. Reduce debug output in config.py
4. Remove unused sensors from DATA_SENSORS

### 5. Weak Reception/Range

**Symptom**: Messages work at close range but fail at distance

**Optimize for Range**:
```python
# In config.py, increase spreading factor (slower, more range)
LORA_CONFIG = {
    'spreading_factor': 12,      # Higher = better range (6-12)
    'tx_power_level': 20,        # Max power (2-20 dBm)
    'bandwidth': 125000,         # Smaller = better range (125/250/500)
    'coding_rate': 8,            # Better error correction
}
```

**Note**: Higher SF = slower transmission rate and more current draw

### 6. Noise/Corruption Detection

**Check CRC**:
```python
# Ensure CRC is enabled
LORA_CONFIG = {
    'crc_enabled': True,
}

# Monitor received data
LORA_CONFIG = {
    'implicit_header': False,  # Use explicit headers for better detection
}
```

### 7. Module Always in Sleep Mode

**Symptom**: Module won't exit sleep, stuck initialization

**Solution**:
```python
# Check OpMode register
from lora_comm import LORARadio
radio = LORARadio()
radio.init_spi()

opmode = radio.read_register(0x01)
print(f"OpMode: 0x{opmode:02X}")
# Bits 0-2 are mode: 00=sleep, 01=standby, 11=TX, 101=RX

# If stuck in sleep, try manual reset
radio.reset()
```

### 8. High Current Consumption

**Symptom**: Battery drains quickly, device gets warm

**Reduce Power**:
```python
# In config.py
POWER = {
    'sleep_enabled': True,       # Sleep between transmissions
    'sleep_duration': 60,        # Sleep 60 seconds
}

LORA_CONFIG = {
    'tx_power_level': 10,        # Reduce from 17 dBm
    'spreading_factor': 8,       # Higher SF uses more power
}
```

**Disable WiFi**:
```python
# In boot.py
import network
network.WLAN(network.STA_IF).active(False)
network.WLAN(network.AP_IF).active(False)
```

### 9. Receiver Not Detecting Messages

**Symptom**: Transmitter works but receiver gets nothing

**Check**:
1. Both devices use same frequency
2. Both have same bandwidth/SF/CR settings
3. Antennas are properly connected
4. Check RSSI on receiver: should show -150 to -50 dBm range
5. Try shorter distance first (< 1 meter)

**Test Receiver**:
```python
# Run receiver_example.py on second device
ampy --port COM4 run receiver_example.py
```

### 10. Debugging LORA Register Values

**Print all register values**:
```python
from lora_comm import LORARadio

radio = LORARadio()
radio.init_spi()
radio.reset()

print("=== LORA Registers ===")
for reg in range(0, 0x42):
    value = radio.read_register(reg)
    print(f"0x{reg:02X}: 0x{value:02X}")
```

**Key Registers**:
```
0x01 - OpMode
0x06-0x08 - Frequency (MSB, MID, LSB)
0x09 - PA Config (TX power)
0x0B - OCP (Over Current Protection)
0x0C - LNA (Low Noise Amplifier)
0x1D - Modem Config 1 (BW, CR, IH)
0x1E - Modem Config 2 (SF, TX, RX)
0x26 - Modem Config 3 (LDR)
0x12 - IRQ Flags
0x13 - RX Bytes
0x42 - Version (should be 0x12)
```

## Enable Detailed Debug Output

```python
# In config.py
DEBUG = {
    'enabled': True,
    'print_packets': True,
    'print_rssi': True,
    'print_raw_bytes': True,  # Include raw register dumps
}
```

## Testing Checklist

- [ ] USB connection working (can run simple Python on device)
- [ ] All SPI pins accessible
- [ ] LORA module version reads correctly (0x12)
- [ ] Can transmit single packet
- [ ] Receiver detects transmission at close range
- [ ] RSSI values reasonable (-50 to -150 dBm)
- [ ] No crashes in continuous transmission
- [ ] Battery voltage reading correct
- [ ] Temperature reading realistic

## Getting Help

If issues persist:
1. Run `test_hardware.py` to check all components
2. Reduce debug output and check serial console
3. Try different frequencies (but check local regulations!)
4. Test with reference MicroPython LORA library
5. Check GitHub issues for LILYGO LORA32 board
