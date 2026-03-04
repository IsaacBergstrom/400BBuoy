# lora_comm.py - LORA communication module for SX1276/SX1278

import machine
import time
import struct
from config import LORA_PINS, LORA_CONFIG

class LORARadio:
    """LORA radio driver for ESP32 LILYGO with SX1276/SX1278"""
    
    # SX1276/SX1278 Register definitions
    REG_FIFO = 0x00
    REG_OPMODE = 0x01
    REG_FREQ_MSB = 0x06
    REG_FREQ_MID = 0x07
    REG_FREQ_LSB = 0x08
    REG_PA_CONFIG = 0x09
    REG_OCP = 0x0B
    REG_LNA = 0x0C
    REG_FIFO_ADDR = 0x0D
    REG_FIFO_TX_ADDR = 0x0E
    REG_FIFO_RX_ADDR = 0x0F
    REG_IRQ_FLAGS = 0x12
    REG_RX_NB_BYTES = 0x13
    REG_MODEM_CONFIG1 = 0x1D
    REG_MODEM_CONFIG2 = 0x1E
    REG_MODEM_CONFIG3 = 0x26
    REG_PREAMBLE_MSB = 0x20
    REG_PREAMBLE_LSB = 0x21
    REG_PAYLOAD_LENGTH = 0x22
    REG_SYNC_WORD = 0x39
    REG_DIO_MAPPING1 = 0x40
    REG_VERSION = 0x42
    
    # Operation modes
    MODE_SLEEP = 0x00
    MODE_STANDBY = 0x01
    MODE_TX = 0x03
    MODE_RXCONT = 0x05
    MODE_RXSINGLE = 0x06
    
    # LORA mode flag
    LORA_MODE = 0x80
    
    def __init__(self):
        """Initialize LORA radio"""
        self.spi = None
        self.cs = None
        self.rst = None
        self.irq = None
        self.tx_done = False
        self.rx_done = False
        self.packet_counter = 0
        
    def init_spi(self):
        """Initialize SPI bus"""
        try:
            self.spi = machine.SPI(
                1,
                baudrate=1000000,
                polarity=0,
                phase=0,
                bits=8,
                firstbit=machine.SPI.MSB,
                sck=machine.Pin(LORA_PINS['sck']),
                mosi=machine.Pin(LORA_PINS['mosi']),
                miso=machine.Pin(LORA_PINS['miso'])
            )
            self.cs = machine.Pin(LORA_PINS['cs'], machine.Pin.OUT, value=1)
            self.rst = machine.Pin(LORA_PINS['rst'], machine.Pin.OUT, value=1)
            self.irq = machine.Pin(LORA_PINS['irq'], machine.Pin.IN)
            print("[LORA] SPI initialized")
            return True
        except Exception as e:
            print(f"[LORA] SPI init error: {e}")
            return False
    
    def reset(self):
        """Reset the LORA module"""
        try:
            self.rst.off()
            time.sleep(0.01)
            self.rst.on()
            time.sleep(0.1)
            print("[LORA] Module reset complete")
            return True
        except Exception as e:
            print(f"[LORA] Reset error: {e}")
            return False
    
    def read_register(self, reg):
        """Read a register from the LORA module"""
        try:
            self.cs.off()
            self.spi.write(bytes([reg & 0x7F]))
            result = self.spi.read(1)
            self.cs.on()
            return result[0] if result else 0
        except Exception as e:
            print(f"[LORA] Register read error: {e}")
            self.cs.on()
            return 0
    
    def write_register(self, reg, value):
        """Write to a register in the LORA module"""
        try:
            self.cs.off()
            self.spi.write(bytes([reg | 0x80, value]))
            self.cs.on()
            return True
        except Exception as e:
            print(f"[LORA] Register write error: {e}")
            self.cs.on()
            return False
    
    def read_registers(self, reg, length):
        """Read multiple registers"""
        try:
            self.cs.off()
            self.spi.write(bytes([reg & 0x7F]))
            result = self.spi.read(length)
            self.cs.on()
            return result
        except Exception as e:
            print(f"[LORA] Register read error: {e}")
            self.cs.on()
            return b''
    
    def write_registers(self, reg, data):
        """Write multiple registers"""
        try:
            self.cs.off()
            self.spi.write(bytes([reg | 0x80]))
            self.spi.write(data)
            self.cs.on()
            return True
        except Exception as e:
            print(f"[LORA] Register write error: {e}")
            self.cs.on()
            return False
    
    def init_module(self):
        """Initialize LORA module with configuration"""
        try:
            # Check module version
            version = self.read_register(self.REG_VERSION)
            print(f"[LORA] Module version: 0x{version:02X}")
            
            if version == 0x00 or version == 0xFF:
                print("[LORA] ERROR: Module not responding (invalid version)")
                return False
            
            # Set to sleep mode
            self.set_mode(self.MODE_SLEEP)
            time.sleep(0.01)
            
            # Enable LORA mode
            opmode = self.read_register(self.REG_OPMODE)
            self.write_register(self.REG_OPMODE, opmode | self.LORA_MODE)
            time.sleep(0.01)
            
            # Set frequency
            self.set_frequency(LORA_CONFIG['frequency'])
            
            # Set TX power
            self.set_tx_power(LORA_CONFIG['tx_power_level'])
            
            # Set modem configuration
            self.set_modem_config()
            
            # Set preamble
            preamble = LORA_CONFIG['preamble_length']
            self.write_register(self.REG_PREAMBLE_MSB, preamble >> 8)
            self.write_register(self.REG_PREAMBLE_LSB, preamble & 0xFF)
            
            # Set sync word
            self.write_register(self.REG_SYNC_WORD, LORA_CONFIG['sync_word'])
            
            # Enable CRC
            if LORA_CONFIG['crc_enabled']:
                modem2 = self.read_register(self.REG_MODEM_CONFIG2)
                self.write_register(self.REG_MODEM_CONFIG2, modem2 | 0x04)
            
            # Set to standby mode
            self.set_mode(self.MODE_STANDBY)
            time.sleep(0.01)
            
            print("[LORA] Module initialized successfully")
            return True
            
        except Exception as e:
            print(f"[LORA] Init error: {e}")
            return False
    
    def set_frequency(self, freq):
        """Set LORA frequency"""
        try:
            freq_int = int(freq / 61.035)  # Convert Hz to register value
            self.write_register(self.REG_FREQ_MSB, (freq_int >> 16) & 0xFF)
            self.write_register(self.REG_FREQ_MID, (freq_int >> 8) & 0xFF)
            self.write_register(self.REG_FREQ_LSB, freq_int & 0xFF)
            print(f"[LORA] Frequency set to {freq/1e6:.1f} MHz")
            return True
        except Exception as e:
            print(f"[LORA] Frequency error: {e}")
            return False
    
    def set_tx_power(self, power):
        """Set TX power level (2-20 dBm)"""
        try:
            power = max(2, min(20, power))  # Clamp to 2-20 dBm
            pa_config = 0x80 | (power - 2)  # PA_BOOST enabled
            self.write_register(self.REG_PA_CONFIG, pa_config)
            print(f"[LORA] TX power set to {power} dBm")
            return True
        except Exception as e:
            print(f"[LORA] TX power error: {e}")
            return False
    
    def set_modem_config(self):
        """Set LORA modem configuration (bandwidth, SF, CR)"""
        try:
            bw = LORA_CONFIG['bandwidth']
            sf = LORA_CONFIG['spreading_factor']
            cr = LORA_CONFIG['coding_rate']
            
            # Map bandwidth to register value
            bw_map = {
                125000: 0x00,  # 125 kHz
                250000: 0x10,  # 250 kHz
                500000: 0x20,  # 500 kHz
            }
            bw_val = bw_map.get(bw, 0x00)
            
            # Modem Config 1: Bandwidth, Coding Rate, Implicit Header
            modem1 = bw_val | ((cr - 5) << 1) | (0 if not LORA_CONFIG['implicit_header'] else 1)
            self.write_register(self.REG_MODEM_CONFIG1, modem1)
            
            # Modem Config 2: Spreading Factor, TX continuous mode, RX single/continuous
            modem2 = ((sf & 0x0F) << 4) | 0x04  # SF, CRC enabled
            self.write_register(self.REG_MODEM_CONFIG2, modem2)
            
            # Modem Config 3: LowDataRateOptimize
            modem3 = 0x08 if sf >= 11 else 0x00
            self.write_register(self.REG_MODEM_CONFIG3, modem3)
            
            print(f"[LORA] Modem config: BW={bw/1000:.0f}kHz, SF={sf}, CR={cr}")
            return True
        except Exception as e:
            print(f"[LORA] Modem config error: {e}")
            return False
    
    def set_mode(self, mode):
        """Set operation mode"""
        try:
            opmode = self.read_register(self.REG_OPMODE)
            opmode = (opmode & 0xF8) | mode
            self.write_register(self.REG_OPMODE, opmode)
            time.sleep(0.01)
            return True
        except Exception as e:
            print(f"[LORA] Mode set error: {e}")
            return False
    
    def transmit(self, data):
        """Transmit data over LORA"""
        try:
            if isinstance(data, str):
                data = data.encode('utf-8')
            
            # Set to standby mode
            self.set_mode(self.MODE_STANDBY)
            time.sleep(0.01)
            
            # Set FIFO pointers
            self.write_register(self.REG_FIFO_ADDR, 0x00)  # TX FIFO base address
            
            # Write payload
            self.cs.off()
            self.spi.write(bytes([self.REG_FIFO | 0x80]))
            self.spi.write(data)
            self.cs.on()
            
            # Set payload length
            self.write_register(self.REG_PAYLOAD_LENGTH, len(data))
            
            # Clear interrupt flags
            self.write_register(self.REG_IRQ_FLAGS, 0xFF)
            
            # Set to TX mode
            self.set_mode(self.MODE_TX)
            
            # Wait for TX complete
            timeout = time.time() + (LORA_CONFIG['tx_timeout'] / 1000.0)
            while time.time() < timeout:
                irq = self.read_register(self.REG_IRQ_FLAGS)
                if irq & 0x08:  # TX done flag
                    self.write_register(self.REG_IRQ_FLAGS, 0xFF)
                    self.set_mode(self.MODE_STANDBY)
                    return True
                time.sleep(0.001)
            
            print("[LORA] TX timeout")
            self.set_mode(self.MODE_STANDBY)
            return False
            
        except Exception as e:
            print(f"[LORA] TX error: {e}")
            self.set_mode(self.MODE_STANDBY)
            return False
    
    def get_rssi(self):
        """Get RSSI (Received Signal Strength Indicator)"""
        try:
            rssi_raw = self.read_register(0x1B)  # RegRssiValue
            rssi = -164 + rssi_raw
            return rssi
        except Exception as e:
            print(f"[LORA] RSSI error: {e}")
            return None
