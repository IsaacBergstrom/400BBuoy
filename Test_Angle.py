# as5600_test.py
# Live angle reader for AS5600 magnetic encoder — spin shaft to verify readings
# Run directly in Thonny, Ctrl+C to stop

import time
import math
from machine import Pin, SoftI2C

from AS5600 import AS5600

# ── Hardware ───────────────────────────────────────────────────────────────────
i2c     = SoftI2C(scl=Pin(3), sda=Pin(2), freq=400_000)
encoder = AS5600(i2c)

def read_raw():
    """Returns raw 12-bit angle (0–4095)."""
    try:
        raw = encoder.RAWANGLE
        return int(raw) if raw is not None else None
    except Exception as e:
        print(f"\nRead error: {e}")
        return None

def raw_to_deg(raw):
    return (raw / 4096.0) * 360.0

def compass_point(deg):
    idx = int((deg + 11.25) / 22.5) % 16
    pts = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
           "S","SSW","SW","WSW","W","WNW","NW","NNW"]
    return pts[idx]

# ── Print header ───────────────────────────────────────────────────────────────
print("AS5600 live reader — spin the shaft, Ctrl+C to stop\n")
print(f"{'Raw':>6}  {'Degrees':>9}  {'Point':>5}  {'Bar'}")
print("-" * 60)

# ── Main loop ──────────────────────────────────────────────────────────────────
while True:
    raw = read_raw()
    if raw is not None:
        deg = raw_to_deg(raw)
        pt  = compass_point(deg)
        bar_len = int(deg / 360.0 * 40)
        bar = "█" * bar_len + "░" * (40 - bar_len)
        print(f"{raw:>6}  {deg:>8.2f}°  {pt:>5}  {bar}", end="\r")
    time.sleep_ms(100)