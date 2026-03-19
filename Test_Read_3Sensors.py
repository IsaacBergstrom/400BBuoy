import ustruct
import time
import onewire
import ds18x20
from machine import Pin, SoftI2C

# --- 1. Import Libraries (Ensure these files are on your Pico) ---
from mpu6500 import MPU6500
from qmc5883P import QMC5883
from AS5600 import AS5600

# --- 2. Hardware Setup (I2C) ---
i2c = SoftI2C(scl=Pin(3), sda=Pin(2))

# Initialize the 3 I2C Sensors
# These are the "definitions" the error was looking for
imu = MPU6500(i2c, 0x69)      # This defines 'imu'
compass = QMC5883(i2c)         # This defines 'compass'
encoder = AS5600(i2c)         # This defines 'encoder'

# --- 3. DS18B20 Setup (Two separate pins) ---
# Sensor 1 on GP15
ow1 = onewire.OneWire(Pin(15))
ds1 = ds18x20.DS18X20(ow1)
roms1 = ds1.scan()

# Sensor 2 on GP16
ow2 = onewire.OneWire(Pin(16))
ds2 = ds18x20.DS18X20(ow2)
roms2 = ds2.scan()


import ustruct
import time

def run_full_stream():
    print("\n" + "="*95)
    print(f"{'ACCEL (m/s^2)':^18} | {'GYRO (deg/s)':^18} | {'MAG (Raw)':^18} | {'ANGLE'}")
    print(f"{'X      Y      Z':^18} | {'X      Y      Z':^18} | {'X      Y      Z':^18} | {'0-4095'}")
    print("="*95)
    
    while True:
        try:
            # 1. Read MPU6500 (Accel & Gyro)
            ax, ay, az = imu.acceleration
            gx, gy, gz = imu.gyro
            
            # 2. Read QMC5883P (Magnetometer)
            compass.measure()
            # 0x00 is the start of X, Y, Z data (6 bytes)
            raw_mag = compass.i2c_readregs(0x00, 6)
            mx, my, mz = ustruct.unpack('<hhh', raw_mag)
            
            # 3. Read AS5600 (Magnetic Encoder)
            try:
                # RAWANGLE is usually the direct sensor data before offsets
                ang = encoder.RAWANGLE()
            except TypeError:
                ang = encoder.RAWANGLE
            
            # 4. Format Output for Scannability
            # Using :>6.1f for floats and :>5 for integers to keep columns locked
            accel_str = f"{ax:>5.1f} {ay:>5.1f} {az:>5.1f}"
            gyro_str  = f"{gx:>5.1f} {gy:>5.1f} {gz:>5.1f}"
            mag_str   = f"{mx:>5} {my:>5} {mz:>5}"
            
            print(f"{accel_str} | {gyro_str} | {mag_str} | {ang:>4}", end="\r")
            
            time.sleep(0.1) # 10Hz refresh rate
            
        except Exception as e:
            print(f"\n[!] Stream Interrupted: {e}")
            break

# Launch the stream
run_full_stream()