# test_hardware.py - Hardware self-test and diagnostics

"""
Hardware self-test for ESP32 LILYGO LORA board.
Run this to verify all components are working correctly.

Usage:
    ampy --port COM3 run test_hardware.py
"""

import machine
import time
from config import LORA_PINS

class HardwareTester:
    """Test ESP32 and LORA module hardware"""
    
    def __init__(self):
        """Initialize tester"""
        self.passed = 0
        self.failed = 0
        self.warnings = 0
    
    def print_header(self, title):
        """Print section header"""
        print(f"\n{'=' * 50}")
        print(f"  {title}")
        print(f"{'=' * 50}\n")
    
    def print_result(self, name, status, message=""):
        """Print test result"""
        if status == "PASS":
            symbol = "[✓]"
            self.passed += 1
        elif status == "FAIL":
            symbol = "[✗]"
            self.failed += 1
        else:  # WARNING
            symbol = "[!]"
            self.warnings += 1
        
        msg = f"{symbol} {name:30s} {status:8s}"
        if message:
            msg += f" - {message}"
        print(msg)
    
    def test_esp32(self):
        """Test ESP32 core functionality"""
        self.print_header("ESP32 Core Tests")
        
        try:
            # CPU frequency
            freq = machine.freq()
            if freq > 0:
                self.print_result("CPU Frequency", "PASS", f"{freq/1e6:.0f} MHz")
            else:
                self.print_result("CPU Frequency", "FAIL")
        except Exception as e:
            self.print_result("CPU Frequency", "FAIL", str(e))
        
        try:
            # Unique ID
            uid = machine.unique_id().hex()
            self.print_result("Unique ID", "PASS", uid[:16] + "...")
        except Exception as e:
            self.print_result("Unique ID", "FAIL", str(e))
        
        try:
            # Free memory
            import gc
            gc.collect()
            free_mem = gc.mem_free()
            total_mem = gc.mem_alloc() + free_mem
            percent = (free_mem / total_mem) * 100
            
            status = "PASS" if free_mem > 100000 else "WARNING"
            self.print_result("Free Memory", status, f"{free_mem/1024:.1f}KB ({percent:.0f}%)")
        except Exception as e:
            self.print_result("Free Memory", "FAIL", str(e))
    
    def test_pins(self):
        """Test GPIO pins"""
        self.print_header("GPIO Pin Tests")
        
        pin_tests = [
            ('SCK', LORA_PINS['sck']),
            ('MOSI', LORA_PINS['mosi']),
            ('MISO', LORA_PINS['miso']),
            ('CS', LORA_PINS['cs']),
            ('IRQ', LORA_PINS['irq']),
            ('RST', LORA_PINS['rst']),
        ]
        
        for name, pin_num in pin_tests:
            try:
                pin = machine.Pin(pin_num, machine.Pin.IN)
                value = pin.value()
                self.print_result(f"GPIO {pin_num} ({name})", "PASS", f"Value: {value}")
            except Exception as e:
                self.print_result(f"GPIO {pin_num} ({name})", "FAIL", str(e))
    
    def test_spi(self):
        """Test SPI bus"""
        self.print_header("SPI Bus Tests")
        
        try:
            spi = machine.SPI(
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
            self.print_result("SPI Initialization", "PASS", "1MHz bus")
            
            # Try to read with chip select
            cs = machine.Pin(LORA_PINS['cs'], machine.Pin.OUT, value=1)
            
            cs.off()
            spi.write(bytes([0x42]))  # Read version register
            result = spi.read(1)
            cs.on()
            
            if result:
                self.print_result("SPI Communication", "PASS")
            else:
                self.print_result("SPI Communication", "WARNING", "No data received")
        
        except Exception as e:
            self.print_result("SPI Bus", "FAIL", str(e))
    
    def test_lora_module(self):
        """Test LORA module"""
        self.print_header("LORA Module Tests")
        
        try:
            from lora_comm import LORARadio
            
            radio = LORARadio()
            
            if not radio.init_spi():
                self.print_result("SPI Init", "FAIL")
                return
            
            self.print_result("SPI Init", "PASS")
            
            if not radio.reset():
                self.print_result("Module Reset", "FAIL")
                return
            
            self.print_result("Module Reset", "PASS")
            
            time.sleep(0.2)
            
            # Read version
            version = radio.read_register(0x42)
            
            if version == 0x12:
                self.print_result("Module Version", "PASS", f"0x{version:02X} (SX127x)")
            elif version in [0x00, 0xFF]:
                self.print_result("Module Version", "FAIL", f"0x{version:02X} (No response)")
            else:
                self.print_result("Module Version", "WARNING", f"0x{version:02X} (Unknown)")
            
            # Check mode register
            opmode = radio.read_register(0x01)
            self.print_result("OpMode Register", "PASS", f"0x{opmode:02X}")
            
        except ImportError:
            self.print_result("LORA Module", "FAIL", "lora_comm module not found")
        except Exception as e:
            self.print_result("LORA Module", "FAIL", str(e))
    
    def test_adc(self):
        """Test ADC for battery monitoring"""
        self.print_header("ADC Tests")
        
        try:
            adc = machine.ADC(machine.Pin(35))
            adc.atten(machine.ADC.ATTN_11DB)
            
            # Take multiple readings
            readings = []
            for _ in range(10):
                readings.append(adc.read())
                time.sleep(0.01)
            
            avg = sum(readings) // len(readings)
            voltage = (avg / 4095.0) * 3.3 * 2
            
            self.print_result("Battery ADC", "PASS", f"{voltage:.2f}V (ADC: {avg})")
        except Exception as e:
            self.print_result("Battery ADC", "WARNING", str(e))
    
    def test_rtc(self):
        """Test RTC (Real-Time Clock)"""
        self.print_header("RTC Tests")
        
        try:
            rtc = machine.RTC()
            current_time = time.time()
            self.print_result("RTC Time", "PASS", f"{current_time} seconds since epoch")
        except Exception as e:
            self.print_result("RTC", "FAIL", str(e))
    
    def print_summary(self):
        """Print test summary"""
        self.print_header("Test Summary")
        
        total = self.passed + self.failed + self.warnings
        
        print(f"  Passed:  {self.passed}/{total}")
        print(f"  Failed:  {self.failed}/{total}")
        print(f"  Warnings: {self.warnings}/{total}\n")
        
        if self.failed == 0:
            if self.warnings == 0:
                print("  ✓ All tests passed!")
            else:
                print("  ✓ All critical tests passed (see warnings above)")
        else:
            print("  ✗ Some tests failed - check connections and configuration")
    
    def run(self):
        """Run all tests"""
        print("\n" * 2)
        print("╔" + "=" * 48 + "╗")
        print("║" + " " * 10 + "ESP32 LILYGO LORA Hardware Tester" + " " * 4 + "║")
        print("╚" + "=" * 48 + "╝")
        
        self.test_esp32()
        self.test_pins()
        self.test_spi()
        self.test_adc()
        self.test_rtc()
        self.test_lora_module()
        
        self.print_summary()

def main():
    """Application entry point"""
    try:
        tester = HardwareTester()
        tester.run()
    except Exception as e:
        print(f"\n[FATAL] {e}")

if __name__ == '__main__':
    main()
