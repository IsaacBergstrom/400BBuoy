# as5600_test.py
# Live angle reader for AS5600 magnetic encoder — spin shaft to verify readings
# Run directly in Thonny, Ctrl+C to stop

import time
import math
from machine import Pin, SoftI2C

from AS5600 import AS5600

# ── Hardware ───────────────────────────────────────────────────────────────────
i2c     = SoftI2C(scl=Pin(3), sda=Pin(2), freq=100_000)
encoder = AS5600(i2c)


encoder.check_magnet()   # run this first to verify your air gap

while True:
    if encoder.magnet_detected:
        print(encoder.angle_deg)