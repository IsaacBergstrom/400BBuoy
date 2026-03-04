# config.py - LORA and system configuration

# ===== LORA HARDWARE PIN CONFIGURATION =====
# LILYGO LORA32 V2.1 ESP32 with SX1276/SX1278
LORA_PINS = {
    'miso': 19,    # SPI MISO
    'mosi': 27,    # SPI MOSI  
    'sck': 5,      # SPI SCK (clock)
    'cs': 18,      # Chip Select (NSS)
    'irq': 26,     # DIO0 interrupt pin
    'rst': 14,     # Reset pin
    'gpio': 35,    # GPIO pin for additional control (if needed)
}

# ===== LORA COMMUNICATION SETTINGS =====
LORA_CONFIG = {
    'frequency': 915000000,      # 915 MHz in Hz (Americas)
    'tx_power_level': 17,         # TX Power: 2-20 dBm (higher = more range, more power)
    'bandwidth': 125000,          # Bandwidth: 125 kHz (125000 Hz)
    'spreading_factor': 12,       # Spreading Factor: 6-12 (higher = more range, slower)
    'coding_rate': 5,             # Coding Rate: 5-8 (error correction)
    'preamble_length': 8,         # Preamble length
    'sync_word': 0x34,            # LoRa sync word (0x34 for public networks)
    'crc_enabled': True,          # CRC for error detection
    'implicit_header': False,     # False for explicit header
}

# ===== TRANSMITTER SETTINGS =====
TX_CONFIG = {
    'mode': 'transmitter',
    'tx_interval': 10,            # Send data every 10 seconds
    'timeout': 5000,              # TX timeout in milliseconds
    'wait_for_ack': False,        # Don't wait for ACK (since we're receiver-only receiving)
}

# ===== MESSAGE FORMAT =====
MESSAGE_CONFIG = {
    'max_payload': 251,           # Max LoRa payload
    'packet_format': 'json',      # 'json' or 'binary'
    'include_timestamp': True,    # Include timestamp in payload
    'include_counter': True,      # Include packet counter
}

# ===== DEVICE IDENTIFICATION =====
DEVICE_CONFIG = {
    'device_id': 'BUOY_001',      # Unique device identifier
    'device_type': 'buoy_transmitter',
    'version': '1.0.0',
}

# ===== DEBUG AND LOGGING =====
DEBUG = {
    'enabled': True,
    'print_packets': True,
    'print_rssi': True,           # Print signal strength
    'print_raw_bytes': False,
}

# ===== POWER MANAGEMENT =====
POWER = {
    'sleep_enabled': False,       # Enable sleep mode between transmissions
    'sleep_duration': 30,         # Sleep duration in seconds
    'adc_read_interval': 5,       # Read battery/sensor ADC every 5 transmissions
}

# ===== SENSOR/DATA CONFIGURATION =====
DATA_SENSORS = {
    'temperature': True,          # Include temperature
    'humidity': False,            # Include humidity
    'battery_voltage': True,      # Include battery voltage
    'signal_strength': True,      # Include RSSI
    'location': False,            # Include GPS coordinates (if GPS module available)
}
