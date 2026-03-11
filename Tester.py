from machine import Pin, SoftI2C
import time
from mpu9250 import MPU9250, MPU6500

i2c = SoftI2C(scl=Pin(22), sda=Pin(21))
print(i2c.scan())

# Manually tell the MPU6500 to let I2C traffic through to the Magnetometer
i2c.writeto_mem(0x69, 0x37, b'\x02') 
mpu6500 = MPU6500(i2c, address=0x69)



while True:
    print("Accel: ",mpu6500.acceleration)
    print("Gyro: ",mpu6500.gyro)
    # print("Mag: ",mpu6500.magnetic)
    print("Temp: ",mpu6500.temperature)
    time.sleep_ms(500)