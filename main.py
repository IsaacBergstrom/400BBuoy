"""Dual-use script:

- on the ESP32/other MicroPython board the file can initialize the
  IMU and record a short burst of acceleration data.
- on a host machine the same file can load the captured data and
  display it with ``matplotlib``.

The device only needs the standard firmware plus the third‑party
``mpu9250.py`` driver; the plotting portion lives entirely on the PC.
"""

import sys

IS_MICROPY = sys.implementation.name.lower().startswith("micropython")

if not IS_MICROPY:
    # host-mode imports
    import matplotlib.pyplot as plt
    import csv

# universal imports
try:
    from machine import Pin, SoftI2C  # type: ignore
except ImportError:
    Pin = SoftI2C = None

import time

# MPU driver is third-party; only available on the board
try:
    from mpu9250 import MPU9250, MPU6500  # type: ignore
except ImportError:
    MPU9250 = MPU6500 = None


# ---------------------------------------------------------------------------
# device helpers
# ---------------------------------------------------------------------------

def init_i2c():
    """Create and configure the I2C bus; enable magnetometer pass-through."""
    i2c = SoftI2C(scl=Pin(22), sda=Pin(21))
    print("I2C devices:", i2c.scan())
    i2c.writeto_mem(0x69, 0x37, b"\x02")
    return i2c


def collect_imu_data(duration_s=10.0, interval_s=0.05):
    """Return a list of IMU samples taken for ``duration_s`` seconds.

    Each sample is a tuple: (ax, ay, az, gx, gy, gz, temp)
    """
    if not IS_MICROPY:
        raise RuntimeError("collect_imu_data() only available on MicroPython")
    i2c = init_i2c()
    mpu = MPU6500(i2c, address=0x69)
    samples = []
    end = time.ticks_ms() + int(duration_s * 1000)
    while time.ticks_ms() < end:
        accel = tuple(mpu.acceleration)
        gyro = tuple(mpu.gyro)
        temp = mpu.temperature
        samples.append(accel + gyro + (temp,))
        time.sleep_ms(int(interval_s * 1000))
    return samples


def save_samples(samples, filename="accel.csv"):
    """Write IMU samples to a CSV file on the board.

    After writing we reopen the file and dump its contents to the REPL so
    you can copy/paste it over to your PC even if you can't run a tool like
    ``ampy``.  On the ESP32 the file lives in the internal filesystem;
    executing ``import os; os.listdir()`` at the REPL will show it.
    """
    if not IS_MICROPY:
        raise RuntimeError("save_samples() only available on MicroPython")

    with open(filename, "w") as f:
        for sample in samples:
            f.write(",".join(str(v) for v in sample) + "\n")
    print(f"saved {len(samples)} samples to {filename}")

    # dump the actual file so the host can grab it through the serial log
    try:
        with open(filename, "r") as f:
            print("--- file contents ---")
            for line in f:
                sys.stdout.write(line)
            print("--- end file ---")
    except Exception as e:
        print("could not read back", e)



# ---------------------------------------------------------------------------
# host helpers
# ---------------------------------------------------------------------------

def load_samples(filename="accel.csv"):
    """Load samples from a CSV file created by the device."""
    if IS_MICROPY:
        raise RuntimeError("load_samples() only available on host Python")
    data = []
    with open(filename, newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) != 3:
                continue
            data.append(tuple(float(v) for v in row))
    return data


def plot_samples(samples=None, filename="accel.csv"):
    """Plot the three acceleration components over time."""
    if samples is None:
        samples = load_samples(filename)
    if not samples:
        print("no data to plot")
        return
    t = list(range(len(samples)))
    xs = [s[0] for s in samples]
    ys = [s[1] for s in samples]
    zs = [s[2] for s in samples]
    plt.figure()
    plt.plot(t, xs, label="x")
    plt.plot(t, ys, label="y")
    plt.plot(t, zs, label="z")
    plt.xlabel("sample #")
    plt.ylabel("accel")
    plt.legend()
    plt.title("Acceleration vs sample number")
    plt.show()


# ---------------------------------------------------------------------------
# entry logic
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if IS_MICROPY:
        # perform the 10‑second run and store results
        data = collect_imu_data(10.0, 0.05)  # ~20Hz sampling
        save_samples(data)
        print("SAMPLES:")
        for row in data:
            print(row)
        # helpful reminder for the developer
        try:
            import os
            print("files on device:", os.listdir())
        except Exception:
            pass
    else:
        print("host mode – plotting accel.csv")
        plot_samples()
