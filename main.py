import ustruct
import time
import math
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

# --- 3. Temperature probe setup (DS18B20) ---
# Each probe can sit on its own 1-Wire pin (GP15/GP16/GP17).
TEMP_PINS = [15, 16, 17]

temp_buses = [onewire.OneWire(Pin(pin)) for pin in TEMP_PINS]
temp_sensors = [ds18x20.DS18X20(bus) for bus in temp_buses]

# --- 4. Wind sensing (magnetic encoder + hall-effect) ---
# The magnetic encoder provides an angle; wind speed via hall-effect is not
# implemented yet, but we reserve a pin for it.
HALL_PIN = 18
hall_pin = Pin(HALL_PIN, Pin.IN, Pin.PULL_UP)

# --- Sensor runtime configuration (global) ---
# Duration for how long each sensor group is sampled before moving on.
POSITION_SAMPLE_DURATION_S = 10.0
WIND_SAMPLE_DURATION_S = 10.0
WIND_SAMPLE_INTERVAL_S = 0.1
# Time to wait for DS18B20 conversion to complete (in milliseconds).
TEMP_CONVERSION_WAIT_MS = 750

# File to which buoy data is logged (must be readable by PostProcess.py)
CSV_FILENAME = "accel.csv"


def read_positional():
    """Read IMU (accelerometer/gyro) and magnetometer."""

    ax, ay, az = imu.acceleration
    gx, gy, gz = imu.gyro

    compass.measure()
    raw_mag = compass.i2c_readregs(0x00, 6)
    mx, my, mz = ustruct.unpack('<hhh', raw_mag)

    return {
        "accel": (ax, ay, az),
        "gyro": (gx, gy, gz),
        "mag": (mx, my, mz),
    }


def read_temperatures(wait_ms=TEMP_CONVERSION_WAIT_MS):
    """Read temperatures from up to three DS18B20 probes.

    Returns list [t1, t2, t3] where missing/failed sensors are None.
    """

    # Start conversion on all connected buses
    for ds in temp_sensors:
        try:
            ds.convert_temp()
        except Exception:
            pass

    time.sleep_ms(wait_ms)

    temps = []
    for ds in temp_sensors:
        roms = ds.scan()
        if not roms:
            temps.append(None)
            continue
        try:
            temps.append(ds.read_temp(roms[0]))
        except Exception:
            temps.append(None)

    return temps


def read_wind(duration_s=WIND_SAMPLE_DURATION_S, interval_s=WIND_SAMPLE_INTERVAL_S):
    """Measure wind over a span of time and return average direction/speed.

    This function is designed so that once the hall-effect speed sensor is
    implemented, it can sample speed continuously and return an average.

    Args:
        duration_s: Total measurement time in seconds.
        interval_s: Sampling interval in seconds.

    Returns:
        dict: {"avg_direction": <deg>, "avg_speed": <units>}
    """

    # Accumulate vector sums to compute a circular mean (avoids wraparound issues).
    sum_sin = 0.0
    sum_cos = 0.0
    count = 0
    speed_samples = []  # placeholder for future hall-effect speed values

    end_ms = time.ticks_add(time.ticks_ms(), int(duration_s * 1000))
    while time.ticks_diff(end_ms, time.ticks_ms()) > 0:
        try:
            raw = encoder.RAWANGLE() if callable(encoder.RAWANGLE) else encoder.RAWANGLE
            # Assume encoder returns 0–4095 (12-bit) where 0/4095 ≈ 0/360°
            # Convert to degrees.
            angle_deg = (raw / 4096.0) * 360.0 if raw is not None else None
        except Exception:
            angle_deg = None

        if angle_deg is not None:
            theta = angle_deg * (3.141592653589793 / 180.0)
            sum_sin += math.sin(theta)
            sum_cos += math.cos(theta)
            count += 1

        # TODO: add hall-effect speed sampling here and append to speed_samples

        time.sleep(interval_s)

    if count:
        avg_theta = math.atan2(sum_sin / count, sum_cos / count)
        avg_dir = (avg_theta * 180.0 / 3.141592653589793) % 360.0
    else:
        avg_dir = None

    avg_speed = None
    if speed_samples:
        avg_speed = sum(speed_samples) / len(speed_samples)

    return {"avg_direction": avg_dir, "avg_speed": avg_speed}


def run_full_stream():
    print("\n" + "=" * 95)
    print(f"{'ACCEL (m/s^2)':^18} | {'GYRO (deg/s)':^18} | {'MAG (Raw)':^18}")
    print(f"{'X      Y      Z':^18} | {'X      Y      Z':^18} | {'X      Y      Z':^18}")
    print("=" * 95)

    # --- 1) Read positional data for POSITION_SAMPLE_DURATION_S ---
    start_ms = time.ticks_ms()

    with open(CSV_FILENAME, "w") as f:
        while time.ticks_diff(time.ticks_ms(), start_ms) < int(POSITION_SAMPLE_DURATION_S * 1000):
            data = read_positional()
            ax, ay, az = data["accel"]
            gx, gy, gz = data["gyro"]
            mx, my, mz = data["mag"]

            # Write a CSV row compatible with PostProcess.py (6 values)
            # Format: ax,ay,az,gx,gy,gz
            f.write(f"{ax},{ay},{az},{gx},{gy},{gz}\n")

            accel_str = f"{ax:>5.1f} {ay:>5.1f} {az:>5.1f}"
            gyro_str = f"{gx:>5.1f} {gy:>5.1f} {gz:>5.1f}"
            mag_str = f"{mx:>5} {my:>5} {mz:>5}"

            print(f"{accel_str} | {gyro_str} | {mag_str}", end="\r")

            time.sleep(0.1)  # 10Hz refresh rate

    temps = read_temperatures()
    print("\nTemps:", temps)

    with open(CSV_FILENAME, "a") as f:
        # Add a marker line at end for temperatures
        # Format: TEMPS,t1,t2,t3
        temp_strs = ["" if t is None else f"{t}" for t in temps]
        f.write("TEMPS," + ",".join(temp_strs) + "\n")

    # --- 3) Read wind direction/speed once, then exit ---
    wind = read_wind()
    print("Wind:", wind)

    with open(CSV_FILENAME, "a") as f:
        # Add a marker line at end for wind
        # Format: WIND,direction,speed
        dir_str = "" if wind["avg_direction"] is None else f"{wind['avg_direction']}"
        spd_str = "" if wind["avg_speed"] is None else f"{wind['avg_speed']}"
        f.write("WIND," + dir_str + "," + spd_str + "\n")

# Launch the stream
run_full_stream()