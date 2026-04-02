import time
import ustruct
import machine
from machine import Pin, SoftI2C

# Using your exact library imports from main.py
from mpu6500 import MPU6500
from qmc5883P import QMC5883

# --- 1. SETUP (Exact Pins and Freq from your main.py) ---
i2c = SoftI2C(scl=Pin(3), sda=Pin(2), freq=400_000)
imu = MPU6500(i2c, 0x69)
compass = QMC5883(i2c)

SAMPLE_COUNT = 500
MAG_CAL_DURATION_S = 30

def run_calibration():
    print("\n" + "="*50)
    print("STEP 1: ACCEL & GYRO STATIC CALIBRATION")
    print("="*50)
    print("Place the buoy on a flat, level surface. Do not touch it.")
    
    for i in range(5, 0, -1):
        print(f"Starting in {i}...")
        time.sleep(1)

    ax_sum, ay_sum, az_sum = 0, 0, 0
    gx_sum, gy_sum, gz_sum = 0, 0, 0

    print("Sampling... please wait.")
    for _ in range(SAMPLE_COUNT):
        # Using your existing imu.acceleration and imu.gyro calls
        ax, ay, az = imu.acceleration
        gx, gy, gz = imu.gyro
        
        ax_sum += ax; ay_sum += ay; az_sum += az
        gx_sum += gx; gy_sum += gy; gz_sum += gz
        time.sleep_ms(5)

    # Averages: For Accel Z, we subtract 9.806 (gravity) to find the actual bias
    a_off = (ax_sum/SAMPLE_COUNT, ay_sum/SAMPLE_COUNT, (az_sum/SAMPLE_COUNT) - 9.806)
    g_off = (gx_sum/SAMPLE_COUNT, gy_sum/SAMPLE_COUNT, gz_sum/SAMPLE_COUNT)

    print("\n" + "="*50)
    print("STEP 2: MAGNETOMETER HARD-IRON CALIBRATION")
    print("="*50)
    print(f"Rotate the buoy in a 3D Figure-8 for {MAG_CAL_DURATION_S} seconds.")
    time.sleep(2)

    mx_min, my_min, mz_min = 32767, 32767, 32767
    mx_max, my_max, mz_max = -32768, -32768, -32768

    start_ms = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start_ms) < (MAG_CAL_DURATION_S * 1000):
        # Using your exact magnetometer reading logic
        compass.measure()
        raw_mag = compass.i2c_readregs(0x00, 6)
        mx, my, mz = ustruct.unpack('<hhh', raw_mag)

        mx_min = min(mx_min, mx); mx_max = max(mx_max, mx)
        my_min = min(my_min, my); my_max = max(my_max, my)
        mz_min = min(mz_min, mz); mz_max = max(mz_max, mz)
        
        print(f"Mag Raw: {mx:>6}, {my:>6}, {mz:>6}", end="\r")
        time.sleep_ms(20)

    m_off = ((mx_max + mx_min)/2, (my_max + my_min)/2, (mz_max + mz_min)/2)

    print("\n\n" + "!"*50)
    print("CALIBRATION SUCCESSFUL")
    print("!"*50)
    print("\nCopy and paste these 3 lines into the top of your main.py:\n")
    print(f"ACCEL_OFFSETS = ({a_off[0]:.5f}, {a_off[1]:.5f}, {a_off[2]:.5f})")
    print(f"GYRO_OFFSETS  = ({g_off[0]:.5f}, {g_off[1]:.5f}, {g_off[2]:.5f})")
    print(f"MAG_OFFSETS   = ({m_off[0]:.1f}, {m_off[1]:.1f}, {m_off[2]:.1f})")
    print("\n" + "="*50)

if __name__ == "__main__":
    run_calibration()