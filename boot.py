# boot.py - Startup configuration for ESP32 LILYGO LORA
# Runs before main.py

import machine
import time

def setup_pins():
    """Initialize critical pins"""
    # Prevent brownout issues
    machine.freq(240000000)  # Set CPU frequency to 240 MHz
    
    # Disable WiFi to save power if not needed
    import network
    network.WLAN(network.STA_IF).active(False)
    network.WLAN(network.AP_IF).active(False)
    
    time.sleep(0.1)

try:
    setup_pins()
    print("Boot initialization complete")
except Exception as e:
    print(f"Boot error: {e}")
