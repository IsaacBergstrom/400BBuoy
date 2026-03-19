"""Host-side post-processing utilities for the buoy.

This module reads a CSV file containing IMU samples (acceleration, gyroscope,
temperature) produced by the buoy and visualizes the raw data.

The file format produced by the transmitter is:
    ax,ay,az,gx,gy,gz        (6 columns)

Legacy files may contain:
    ax,ay,az                  (3 columns)
    ax,ay,az,gx,gy,gz,temp    (7 columns)

Usage example::

    from PostProcess import load_and_plot
    load_and_plot()
"""

import csv
import matplotlib.pyplot as plt  # type: ignore
import numpy as np
from scipy import signal  # type: ignore


def load_log(filename=None):
    """Load a buoy log file containing raw samples plus summary metadata.

    The file can contain:
      - Raw IMU samples (6 columns): ax, ay, az, gx, gy, gz
      - An optional temperature summary line: TEMPS,t1,t2,t3
      - An optional wind summary line: WIND,direction,speed

    Returns:
        dict containing:
          - 'samples': list of (ax,ay,az,gx,gy,gz) tuples
          - 'temps': list of 3 temperature values (or None if missing)
          - 'wind': dict {'avg_direction': float|None, 'avg_speed': float|None}
    """

    if filename is None:
        filename = "accel.csv"

    samples = []
    temps = None
    wind = None

    try:
        with open(filename, newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                # Handle marker lines added by the buoy script
                if not row:
                    continue
                tag = row[0].strip().upper()
                if tag == "TEMPS":
                    # TEMPS,t1,t2,t3
                    values = []
                    for v in row[1:]:
                        try:
                            values.append(float(v))
                        except ValueError:
                            values.append(None)
                    temps = values
                    continue
                if tag == "WIND":
                    # WIND,direction,speed
                    wind = {"avg_direction": None, "avg_speed": None}
                    if len(row) > 1:
                        try:
                            wind["avg_direction"] = float(row[1])
                        except ValueError:
                            pass
                    if len(row) > 2:
                        try:
                            wind["avg_speed"] = float(row[2])
                        except ValueError:
                            pass
                    continue

                # Otherwise treat as a sample row
                if len(row) == 6:
                    # New format: ax,ay,az,gx,gy,gz
                    pass
                elif len(row) == 7:
                    # Includes temp; ignore temp for now
                    row = row[:6]
                elif len(row) == 3:
                    # Old accel-only data; pad gyro with zeros
                    row = row + ["0", "0", "0"]
                else:
                    # Unknown row format; skip
                    continue

                try:
                    samples.append(tuple(float(v) for v in row))
                except ValueError:
                    continue

        print(f"Successfully loaded {len(samples)} samples from {filename}")
    except FileNotFoundError:
        print(f"File {filename} not found. Transfer accel.csv from the ESP32 to this directory first.")

    return {"samples": samples, "temps": temps, "wind": wind}


def load_samples(filename=None):
    """Legacy helper: return only the raw sample list (for compatibility)."""
    return load_log(filename)["samples"]


# (rest of file omitted for brevity — implement plotting/analyzers as needed)
