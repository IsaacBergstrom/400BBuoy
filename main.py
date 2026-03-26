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
imu     = MPU6500(i2c, 0x69)
compass = QMC5883(i2c)
encoder = AS5600(i2c)

# --- 3. Temperature probe setup (DS18B20) ---
TEMP_PINS    = [15, 16, 17]
temp_buses   = [onewire.OneWire(Pin(pin)) for pin in TEMP_PINS]
temp_sensors = [ds18x20.DS18X20(bus) for bus in temp_buses]

# --- 4. Wind sensing ---
HALL_PIN = 18
hall_pin = Pin(HALL_PIN, Pin.IN, Pin.PULL_UP)

# --- Sensor runtime configuration ---
POSITION_SAMPLE_DURATION_S = 20.0
WIND_SAMPLE_DURATION_S     = 10.0
WIND_SAMPLE_INTERVAL_S     = 0.1
TEMP_CONVERSION_WAIT_MS    = 750
SAMPLE_INTERVAL_S          = 0.1   # 10 Hz

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
        "gyro":  (gx, gy, gz),
        "mag":   (mx, my, mz),
    }


def read_temperatures(wait_ms=TEMP_CONVERSION_WAIT_MS):
    """Read temperatures from up to three DS18B20 probes.
    Returns list [t1, t2, t3] where missing/failed sensors are None.
    """
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


def read_wind(duration_s=WIND_SAMPLE_DURATION_S,
              interval_s=WIND_SAMPLE_INTERVAL_S):
    """Measure wind over a span of time and return average direction/speed.

    Uses circular mean to avoid 0°/360° wraparound errors.
    """
    sum_sin      = 0.0
    sum_cos      = 0.0
    count        = 0
    speed_samples = []

    end_ms = time.ticks_add(time.ticks_ms(), int(duration_s * 1000))
    while time.ticks_diff(end_ms, time.ticks_ms()) > 0:
        try:
            raw = encoder.RAWANGLE() if callable(encoder.RAWANGLE) else encoder.RAWANGLE
            angle_deg = (raw / 4096.0) * 360.0 if raw is not None else None
        except Exception:
            angle_deg = None

        if angle_deg is not None:
            theta     = angle_deg * (math.pi / 180.0)
            sum_sin  += math.sin(theta)
            sum_cos  += math.cos(theta)
            count    += 1

        # TODO: hall-effect speed sampling → append to speed_samples

        time.sleep(interval_s)

    avg_dir = None
    if count:
        avg_theta = math.atan2(sum_sin / count, sum_cos / count)
        avg_dir   = (avg_theta * 180.0 / math.pi) % 360.0

    avg_speed = (sum(speed_samples) / len(speed_samples)) if speed_samples else None

    return {"avg_direction": avg_dir, "avg_speed": avg_speed}


def run_full_stream():
    print("\n" + "=" * 115)
    print(f"{'TIME (ms)':>10} | {'ACCEL (m/s^2)':^20} | {'GYRO (deg/s)':^20} | {'MAG (Raw)':^20}")
    print(f"{'':>10} | {'X      Y      Z':^20} | {'X      Y      Z':^20} | {'X      Y      Z':^20}")
    print("=" * 115)

    # Record the absolute start time in milliseconds (MicroPython epoch)
    # time.ticks_ms() is a relative ms counter — we use it for dt only.
    # For an absolute wall-clock stamp we use time.time() (seconds since epoch).
    # Both are written so PostProcess.py can use whichever is more convenient.
    epoch_start_s  = time.time()          # absolute seconds (RTC, if set)
    ticks_start_ms = time.ticks_ms()      # relative ms counter

    with open(CSV_FILENAME, "w") as f:
        # Header comment — PostProcess.py skips non-numeric rows automatically
        f.write(f"# epoch_start_s={epoch_start_s}\n")

        end_ms = time.ticks_add(ticks_start_ms,
                                int(POSITION_SAMPLE_DURATION_S * 1000))

        while time.ticks_diff(end_ms, time.ticks_ms()) > 0:
            # Elapsed time since first sample (seconds, 3 decimal places)
            elapsed_ms = time.ticks_diff(time.ticks_ms(), ticks_start_ms)
            t_s = elapsed_ms / 1000.0

            data = read_positional()
            ax, ay, az = data["accel"]
            gx, gy, gz = data["gyro"]
            mx, my, mz = data["mag"]

            # Write a CSV row compatible with PostProcess.py (9 values)
            # CSV row format:
            #   timestamp_s, ax, ay, az, gx, gy, gz, mx, my, mz
            f.write(
                f"{t_s:.3f},"
                f"{ax},{ay},{az},"
                f"{gx},{gy},{gz},"
                f"{mx},{my},{mz}\n"
            )

            # Console output
            accel_str = f"{ax:>5.1f} {ay:>5.1f} {az:>5.1f}"
            gyro_str  = f"{gx:>5.1f} {gy:>5.1f} {gz:>5.1f}"
            mag_str   = f"{mx:>5} {my:>5} {mz:>5}"
            print(f"{t_s:>10.3f} | {accel_str} | {gyro_str} | {mag_str}", end="\r")

            time.sleep(SAMPLE_INTERVAL_S)

    # --- Temperatures ---
    temps = read_temperatures()
    print("\nTemps:", temps)
    with open(CSV_FILENAME, "a") as f:
        temp_strs = ["" if t is None else str(t) for t in temps]
        f.write("TEMPS," + ",".join(temp_strs) + "\n")

    # --- Wind ---
    wind = read_wind()
    print("Wind:", wind)
    with open(CSV_FILENAME, "a") as f:
        dir_str = "" if wind["avg_direction"] is None else str(wind["avg_direction"])
        spd_str = "" if wind["avg_speed"]     is None else str(wind["avg_speed"])
        f.write("WIND," + dir_str + "," + spd_str + "\n")

    print("\nLogging complete →", CSV_FILENAME)


# Launch
run_full_stream()