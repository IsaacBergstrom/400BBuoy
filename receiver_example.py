# receiver_example.py - LORA receiver example for testing

"""
Example LORA receiver for testing transmissions.
Run this on a second ESP32 to receive messages from the transmitter.
"""

import time
import json
from lora_comm import LORARadio
from config import LORA_PINS, LORA_CONFIG

class LORAReceiver:
    """Simple LORA receiver for testing"""
    
    def __init__(self):
        """Initialize receiver"""
        self.radio = LORARadio()
        self.running = True
        self.rx_count = 0
        self.rx_success_count = 0
        
        print("=" * 50)
        print("LORA Receiver - TESTING")
        print("=" * 50)
    
    def initialize(self):
        """Initialize receiver components"""
        print("\n[INIT] Starting initialization...")
        
        if not self.radio.init_spi():
            print("[INIT] ERROR: Failed to initialize SPI")
            return False
        
        time.sleep(0.1)
        
        if not self.radio.reset():
            print("[INIT] ERROR: Failed to reset LORA module")
            return False
        
        time.sleep(0.5)
        
        if not self.radio.init_module():
            print("[INIT] ERROR: Failed to initialize LORA module")
            return False
        
        print("[INIT] All components initialized successfully!\n")
        return True
    
    def receive_packet(self):
        """Receive a single packet"""
        try:
            # Set to RX continuous mode
            self.radio.set_mode(self.radio.MODE_RXCONT)
            
            # Wait for packet (timeout after 30 seconds)
            timeout = time.time() + 30
            
            while time.time() < timeout:
                # Check IRQ flags
                irq = self.radio.read_register(self.radio.REG_IRQ_FLAGS)
                
                if irq & 0x40:  # RX done
                    # Get payload length
                    length = self.radio.read_register(self.radio.REG_RX_NB_BYTES)
                    
                    # Read FIFO
                    self.radio.write_register(self.radio.REG_FIFO_ADDR, 
                                            self.radio.read_register(self.radio.REG_FIFO_RX_ADDR))
                    data = self.radio.read_registers(self.radio.REG_FIFO, length)
                    
                    # Get RSSI
                    rssi = self.radio.get_rssi()
                    
                    # Clear IRQ
                    self.radio.write_register(self.radio.REG_IRQ_FLAGS, 0xFF)
                    
                    self.rx_success_count += 1
                    return data, rssi, length
                
                if irq & 0x20:  # RX timeout
                    self.radio.write_register(self.radio.REG_IRQ_FLAGS, 0xFF)
                    return None, None, None
                
                time.sleep(0.01)
            
            return None, None, None
            
        except Exception as e:
            print(f"[RX] ERROR: {e}")
            return None, None, None
    
    def parse_message(self, data):
        """Parse received message"""
        try:
            # Try JSON first
            msg_str = data.decode('utf-8')
            msg_obj = json.loads(msg_str)
            return 'json', msg_obj, msg_str
        except:
            # Try binary format
            if len(data) >= 11:
                try:
                    # Extract fields (see data_handler.py for format)
                    dev_hash = int.from_bytes(data[0:4], 'big')
                    counter = int.from_bytes(data[4:6], 'big')
                    temp = int.from_bytes(data[6:8], 'big', signed=True)
                    batt = int.from_bytes(data[8:10], 'big') / 1000.0
                    rssi_byte = data[10]
                    
                    return 'binary', {
                        'device_hash': dev_hash,
                        'counter': counter,
                        'temperature': temp,
                        'battery_v': batt,
                        'rssi': rssi_byte
                    }, data.hex()
                except:
                    pass
            
            return 'unknown', data, data.hex()
    
    def run(self):
        """Main receiver loop"""
        if not self.initialize():
            print("[MAIN] Initialization failed. Exiting.")
            return
        
        print("[MAIN] Starting RX listening...")
        print("[MAIN] Waiting for packets... (Ctrl+C to stop)\n")
        
        try:
            while self.running:
                print(f"[RX] Listening for packet #{self.rx_count + 1}... ", end="")
                
                data, rssi, length = self.receive_packet()
                
                if data is not None:
                    self.rx_count += 1
                    msg_type, parsed, raw = self.parse_message(data)
                    
                    print(f"SUCCESS")
                    print(f"  Payload length: {length} bytes")
                    print(f"  RSSI: {rssi} dBm")
                    print(f"  Format: {msg_type}")
                    
                    if msg_type == 'json':
                        print(f"  Data: {raw}")
                    elif msg_type == 'binary':
                        print(f"  Counter: {parsed['counter']}")
                        print(f"  Temperature: {parsed['temperature']}°C")
                        print(f"  Battery: {parsed['battery_v']:.2f}V")
                    
                    print()
                else:
                    print("timeout")
        
        except KeyboardInterrupt:
            print("\n[MAIN] Interrupted by user")
        except Exception as e:
            print(f"[MAIN] Runtime error: {e}")
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Shutdown and cleanup"""
        print("\n[SHUTDOWN] Cleaning up...")
        self.running = False
        
        try:
            self.radio.set_mode(self.radio.MODE_SLEEP)
        except:
            pass
        
        print(f"\n[SHUTDOWN] === Statistics ===")
        print(f"  Total receive attempts: {self.rx_count}")
        print(f"  Successful receptions: {self.rx_success_count}")
        if self.rx_count > 0:
            success_rate = (self.rx_success_count / self.rx_count) * 100
            print(f"  Success rate: {success_rate:.1f}%")
        print("[SHUTDOWN] Receiver ready for next session")

def main():
    """Application entry point"""
    try:
        app = LORAReceiver()
        app.run()
    except Exception as e:
        print(f"[FATAL] {e}")

if __name__ == '__main__':
    main()
