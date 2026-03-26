# main.py — Marine Buoy Control System
# Raspberry Pi Pico W + MPU6500 + QMC5883P + DS18B20
# Duty cycle: sample 5 min at 10 Hz, sleep 30 min, repeat via deepsleep reset

import ustruct
import time
import math
import gc
import sys
import onewire
import ds18x20
from machine import Pin, SoftI2C, WDT, deepsleep, reset_cause, DEEPSLEEP_RESET

# ── Optional: import your sensor libraries ─────────────────────────────────────
from mpu6500 import MPU6500
from qmc5883P import QMC5883
from AS5600 import AS5600

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION  —  edit these values only
# ══════════════════════════════════════════════════════════════════════════════
SAMPLE_DURATION_S   = 5 * 60        # 5 minutes of sampling
SLEEP_DURATION_MS   = 30 * 60 * 1000  # 30 minutes deepsleep
SAMPLE_RATE_HZ      = 10            # target sample rate
SAMPLE_INTERVAL_MS  = 1000 // SAMPLE_RATE_HZ   # 100 ms

WDT_TIMEOUT_MS      = 8000          # watchdog bites after 8 s of silence

# I2C pins
I2C_SCL = 3
I2C_SDA = 2

# Temperature probe GPIO pins (one DS18B20 per pin)
TEMP_PINS = [15, 16, 17]

# CSV output — change path to "/sd/accel.csv" when SD card is added
# SD card integration: mount your SD with `uos.mount(SDCard(...), "/sd")`
# then update this constant — nothing else needs to change.
CSV_PATH = "accel.csv"

# ══════════════════════════════════════════════════════════════════════════════
# BOOT LOGGING — persists a counter across deepsleep resets
# Uses a tiny flat file; replace with SD append when card is available.
# ══════════════════════════════════════════════════════════════════════════════

def read_session_count():
    try:
        with open("session.txt", "r") as f:
            return int(f.read().strip())
    except Exception:
        return 0

def write_session_count(n):
    try:
        with open("session.txt", "w") as f:
            f.write(str(n))
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════════
# SENSOR INITIALISATION
# Called once every boot — safe because deepsleep fully resets the chip.
# ══════════════════════════════════════════════════════════════════════════════

def init_sensors():
    """
    Initialise all I2C sensors. Returns a dict of sensor objects, or raises
    on hard failure so the WDT eventually resets us rather than hanging.
    """
    i2c = SoftI2C(scl=Pin(I2C_SCL), sda=Pin(I2C_SDA), freq=400_000)

    # I2C scan for diagnostics — logged but non-fatal
    found = i2c.scan()
    print(f"[INIT] I2C devices: {[hex(a) for a in found]}")

    sensors = {}

    try:
        sensors["imu"] = MPU6500(i2c, 0x69)
        print("[INIT] MPU6500 OK")
    except Exception as e:
        print(f"[INIT] MPU6500 FAILED: {e}")
        sensors["imu"] = None

    try:
        sensors["compass"] = QMC5883(i2c)
        print("[INIT] QMC5883P OK")
    except Exception as e:
        print(f"[INIT] QMC5883P FAILED: {e}")
        sensors["compass"] = None

    try:
        sensors["encoder"] = AS5600(i2c)
        print("[INIT] AS5600 OK")
    except Exception as e:
        print(f"[INIT] AS5600 FAILED: {e}")
        sensors["encoder"] = None

    # 1-Wire temperature probes (failures are per-probe, non-fatal)
    temp_buses   = [onewire.OneWire(Pin(p)) for p in TEMP_PINS]
    temp_sensors = [ds18x20.DS18X20(b) for b in temp_buses]
    sensors["temp"] = temp_sensors

    return sensors


# ══════════════════════════════════════════════════════════════════════════════
# SENSOR READS  (unchanged from your original — just moved inside functions)
# ══════════════════════════════════════════════════════════════════════════════

def read_positional(sensors):
    imu     = sensors["imu"]
    compass = sensors["compass"]

    ax, ay, az = imu.acceleration
    gx, gy, gz = imu.gyro

    mx = my = mz = 0
    if compass:
        try:
            compass.measure()
            raw_mag = compass.i2c_readregs(0x00, 6)
            mx, my, mz = ustruct.unpack('<hhh', raw_mag)
        except Exception:
            pass

    return {
        "accel": (ax, ay, az),
        "gyro":  (gx, gy, gz),
        "mag":   (mx, my, mz),
    }


def read_temperatures(sensors, wait_ms=750):
    results = []
    for ds in sensors["temp"]:
        try:
            ds.convert_temp()
        except Exception:
            pass
    time.sleep_ms(wait_ms)
    for ds in sensors["temp"]:
        roms = ds.scan()
        if not roms:
            results.append(None)
            continue
        try:
            results.append(ds.read_temp(roms[0]))
        except Exception:
            results.append(None)
    return results


# ══════════════════════════════════════════════════════════════════════════════
# SAMPLING SESSION  — 5-minute data collection with WDT feeding
# ══════════════════════════════════════════════════════════════════════════════

def run_sampling_session(sensors, wdt):
    """
    Sample sensors at 10 Hz for SAMPLE_DURATION_S seconds.
    Writes one CSV row per sample. Feeds the WDT every iteration.

    CSV columns: timestamp_ms, ax, ay, az, gx, gy, gz, mx, my, mz
    """
    print(f"\n[SAMPLE] Starting {SAMPLE_DURATION_S}s session at {SAMPLE_RATE_HZ} Hz")
    sample_count = 0
    end_ms = time.ticks_add(time.ticks_ms(), SAMPLE_DURATION_S * 1000)

    # ── SD card swap point ────────────────────────────────────────────────────
    # To use SD: replace CSV_PATH with "/sd/accel.csv" in the config above.
    # The open() call below is identical — no other changes needed.
    # ─────────────────────────────────────────────────────────────────────────
    with open(CSV_PATH, "w") as f:
        # Header row
        f.write("t_ms,ax,ay,az,gx,gy,gz,mx,my,mz\n")

        while time.ticks_diff(end_ms, time.ticks_ms()) > 0:
            t0 = time.ticks_ms()

            # ── Feed the watchdog first — ensures a hung sensor read
            #    is caught within WDT_TIMEOUT_MS, not after multiple samples
            wdt.feed()

            try:
                data = read_positional(sensors)
            except Exception as e:
                print(f"[SAMPLE] Read error: {e}")
                continue

            ax, ay, az = data["accel"]
            gx, gy, gz = data["gyro"]
            mx, my, mz = data["mag"]

            # Write CSV row — flush every 50 rows to limit data loss on crash
            f.write(f"{t0},{ax:.4f},{ay:.4f},{az:.4f},"
                    f"{gx:.4f},{gy:.4f},{gz:.4f},"
                    f"{mx},{my},{mz}\n")

            sample_count += 1
            if sample_count % 50 == 0:
                f.flush()
                gc.collect()          # keep heap healthy over long sessions
                print(f"[SAMPLE] {sample_count} samples collected", end="\r")

            # Maintain target sample rate — sleep remaining time in this window
            elapsed = time.ticks_diff(time.ticks_ms(), t0)
            remaining = SAMPLE_INTERVAL_MS - elapsed
            if remaining > 0:
                time.sleep_ms(remaining)

    print(f"\n[SAMPLE] Done. {sample_count} samples written to {CSV_PATH}")
    return sample_count


# ══════════════════════════════════════════════════════════════════════════════
# ANALYSIS  — compute summary stats from the collected CSV
# Kept separate so you can swap in your full FFT pipeline (wave_dsp.py) later
# ══════════════════════════════════════════════════════════════════════════════

def analyse_session():
    """
    Read the CSV written by run_sampling_session() and compute basic stats.
    Replace the body of this function with your FFT / Hs / Tp pipeline
    when ready — the return dict shape is what transmit_results() consumes.
    """
    az_vals = []
    try:
        with open(CSV_PATH, "r") as f:
            next(f)  # skip header
            for line in f:
                parts = line.strip().split(",")
                if len(parts) == 10:
                    try:
                        az_vals.append(float(parts[3]))  # az column
                    except ValueError:
                        pass
    except Exception as e:
        print(f"[ANALYSE] Could not read CSV: {e}")
        return {}

    if not az_vals:
        return {}

    n      = len(az_vals)
    mean   = sum(az_vals) / n
    devsq  = sum((v - mean) ** 2 for v in az_vals)
    std    = math.sqrt(devsq / n)

    # Hs placeholder: 4 * std of vertical acceleration (rough proxy only)
    # Replace with proper spectral Hs from wave_dsp.compute_wave_params()
    hs_proxy = round(4.0 * std, 3)

    print(f"[ANALYSE] n={n}  az_mean={mean:.3f}  az_std={std:.3f}  Hs_proxy={hs_proxy} m")
    return {
        "sample_count": n,
        "az_mean":      round(mean, 4),
        "az_std":       round(std, 4),
        "Hs_proxy":     hs_proxy,
    }


# ══════════════════════════════════════════════════════════════════════════════
# TRANSMISSION PLACEHOLDER
# Replace the body with your LoRa (lora_packet.py) or Wi-Fi POST call
# ══════════════════════════════════════════════════════════════════════════════

def transmit_results(results, session_n):
    """
    Send processed results to shore station.

    LoRa swap-in:
        from lora_packet import encode_packet
        from rylr998 import RYLR998
        lora = RYLR998(...)
        payload = encode_packet(results["Hs"], results["Tp"], ...)
        lora.send(dest=1, message=payload)

    Wi-Fi swap-in (Pico W):
        import urequests, network
        # connect wlan, then:
        urequests.post("http://yourserver/data", json=results)
    """
    print(f"[TX] Session {session_n} results: {results}")
    # ── INSERT TRANSMISSION CODE HERE ─────────────────────────────────────────
    pass


# ══════════════════════════════════════════════════════════════════════════════
# MAIN  — runs once per boot (deepsleep resets the chip each cycle)
# ══════════════════════════════════════════════════════════════════════════════

def main():
    # ── 1. Log wake reason ────────────────────────────────────────────────────
    cause = reset_cause()
    session_n = read_session_count() + 1
    write_session_count(session_n)

    if cause == DEEPSLEEP_RESET:
        print(f"\n[BOOT] Wake from deepsleep — session #{session_n}")
    else:
        print(f"\n[BOOT] Cold start (cause={cause}) — session #{session_n}")

    # ── 2. Start watchdog ─────────────────────────────────────────────────────
    # WDT must be fed at least every WDT_TIMEOUT_MS ms or the chip resets.
    # Maximum on Pico W is 8300 ms.
    wdt = WDT(timeout=WDT_TIMEOUT_MS)
    wdt.feed()

    # ── 3. Initialise sensors ─────────────────────────────────────────────────
    try:
        sensors = init_sensors()
    except Exception as e:
        # Hard sensor failure — log and let the WDT reset us after a pause
        print(f"[BOOT] Sensor init failed: {e}")
        # Don't feed wdt here — let it reset naturally
        time.sleep(10)
        return

    wdt.feed()

    # ── 4. Read temperatures (once per session, before long sampling loop) ────
    temps = read_temperatures(sensors)
    print(f"[BOOT] Temperatures: {temps}")
    wdt.feed()

    # ── 5. Run 5-minute sampling session ──────────────────────────────────────
    try:
        run_sampling_session(sensors, wdt)
    except Exception as e:
        print(f"[SAMPLE] Unhandled error: {e}")
        # WDT will reset if we hang; otherwise fall through to sleep

    wdt.feed()

    # ── 6. Analyse ────────────────────────────────────────────────────────────
    results = analyse_session()
    results["temps"]     = temps
    results["session_n"] = session_n
    wdt.feed()

    # ── 7. Transmit ───────────────────────────────────────────────────────────
    transmit_results(results, session_n)
    wdt.feed()

    # ── 8. Enter deepsleep ────────────────────────────────────────────────────
    print(f"[SLEEP] Entering deepsleep for {SLEEP_DURATION_MS // 60000} minutes...\n")
    deepsleep(SLEEP_DURATION_MS)
    # Execution never reaches here — chip resets on wake


# ── Entry point ───────────────────────────────────────────────────────────────
try:
    main()
except Exception as e:
    # Catch-all: print the error then let the WDT reset the board
    # rather than hanging at a bare REPL indefinitely
    sys.print_exception(e)
    print("[FATAL] Unhandled top-level exception — waiting for WDT reset")
    while True:
        time.sleep(1)   # WDT not fed → resets after WDT_TIMEOUT_MS