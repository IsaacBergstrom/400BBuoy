import time
import ustruct
import machine
from machine import Pin, SoftI2C
from qmc5883P import QMC5883  # Uses your existing library

# --- HARDWARE SETUP (Matching your main.py) ---
I2C_SCL_PIN = 3
I2C_SDA_PIN = 2
SAMPLE_RATE_HZ = 20
DURATION_S = 60 

# Initialize I2C and Sensor
i2c = SoftI2C(scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN), freq=400_000)
compass = QMC5883(i2c)

print("--- MAGNETOMETER CALIBRATION ---")
print("1. Start the script.")
print("2. Slowly rotate the buoy in ALL directions (3D Tumble).")
print("3. Copy the numbers below into a .csv file when finished.")
time.sleep(3)

print("mx,my,mz") # CSV Header

start_ticks = time.ticks_ms()
end_ticks = time.ticks_add(start_ticks, DURATION_S * 1000)

try:
    while time.ticks_diff(end_ticks, time.ticks_ms()) > 0:
        loop_start = time.ticks_ms()
        
        # Read raw registers directly (matching your main.py logic)
        compass.measure()
        raw_mag = compass.i2c_readregs(0x00, 6)
        mx, my, mz = ustruct.unpack('<hhh', raw_mag)
        
        # Output raw values for processing
        print(f"{mx},{my},{mz}")
        
        # Maintain timing
        elapsed = time.ticks_diff(time.ticks_ms(), loop_start)
        time.sleep_ms(max(0, (1000 // SAMPLE_RATE_HZ) - elapsed))

except KeyboardInterrupt:
    pass

print("--- CALIBRATION FINISHED ---")