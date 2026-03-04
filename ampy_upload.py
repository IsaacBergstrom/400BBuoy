# ampy_upload.py - Utility to upload files to ESP32 using ampy

"""
Upload MicroPython code to ESP32 LILYGO using ampy.

Prerequisites:
1. Install ampy: pip install adafruit-ampy
2. Install esptool: pip install esptool
3. Connect ESP32 to computer via USB

Usage:
    python ampy_upload.py --port COM3  # Windows
    python ampy_upload.py --port /dev/ttyUSB0  # Linux
"""

import os
import sys
import argparse
import subprocess

# Files to upload to the ESP32
FILES_TO_UPLOAD = [
    'boot.py',
    'config.py',
    'lora_comm.py',
    'data_handler.py',
    'main.py'
]

def get_port():
    """Auto-detect ESP32 port"""
    result = subprocess.run(['python', '-m', 'esptool', 'version'], 
                          capture_output=True, text=True)
    if 'Serial ports:' in result.stdout:
        for line in result.stdout.split('\n'):
            if 'Serial port:' in line:
                return line.split('Serial port:')[1].strip()
    return None

def upload_files(port):
    """Upload files to ESP32"""
    print(f"[UPLOAD] Starting upload to {port}\n")
    
    for filename in FILES_TO_UPLOAD:
        if not os.path.exists(filename):
            print(f"[UPLOAD] WARNING: {filename} not found, skipping")
            continue
        
        print(f"[UPLOAD] Uploading {filename}...", end=" ")
        
        cmd = ['ampy', '--port', port, 'put', filename]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("OK")
        else:
            print(f"FAILED: {result.stderr}")
            return False
    
    print(f"\n[UPLOAD] All files uploaded successfully!")
    print(f"[UPLOAD] Device will restart. Check serial output for status.\n")
    return True

def monitor_serial(port):
    """Monitor serial output from device"""
    print(f"[MONITOR] Connecting to {port}... Press Ctrl+C to exit\n")
    
    cmd = ['ampy', '--port', port, 'run', 'main.py']
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\n[MONITOR] Disconnected")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Upload MicroPython code to ESP32')
    parser.add_argument('--port', help='Serial port (e.g., COM3, /dev/ttyUSB0)')
    parser.add_argument('--monitor', action='store_true', help='Monitor serial output after upload')
    parser.add_argument('--auto', action='store_true', help='Auto-detect serial port')
    
    args = parser.parse_args()
    
    port = args.port
    if args.auto:
        port = get_port()
        if port:
            print(f"[AUTO] Detected port: {port}\n")
    
    if not port:
        print("[ERROR] No port specified. Use --port or --auto flag")
        sys.exit(1)
    
    if upload_files(port):
        if args.monitor:
            monitor_serial(port)
