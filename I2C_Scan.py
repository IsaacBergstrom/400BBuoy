from machine import Pin, SoftI2C
import time
from mpu9250 import MPU9250, MPU6500

i2c = SoftI2C(scl=Pin(3), sda=Pin(2), freq=50000)
print(i2c.scan())

while True:
    print(i2c.scan())
    time.sleep_ms(500)