"""
main.py — Pico Weather Station
Sequence: IMU/Mag stream (20 s) → Temperature read → Wind speed (5 s)
All data saved to /sd/accel.csv (auto-incremented if file already exists)
"""

import os
import math
import time
import ustruct
import machine
from machine import Pin, SoftI2C

import onewire
import ds18x20
import sdcard

from mpu6500 import MPU6500
from qmc5883P import QMC5883
from AS5600 import AS5600

# ── LEDs ──────────────────────────────────────────────────────────────────────
# GP14 = yellow (sampling active)   GP15 = red (error)
led_yellow = Pin(14, Pin.OUT)
led_red    = Pin(15, Pin.OUT)
led_yellow.off()   # explicit reset — value=0 in constructor is not
led_red.off()      # guaranteed to fire if pin was already high on restart

def leds_off():
    led_yellow.off()
    led_red.off()

# ── 1. SD Card (SPI 1) ────────────────────────────────────────────────────────
spi = machine.SPI(
    1,
    baudrate=1_000_000,
    sck=machine.Pin(10),
    mosi=machine.Pin(11),
    miso=machine.Pin(12),
)
cs = machine.Pin(13, machine.Pin.OUT, value=1)

try:
    sd = sdcard.SDCard(spi, cs)
    os.mount(sd, "/sd")
    print("SD card mounted.")
except Exception as e:
    print("SD mount failed:", e)
    led_red.on()     # red on — fatal error before loop even starts
    raise


def get_next_filename(base="accel", ext=".csv"):
    """Return /sd/accel.csv, /sd/accel1.csv, /sd/accel2.csv … whichever is free."""
    files = os.listdir("/sd/")
    candidate = f"{base}{ext}"
    if candidate not in files:
        return "/sd/" + candidate
    n = 1
    while True:
        candidate = f"{base}{n}{ext}"
        if candidate not in files:
            return "/sd/" + candidate
        n += 1


CSV_PATH = get_next_filename()
print(f"Logging to: {CSV_PATH}")

# ── 2. I2C Sensors ────────────────────────────────────────────────────────────
try:
    i2c     = SoftI2C(scl=Pin(3), sda=Pin(2), freq=400_000)
    imu     = MPU6500(i2c, 0x69)
    compass = QMC5883(i2c)
    encoder = AS5600(i2c)
    print("I2C sensors initialised.")
except Exception as e:
    print("I2C init failed:", e)
    led_red.on()
    raise

# ── 3. Temperature Probes (DS18B20) ───────────────────────────────────────────
try:
    TEMP_PINS    = [7, 8, 9]
    temp_buses   = [onewire.OneWire(Pin(p)) for p in TEMP_PINS]
    temp_sensors = [ds18x20.DS18X20(bus) for bus in temp_buses]
    print("Temperature buses initialised.")
except Exception as e:
    print("Temperature init failed:", e)
    led_red.on()
    raise

TEMP_CONVERSION_WAIT_MS = 750

# ── 4. Hall-Effect Wind Sensor (GP16, IRQ) ────────────────────────────────────
hall_pin = Pin(16, Pin.IN, Pin.PULL_UP)
click_timestamps = []   # populated by ISR

def _hall_irq(pin):
    click_timestamps.append(time.ticks_us())

hall_pin.irq(trigger=Pin.IRQ_FALLING, handler=_hall_irq)

# ── Sensor calibration offsets ───────────────────────────────────────────────
ACCEL_OFFSETS = (-0.61479, -0.08098,  0.17939)
GYRO_OFFSETS  = (-0.18238, -0.04456,  0.01112)
MAG_OFFSETS   = ( 0.0,     -0.5,    124.5    )

# ── Runtime config ────────────────────────────────────────────────────────────
POSITION_SAMPLE_DURATION_S = 300.0  # how long to stream IMU/Mag (5 min)
WIND_SAMPLE_DURATION_S      =  30.0 # hall-effect window (direction + speed each)
IMU_SAMPLE_INTERVAL_S       =   0.1 # 10 Hz
REST_DURATION_S             = 120.0 # sleep between logging cycles (2 min)

# ─────────────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────────────

def read_positional():
    """Return one calibrated IMU + magnetometer sample."""
    ax_raw, ay_raw, az_raw = imu.acceleration
    gx_raw, gy_raw, gz_raw = imu.gyro

    compass.measure()
    raw_mag = compass.i2c_readregs(0x00, 6)
    mx_raw, my_raw, mz_raw = ustruct.unpack('<hhh', raw_mag)

    ax = ax_raw - ACCEL_OFFSETS[0]
    ay = ay_raw - ACCEL_OFFSETS[1]
    az = az_raw - ACCEL_OFFSETS[2]

    gx = gx_raw - GYRO_OFFSETS[0]
    gy = gy_raw - GYRO_OFFSETS[1]
    gz = gz_raw - GYRO_OFFSETS[2]

    mx = mx_raw - MAG_OFFSETS[0]
    my = my_raw - MAG_OFFSETS[1]
    mz = mz_raw - MAG_OFFSETS[2]

    return (ax, ay, az, gx, gy, gz, mx, my, mz)


def read_temperatures():
    """
    Trigger conversion on every bus, wait, then read.
    Returns [t1, t2, t3]; missing/failed probes → None.
    """
    for ds in temp_sensors:
        try:
            ds.convert_temp()
        except Exception:
            pass

    time.sleep_ms(TEMP_CONVERSION_WAIT_MS)

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


def read_wind_direction(duration_s=WIND_SAMPLE_DURATION_S, interval_s=0.1):
    """Poll AS5600 for `duration_s` seconds, return circular-mean direction in degrees."""
    sum_sin   = 0.0
    sum_cos   = 0.0
    dir_count = 0

    end_ms = time.ticks_add(time.ticks_ms(), int(duration_s * 1000))
    while time.ticks_diff(end_ms, time.ticks_ms()) > 0:
        try:
            if encoder.magnet_detected:
                angle_deg  = encoder.angle_deg
                theta      = angle_deg * (math.pi / 180.0)
                sum_sin   += math.sin(theta)
                sum_cos   += math.cos(theta)
                dir_count += 1
        except Exception:
            pass
        time.sleep(interval_s)

    if dir_count:
        avg_theta = math.atan2(sum_sin / dir_count, sum_cos / dir_count)
        return (avg_theta * 180.0 / math.pi) % 360.0
    return None


def read_wind_speed(duration_s=WIND_SAMPLE_DURATION_S):
    """Count hall-effect pulses for `duration_s` seconds via ISR. Returns CPS and avg period."""
    global click_timestamps
    click_timestamps = []           # reset ISR buffer

    time.sleep(duration_s)          # ISR fills list in background

    samples = list(click_timestamps)
    total   = len(samples)
    cps     = total / duration_s

    avg_period_s = None
    if total > 1:
        span_us = time.ticks_diff(samples[-1], samples[0])
        if span_us > 0:
            avg_period_s = (span_us / 1_000_000) / (total - 1)

    return {
        "total_clicks" : total,
        "cps"          : cps,
        "avg_period_s" : avg_period_s,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main routine
# ─────────────────────────────────────────────────────────────────────────────

def run_full_stream(csv_path):
    # ── Console header ────────────────────────────────────────────────────────
    print("\n" + "=" * 115)
    print(f"{'TIME (s)':>10} | {'ACCEL (m/s²)':^20} | {'GYRO (°/s)':^20} | {'MAG (raw)':^20}")
    print(f"{'':>10} | {'X      Y      Z':^20} | {'X      Y      Z':^20} | {'X      Y      Z':^20}")
    print("=" * 115)

    led_yellow.on()   # sampling active

    epoch_start_s  = time.time()
    ticks_start_ms = time.ticks_ms()

    with open(csv_path, "w") as f:
        # ── File header ───────────────────────────────────────────────────────
        f.write(f"# epoch_start_s={epoch_start_s}\n")
        f.write(
            "timestamp_s,"
            "accel_x,accel_y,accel_z,"
            "gyro_x,gyro_y,gyro_z,"
            "mag_x,mag_y,mag_z,"
            "wind_vane_deg\n"
            "# wind_vane_deg is blank for the first "
            f"{POSITION_SAMPLE_DURATION_S - WIND_SAMPLE_DURATION_S:.0f} s, "
            f"populated for the final {WIND_SAMPLE_DURATION_S:.0f} s\n"
        )

        # ── Phase 1: IMU / Magnetometer stream ───────────────────────────────
        # During the final WIND_SAMPLE_DURATION_S seconds, also read the AS5600
        # wind vane so wind direction is time-aligned with IMU data for post-
        # processing into a true heading. Earlier rows get an empty wind column.
        end_ms       = time.ticks_add(ticks_start_ms, int(POSITION_SAMPLE_DURATION_S * 1000))
        wind_start_s = POSITION_SAMPLE_DURATION_S - WIND_SAMPLE_DURATION_S

        while time.ticks_diff(end_ms, time.ticks_ms()) > 0:
            elapsed_ms = time.ticks_diff(time.ticks_ms(), ticks_start_ms)
            t_s = elapsed_ms / 1000.0

            ax, ay, az, gx, gy, gz, mx, my, mz = read_positional()

            # Read wind vane only during the final wind-sampling window
            wind_deg_str = ""
            if t_s >= wind_start_s:
                try:
                    if encoder.magnet_detected:
                        wind_deg_str = f"{encoder.angle_deg:.2f}"
                except Exception:
                    pass

            f.write(
                f"{t_s:.3f},"
                f"{ax},{ay},{az},"
                f"{gx},{gy},{gz},"
                f"{mx},{my},{mz},"
                f"{wind_deg_str}\n"
            )

            # Live console output
            print(
                f"{t_s:>10.3f} | "
                f"{ax:>5.1f} {ay:>5.1f} {az:>5.1f} | "
                f"{gx:>5.1f} {gy:>5.1f} {gz:>5.1f} | "
                f"{mx:>5} {my:>5} {mz:>5}"
                + (f" | wind {wind_deg_str}°" if wind_deg_str else ""),
                end="\r",
            )

            time.sleep(IMU_SAMPLE_INTERVAL_S)

    # ── Phase 2: Temperatures ─────────────────────────────────────────────────
    print("\nReading temperatures…")
    temps = read_temperatures()
    print("Temps (°C):", temps)

    with open(csv_path, "a") as f:
        f.write("# --- temperatures (°C) ---\n")
        f.write("# format: TEMPS,t_pin7,t_pin8,t_pin9\n")
        t_strs = [("" if t is None else f"{t:.4f}") for t in temps]
        f.write("TEMPS," + ",".join(t_strs) + "\n")

    # ── Phase 3a: Wind direction (10 s AS5600) ───────────────────────────────
    print(f"Sampling wind direction for {WIND_SAMPLE_DURATION_S:.0f} s (AS5600)…")
    avg_direction_deg = read_wind_direction()
    dir_str = f"{avg_direction_deg:.2f}°" if avg_direction_deg is not None else "N/A"
    print(f"  Avg direction: {dir_str}")

    # ── Phase 3b: Wind speed (10 s hall-effect) ───────────────────────────────
    print(f"Sampling wind speed for {WIND_SAMPLE_DURATION_S:.0f} s (hall-effect)…")
    wind = read_wind_speed()
    print(
        f"  Total clicks : {wind['total_clicks']}\n"
        f"  CPS          : {wind['cps']:.4f}\n"
        f"  Avg period   : "
        + (f"{wind['avg_period_s']:.6f} s" if wind['avg_period_s'] is not None else "N/A")
    )

    with open(csv_path, "a") as f:
        f.write("# --- wind ---\n")
        f.write("# format: WIND,total_clicks,cps,avg_period_s,avg_direction_deg\n")
        p_str = ("" if wind["avg_period_s"]  is None else f"{wind['avg_period_s']:.6f}")
        d_str = ("" if avg_direction_deg     is None else f"{avg_direction_deg:.2f}")
        f.write(f"WIND,{wind['total_clicks']},{wind['cps']:.4f},{p_str},{d_str}\n")

    print(f"\nLogging complete → {csv_path}")
    print("Files on SD:", os.listdir("/sd/"))
    led_yellow.off()  # sampling done


# ── Entry point — continuous logging loop ─────────────────────────────────────
cycle = 0
while True:
    cycle += 1
    csv_path = get_next_filename()
    leds_off()   # both off at the start of every cycle
    print(f"\n{'='*40}")
    print(f"  Cycle {cycle}  →  {csv_path}")
    print(f"{'='*40}")

    try:
        run_full_stream(csv_path)
    except Exception as e:
        # Log the error, light red, keep the loop alive
        print(f"ERROR in cycle {cycle}: {e}")
        led_yellow.off()
        led_red.on()

    print(f"Resting for {REST_DURATION_S:.0f} s before next cycle…")
    time.sleep(REST_DURATION_S)