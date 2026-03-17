# buoy_main.py  — runs on the TRANSMITTER board
import time
from machine import SPI, Pin, I2C
from sx127x import SX127x
from lora_config import LORA_CONFIG
from wave_dsp import compute_wave_params, make_highpass, FS, N
from wave_direction import compute_heading, compute_roll_pitch, estimate_swell_direction
from lora_packet import encode_packet

# ── I2C sensors ───────────────────────────────────────────────────────────────
i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400_000)
# TODO: import your MPU6500 and QMC5883P drivers here
# from mpu6500 import MPU6500
# from qmc5883p import QMC5883P
# imu = MPU6500(i2c, address=0x69)
# mag = QMC5883P(i2c)

# ── LoRa radio ─────────────────────────────────────────────────────────────────
spi = SPI(1, baudrate=10_000_000,
          sck=Pin(LORA_CONFIG["sck"]),
          mosi=Pin(LORA_CONFIG["mosi"]),
          miso=Pin(LORA_CONFIG["miso"]))
lora = SX127x(spi,
              pins={"ss": LORA_CONFIG["cs"],
                    "rst": LORA_CONFIG["rst"],
                    "dio0": LORA_CONFIG["dio0"]},
              parameters={
                  "frequency":        LORA_CONFIG["frequency"],
                  "tx_power":         LORA_CONFIG["tx_power"],
                  "bandwidth":        LORA_CONFIG["bandwidth"],
                  "spreading_factor": LORA_CONFIG["sf"],
                  "coding_rate":      LORA_CONFIG["coding_rate"],
                  "preamble_length":  LORA_CONFIG["preamble"],
                  "sync_word":        LORA_CONFIG["sync_word"],
                  "enable_CRC":       LORA_CONFIG["crc"],
              })

# ── Sampling loop ─────────────────────────────────────────────────────────────
def collect_and_transmit(seq=0):
    az_buf, ax_buf, ay_buf = [], [], []
    heading_samples = []
    sample_interval_ms = int(1000 / FS)  # 250 ms

    print(f"Collecting {N} samples at {FS} Hz ({N/FS:.0f} s window)...")

    for _ in range(N):
        t_start = time.ticks_ms()

        # ── Replace these with real sensor reads ──────────────────────────────
        # ax, ay, az = imu.acceleration  # m/s² with gravity
        # az -= 9.81                     # subtract gravity for dynamic accel only
        # mx, my, mz = mag.magnetic      # µT
        ax, ay, az = 0.0, 0.0, 0.0    # placeholder
        mx, my, mz = 1.0, 0.0, 0.0   # placeholder
        # ──────────────────────────────────────────────────────────────────────

        az_buf.append(az)
        ax_buf.append(ax)
        ay_buf.append(ay)

        roll, pitch = compute_roll_pitch(ax, ay, az)
        heading_samples.append(compute_heading(mx, my, mz, roll, pitch))

        elapsed = time.ticks_diff(time.ticks_ms(), t_start)
        time.sleep_ms(max(0, sample_interval_ms - elapsed))

    # ── Compute wave parameters ───────────────────────────────────────────────
    params    = compute_wave_params(az_buf)
    avg_heading = sum(heading_samples) / len(heading_samples)
    direction = estimate_swell_direction(ax_buf, ay_buf, az_buf, avg_heading)

    print(f"[WAVE] Hs={params['Hs']}m  Tp={params['Tp']}s  "
          f"E={params['energy']:.5f}m²  Dir={direction}°")

    # ── Encode and transmit ───────────────────────────────────────────────────
    payload = encode_packet(params["Hs"], params["Tp"],
                            params["energy"], direction, seq)
    lora.println(payload)
    print(f"[TX] {len(payload)} bytes sent (seq={seq})\n")
    return (seq + 1) & 0xFF


seq = 0
while True:
    seq = collect_and_transmit(seq)
    # No sleep needed — the 128 s collection window IS the interval
