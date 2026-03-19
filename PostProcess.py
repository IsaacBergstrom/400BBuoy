import csv
import os
import math
import matplotlib.pyplot as plt

# ── micropython-fusion (fusion.py) must be in the same directory ──────────────
# Install via: pip install micropython-fusion
# Or download fusion.py from https://github.com/micropython-IMU/micropython-fusion
from fusion import Fusion

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
SAMPLE_RATE_HZ = 10          # Fixed IMU sample rate
TIMEDIFF       = 1 / SAMPLE_RATE_HZ   # seconds between samples


def _resolve_file(filename: str) -> str:
    """Resolve a filename relative to this script's directory."""
    if os.path.isabs(filename):
        return filename
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, filename)


# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADING  (unchanged from original)
# ─────────────────────────────────────────────────────────────────────────────
def load_log(filename: str = "accel.csv"):
    """
    Loads buoy log data supporting 3, 6, or 9 columns.
    Returns a dictionary containing samples, temps, and wind data.
    """
    path = _resolve_file(filename)
    samples = []
    temps = None
    wind = {"avg_direction": None, "avg_speed": None}

    try:
        with open(path, newline="", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f, skipinitialspace=True)
            for row in reader:
                if not row or not any(field.strip() for field in row):
                    continue

                tag = str(row[0]).strip().upper()

                if tag == "TEMPS":
                    temps = [float(v) if v.strip() else None for v in row[1:]]
                    continue

                if tag == "WIND":
                    if len(row) > 1 and row[1].strip():
                        try:
                            wind["avg_direction"] = float(row[1])
                        except ValueError:
                            pass
                    if len(row) > 2 and row[2].strip():
                        try:
                            wind["avg_speed"] = float(row[2])
                        except ValueError:
                            pass
                    continue

                try:
                    numeric_row = [float(v) for v in row if v.strip()]
                    if len(numeric_row) >= 9:
                        samples.append(tuple(numeric_row[:9]))
                    elif len(numeric_row) >= 6:
                        samples.append(tuple(numeric_row[:6] + [0.0, 0.0, 0.0]))
                    elif len(numeric_row) >= 3:
                        samples.append(tuple(numeric_row[:3] + [0.0] * 6))
                except ValueError:
                    continue

        print(f"Loaded {len(samples)} samples from {path}")
        if temps:
            print(f"Temperatures: {temps}")
        if wind["avg_direction"] is not None:
            print(f"Wind Direction: {wind['avg_direction']}°  Speed: {wind['avg_speed']}")

    except FileNotFoundError:
        print(f"Error: {path} not found.")

    return {"samples": samples, "temps": temps, "wind": wind}


# ─────────────────────────────────────────────────────────────────────────────
# SENSOR FUSION
# ─────────────────────────────────────────────────────────────────────────────
def run_fusion(samples: list) -> dict:
    """
    Runs micropython-fusion (Mahony filter) over all samples.

    fusion.py expects:
        accel  – (ax, ay, az)  in any consistent unit (m/s² or g)
        gyro   – (gx, gy, gz)  in deg/s
        mag    – (mx, my, mz)  in any consistent unit (µT or raw)

    Returns dict of lists: pitch, roll, heading, and quaternion components.
    """
    fuse = Fusion(lambda *_: TIMEDIFF)

    pitches   = []
    rolls     = []
    headings  = []
    q0s, q1s, q2s, q3s = [], [], [], []

    for sample in samples:
        ax, ay, az = sample[0], sample[1], sample[2]
        gx, gy, gz = sample[3], sample[4], sample[5]
        mx, my, mz = sample[6], sample[7], sample[8]

        accel = (ax, ay, az)
        gyro  = (gx, gy, gz)
        mag   = (mx, my, mz)

        # Use 9-DOF update when mag data is present, else 6-DOF
        has_mag = any(v != 0.0 for v in mag)
        if has_mag:
            fuse.update(accel, gyro, mag, TIMEDIFF)
        else:
            fuse.update_nomag(accel, gyro, TIMEDIFF)

        pitches.append(fuse.pitch)
        rolls.append(fuse.roll)
        headings.append(fuse.heading)
        q0s.append(fuse.q[0])
        q1s.append(fuse.q[1])
        q2s.append(fuse.q[2])
        q3s.append(fuse.q[3])

    print(f"Fusion complete. {len(pitches)} attitude estimates produced.")
    return {
        "pitch":   pitches,
        "roll":    rolls,
        "heading": headings,
        "q0": q0s, "q1": q1s, "q2": q2s, "q3": q3s,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PLOTTING
# ─────────────────────────────────────────────────────────────────────────────
def plot_raw(data_dict: dict):
    """Plot raw Accelerometer, Gyroscope, and Magnetometer traces."""
    samples = data_dict.get("samples", [])
    if not samples:
        print("No raw data to plot.")
        return

    cols = list(zip(*samples))
    ax, ay, az = cols[0], cols[1], cols[2]
    gx, gy, gz = cols[3], cols[4], cols[5]
    mx, my, mz = cols[6], cols[7], cols[8]

    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    fig.suptitle("Raw IMU Data", fontsize=14)

    for data, label, color in zip([ax, ay, az], ["X", "Y", "Z"],
                                   ["tab:red", "tab:green", "tab:blue"]):
        axes[0].plot(data, label=label, color=color, alpha=0.8)
    axes[0].set_title("Accelerometer (m/s²)")
    axes[0].legend(loc="right")
    axes[0].grid(True, linestyle="--", alpha=0.5)

    for data, label, color in zip([gx, gy, gz], ["X", "Y", "Z"],
                                   ["tab:red", "tab:green", "tab:blue"]):
        axes[1].plot(data, label=label, color=color, alpha=0.8)
    axes[1].set_title("Gyroscope (deg/s)")
    axes[1].legend(loc="right")
    axes[1].grid(True, linestyle="--", alpha=0.5)

    for data, label, color in zip([mx, my, mz], ["X", "Y", "Z"],
                                   ["tab:red", "tab:green", "tab:blue"]):
        axes[2].plot(data, label=label, color=color, alpha=0.8)
    axes[2].set_title("Magnetometer (Raw Units)")
    axes[2].set_xlabel("Sample Index")
    axes[2].legend(loc="right")
    axes[2].grid(True, linestyle="--", alpha=0.5)

    plt.tight_layout()


def plot_attitude(fusion_data: dict):
    """Plot fused Pitch, Roll, Heading, and Quaternion components."""
    n = len(fusion_data["pitch"])
    t = [i * TIMEDIFF for i in range(n)]   # real-time axis in seconds

    fig, axes = plt.subplots(4, 1, figsize=(12, 14), sharex=True)
    fig.suptitle("Fused Attitude  (Mahony filter @ 10 Hz)", fontsize=14)

    # Pitch
    axes[0].plot(t, fusion_data["pitch"], color="tab:red", alpha=0.85)
    axes[0].set_title("Pitch (°)")
    axes[0].set_ylabel("Degrees")
    axes[0].axhline(0, color="black", linewidth=0.6, linestyle="--")
    axes[0].grid(True, linestyle="--", alpha=0.5)

    # Roll
    axes[1].plot(t, fusion_data["roll"], color="tab:green", alpha=0.85)
    axes[1].set_title("Roll (°)")
    axes[1].set_ylabel("Degrees")
    axes[1].axhline(0, color="black", linewidth=0.6, linestyle="--")
    axes[1].grid(True, linestyle="--", alpha=0.5)

    # Heading
    axes[2].plot(t, fusion_data["heading"], color="tab:blue", alpha=0.85)
    axes[2].set_title("Heading (°)  — magnetic north = 0°")
    axes[2].set_ylabel("Degrees")
    axes[2].set_ylim(0, 360)
    axes[2].grid(True, linestyle="--", alpha=0.5)

    # Quaternion
    for key, label, color in zip(
        ["q0", "q1", "q2", "q3"],
        ["w", "x", "y", "z"],
        ["black", "tab:red", "tab:green", "tab:blue"],
    ):
        axes[3].plot(t, fusion_data[key], label=f"q{label}", color=color, alpha=0.8)
    axes[3].set_title("Quaternion")
    axes[3].set_ylabel("Component")
    axes[3].set_xlabel("Time (s)")
    axes[3].legend(loc="right")
    axes[3].grid(True, linestyle="--", alpha=0.5)

    plt.tight_layout()


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    data        = load_log("accel.csv")
    fusion_data = run_fusion(data["samples"])

    plot_raw(data)              # Raw accel / gyro / mag
    plot_attitude(fusion_data)  # Pitch, roll, heading, quaternion

    plt.show()                  # Show all figures at once (non-blocking)