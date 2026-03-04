# data_handler.py - Data formatting and sensor reading

import time
import json
import machine
from config import MESSAGE_CONFIG, DEVICE_CONFIG, DATA_SENSORS, DEBUG

class DataHandler:
    """Handle sensor data collection and message formatting"""
    
    def __init__(self):
        """Initialize sensor ADCs and data structures"""
        self.packet_counter = 0
        self.last_adc_read = time.time()
        self.temperature = None
        self.humidity = None
        self.battery_voltage = None
        self.signal_strength = None
        
        # Initialize ADC for battery reading if available
        try:
            self.adc_battery = machine.ADC(machine.Pin(35))  # GPIO35 for battery voltage
            self.adc_battery.atten(machine.ADC.ATTN_11DB)  # Full range
        except Exception as e:
            print(f"[DATA] Battery ADC not available: {e}")
            self.adc_battery = None
    
    def read_temperature(self):
        """Read temperature from internal sensor or external module"""
        try:
            # ESP32 has an internal temperature sensor
            import esp32
            temp_raw = esp32.raw_temperature()
            # Formula: temp_c = (temp_raw - 32) / 1.8
            self.temperature = (temp_raw - 32) / 1.8
            return self.temperature
        except Exception as e:
            if DEBUG['enabled']:
                print(f"[DATA] Temperature read error: {e}")
            return None
    
    def read_battery_voltage(self):
        """Read battery voltage from ADC"""
        try:
            if self.adc_battery is None:
                return None
            
            # Read ADC multiple times and average
            readings = []
            for _ in range(10):
                readings.append(self.adc_battery.read())
            
            adc_value = sum(readings) // len(readings)
            # Convert to voltage (assuming 3.3V reference and voltage divider)
            # Adjust these values based on your actual circuit
            voltage = (adc_value / 4095.0) * 3.3 * 2  # *2 if voltage divider is 1:1
            self.battery_voltage = voltage
            return self.battery_voltage
        except Exception as e:
            if DEBUG['enabled']:
                print(f"[DATA] Battery voltage read error: {e}")
            return None
    
    def read_humidity(self):
        """Read humidity from external sensor (if available)"""
        # This would need an external sensor like DHT22, BME280, etc.
        # Placeholder for future implementation
        return None
    
    def format_json_message(self, rssi=None):
        """Format sensor data as JSON"""
        try:
            data = {
                'device_id': DEVICE_CONFIG['device_id'],
                'device_type': DEVICE_CONFIG['device_type'],
                'timestamp': int(time.time()),
                'packet_counter': self.packet_counter,
            }
            
            # Add sensor data if enabled
            if DATA_SENSORS['temperature']:
                self.read_temperature()
                if self.temperature is not None:
                    data['temperature_c'] = round(self.temperature, 2)
            
            if DATA_SENSORS['humidity']:
                self.read_humidity()
                if self.humidity is not None:
                    data['humidity_pct'] = round(self.humidity, 1)
            
            if DATA_SENSORS['battery_voltage']:
                self.read_battery_voltage()
                if self.battery_voltage is not None:
                    data['battery_v'] = round(self.battery_voltage, 2)
            
            if DATA_SENSORS['signal_strength'] and rssi is not None:
                data['rssi_dbm'] = rssi
            
            return json.dumps(data)
        except Exception as e:
            print(f"[DATA] JSON format error: {e}")
            return None
    
    def format_binary_message(self, rssi=None):
        """Format sensor data as compact binary"""
        try:
            # Binary format: [device_id(4)] [counter(2)] [temp(2)] [battery(2)] [rssi(1)]
            # Total: 11 bytes minimum
            msg = b''
            
            # Device ID (4 bytes, truncated hash)
            dev_hash = hash(DEVICE_CONFIG['device_id']) & 0xFFFFFFFF
            msg += dev_hash.to_bytes(4, 'big')
            
            # Packet counter (2 bytes)
            msg += (self.packet_counter & 0xFFFF).to_bytes(2, 'big')
            
            # Temperature (2 bytes, signed int: -50 to 100°C)
            if self.temperature is not None:
                temp_int = max(-50, min(100, int(self.temperature)))
                msg += (temp_int & 0xFFFF).to_bytes(2, 'big', signed=True)
            else:
                msg += (0).to_bytes(2, 'big', signed=True)
            
            # Battery voltage (2 bytes, 0-5V as uint16)
            if self.battery_voltage is not None:
                batt_int = int(self.battery_voltage * 1000) & 0xFFFF
                msg += batt_int.to_bytes(2, 'big')
            else:
                msg += (0).to_bytes(2, 'big')
            
            # RSSI (1 byte, -164 to -20 dBm mapped to 0-144)
            if rssi is not None:
                rssi_byte = max(0, min(144, int(rssi + 164)))
                msg += rssi_byte.to_bytes(1, 'big')
            else:
                msg += (0).to_bytes(1, 'big')
            
            return msg
        except Exception as e:
            print(f"[DATA] Binary format error: {e}")
            return None
    
    def get_message(self, rssi=None):
        """Get formatted message based on config"""
        self.packet_counter += 1
        
        if MESSAGE_CONFIG['packet_format'] == 'json':
            return self.format_json_message(rssi)
        elif MESSAGE_CONFIG['packet_format'] == 'binary':
            return self.format_binary_message(rssi)
        else:
            return None
    
    def print_status(self, rssi=None):
        """Print current sensor status"""
        print("\n[DATA] === Sensor Status ===")
        print(f"  Packet Counter: {self.packet_counter}")
        print(f"  Device ID: {DEVICE_CONFIG['device_id']}")
        
        if DATA_SENSORS['temperature']:
            temp = self.read_temperature()
            print(f"  Temperature: {temp:.2f}°C" if temp else "  Temperature: N/A")
        
        if DATA_SENSORS['battery_voltage']:
            batt = self.read_battery_voltage()
            print(f"  Battery: {batt:.2f}V" if batt else "  Battery: N/A")
        
        if rssi is not None:
            print(f"  RSSI: {rssi} dBm")
        
        print()
