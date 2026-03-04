# main.py - Main application for LORA transmitter on ESP32 LILYGO

import time
import machine
from lora_comm import LORARadio
from data_handler import DataHandler
from config import TX_CONFIG, DEVICE_CONFIG, DEBUG

class LORATransmitter:
    """Main LORA transmitter application"""
    
    def __init__(self):
        """Initialize transmitter components"""
        self.radio = LORARadio()
        self.data = DataHandler()
        self.running = True
        self.tx_count = 0
        self.tx_success_count = 0
        self.last_tx_time = time.time()
        
        print("=" * 50)
        print(f"LORA Transmitter - {DEVICE_CONFIG['device_id']}")
        print(f"Version: {DEVICE_CONFIG['version']}")
        print(f"Mode: {TX_CONFIG['mode'].upper()}")
        print("=" * 50)
    
    def initialize(self):
        """Initialize all components"""
        print("\n[INIT] Starting initialization...")
        
        # Initialize SPI
        if not self.radio.init_spi():
            print("[INIT] ERROR: Failed to initialize SPI")
            return False
        
        time.sleep(0.1)
        
        # Reset LORA module
        if not self.radio.reset():
            print("[INIT] ERROR: Failed to reset LORA module")
            return False
        
        time.sleep(0.5)
        
        # Initialize LORA module
        if not self.radio.init_module():
            print("[INIT] ERROR: Failed to initialize LORA module")
            return False
        
        print("[INIT] All components initialized successfully!\n")
        return True
    
    def transmit_packet(self):
        """Transmit a single packet"""
        try:
            # Get RSSI before transmission
            rssi = self.radio.get_rssi()
            
            # Format message
            message = self.data.get_message(rssi)
            if message is None:
                print("[TX] ERROR: Failed to format message")
                return False
            
            # Display message info
            if isinstance(message, bytes):
                msg_type = "BINARY"
                msg_size = len(message)
            else:
                msg_type = "JSON"
                msg_size = len(message.encode('utf-8'))
            
            if DEBUG['enabled'] and DEBUG['print_packets']:
                print(f"\n[TX] Transmitting packet #{self.tx_count}")
                print(f"  Type: {msg_type}")
                print(f"  Size: {msg_size} bytes")
                if isinstance(message, str):
                    print(f"  Data: {message}")
            
            # Transmit
            start_time = time.time()
            if self.radio.transmit(message):
                elapsed = time.time() - start_time
                self.tx_success_count += 1
                print(f"[TX] SUCCESS - Packet #{self.tx_count} transmitted in {elapsed*1000:.1f}ms")
                
                if DEBUG['enabled']:
                    self.data.print_status(rssi)
                
                return True
            else:
                print(f"[TX] FAILED - Packet #{self.tx_count} transmission failed")
                return False
                
        except Exception as e:
            print(f"[TX] ERROR: {e}")
            return False
    
    def run(self):
        """Main transmitter loop"""
        if not self.initialize():
            print("[MAIN] Initialization failed. Exiting.")
            return
        
        print(f"[MAIN] Starting transmission loop")
        print(f"[MAIN] Interval: {TX_CONFIG['tx_interval']} seconds\n")
        
        try:
            while self.running:
                # Check if it's time to transmit
                if time.time() - self.last_tx_time >= TX_CONFIG['tx_interval']:
                    self.tx_count += 1
                    self.transmit_packet()
                    self.last_tx_time = time.time()
                
                # Small delay to prevent CPU hogging
                time.sleep(0.1)
                
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
        
        # Put radio to sleep
        try:
            self.radio.set_mode(self.radio.MODE_SLEEP)
        except:
            pass
        
        # Print statistics
        print(f"\n[SHUTDOWN] === Statistics ===")
        print(f"  Total packets sent: {self.tx_count}")
        print(f"  Successful transmissions: {self.tx_success_count}")
        if self.tx_count > 0:
            success_rate = (self.tx_success_count / self.tx_count) * 100
            print(f"  Success rate: {success_rate:.1f}%")
        print(f"  Runtime: {time.time():.0f}s")
        print("[SHUTDOWN] Device ready for next session")

def main():
    """Application entry point"""
    try:
        app = LORATransmitter()
        app.run()
    except Exception as e:
        print(f"[FATAL] {e}")

if __name__ == '__main__':
    main()
